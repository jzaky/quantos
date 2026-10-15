"""AEGIS authorization (Priority 2) against the local AEGIS stand-in. No real broker, no network.

Every test counts what reached the fake paper broker. "No order" means zero submit calls.
"""
from __future__ import annotations

import os
import socket
import tempfile
import unittest

import support
from aegis_standin import AGENT_KEY, INTEGRATION_KEY, StandIn

ADMIN = {"X-QOS-Admin-Token": support.ADMIN_TOKEN}
AEGIS_ENV = ("QOS_AEGIS_URL", "QOS_AEGIS_AGENT_KEY", "QOS_AEGIS_INTEGRATION_KEY", "QOS_AEGIS_TIMEOUT_SECONDS", "QOS_AEGIS_TOOL")


def closed_port_url() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


class AegisBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.q = support.load(self._tmp.name)
        self.c = self.q.client
        self.aegis = StandIn()
        self._env = {k: os.environ.get(k) for k in AEGIS_ENV}
        os.environ.update({"QOS_AEGIS_URL": self.aegis.url, "QOS_AEGIS_AGENT_KEY": AGENT_KEY,
                           "QOS_AEGIS_INTEGRATION_KEY": INTEGRATION_KEY, "QOS_AEGIS_TIMEOUT_SECONDS": "0.5"})
        self.ws, self.key, self.conn = support.workspace(self.q, "aegis")

    def tearDown(self):
        self.aegis.close()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def order(self, idem, **over):
        return self.c.post("/api/v1/orders", headers={"X-QOS-API-Key": self.key, "X-QOS-Idempotency-Key": idem},
                           json=support.order_body(self.conn, **over))

    def submits(self):
        return support.fakes.submits("aegis")

    def code(self, r):
        d = r.json().get("detail")
        return d.get("code") if isinstance(d, dict) else d


class Flow(AegisBase):
    def test_authorized_order_follows_the_nine_steps(self):
        r = self.order("flow-1")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # 3-5: one AEGIS request in agent mode with the exact parameters; a grant was issued.
        reqs = self.aegis.paths("/v1/gateway/actions")
        self.assertEqual(len(reqs), 1)
        p = reqs[0]["params"]
        self.assertEqual(reqs[0]["executionMode"], "agent")
        self.assertEqual((p["symbol"], p["side"], p["type"], p["qty"], p["timeInForce"]), ("NVDA", "buy", "market", 10, "day"))
        self.assertEqual(p["reference"], body["client_order_id"])
        # 6: the grant was verified once, with the integration key, and consumed.
        self.assertEqual(len(self.aegis.paths("/grants/verify")), 1)
        # 7: exactly the authorized order reached the broker, under the authorized reference.
        sub = self.submits()
        self.assertEqual(len(sub), 1)
        self.assertEqual(sub[0][1:6], (p["reference"], "NVDA", "buy", 10.0, "market"))
        # 8-9: the broker outcome was reported to AEGIS and recorded on the Quant OS side.
        ex = self.aegis.paths("/execute")
        self.assertEqual(len(ex), 1)
        self.assertEqual(ex[0]["outcome"], "succeeded")
        self.assertEqual(ex[0]["reference"], body["order"]["broker_order_id"])
        self.assertTrue(body["authorization"]["verified"])
        self.assertTrue(body["authorization"]["outcome_reported"])
        events = [e["type"] for e in self.q.tenant_store.list_events(self.ws, 50)]
        self.assertIn("broker_order_submitted", events)
        self.assertIn("aegis_outcome_reported", events)

    def test_aegis_never_receives_broker_credentials(self):
        self.order("creds-1")
        for _, _, b in self.aegis.calls:
            text = str(b)
            self.assertNotIn("fake-key", text)
            self.assertNotIn("fake-secret", text)

    def test_automation_is_authorized_too(self):
        support.force_buy_signals(self.q)
        self.q.saas_engine.cycle_workspace(support.automation_config(self.ws, self.conn))
        self.assertEqual(len(self.submits()), 1)
        self.assertEqual(len(self.aegis.paths("/grants/verify")), 1)
        self.assertEqual(self.aegis.paths("/v1/gateway/actions")[0]["context"]["source"], "automation")


