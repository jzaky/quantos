"""Priority 3 failure scenarios not covered by test_safety_regressions.py and test_aegis_authorization.py:
risk governor failure, duplicate requests, concurrent requests, database restart, database
unavailable, and partial system failure. No real broker, no network.
"""
from __future__ import annotations

import os
import tempfile
import threading
import unittest

import support
from aegis_standin import AGENT_KEY, INTEGRATION_KEY, StandIn


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.q = support.load(self.dir)
        self.c = self.q.client
        self.ws, self.key, self.conn = support.workspace(self.q, "matrix")

    def tearDown(self):
        self._tmp.cleanup()

    def order(self, idem, client=None, **over):
        return (client or self.c).post("/api/v1/orders", headers={"X-QOS-API-Key": self.key, "X-QOS-Idempotency-Key": idem},
                                       json=support.order_body(self.conn, **over))

    def submits(self):
        return support.fakes.submits("matrix")


class GovernorFailure(Base):
    def test_risk_governor_exception_refuses_the_order(self):
        rg = self.q.pkg.risk_engine.RiskGovernor
        real = rg.evaluate

        def broken(self_, **kw):
            raise ZeroDivisionError("governor bug")
        rg.evaluate = broken
        try:
            r = self.order("gov-broken")
        finally:
            rg.evaluate = real
        self.assertEqual(r.status_code, 503, r.text)
        self.assertEqual(r.json()["detail"]["code"], "safety_check_failed")
        self.assertEqual(self.submits(), [])
        # Nothing was sent, so the same key can be retried once the fault is fixed.
        self.assertEqual(self.order("gov-broken").status_code, 200)
        self.assertEqual(len(self.submits()), 1)

    def test_automation_survives_governor_exception_without_trading(self):
        support.force_buy_signals(self.q)
        rg = self.q.pkg.risk_engine.RiskGovernor
        real = rg.evaluate
        rg.evaluate = lambda self_, **kw: (_ for _ in ()).throw(RuntimeError("governor bug"))
        try:
            self.q.saas_engine.cycle_workspace(support.automation_config(self.ws, self.conn))
        finally:
            rg.evaluate = real
        self.assertEqual(self.submits(), [])


class Duplicates(Base):
    def test_same_request_twice_places_one_order(self):
        a = self.order("dup-1")
        b = self.order("dup-1")
        self.assertEqual((a.status_code, b.status_code), (200, 200))
        self.assertTrue(b.json().get("idempotent_replay"))
        self.assertEqual(a.json()["client_order_id"], b.json()["client_order_id"])
        self.assertEqual(len(self.submits()), 1)

    def test_same_key_different_order_is_refused(self):
        self.assertEqual(self.order("dup-2").status_code, 200)
        r = self.order("dup-2", side="sell")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(len(self.submits()), 1)

    def test_automation_repeats_on_the_same_signal_bar_place_one_order(self):
        support.force_buy_signals(self.q)
        cfg = support.automation_config(self.ws, self.conn)
        self.q.saas_engine.cycle_workspace(cfg)
        db = self.q.tenant_store.connect()
        db.execute("DELETE FROM automation_state")  # defeat the cooldown: only idempotency remains
        db.commit()
        db.close()
        self.q.saas_engine.cycle_workspace(cfg)
        self.assertEqual(len(self.submits()), 1)


class Concurrency(Base):
    def _parallel(self, n, fn):
        out = [None] * n
        barrier = threading.Barrier(n)

        def run(i):
            barrier.wait()
            out[i] = fn(i)
        threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        return out

    def test_concurrent_requests_with_one_key_place_one_order(self):
        support.fakes.book("matrix")["submit_delay"] = 0.3  # hold the first request inside the broker call
        statuses = self._parallel(6, lambda i: self.order("race-1").status_code)
        self.assertEqual(len(self.submits()), 1, statuses)
        self.assertIn(200, statuses)
        self.assertTrue(all(s in (200, 409) for s in statuses), statuses)

    def test_concurrent_requests_with_different_keys_respect_exposure_limit(self):
        """Ten concurrent 3% orders in one symbol: the 12% symbol limit must hold at the broker."""
        support.fakes.book("matrix")["submit_delay"] = 0.05
        statuses = self._parallel(10, lambda i: self.order(f"race-k{i}", quantity=30).status_code)
        held_pct = support.fakes.book("matrix")["positions"].get("NVDA", 0) * 100.0 / 100_000.0 * 100.0  # qty x price / equity, in percent
        self.assertLessEqual(held_pct, 12.0 + 1e-9, (held_pct, statuses))
        self.assertEqual(statuses.count(200), 4, statuses)  # 4 x 3% fit under 12%; the rest are refused

    def test_concurrent_automation_cycles_place_one_order(self):
        support.force_buy_signals(self.q)
        support.fakes.book("matrix")["submit_delay"] = 0.2
        cfg = support.automation_config(self.ws, self.conn)
        self._parallel(4, lambda i: self.q.saas_engine.cycle_workspace(dict(cfg)))
        self.assertEqual(len(self.submits()), 1)


