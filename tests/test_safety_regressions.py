"""Regression tests for the order-safety defects found in the audit of commit 8c27f61.

Each test was written before its fix and failed against 8c27f61; the docstring names the defect.
No test reaches a real broker: the fake paper broker records every call, and the network is blocked.
"""
from __future__ import annotations

import tempfile
import unittest

import support
from support import ADMIN_TOKEN, order_body

ADMIN = {"X-QOS-Admin-Token": ADMIN_TOKEN}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.q = support.load(self.dir)
        self.c = self.q.client

    def tearDown(self):
        self._tmp.cleanup()

    def restart(self):
        self.q = support.load(self.dir)
        self.c = self.q.client

    def order(self, key, conn_id, idem, **over):
        return self.c.post("/api/v1/orders", headers={"X-QOS-API-Key": key, "X-QOS-Idempotency-Key": idem}, json=order_body(conn_id, **over))

    def engage_platform(self):
        r = self.c.post("/api/risk/kill-switch", headers=ADMIN, json={"enabled": True, "reason": "test"})
        self.assertEqual(r.status_code, 200, r.text)


class KillSwitch(Base):
    def test_kill_switch_persists_across_restart(self):
        """Defect Q3: the kill switch lived only in process memory and reset to off on restart."""
        self.engage_platform()
        self.restart()
        snap = self.c.get("/api/snapshot").json()
        self.assertEqual(snap["riskState"], "HALTED")
        ws, key, conn = support.workspace(self.q, "persist")
        r = self.order(key, conn, "after-restart")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(support.fakes.submits("persist"), [])

    def test_kill_switch_changes_require_authentication(self):
        """Defect Q4: anyone who could reach the API could turn the kill switch off."""
        self.assertEqual(self.c.post("/api/risk/kill-switch", json={"enabled": True}).status_code, 401)
        self.engage_platform()
        self.assertEqual(self.c.post("/api/risk/kill-switch", json={"enabled": False}).status_code, 401)
        bad = self.c.post("/api/risk/kill-switch", headers={"X-QOS-Admin-Token": "wrong"}, json={"enabled": False})
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(self.c.get("/api/snapshot").json()["riskState"], "HALTED")

    def test_workspace_users_can_engage_but_only_platform_admin_releases(self):
        """Defect Q4 (authorization): engaging is safety-positive; releasing needs the platform admin token."""
        ws, key, conn = support.workspace(self.q, "authz")
        engage = self.c.post("/api/risk/kill-switch", headers={"X-QOS-API-Key": key}, json={"enabled": True})
        self.assertEqual(engage.status_code, 200, engage.text)
        release = self.c.post("/api/risk/kill-switch", headers={"X-QOS-API-Key": key}, json={"enabled": False})
        self.assertEqual(release.status_code, 403, release.text)
        ok = self.c.post("/api/risk/kill-switch", headers=ADMIN, json={"enabled": False})
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_manual_broker_order_blocked_by_platform_kill_switch(self):
        """Defect Q1: the broker order route never checked the kill switch."""
        ws, key, conn = support.workspace(self.q, "manual-kill")
        self.engage_platform()
        r = self.order(key, conn, "k1")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(support.fakes.submits("manual-kill"), [])

    def test_manual_broker_order_blocked_by_workspace_kill_switch(self):
        """Defect Q1 and Q3: there was no per-workspace kill switch for broker orders."""
        ws, key, conn = support.workspace(self.q, "ws-kill")
        r = self.c.post("/api/v1/kill-switch", headers={"X-QOS-API-Key": key}, json={"enabled": True, "reason": "test"})
        self.assertEqual(r.status_code, 200, r.text)
        blocked = self.order(key, conn, "k2")
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(support.fakes.submits("ws-kill"), [])

    def test_automation_blocked_by_kill_switch(self):
        """Defect Q2: automation called the governor with kill_switch=False and never checked the switch."""
        ws, key, conn = support.workspace(self.q, "auto-kill")
        support.force_buy_signals(self.q)
        self.engage_platform()
        self.q.saas_engine.cycle_workspace(support.automation_config(ws, conn))
        self.assertEqual(support.fakes.submits("auto-kill"), [])

    def test_simulator_honours_persisted_kill_switch(self):
        """Defect Q3 (simulator path): after a restart the simulated engine traded again."""
        self.engage_platform()
        self.restart()
        r = self.c.post("/api/paper/orders/submit", json={"symbol": "NVDA", "side": "BUY", "quantity": 1, "strategy_id": "vector-momentum", "confidence": 0.9, "requested_risk_pct": 0.2})
        self.assertEqual(r.status_code, 409, r.text)