class GatewayFailure(AegisBase):
    def assert_refused(self, idem, status, code):
        r = self.order(idem)
        self.assertEqual(r.status_code, status, r.text)
        self.assertEqual(self.code(r), code)
        self.assertEqual(self.submits(), [])

    def test_gateway_unavailable(self):
        os.environ["QOS_AEGIS_URL"] = closed_port_url()
        self.assert_refused("down-1", 503, "aegis_unavailable")

    def test_gateway_timeout(self):
        self.aegis.fault = "timeout"
        self.assert_refused("timeout-1", 503, "aegis_unavailable")

    def test_gateway_server_error(self):
        self.aegis.fault = "500"
        self.assert_refused("err-1", 503, "aegis_unavailable")

    def test_gateway_malformed_response(self):
        self.aegis.fault = "malformed"
        self.assert_refused("bad-1", 503, "aegis_unavailable")

    def test_misconfigured_keys_fail_closed(self):
        os.environ["QOS_AEGIS_INTEGRATION_KEY"] = ""
        self.assert_refused("cfg-1", 503, "aegis_misconfigured")

    def test_plain_http_to_a_remote_host_is_refused(self):
        os.environ["QOS_AEGIS_URL"] = "http://aegis.example.com"
        self.assert_refused("cfg-2", 503, "aegis_misconfigured")

    def test_unavailable_during_verification(self):
        """AEGIS answered the decision, then failed before verification: nothing is sent."""
        self.aegis.fail_paths.add("/grants/verify")
        r = self.order("verify-down")
        self.assertEqual((r.status_code, self.code(r)), (503, "aegis_unavailable"), r.text)
        self.assertEqual(len(self.aegis.paths("/v1/gateway/actions")), 1)
        self.assertEqual(self.submits(), [])


class Decisions(AegisBase):
    def test_denied(self):
        self.aegis.mode = "deny"
        r = self.order("deny-1")
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_denied"), r.text)
        self.assertEqual(self.submits(), [])

    def test_restricted_parameters_are_not_sent(self):
        self.aegis.mode = "restrict"
        r = self.order("restrict-1")
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_restricted"), r.text)
        self.assertEqual(self.submits(), [])

    def test_held_for_approval_then_approved(self):
        self.aegis.mode = "approval"
        r = self.order("appr-1")
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_approval_pending"), r.text)
        self.assertEqual(self.submits(), [])
        rid = r.json()["detail"]["details"]["aegis_request_id"]
        self.aegis.approve(rid)
        ok = self.order("appr-1")
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(len(self.submits()), 1)
        self.assertEqual(len(self.aegis.paths("/v1/gateway/actions")), 2)  # same AEGIS request, by idempotency key
        self.assertEqual(len(self.aegis.requests), 1)


class Grants(AegisBase):
    def test_expired_grant(self):
        self.aegis.grant_ttl = -1
        r = self.order("exp-1")
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_grant_rejected"), r.text)
        self.assertIn("expired", r.text)
        self.assertEqual(self.submits(), [])

    def test_voided_grant_after_aegis_pause(self):
        real_verify = self.q.pkg.aegis_client.AegisClient.verify

        def pause_then_verify(client, auth, intent, cid):
            self.aegis.pause()
            return real_verify(client, auth, intent, cid)
        self.q.pkg.aegis_client.AegisClient.verify = pause_then_verify
        try:
            r = self.order("void-1")
        finally:
            self.q.pkg.aegis_client.AegisClient.verify = real_verify
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_grant_rejected"), r.text)
        self.assertIn("voided", r.text)
        self.assertEqual(self.submits(), [])

    def test_replayed_grant_is_refused(self):
        ac = self.q.pkg.aegis_client
        captured = {}
        real_verify = ac.AegisClient.verify

        def capture(client, auth, intent, cid):
            captured.update(client=client, auth=auth, intent=intent, cid=cid)
            return real_verify(client, auth, intent, cid)
        ac.AegisClient.verify = capture
        try:
            self.assertEqual(self.order("replay-1").status_code, 200)
        finally:
            ac.AegisClient.verify = real_verify
        with self.assertRaises(self.q.pkg.order_safety.OrderRejected) as e:
            captured["client"].verify(captured["auth"], captured["intent"], captured["cid"])
        self.assertEqual(e.exception.code, "aegis_grant_rejected")
        self.assertIn("consumed", e.exception.message)
        self.assertEqual(len(self.submits()), 1)

    def test_changed_parameters_invalidate_the_grant(self):
        """Any material change after authorization (here the quantity) fails verification."""
        ac = self.q.pkg.aegis_client
        real_authorize = ac.AegisClient.authorize

        def tamper(client, intent, cid, evidence):
            auth = real_authorize(client, intent, cid, evidence)
            intent.quantity = 11  # changed after AEGIS decided
            return auth
        ac.AegisClient.authorize = tamper
        try:
            r = self.order("tamper-1")
        finally:
            ac.AegisClient.authorize = real_authorize
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_grant_rejected"), r.text)
        self.assertIn("hash_mismatch", r.text)
        self.assertEqual(self.submits(), [])

    def test_changed_parameters_under_the_same_key_are_refused(self):
        self.assertEqual(self.order("same-key").status_code, 200)
        r = self.order("same-key", quantity=11)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(len(self.submits()), 1)

    def test_unsupported_order_type(self):
        r = self.order("stop-1", order_type="stop", stop_price=90)
        self.assertEqual((r.status_code, self.code(r)), (409, "aegis_unsupported_order_type"), r.text)
        self.assertEqual(self.submits(), [])


