"""A fake paper broker that records every call. It behaves like Alpaca in the ways the safety tests
depend on: client_order_id must be unique, and an order can be looked up by client_order_id."""
from __future__ import annotations

import time
import uuid

BOOKS: dict[str, dict] = {}


def reset_book(name: str, *, price: float = 100.0, cash: float = 100_000.0, positions: dict | None = None):
    BOOKS[name] = {
        "price": price, "cash": cash, "positions": dict(positions or {}), "orders": {}, "calls": [],
        "fail_account": False, "fail_positions": False, "account_status": "ACTIVE",
        "timeout_after_place": 0,   # next N submits place the order, then raise a timeout
        "timeout_before_place": 0,  # next N submits raise a timeout without placing
        "reject_next": 0,
        "submit_delay": 0.0,
    }
    return BOOKS[name]


def book(name: str) -> dict:
    return BOOKS[name]


def make_fake_broker(base):
    Rejected = getattr(base, "BrokerRejected", RuntimeError)
    Unknown = getattr(base, "BrokerOutcomeUnknown", TimeoutError)
    Unavailable = getattr(base, "BrokerUnavailable", RuntimeError)

    class FakePaperBroker(base.BrokerAdapter):
        slug = "fake_paper"
        label = "Fake Paper (tests)"
        paper_only = True

        def __init__(self, credentials, config=None):
            super().__init__(credentials, config)
            self.name = self.config.get("book", "default")
            if self.name not in BOOKS:
                reset_book(self.name, price=float(self.config.get("price", 100.0)), cash=float(self.config.get("cash", 100_000.0)))
            self.b = BOOKS[self.name]

        def _mv(self):
            return sum(q * self.b["price"] for q in self.b["positions"].values())

        def account(self):
            self.b["calls"].append(("account",))
            if self.b["fail_account"]:
                raise Unavailable("account endpoint unavailable")
            eq = self.b["cash"] + self._mv()
            return base.BrokerAccount(self.slug, "fake-" + self.name, self.b["account_status"], "USD", eq, self.b["cash"], max(eq * 2, 0), True)

        def list_positions(self):
            self.b["calls"].append(("positions",))
            if self.b["fail_positions"]:
                raise Unavailable("positions endpoint unavailable")
            p = self.b["price"]
            return [base.BrokerPosition(self.slug, s, q, p, q * p, 0.0, "long" if q >= 0 else "short") for s, q in self.b["positions"].items() if abs(q) > 1e-12]

        def _place(self, o):
            cid = o.client_order_id or ""
            if cid and cid in {x.client_order_id for x in self.b["orders"].values()}:
                raise Rejected("client_order_id must be unique")
            oid = str(uuid.uuid4())
            signed = o.quantity if o.side == "buy" else -o.quantity
            self.b["positions"][o.symbol.upper()] = self.b["positions"].get(o.symbol.upper(), 0) + signed
            self.b["cash"] -= signed * self.b["price"]
            r = base.BrokerOrder(self.slug, oid, cid, o.symbol.upper(), o.side, o.quantity, o.order_type, "filled", o.quantity, self.b["price"], str(time.time()), {"limit_price": o.limit_price, "stop_price": o.stop_price, "time_in_force": o.time_in_force})
            self.b["orders"][oid] = r
            return r

        def submit_order(self, o):
            self.b["calls"].append(("submit", o.client_order_id, o.symbol, o.side, o.quantity, o.order_type, o.limit_price))
            if self.b["submit_delay"]:
                time.sleep(self.b["submit_delay"])
            if self.b["reject_next"]:
                self.b["reject_next"] -= 1
                raise Rejected("insufficient buying power")
            if self.b["timeout_before_place"]:
                self.b["timeout_before_place"] -= 1
                raise Unknown("timed out before the broker answered")
            r = self._place(o)
            if self.b["timeout_after_place"]:
                self.b["timeout_after_place"] -= 1
                raise Unknown("timed out after the request was sent")
            return r

        def get_order_by_client_order_id(self, client_order_id):
            self.b["calls"].append(("lookup", client_order_id))
            for r in self.b["orders"].values():
                if r.client_order_id == client_order_id:
                    return r
            return None

        def get_order(self, broker_order_id):
            return self.b["orders"][broker_order_id]

        def cancel_order(self, broker_order_id):
            return broker_order_id in self.b["orders"]

        def close_position(self, symbol):
            return None

    return FakePaperBroker


def submits(name: str) -> list:
    return [c for c in BOOKS[name]["calls"] if c[0] == "submit"]


def placed(name: str) -> int:
    return len(BOOKS[name]["orders"])