class RiskGovernor(Base):
    def test_manual_order_enforces_risk_governor(self):
        """Defect Q1: manual broker orders skipped the risk governor (here, symbol exposure above 12% of equity)."""
        ws, key, conn = support.workspace(self.q, "governor")
        r = self.order(key, conn, "big", quantity=200)  # 20,000 of 100,000 equity = 20% in one symbol
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(support.fakes.submits("governor"), [])

    def test_automation_uses_live_drawdown(self):
        """Defect Q2: automation passed drawdown=0.0 regardless of the account's real drawdown."""
        ws, key, conn = support.workspace(self.q, "drawdown")
        support.force_buy_signals(self.q)
        # First cycle records the account's high-water mark (100,000) and may trade.
        self.q.saas_engine.cycle_workspace(support.automation_config(ws, conn, cooldown_seconds=60))
        before = len(support.fakes.submits("drawdown"))
        # The account loses 5% (governor limit is 3%).
        support.fakes.book("drawdown")["cash"] -= 5_000 + 0.0
        self.q.tenant_store.connect().execute("DELETE FROM automation_state").connection.commit()
        self.q.saas_engine.cycle_workspace(support.automation_config(ws, conn, cooldown_seconds=60))
        self.assertEqual(len(support.fakes.submits("drawdown")), before, "an order was placed while drawdown exceeded the limit")

    def test_manual_order_rejected_when_account_unavailable(self):
        """Required risk information unavailable: the order must be rejected, not sent."""
        ws, key, conn = support.workspace(self.q, "no-account")
        support.fakes.book("no-account")["fail_account"] = True
        r = self.order(key, conn, "na")
        self.assertIn(r.status_code, (409, 503), r.text)
        self.assertEqual(support.fakes.submits("no-account"), [])

    def test_manual_order_rejected_when_positions_unavailable(self):
        ws, key, conn = support.workspace(self.q, "no-positions")
        support.fakes.book("no-positions")["fail_positions"] = True
        r = self.order(key, conn, "np")
        self.assertIn(r.status_code, (409, 503), r.text)
        self.assertEqual(support.fakes.submits("no-positions"), [])

    def test_manual_market_order_rejected_on_stale_price(self):
        """A market order must not be sized or checked against a stale or synthetic price."""
        ws, key, conn = support.workspace(self.q, "stale")
        support.set_quote("NVDA", 100.0, stale=True)
        r = self.order(key, conn, "st")
        self.assertIn(r.status_code, (409, 503), r.text)
        self.assertEqual(support.fakes.submits("stale"), [])

    def test_automation_rejected_when_account_unavailable(self):
        """Preserved behaviour: automation already stopped when the broker account could not be read."""
        ws, key, conn = support.workspace(self.q, "auto-na")
        support.force_buy_signals(self.q)
        support.fakes.book("auto-na")["fail_account"] = True
        self.q.saas_engine.cycle_workspace(support.automation_config(ws, conn))
        self.assertEqual(support.fakes.submits("auto-na"), [])


class Idempotency(Base):
    def test_manual_retry_after_broker_timeout_does_not_duplicate(self):
        """Defect Q5 (manual): the idempotency record was written only after success, so a retry after a
        timeout sent a second order with a new client_order_id."""
        ws, key, conn = support.workspace(self.q, "dup-manual")
        support.fakes.book("dup-manual")["timeout_after_place"] = 1
        first = self.order(key, conn, "same-key")
        self.assertNotEqual(first.status_code, 200)
        self.order(key, conn, "same-key")
        self.order(key, conn, "same-key")
        self.assertEqual(support.fakes.placed("dup-manual"), 1, support.fakes.book("dup-manual")["calls"])

    def test_retry_reconciles_before_resubmitting(self):
        """An uncertain outcome is looked up at the broker before any retry is sent."""
        ws, key, conn = support.workspace(self.q, "reconcile")
        support.fakes.book("reconcile")["timeout_after_place"] = 1
        self.order(key, conn, "rk")
        retry = self.order(key, conn, "rk")
        self.assertEqual(retry.status_code, 200, retry.text)
        calls = [c[0] for c in support.fakes.book("reconcile")["calls"]]
        self.assertIn("lookup", calls)
        self.assertEqual(calls.count("submit"), 1, calls)

    def test_automation_retry_after_broker_timeout_does_not_duplicate(self):
        """Defect Q5 (automation): a random client_order_id per attempt meant a retry after a lost
        response placed the order twice."""
        ws, key, conn = support.workspace(self.q, "dup-auto")
        support.force_buy_signals(self.q)
        support.fakes.book("dup-auto")["timeout_after_place"] = 1
        cfg = support.automation_config(ws, conn)
        self.q.saas_engine.cycle_workspace(cfg)
        self.q.saas_engine.cycle_workspace(cfg)
        self.assertEqual(support.fakes.placed("dup-auto"), 1, support.fakes.book("dup-auto")["calls"])


class SinglePath(Base):
    def test_manual_and_automated_orders_use_the_same_safety_checks(self):
        """All execution paths go through one order-safety function."""
        import importlib
        safety = importlib.import_module("quantos.order_safety")
        seen = []
        real = safety.submit_order

        def spy(intent, **kw):
            seen.append(intent.source)
            return real(intent, **kw)

        safety.submit_order = spy
        try:
            ws, key, conn = support.workspace(self.q, "single")
            support.force_buy_signals(self.q)
            self.order(key, conn, "s1", quantity=1)
            self.q.saas_engine.cycle_workspace(support.automation_config(ws, conn))
        finally:
            safety.submit_order = real
        self.assertIn("manual", seen)
        self.assertIn("automation", seen)
        for call in support.fakes.book("single")["calls"]:
            if call[0] == "submit":
                self.assertTrue(str(call[1]).startswith("qos-"), call)


if __name__ == "__main__":
    unittest.main()
