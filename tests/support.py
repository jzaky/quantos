"""Test harness for Quant OS.

- Loads the repository root as the package ``quantos`` (as the Railway image does with /srv/quantos),
  without putting the repository root on sys.path.
- Points every SQLite database at a temporary directory.
- Blocks all network access except loopback, so no test can reach a real broker or market-data service.
- Replaces market data with deterministic, offline quotes and bars.
- Registers a fake paper broker that records every call, so tests can count what reached the "broker".
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent

# The repository root must never be importable as a top-level path.
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != ROOT]
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import fakes  # noqa: E402  (the fake broker book; reloaded on each load())

# ---------------------------------------------------------------- network guard
_real_connect = socket.socket.connect
_real_create_connection = socket.create_connection


def _is_loopback(address) -> bool:
    host = address[0] if isinstance(address, tuple) else address
    return host in ("127.0.0.1", "::1", "localhost")


def _guarded_connect(self, address):
    if not _is_loopback(address):
        raise ConnectionRefusedError(f"network access blocked in tests: {address!r}")
    return _real_connect(self, address)


def _guarded_create_connection(address, *args, **kwargs):
    if not _is_loopback(address):
        raise ConnectionRefusedError(f"network access blocked in tests: {address!r}")
    return _real_create_connection(address, *args, **kwargs)


socket.socket.connect = _guarded_connect
socket.create_connection = _guarded_create_connection

# ---------------------------------------------------------------- environment
ADMIN_TOKEN = "test-admin-token-0123456789"
os.environ["QOS_ADMIN_TOKEN"] = ADMIN_TOKEN
os.environ["QOS_BOOTSTRAP_TOKEN"] = "test-bootstrap-token"
os.environ["QOS_ENV"] = "test"
os.environ["QOS_WRITE_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["QOS_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["QOS_SECRET_FAKE_API_KEY"] = "fake-key"
os.environ["QOS_SECRET_FAKE_API_SECRET"] = "fake-secret"

QUOTES: dict[str, dict] = {}  # symbol -> {"price": float, "stale": bool, "age": float}
BARS = {"offset": 0}  # whole 5-minute bars added to the clock, so a test can move to the next signal bar


def advance_bar(n: int = 1) -> None:
    BARS["offset"] += n


def set_quote(symbol: str, price: float = 100.0, stale: bool = False, age: float = 0.0) -> None:
    QUOTES[symbol.upper()] = {"price": price, "stale": stale, "age": age}


def _purge():
    for name in list(sys.modules):
        if name == "quantos" or name.startswith("quantos."):
            del sys.modules[name]


def load(data_dir: str) -> SimpleNamespace:
    """Fresh import of the whole package against ``data_dir``. Calling it again with the same
    directory simulates a process restart: all in-memory state is lost, the databases remain."""
    _purge()
    os.environ["QOS_DATA_DIR"] = data_dir
    spec = importlib.util.spec_from_file_location("quantos", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["quantos"] = pkg
    spec.loader.exec_module(pkg)

    store = importlib.import_module("quantos.store")
    tenant_store = importlib.import_module("quantos.tenant_store")
    store.DB_PATH = Path(data_dir) / "quant_os.db"
    tenant_store.DB_PATH = Path(data_dir) / "quant_os_saas.db"

    market_data = importlib.import_module("quantos.market_data")

    def fake_quote(self, symbol):
        s = symbol.upper().strip()
        q = QUOTES.get(s, {"price": 100.0, "stale": False, "age": 0.0})
        return market_data.Quote(s, float(q["price"]), time.time() - float(q["age"]), "test", bool(q["stale"]))

    def fake_history(self, symbol, period="3mo", interval="1d"):
        price = QUOTES.get(symbol.upper(), {"price": 100.0})["price"]
        last = (int(time.time()) // 300 + BARS["offset"]) * 300  # bar timestamps are stable within a bar, like real data
        return [{"ts": last - (59 - i) * 300, "open": price, "high": price, "low": price, "close": price, "volume": 1000} for i in range(60)]

    market_data.MarketDataHub.quote = fake_quote
    market_data.MarketDataHub.history = fake_history

    registry = importlib.import_module("quantos.registry")
    fakes = importlib.import_module("fakes")
    importlib.reload(fakes)
    fake_cls = fakes.make_fake_broker(importlib.import_module("quantos.base"))
    registry.register(fake_cls)

    main = importlib.import_module("quantos.main")
    tracking = importlib.import_module("quantos.tracking")
    saas_engine = importlib.import_module("quantos.saas_engine")
    api_saas = importlib.import_module("quantos.api_saas")

    # What the FastAPI startup hook does, without starting the background trading loops.
    store.init_db()
    tenant_store.init_db()
    tracking.init_tracking()
    tenant_store.ensure_automation_schema()
    tenant_store.migrate_production_schema()
    if hasattr(main, "order_safety"):
        main.order_safety.init_schema()
    main.state["engineRunning"] = False

    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    return SimpleNamespace(pkg=pkg, main=main, store=store, tenant_store=tenant_store, tracking=tracking,
                           saas_engine=saas_engine, api_saas=api_saas, registry=registry, FakeBroker=fake_cls,
                           fakes=fakes, client=client)


def workspace(q: SimpleNamespace, book: str, *, price: float = 100.0, cash: float = 100_000.0, role: str = "admin", **broker_config):
    """A workspace with an armed fake paper connection. Returns (workspace_id, api_key, connection_id)."""
    ws, key = q.tenant_store.create_workspace("Test " + book)
    if role != "admin":
        _, key = q.tenant_store.issue_api_key(ws["id"], role + " key", role)
    config = {"book": book, "price": price, "cash": cash, **broker_config}
    conn = q.tenant_store.create_connection(ws["id"], "fake_paper", "Fake " + book, "FAKE", config, True)
    q.fakes.reset_book(book, price=price, cash=cash, positions=broker_config.get("positions"))
    set_quote("NVDA", price)
    set_quote("AAPL", price)
    return ws["id"], key, conn["id"]


def order_body(conn_id: str, **over):
    body = {"connection_id": conn_id, "symbol": "NVDA", "side": "buy", "quantity": 10, "order_type": "market", "time_in_force": "day"}
    body.update(over)
    return body


def automation_config(ws_id: str, conn_id: str, **over):
    cfg = {"workspace_id": ws_id, "connection_id": conn_id, "enabled": True,
           "strategies": [{"strategy_id": "vector-momentum", "symbol": "NVDA"}],
           "min_confidence": 0.6, "max_order_notional": 1000.0, "requested_risk_pct": 0.2, "cooldown_seconds": 60}
    cfg.update(over)
    return cfg


def force_buy_signals(q: SimpleNamespace):
    """Make the automation layer produce an eligible BUY for every configured strategy, so the
    tests exercise the order path rather than the research models."""
    se = q.saas_engine
    strategies = importlib.import_module("quantos.strategies")
    smart = importlib.import_module("quantos.smart_quant")

    def run_strategy(sid, symbol, bars):
        return strategies.Signal(sid, symbol, 0.9, 0.95, "BUY", "test signal")

    def evaluate_candidate(sid, symbol, score, confidence, bars, other=None, **kw):
        return smart.TradeIntelligence(sid, symbol, "TREND", 0.9, 0.01, 0.01, 0.5, 20.0, 4.0, 16.0, 0.0, 1.0, 0.9, True, [])

    se.run_strategy = run_strategy
    se.evaluate_candidate = evaluate_candidate
    se.backtest = lambda sid, symbol, bars, *a, **k: {"metrics": {"sharpe": 2.0}}
    se.health_score = lambda *a, **k: 90.0
    se.health_state = lambda h: "FULL"
    se.validation_report = lambda *a, **k: {"eligible": True, "kelly": {"fractionalKelly": 0.05}}