class IndependentControls(AegisBase):
    """Quant OS's own controls still apply when AEGIS says allow."""

    def test_kill_switch_blocks_before_aegis_is_asked(self):
        self.c.post("/api/risk/kill-switch", headers=ADMIN, json={"enabled": True})
        r = self.order("ks-1")
        self.assertEqual((r.status_code, self.code(r)), (409, "kill_switch_engaged"), r.text)
        self.assertEqual(self.aegis.calls, [])
        self.assertEqual(self.submits(), [])

    def test_kill_switch_engaged_after_authorization_blocks_and_leaves_grant_unused(self):
        ac = self.q.pkg.aegis_client
        real_authorize = ac.AegisClient.authorize
        osf = self.q.pkg.order_safety

        def authorize_then_halt(client, intent, cid, evidence):
            auth = real_authorize(client, intent, cid, evidence)
            osf.set_kill_switch(None, True, "test", "halt during authorization")
            return auth
        ac.AegisClient.authorize = authorize_then_halt
        try:
            r = self.order("ks-2")
        finally:
            ac.AegisClient.authorize = real_authorize
        self.assertEqual((r.status_code, self.code(r)), (409, "kill_switch_engaged"), r.text)
        self.assertEqual(self.aegis.paths("/grants/verify"), [])
        self.assertEqual(self.submits(), [])

    def test_risk_governor_blocks_even_if_aegis_allows(self):
        r = self.order("gov-1", quantity=200)
        self.assertEqual((r.status_code, self.code(r)), (409, "risk_governor_blocked"), r.text)
        self.assertEqual(self.aegis.calls, [])
        self.assertEqual(self.submits(), [])

    def test_account_unavailable_blocks_even_if_aegis_allows(self):
        support.fakes.book("aegis")["fail_account"] = True
        r = self.order("acct-1")
        self.assertEqual(r.status_code, 503, r.text)
        self.assertEqual(self.submits(), [])


class BrokerAmbiguity(AegisBase):
    def test_broker_timeout_after_submission_is_reconciled_once(self):
        support.fakes.book("aegis")["timeout_after_place"] = 1
        first = self.order("amb-1")
        self.assertEqual((first.status_code, self.code(first)), (504, "outcome_unknown"), first.text)
        second = self.order("amb-1")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json().get("reconciled"))
        self.assertEqual(support.fakes.placed("aegis"), 1)
        self.assertEqual(len(self.aegis.paths("/v1/gateway/actions")), 1)  # no second authorization
        self.assertEqual(len(self.aegis.paths("/grants/verify")), 1)
        ex = self.aegis.paths("/execute")
        self.assertEqual([e["outcome"] for e in ex], ["succeeded"])

    def test_broker_timeout_before_placement_closes_the_aegis_request(self):
        support.fakes.book("aegis")["timeout_before_place"] = 1
        self.assertEqual(self.order("amb-2").status_code, 504)
        retry = self.order("amb-2")
        # The broker confirms the order is absent; AEGIS is told it failed; a new decision is needed.
        self.assertEqual(retry.status_code, 409, retry.text)
        self.assertEqual(support.fakes.placed("aegis"), 0)
        self.assertEqual([e["outcome"] for e in self.aegis.paths("/execute")], ["failed"])

    def test_broker_rejection_is_reported_as_failed(self):
        support.fakes.book("aegis")["reject_next"] = 1
        r = self.order("rej-1")
        self.assertEqual((r.status_code, self.code(r)), (422, "broker_rejected"), r.text)
        self.assertEqual([e["outcome"] for e in self.aegis.paths("/execute")], ["failed"])


if __name__ == "__main__":
    unittest.main()
