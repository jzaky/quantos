"""AEGIS authorization for broker orders (agent mode). Standard library only.

AEGIS is the independent authorization layer. It never holds broker credentials and never places
orders. Quant OS asks it for a decision, receives a single-use grant bound to the exact order
parameters, has the grant verified (and consumed) with a separate integration key immediately before
sending, sends exactly those parameters to the broker, and reports the outcome.

Configuration (environment only, nothing in the repository):
  QOS_AEGIS_URL              base URL of the AEGIS API, e.g. http://127.0.0.1:4000. Unset: AEGIS is off.
  QOS_AEGIS_AGENT_KEY        agent API key (submits requests, fetches grants, reports outcomes)
  QOS_AEGIS_INTEGRATION_KEY  integration API key (verifies grants only)
  QOS_AEGIS_TOOL             tool key in AEGIS (default place-order)
  QOS_AEGIS_TIMEOUT_SECONDS  per-call timeout (default 5)

Fail closed: when QOS_AEGIS_URL is set, any missing key, timeout, connection error, non-2xx status,
malformed response, denial, hold, restriction, or verification failure refuses the order.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .order_safety import OrderIntent, OrderRejected

AUTHORIZABLE_TYPES = ('market', 'limit')


@dataclass
class Authorization:
    request_id: str
    grant: str
    expires_at: str
    params: dict
    decision: str
    policy_version_ids: list = field(default_factory=list)
    verified: bool = False

    def evidence(self) -> dict:
        return {'aegis_request_id': self.request_id, 'decision': self.decision, 'grant_expires_at': self.expires_at,
                'policy_version_ids': self.policy_version_ids, 'verified': self.verified}


def enabled() -> bool:
    return bool(os.getenv('QOS_AEGIS_URL', '').strip())


def order_params(intent: OrderIntent, client_order_id: str, notional: float) -> dict:
    """The parameters AEGIS authorizes. They are rebuilt from the order at verification time, so any
    change to the order after authorization produces a different hash and is refused."""
    m = intent.material()
    p: dict[str, Any] = {
        'symbol': m['symbol'], 'side': m['side'], 'type': m['order_type'], 'qty': _n(m['quantity']),
        'notional': round(float(notional), 2), 'timeInForce': m['time_in_force'], 'reference': client_order_id,
        'reason': f"quantos {intent.source}" + (f" strategy {intent.strategy_id}" if intent.strategy_id else ''),
    }
    if m['limit_price'] is not None:
        p['limitPrice'] = _n(m['limit_price'])
    return p


def _n(v):
    f = float(v)
    return int(f) if f.is_integer() else f


class AegisClient:
    def __init__(self, base_url: str, agent_key: str, integration_key: str, tool: str = 'place-order', timeout: float = 5.0):
        self.base_url = base_url.rstrip('/')
        self.agent_key = agent_key
        self.integration_key = integration_key
        self.tool = tool
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> 'AegisClient':
        url = os.getenv('QOS_AEGIS_URL', '').strip()
        agent = os.getenv('QOS_AEGIS_AGENT_KEY', '').strip()
        integ = os.getenv('QOS_AEGIS_INTEGRATION_KEY', '').strip()
        if not (url and agent and integ):
            raise OrderRejected(503, 'aegis_misconfigured', 'AEGIS is enabled but its URL or keys are not configured; no order is sent')
        if not (url.startswith('https://') or url.startswith('http://127.0.0.1') or url.startswith('http://localhost')):
            raise OrderRejected(503, 'aegis_misconfigured', 'AEGIS must be reached over HTTPS (plain HTTP is allowed only on localhost)')
        return cls(url, agent, integ, os.getenv('QOS_AEGIS_TOOL', 'place-order').strip() or 'place-order',
                   float(os.getenv('QOS_AEGIS_TIMEOUT_SECONDS', '5')))

    # ---------------------------------------------------------------- transport
    def _call(self, method: str, path: str, key: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header('Authorization', 'Bearer ' + key)
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except Exception as e:  # timeout, refused, reset, TLS failure: no decision means no order
            raise OrderRejected(503, 'aegis_unavailable', 'AEGIS could not be reached; no order is sent', {'error': type(e).__name__})
        try:
            parsed = json.loads(raw.decode() or '{}')
        except Exception:
            raise OrderRejected(503, 'aegis_unavailable', 'AEGIS returned a malformed response; no order is sent', {'status': status})
        if not isinstance(parsed, dict):
            raise OrderRejected(503, 'aegis_unavailable', 'AEGIS returned a malformed response; no order is sent', {'status': status})
        if status >= 500:
            raise OrderRejected(503, 'aegis_unavailable', 'AEGIS returned a server error; no order is sent', {'status': status})
        return status, parsed

    # ---------------------------------------------------------------- flow
    def authorize(self, intent: OrderIntent, client_order_id: str, evidence: dict) -> Authorization:
        if intent.order_type not in AUTHORIZABLE_TYPES:
            raise OrderRejected(409, 'aegis_unsupported_order_type', f'{intent.order_type} orders cannot be authorized through AEGIS yet')
        params = order_params(intent, client_order_id, float(evidence['reference_price']) * float(intent.quantity))
        body = {
            'tool': self.tool, 'action': 'execute', 'params': params, 'executionMode': 'agent',
            'idempotencyKey': 'quantos:' + client_order_id, 'correlationId': client_order_id,
            'justification': params['reason'],
            'context': {'source': intent.source, 'strategyId': intent.strategy_id, 'quantosChecks': {
                k: evidence.get(k) for k in ('equity', 'drawdown_pct', 'post_gross_pct', 'post_symbol_pct', 'risk_reducing', 'quote_source')}},
        }
        status, r = self._call('POST', '/v1/gateway/actions', self.agent_key, body)
        decision = r.get('decision')
        rid = r.get('requestId')
        details = {'aegis_request_id': rid, 'decision': decision, 'reasons': r.get('reasons', [])}
        if status == 409:
            raise OrderRejected(409, 'aegis_conflict', 'AEGIS refused the request (idempotency conflict)', details)
        if not isinstance(rid, str) or not rid:
            raise OrderRejected(503, 'aegis_unavailable', 'AEGIS response had no request id; no order is sent', {'status': status})
        if decision == 'restrict':
            # Quant OS never silently sends different parameters from the ones it decided on.
            raise OrderRejected(409, 'aegis_restricted', 'AEGIS would only allow modified parameters; the order is not sent', {**details, 'restrictions': r.get('restrictions')})
        if decision in ('require_approval', 'quarantine', 'request_more_information') and r.get('status') not in ('approved',):
            raise OrderRejected(409, 'aegis_approval_pending', 'AEGIS is holding this order for review; retry with the same idempotency key after approval', {**details, 'approval': r.get('approval')})
        if status == 403 or decision in ('deny', 'error'):
            raise OrderRejected(409, 'aegis_denied', 'AEGIS denied the order', details)
        if r.get('status') not in ('allowed', 'approved'):
            raise OrderRejected(409, 'aegis_not_executable', f"AEGIS request is {r.get('status')}; no new grant can be issued", details)
        grant = (r.get('grant') or {}).get('token') if isinstance(r.get('grant'), dict) else None
        expires = (r.get('grant') or {}).get('expiresAt', '') if isinstance(r.get('grant'), dict) else ''
        if not grant:
            # Approved after a hold, or a repeated submission: fetch the single live grant.
            gs, g = self._call('POST', f'/v1/gateway/actions/{rid}/grant', self.agent_key, {})
            if gs != 200 or not isinstance(g.get('grant'), str):
                raise OrderRejected(409, 'aegis_no_grant', 'AEGIS did not issue an execution grant', {**details, 'status': gs, 'error': g.get('error')})
            grant, expires = g['grant'], str(g.get('expiresAt', ''))
        return Authorization(rid, grant, expires, params, decision or r.get('status'), list(r.get('policyVersionIds') or []))

    def verify(self, auth: Authorization, intent: OrderIntent, client_order_id: str) -> None:
        """Consumes the grant for the parameters about to be sent. A replayed, expired, voided or
        mismatched grant is refused by AEGIS, and nothing is sent."""
        params = order_params(intent, client_order_id, auth.params['notional'])
        status, r = self._call('POST', '/v1/gateway/grants/verify', self.integration_key,
                               {'grant': auth.grant, 'toolKey': self.tool, 'action': 'execute', 'params': params})
        if status != 200 or r.get('ok') is not True or r.get('actionRequestId') != auth.request_id:
            raise OrderRejected(409, 'aegis_grant_rejected', f"AEGIS refused the grant: {r.get('reason') or r.get('error') or status}",
                                {'aegis_request_id': auth.request_id, 'reason': r.get('reason')})
        auth.verified = True

    def report(self, auth: Authorization, outcome: str, reference: str | None, summary: dict) -> bool:
        try:
            status, _ = self._call('POST', f'/v1/gateway/actions/{auth.request_id}/execute', self.agent_key,
                                   {'grant': auth.grant, 'outcome': outcome, 'reference': reference, 'summary': summary})
            return status == 200
        except OrderRejected:
            return False