class DatabaseRestart(Base):
    def test_restart_after_an_unknown_outcome_reconciles_instead_of_resubmitting(self):
        support.fakes.book("matrix")["timeout_after_place"] = 1
        self.assertEqual(self.order("restart-1").status_code, 504)
        self.q = support.load(self.dir)  # process restart: memory gone, databases kept
        retry = self.order("restart-1", client=self.q.client)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(support.fakes.placed("matrix"), 1)
        self.assertEqual([c[0] for c in support.fakes.book("matrix")["calls"]].count("submit"), 1)

    def test_crash_between_send_and_record_is_reconciled_after_restart(self):
        """The process dies after the broker accepted the order but before Quant OS recorded it."""
        osf = self.q.pkg.order_safety
        real = osf._record_submitted

        def crash(*a, **k):
            raise SystemExit("process killed")
        osf._record_submitted = crash
        try:
            with self.assertRaises(BaseException):
                self.order("crash-1")
        finally:
            osf._record_submitted = real
        self.assertEqual(support.fakes.placed("matrix"), 1)
        # The lease of the dead process expires; a restarted process reconciles.
        db = self.q.tenant_store.connect()
        db.execute("UPDATE order_intents SET lease_until=0")
        db.commit()
        db.close()
        self.q = support.load(self.dir)
        retry = self.order("crash-1", client=self.q.client)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertTrue(retry.json().get("reconciled"))
        self.assertEqual(support.fakes.placed("matrix"), 1)

    def test_automation_after_restart_reconciles_pending_orders_first(self):
        support.force_buy_signals(self.q)
        support.fakes.book("matrix")["timeout_after_place"] = 1
        cfg = support.automation_config(self.ws, self.conn)
        self.q.saas_engine.cycle_workspace(cfg)
        self.q = support.load(self.dir)
        support.force_buy_signals(self.q)
        db = self.q.tenant_store.connect()
        db.execute("DELETE FROM automation_state")
        db.commit()
        db.close()
        self.q.saas_engine.cycle_workspace(cfg)
        self.assertEqual(support.fakes.placed("matrix"), 1)
        self.assertIn("lookup", [c[0] for c in support.fakes.book("matrix")["calls"]])


class DatabaseUnavailable(Base):
    def test_kill_switch_state_unreadable_fails_closed(self):
        ts = self.q.tenant_store
        osf = self.q.pkg.order_safety
        real_connect = ts.connect

        def failing_connect():
            raise OSError("database unavailable")
        # Only the kill-switch read fails; everything else works, so the refusal is the switch's.
        real_status = osf.kill_switch_status

        def status(ws=None):
            ts.connect = failing_connect
            try:
                return real_status(ws)
            finally:
                ts.connect = real_connect
        osf.kill_switch_status = status
        try:
            r = self.order("db-down")
        finally:
            osf.kill_switch_status = real_status
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("unreadable", r.text)
        self.assertEqual(self.submits(), [])

    def test_database_unavailable_refuses_the_order(self):
        self.q.tenant_store.DB_PATH = self.q.tenant_store.DB_PATH.parent / "missing-dir" / "x.db"
        try:
            r = self.order("db-gone")
        except Exception as e:  # the API may also fail with a 500 before any broker call
            r = None
            self.assertNotIsInstance(e, AssertionError)
        self.assertTrue(r is None or r.status_code >= 400)
        self.assertEqual(self.submits(), [])


class PartialFailure(Base):
    def setUp(self):
        super().setUp()
        self.aegis = StandIn()
        self._env = {k: os.environ.get(k) for k in ("QOS_AEGIS_URL", "QOS_AEGIS_AGENT_KEY", "QOS_AEGIS_INTEGRATION_KEY", "QOS_AEGIS_TIMEOUT_SECONDS")}
        os.environ.update({"QOS_AEGIS_URL": self.aegis.url, "QOS_AEGIS_AGENT_KEY": AGENT_KEY,
                           "QOS_AEGIS_INTEGRATION_KEY": INTEGRATION_KEY, "QOS_AEGIS_TIMEOUT_SECONDS": "0.5"})

    def tearDown(self):
        self.aegis.close()
        for k, v in self._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def test_outcome_report_failure_does_not_hide_a_placed_order(self):
        self.aegis.fail_paths.add("/execute")
        r = self.order("report-down")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["authorization"]["outcome_reported"])
        self.assertEqual(len(self.submits()), 1)
        types = [e["type"] for e in self.q.tenant_store.list_events(self.ws, 50)]
        self.assertIn("aegis_report_failed", types)
        self.assertIn("broker_order_submitted", types)

    def test_broker_positions_down_with_aegis_up(self):
        support.fakes.book("matrix")["fail_positions"] = True
        r = self.order("pos-down")
        self.assertEqual(r.status_code, 503, r.text)
        self.assertEqual(self.aegis.calls, [])  # Quant OS's own gate refused before asking AEGIS
        self.assertEqual(self.submits(), [])

    def test_concurrent_requests_get_one_grant(self):
        support.fakes.book("matrix")["submit_delay"] = 0.3
        out = []
        barrier = threading.Barrier(4)

        def run():
            barrier.wait()
            out.append(self.order("race-aegis").status_code)
        ts = [threading.Thread(target=run) for _ in range(4)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual(len(self.submits()), 1, out)
        self.assertEqual(len(self.aegis.paths("/grants/verify")), 1, out)


if __name__ == "__main__":
    unittest.main()
