"""Quant OS against the REAL AEGIS gateway, running locally. Opt-in; skipped unless configured:

  QOS_AEGIS_LIVE_URL   e.g. http://127.0.0.1:4000 (loopback only; the network guard blocks anything else)
  QOS_AEGIS_LIVE_KEYS  path to the JSON written by aegis/packages/core/scripts/quantos-tenant-setup.ts

The broker is still the fake paper broker: no Alpaca call, paper or live, is made.
AEGIS holds no broker credentials: its "quantos-broker" integration only verifies grants.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
import urllib.request

import support

LIVE_URL = os.getenv("QOS_AEGIS_LIVE_URL", "")
LIVE_KEYS = os.getenv("QOS_AEGIS_LIVE_KEYS", "")
OWNER_DB = os.getenv("QOS_AEGIS_LIVE_OWNER_DB", "")  # local AEGIS owner-role URL, for the tamper test only
AEGIS_ENV = ("QOS_AEGIS_URL", "QOS_AEGIS_AGENT_KEY", "QOS_AEGIS_INTEGRATION_KEY", "QOS_AEGIS_TIMEOUT_SECONDS")


def http(method, url, body=None, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "null"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "null"), e.headers


@unittest.skipUnless(LIVE_URL and LIVE_KEYS, "set QOS_AEGIS_LIVE_URL and QOS_AEGIS_LIVE_KEYS to run against a local AEGIS")
class RealAegis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(LIVE_KEYS) as f:
            cls.keys = json.load(f)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.q = support.load(self._tmp.name)
        self.c = self.q.client
        self._env = {k: os.environ.get(k) for k in AEGIS_ENV}
        os.environ.update({"QOS_AEGIS_URL": LIVE_URL, "QOS_AEGIS_AGENT_KEY": self.keys["agentKey"],
                           "QOS_AEGIS_INTEGRATION_KEY": self.keys["integrationKey"], "QOS_AEGIS_TIMEOUT_SECONDS": "10"})
        self.ws, self.key, self.conn = support.workspace(self.q, "live")
        support.set_quote("MSFT", 100.0)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def order(self, idem, **over):
        return self.c.post("/api/v1/orders", headers={"X-QOS-API-Key": self.key, "X-QOS-Idempotency-Key": idem},
                           json=support.order_body(self.conn, **over))

    def code(self, r):
        d = r.json().get("detail")
        return d.get("code") if isinstance(d, dict) else d

    def aegis_request(self, rid):
        s, body, _ = http("GET", f"{LIVE_URL}/v1/gateway/actions/{rid}", headers={"Authorization": "Bearer " + self.keys["agentKey"]})
        self.assertEqual(s, 200, body)
        return body

    _sessions: dict = {}

    def login(self, email):
        # AEGIS rate-limits logins, so each user signs in once per run.
        if email not in RealAegis._sessions:
            s, body, headers = http("POST", f"{LIVE_URL}/v1/auth/login", {"email": email, "password": self.keys["password"]})
            self.assertEqual(s, 200, body)
            RealAegis._sessions[email] = headers.get("Set-Cookie").split(";")[0]
        return RealAegis._sessions[email]

    def test_allowed_order_end_to_end(self):
        r = self.order("live-allow")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["authorization"]["verified"])
        self.assertTrue(body["authorization"]["outcome_reported"])
        self.assertEqual(len(support.fakes.submits("live")), 1)
        req = self.aegis_request(body["authorization"]["aegis_request_id"])
        self.assertEqual(req["status"], "executed")
        self.assertEqual(req["params"]["reference"], body["client_order_id"])
        self.assertEqual(req["receipts"][-1]["downstreamReference"], body["order"]["broker_order_id"])
        grants = req["grants"]
        self.assertEqual(len(grants), 1)
        self.assertIsNotNone(grants[0]["consumedAt"])
        types = [e["type"] for e in req["evidence"]]
        self.assertIn("gateway.decision.allow", types)
        self.assertIn("gateway.executed", types)
        # The downstream verification is recorded against the request by the integration's key.
        cookie = self.login(self.keys["ownerEmail"])
        s, ev, _ = http("GET", f"{LIVE_URL}/v1/assurance/evidence?subjectId={req['id']}&pageSize=200", headers={"Cookie": cookie})
        self.assertEqual(s, 200, ev)
        rows = ev.get("items") or ev.get("events") or ev.get("rows") or []
        self.assertIn("gateway.grant_verified_downstream", [e["type"] for e in rows], ev)

    def test_replayed_grant_is_refused_by_aegis(self):
        ac = self.q.pkg.aegis_client
        captured = {}
        real = ac.AegisClient.verify

        def capture(client, auth, intent, cid):
            captured.update(client=client, auth=auth, intent=intent, cid=cid)
            return real(client, auth, intent, cid)
        ac.AegisClient.verify = capture
        try:
            self.assertEqual(self.order("live-replay").status_code, 200)
        finally:
            ac.AegisClient.verify = real
        with self.assertRaises(self.q.pkg.order_safety.OrderRejected) as e:
            captured["client"].verify(captured["auth"], captured["intent"], captured["cid"])
        self.assertIn("consumed", e.exception.message)
        self.assertEqual(len(support.fakes.submits("live")), 1)

    def test_changed_parameters_are_refused_by_aegis(self):
        ac = self.q.pkg.aegis_client
        real = ac.AegisClient.authorize

        def tamper(client, intent, cid, evidence):
            auth = real(client, intent, cid, evidence)
            intent.quantity = 11
            return auth
        ac.AegisClient.authorize = tamper
        try:
            r = self.order("live-tamper")
        finally:
            ac.AegisClient.authorize = real
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_grant_rejected"), r.text)
        self.assertIn("hash_mismatch", r.text)
        self.assertEqual(support.fakes.submits("live"), [])

    def test_policy_denial(self):
        r = self.order("live-deny", symbol="MSFT")  # not in the mandate's instrument list
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_denied"), r.text)
        self.assertEqual(support.fakes.submits("live"), [])

    def test_approval_band_then_human_approval(self):
        r = self.order("live-approval", quantity=60)  # USD 6,000: needs one approver
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_approval_pending"), r.text)
        self.assertEqual(support.fakes.submits("live"), [])
        approval_id = r.json()["detail"]["details"]["approval"]["approvalRequestId"]
        cookie = self.login(self.keys["approverEmail"])
        s, appr, _ = http("GET", f"{LIVE_URL}/v1/approvals/{approval_id}", headers={"Cookie": cookie})
        self.assertEqual(s, 200, appr)
        request_hash = appr.get("requestHash") or appr.get("request", {}).get("paramsHash")
        s, decided, _ = http("POST", f"{LIVE_URL}/v1/approvals/{approval_id}/decide",
                             {"decision": "approve", "comment": "integration test", "requestHash": request_hash}, headers={"Cookie": cookie})
        self.assertEqual(s, 200, decided)
        ok = self.order("live-approval", quantity=60)
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(len(support.fakes.submits("live")), 1)

    def test_evidence_chain_verifies(self):
        self.assertEqual(self.order("live-chain").status_code, 200)
        cookie = self.login(self.keys["ownerEmail"])
        s, body, _ = http("POST", f"{LIVE_URL}/v1/assurance/evidence/verify", {}, headers={"Cookie": cookie})
        self.assertEqual(s, 200, body)
        self.assertIs(body["valid"], True, body)
        self.assertGreater(body["checked"], 0, body)


    @unittest.skipUnless(OWNER_DB, "set QOS_AEGIS_LIVE_OWNER_DB (local owner-role URL) to run the tamper test")
    def test_tampered_trading_record_is_detected(self):
        """Someone with database owner rights rewrites the evidence of a Quant OS order (here, the
        verified quantity). Chain verification reports the first altered record."""
        r = self.order("live-tamper-evidence")
        self.assertEqual(r.status_code, 200, r.text)
        rid = r.json()["authorization"]["aegis_request_id"]

        def psql(sql):
            return subprocess.run(["psql", OWNER_DB, "-v", "ON_ERROR_STOP=1", "-Atc", sql], check=True, capture_output=True, text=True).stdout.strip()
        row = psql(f"select id || '|' || seq || '|' || payload::text from evidence_events where org_id='{self.keys['orgId']}' "
                   f"and subject_id='{rid}' and type='gateway.grant_verified_downstream' order by seq limit 1")
        ev_id, seq, original = row.split("|", 2)
        forged = json.dumps({**json.loads(original), "forged": True}).replace("'", "''")
        orig_sql = original.replace("'", "''")
        psql(f"begin; alter table evidence_events disable trigger forbid_mutation; update evidence_events set payload='{forged}'::jsonb where id='{ev_id}'; "
             f"alter table evidence_events enable trigger forbid_mutation; commit;")
        try:
            cookie = self.login(self.keys["ownerEmail"])
            s, body, _ = http("POST", f"{LIVE_URL}/v1/assurance/evidence/verify", {}, headers={"Cookie": cookie})
            self.assertEqual(s, 200, body)
            self.assertIs(body["valid"], False, body)
            self.assertEqual(str(body["firstBadSeq"]), seq, body)
        finally:
            psql(f"begin; alter table evidence_events disable trigger forbid_mutation; update evidence_events set payload='{orig_sql}'::jsonb where id='{ev_id}'; "
                 f"alter table evidence_events enable trigger forbid_mutation; commit;")
        s, body, _ = http("POST", f"{LIVE_URL}/v1/assurance/evidence/verify", {}, headers={"Cookie": cookie})
        self.assertIs(body["valid"], True, body)


if __name__ == "__main__":
    unittest.main()
