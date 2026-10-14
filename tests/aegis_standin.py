"""A local stand-in for the AEGIS agent-mode API, for tests. Loopback only.

It implements the parts of the contract Quant OS depends on, with the same semantics as AEGIS:
- POST /v1/gateway/actions (agent key): decision by the configured mode; idempotency by key with a
  parameter-hash check; on allow, a single-use grant bound to sha256(canonical {toolKey, action, params}).
- POST /v1/gateway/actions/:id/grant (agent key): one live grant per request, only for allowed or
  approved requests that have not started executing.
- POST /v1/gateway/grants/verify (integration key): refuses unknown, expired, voided, consumed and
  hash-mismatched grants; consuming moves the request to executing.
- POST /v1/gateway/actions/:id/execute (agent key): records the reported outcome.
Faults can be injected: down (connection refused), timeout, 500, malformed JSON.
The real AEGIS gateway is exercised separately (tests/test_aegis_live.py).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_KEY = "aegis-agent-test-key"
INTEGRATION_KEY = "aegis-integration-test-key"


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class StandIn:
    def __init__(self):
        self.mode = "allow"           # allow | deny | approval | restrict
        self.fault = None             # None | timeout | 500 | malformed
        self.fail_paths: set[str] = set()  # path suffixes that answer 500 (fault on one step only)
        self.grant_ttl = 300.0
        self.timeout_seconds = 2.0
        self.requests: dict[str, dict] = {}
        self.by_idem: dict[str, str] = {}
        self.grants: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict]] = []  # (method, path, body)
        self.lock = threading.Lock()
        handler = self._handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # ------------------------------------------------------------ helpers for tests
    def approve(self, request_id: str):
        with self.lock:
            self.requests[request_id]["status"] = "approved"

    def pause(self):
        """Like the AEGIS emergency pause: every live grant is voided."""
        with self.lock:
            for g in self.grants.values():
                if not g["consumed"]:
                    g["voided"] = True

    def paths(self, suffix: str) -> list[dict]:
        return [b for m, p, b in self.calls if p.endswith(suffix)]

    # ------------------------------------------------------------ server
    def _issue(self, req: dict) -> dict:
        token = "aegis_gr2." + secrets.token_urlsafe(16) + ".sig"
        exp = time.time() + self.grant_ttl
        self.grants[token] = {"req": req["id"], "hash": req["hash"], "exp": exp, "consumed": False, "voided": False}
        return {"token": token, "expiresAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp))}

    def _handle(self, method: str, path: str, auth: str, body: dict) -> tuple[int, dict]:
        key = auth.removeprefix("Bearer ").strip()
        with self.lock:
            self.calls.append((method, path, body))
            if path == "/v1/gateway/actions" and method == "POST":
                if key != AGENT_KEY:
                    return 401, {"error": {"code": "unauthorized"}}
                h = canonical_hash({"toolKey": body.get("tool"), "action": body.get("action", "execute"), "params": body.get("params", {})})
                idem = body.get("idempotencyKey", "")
                if idem in self.by_idem:
                    req = self.requests[self.by_idem[idem]]
                    if req["hash"] != h:
                        return 409, {"error": {"code": "conflict", "message": "Idempotency key was already used with different parameters"}}
                    return (202 if req["status"] == "pending_approval" else 200), {"requestId": req["id"], "status": req["status"], "decision": req["decision"], "reasons": [], "policyVersionIds": ["pv-test"]}
                rid = str(uuid.uuid4())
                decision = self.mode
                status = {"allow": "allowed", "deny": "denied", "approval": "pending_approval", "restrict": "allowed"}[decision]
                if decision == "approval":
                    decision = "require_approval"
                req = {"id": rid, "hash": h, "status": status, "decision": decision, "params": body.get("params", {}), "tool": body.get("tool")}
                self.requests[rid] = req
                self.by_idem[idem] = rid
                out = {"requestId": rid, "status": status, "decision": decision, "reasons": [] if decision != "deny" else ["policy"], "policyVersionIds": ["pv-test"]}
                if decision == "allow":
                    out["grant"] = self._issue(req)
                if decision == "restrict":
                    out["restrictions"] = {"applied": ["max qty"], "params": {**req["params"], "qty": 1}, "note": "narrowed"}
                code = 200 if decision in ("allow", "restrict") else 202 if decision == "require_approval" else 403
                return code, out
            if path.startswith("/v1/gateway/actions/") and path.endswith("/grant"):
                if key != AGENT_KEY:
                    return 401, {"error": {"code": "unauthorized"}}
                req = self.requests.get(path.split("/")[4])
                if not req:
                    return 404, {"error": {"code": "not_found"}}
                if req["status"] not in ("allowed", "approved"):
                    return 409, {"error": {"code": "conflict", "message": f"Request is {req['status']}"}}
                now = time.time()
                live = [g for g in self.grants.values() if g["req"] == req["id"] and not g["consumed"] and not g["voided"] and g["exp"] > now]
                if live:
                    return 409, {"error": {"code": "conflict", "message": "An execution grant is already outstanding"}}
                g = self._issue(req)
                return 200, {"grant": g["token"], "expiresAt": g["expiresAt"], "params": req["params"]}
            if path == "/v1/gateway/grants/verify":
                if key != INTEGRATION_KEY:
                    return 403, {"error": {"code": "forbidden", "message": "Use an integration API key"}}
                g = self.grants.get(body.get("grant", ""))
                if not g:
                    return 403, {"ok": False, "reason": "invalid_token"}
                if g["consumed"]:
                    return 403, {"ok": False, "reason": "consumed"}
                if g["voided"]:
                    return 403, {"ok": False, "reason": "voided"}
                if g["exp"] <= time.time():
                    return 403, {"ok": False, "reason": "expired"}
                h = canonical_hash({"toolKey": body.get("toolKey"), "action": body.get("action", "execute"), "params": body.get("params", {})})
                if h != g["hash"]:
                    return 403, {"ok": False, "reason": "hash_mismatch"}
                req = self.requests[g["req"]]
                if req["status"] not in ("allowed", "approved"):
                    return 403, {"ok": False, "reason": "request_not_executable"}
                g["consumed"] = True
                req["status"] = "executing"
                return 200, {"ok": True, "actionRequestId": req["id"], "requestHash": h}
            if path.startswith("/v1/gateway/actions/") and path.endswith("/execute"):
                if key != AGENT_KEY:
                    return 401, {"error": {"code": "unauthorized"}}
                req = self.requests.get(path.split("/")[4])
                if not req:
                    return 404, {"error": {"code": "not_found"}}
                if req.get("receipt"):
                    return 200, req["receipt"]
                g = self.grants.get(body.get("grant", ""))
                if not g or g["req"] != req["id"]:
                    return 403, {"error": {"code": "forbidden"}}
                if not g["consumed"]:
                    g["consumed"] = True
                req["status"] = "executed" if body.get("outcome") == "succeeded" else "failed"
                req["receipt"] = {"status": req["status"], "reference": body.get("reference"), "summary": body.get("summary")}
                return 200, req["receipt"]
            return 404, {"error": {"code": "not_found"}}

    def _handler(self):
        standin = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n).decode() or "{}")
                except Exception:
                    body = {}
                if standin.fault == "timeout":
                    time.sleep(standin.timeout_seconds)
                    return
                if standin.fault == "500" or any(self.path.endswith(x) for x in standin.fail_paths):
                    self._send(500, b'{"error":{"code":"internal"}}')
                    return
                if standin.fault == "malformed":
                    self._send(200, b"<html>not json</html>")
                    return
                code, out = standin._handle("POST", self.path, self.headers.get("Authorization", ""), body)
                self._send(code, json.dumps(out).encode())

            def _send(self, code, raw):
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        return H
