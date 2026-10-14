"""Centralized order safety for every broker-routed order.

Manual orders (POST /api/v1/orders) and automated orders (saas_engine) both call ``submit_order``.
Nothing else in Quant OS calls ``adapter.submit_order``. In order, ``submit_order``:

1. validates the order parameters and the connection (enabled, armed, paper only);
2. records the order intent under the caller's idempotency key, with a hash of the exact parameters
   and a client_order_id derived from that key, so a retry can never become a second order;
3. if an earlier attempt may have reached the broker, looks the order up by client_order_id before
   doing anything else (reconciliation before retry);
4. checks the persisted platform and workspace kill switches (fail closed if they cannot be read);
5. reads live account and position state from the broker and a fresh quote, and refuses the order if
   any of them is unavailable, stale or implausible;
6. runs the risk governor on that live state (drawdown from a persisted high-water mark, post-trade
   gross and single-symbol exposure, and the model checks for automated orders);
7. when AEGIS is configured (QOS_AEGIS_URL), asks it for a decision and a single-use grant, re-runs
   steps 4 to 6 on fresh state, then has the grant verified and consumed for the exact parameters;
8. rechecks the kill switches, sends exactly the checked parameters to the broker, classifies the
   outcome and reports it to AEGIS.

The quantity is never changed here. Sizing happens before the intent is created, so the parameters
that are checked, authorized and sent are the same parameters.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from . import tenant_store
from .base import BrokerOutcomeUnknown, BrokerRejected, SubmitOrder
from .market_data import MarketDataHub
from .risk_engine import RiskGovernor

PLATFORM = 'platform'
LEASE_SECONDS = 60.0
ACCOUNT_LOCK_SECONDS = 60.0
ACCOUNT_LOCK_WAIT = float(os.getenv('QOS_ACCOUNT_LOCK_WAIT_SECONDS', '15'))
OPEN_ORDER_STATUSES_DONE = ('filled', 'canceled', 'cancelled', 'rejected', 'expired', 'done_for_day', 'replaced')

_hub = MarketDataHub()
_governor = RiskGovernor()


class OrderRejected(Exception):
    """An order was refused before or by the broker. ``status`` is the HTTP status to return."""

    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        return {'code': self.code, 'message': self.message, **({'details': self.details} if self.details else {})}


@dataclass
class ModelContext:
    """Inputs the risk governor needs for model-generated orders. Manual orders have none."""
    confidence: float
    requested_risk_pct: float
    regime_fit: float = 1.0
    net_edge_bps: float = 999.0
    correlation_penalty: float = 0.0
    strategy_health: float = 100.0
    health_state: str = 'NORMAL'


@dataclass
class OrderIntent:
    workspace_id: str
    connection_id: str
    symbol: str
    side: str
    quantity: float
    idempotency_key: str
    source: str  # 'manual' or 'automation'
    order_type: str = 'market'
    time_in_force: str = 'day'
    limit_price: float | None = None
    stop_price: float | None = None
    strategy_id: str | None = None
    model: ModelContext | None = None
    metadata: dict = field(default_factory=dict)

    def material(self) -> dict:
        """Every parameter that changes what the broker would do. Bound by the request hash and,
        when AEGIS is enabled, by the authorization grant."""
        return {
            'connection_id': self.connection_id, 'symbol': self.symbol.upper(), 'side': self.side.lower(),
            'quantity': _num(self.quantity), 'order_type': self.order_type, 'time_in_force': self.time_in_force,
            'limit_price': _num(self.limit_price), 'stop_price': _num(self.stop_price), 'strategy_id': self.strategy_id,
        }


def _num(v):
    if v is None:
        return None
    return float(f'{float(v):.10g}')


def request_hash(intent: OrderIntent) -> str:
    return hashlib.sha256(json.dumps(intent.material(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def client_order_id(workspace_id: str, idempotency_key: str) -> str:
    """Stable across retries and restarts: the same idempotency key always gives the same broker id."""
    return 'qos-' + hashlib.sha256(f'{workspace_id}|{idempotency_key}'.encode()).hexdigest()[:24]


def max_quote_age() -> float:
    return float(os.getenv('QOS_MAX_QUOTE_AGE_SECONDS', '30'))


# ------------------------------------------------------------------ schema


# Intent states. 'blocked' was never sent and may be re-evaluated. 'submitting' and 'unknown' may have
# reached the broker and must be reconciled first. 'submitted' and 'rejected' are terminal.
UNRESOLVED = ('submitting', 'unknown')


def init_schema() -> None:
    """The safety tables are created by tenant_store.migrate_production_schema (migration 5)."""
    tenant_store.migrate_production_schema()


# ------------------------------------------------------------------ kill switches

def _scope(workspace_id: str | None) -> str:
    return PLATFORM if workspace_id is None else 'ws:' + workspace_id


def set_kill_switch(workspace_id: str | None, engaged: bool, actor: str, reason: str = '') -> dict:
    scope = _scope(workspace_id)
    now = time.time()
    with tenant_store._lock:
        c = tenant_store.connect()
        try:
            c.execute('''INSERT INTO safety_state(scope,engaged,reason,actor,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(scope) DO UPDATE SET engaged=excluded.engaged,reason=excluded.reason,actor=excluded.actor,updated_at=excluded.updated_at''',
                      (scope, int(engaged), reason[:300], actor[:120], now))
            c.commit()
        finally:
            c.close()
    payload = {'scope': scope, 'engaged': engaged, 'reason': reason[:300], 'actor': actor[:120]}
    tenant_store.event(workspace_id or PLATFORM, 'kill_switch_engaged' if engaged else 'kill_switch_released', payload)
    return {**payload, 'updated_at': now}


def kill_switch_status(workspace_id: str | None = None) -> dict:
    """Platform switch, plus the workspace switch when a workspace is given. Fails closed: if the
    state cannot be read, the switch reads as engaged."""
    out = {'engaged': False, 'reasons': [], 'platform': None, 'workspace': None}
    if os.getenv('QOS_KILL_SWITCH', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        out['engaged'] = True
        out['reasons'].append('QOS_KILL_SWITCH is set in the environment')
    scopes = [PLATFORM] + ([_scope(workspace_id)] if workspace_id else [])
    try:
        c = tenant_store.connect()
        try:
            rows = {r['scope']: dict(r) for r in c.execute(
                f'SELECT * FROM safety_state WHERE scope IN ({",".join("?" * len(scopes))})', scopes).fetchall()}
        finally:
            c.close()
    except Exception as e:  # unreadable state never means "clear"
        out['engaged'] = True
        out['reasons'].append(f'kill switch state unreadable: {type(e).__name__}')
        return out
    for scope in scopes:
        row = rows.get(scope)
        key = 'platform' if scope == PLATFORM else 'workspace'
        out[key] = {'engaged': bool(row and row['engaged']), 'reason': row['reason'] if row else '',
                    'actor': row['actor'] if row else '', 'updated_at': row['updated_at'] if row else None}
        if row and row['engaged']:
            out['engaged'] = True
            out['reasons'].append(f'{key} kill switch engaged' + (f': {row["reason"]}' if row['reason'] else ''))
    return out


def platform_halted() -> bool:
    return kill_switch_status(None)['engaged']


def require_clear(workspace_id: str | None) -> None:
    ks = kill_switch_status(workspace_id)
    if ks['engaged']:
        raise OrderRejected(409, 'kill_switch_engaged', 'Trading is halted by the kill switch', {'reasons': ks['reasons']})


# ------------------------------------------------------------------ intents

def _get_intent(workspace_id: str, idem: str) -> dict | None:
    c = tenant_store.connect()
    try:
        r = c.execute('SELECT * FROM order_intents WHERE workspace_id=? AND idem_key=?', (workspace_id, idem)).fetchone()
    finally:
        c.close()
    return dict(r) if r else None


def _create_intent(intent: OrderIntent, h: str, cid: str) -> dict:
    now = time.time()
    with tenant_store._lock:
        c = tenant_store.connect()
        try:
            c.execute('''INSERT OR IGNORE INTO order_intents(workspace_id,idem_key,request_hash,client_order_id,source,connection_id,
                params_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                      (intent.workspace_id, intent.idempotency_key, h, cid, intent.source, intent.connection_id,
                       json.dumps(intent.material(), sort_keys=True), 'new', now, now))
            c.commit()
        finally:
            c.close()
    row = _get_intent(intent.workspace_id, intent.idempotency_key)
    if row is None:
        raise OrderRejected(503, 'intent_store_unavailable', 'The order intent could not be recorded')
    return row


def _acquire_lease(workspace_id: str, idem: str) -> str | None:
    owner = uuid.uuid4().hex
    now = time.time()
    with tenant_store._lock:
        c = tenant_store.connect()
        try:
            cur = c.execute('''UPDATE order_intents SET lease_owner=?, lease_until=? WHERE workspace_id=? AND idem_key=?
                AND (lease_until IS NULL OR lease_until<?)''', (owner, now + LEASE_SECONDS, workspace_id, idem, now))
            c.commit()
            return owner if cur.rowcount == 1 else None
        finally:
            c.close()


def _update_intent(workspace_id: str, idem: str, owner: str | None, **fields) -> None:
    fields['updated_at'] = time.time()
    cols = ','.join(f'{k}=?' for k in fields)
    sql = f'UPDATE order_intents SET {cols} WHERE workspace_id=? AND idem_key=?'
    args = list(fields.values()) + [workspace_id, idem]
    if owner is not None:
        sql += ' AND lease_owner=?'
        args.append(owner)
    with tenant_store._lock:
        c = tenant_store.connect()
        try:
            cur = c.execute(sql, args)
            c.commit()
        finally:
            c.close()
    if cur.rowcount != 1:
        raise OrderRejected(503, 'intent_store_unavailable', 'The order intent could not be updated')


def unresolved_intents(workspace_id: str, connection_id: str | None = None) -> list[dict]:
    c = tenant_store.connect()
    try:
        sql = f'SELECT * FROM order_intents WHERE workspace_id=? AND status IN ({",".join("?" * len(UNRESOLVED))})'
        args: list[Any] = [workspace_id, *UNRESOLVED]
        if connection_id:
            sql += ' AND connection_id=?'
            args.append(connection_id)
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


# ------------------------------------------------------------------ account lock

@contextmanager
def account_lock(workspace_id: str, connection_id: str, wait: float | None = None):
    """Serializes check-then-send per broker account, across threads and processes sharing the
    database. Without it, concurrent orders each pass the exposure limits against the same
    positions and together exceed them."""
    key = f'{workspace_id}|{connection_id}'
    owner = uuid.uuid4().hex
    deadline = time.time() + (ACCOUNT_LOCK_WAIT if wait is None else wait)
    while True:
        now = time.time()
        with tenant_store._lock:
            c = tenant_store.connect()
            try:
                c.execute('DELETE FROM account_locks WHERE lock_key=? AND expires_at<?', (key, now))
                got = c.execute('INSERT OR IGNORE INTO account_locks(lock_key,owner,expires_at) VALUES(?,?,?)',
                                (key, owner, now + ACCOUNT_LOCK_SECONDS)).rowcount == 1
                c.commit()
            finally:
                c.close()
        if got:
            break
        if now >= deadline:
            raise OrderRejected(409, 'account_busy', 'Another order for this broker account is being checked and sent; retry with the same key')
        time.sleep(0.02)
    try:
        yield
    finally:
        try:
            with tenant_store._lock:
                c = tenant_store.connect()
                try:
                    c.execute('DELETE FROM account_locks WHERE lock_key=? AND owner=?', (key, owner))
                    c.commit()
                finally:
                    c.close()
        except Exception:
            pass  # expires after ACCOUNT_LOCK_SECONDS


def pending_exposure(workspace_id: str, connection_id: str, symbol: str, exclude_idem: str) -> dict:
    """Signed quantity and gross notional of this account's orders that may not be in the broker's
    positions yet: in flight, unknown, or submitted but not filled or closed in the last 24 hours."""
    c = tenant_store.connect()
    try:
        rows = c.execute('''SELECT idem_key, status, params_json, response_json, ref_price FROM order_intents WHERE workspace_id=? AND connection_id=?
            AND status IN ('submitting','unknown','submitted') AND updated_at>?''', (workspace_id, connection_id, time.time() - 86400)).fetchall()
    finally:
        c.close()
    sym_qty = 0.0
    gross_qty: dict[str, float] = {}
    notional_by_symbol: dict[str, float] = {}
    for r in rows:
        if r['idem_key'] == exclude_idem:
            continue
        if r['status'] == 'submitted':
            try:
                o = json.loads(r['response_json'] or '{}').get('order') or {}
            except Exception:
                o = {}
            status = str(o.get('status', '')).lower()
            if status in OPEN_ORDER_STATUSES_DONE:
                continue
            remaining = float(o.get('quantity') or 0) - float(o.get('filled_quantity') or 0)
        else:
            remaining = float(json.loads(r['params_json']).get('quantity') or 0)
        p = json.loads(r['params_json'])
        signed = remaining if p.get('side') == 'buy' else -remaining
        s = p.get('symbol', '')
        gross_qty[s] = gross_qty.get(s, 0.0) + abs(signed)
        notional_by_symbol[s] = notional_by_symbol.get(s, 0.0) + abs(signed) * float(r['ref_price'] or 0.0)
        if s == symbol.upper():
            sym_qty += signed
    return {'symbol_qty': sym_qty, 'qty_by_symbol': gross_qty, 'notional_by_symbol': notional_by_symbol}


# ------------------------------------------------------------------ live risk state

def observe_drawdown(workspace_id: str, connection_id: str, equity: float) -> float:
    """Drawdown in percent from the persisted high-water mark of this broker account."""
    now = time.time()
    with tenant_store._lock:
        c = tenant_store.connect()
        try:
            r = c.execute('SELECT high_water FROM account_marks WHERE workspace_id=? AND connection_id=?', (workspace_id, connection_id)).fetchone()
            hwm = max(float(r['high_water']) if r else equity, equity)
            c.execute('''INSERT INTO account_marks(workspace_id,connection_id,high_water,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(workspace_id,connection_id) DO UPDATE SET high_water=excluded.high_water,updated_at=excluded.updated_at''',
                      (workspace_id, connection_id, hwm, now))
            c.commit()
        finally:
            c.close()
    return max(0.0, (hwm - equity) / hwm * 100.0) if hwm > 0 else 100.0


def live_state(adapter, workspace_id: str, connection_id: str) -> dict:
    """Account and positions read from the broker now. Raises OrderRejected(503) when unavailable."""
    try:
        account = adapter.account()
    except Exception as e:
        raise OrderRejected(503, 'risk_info_unavailable', 'Broker account state is unavailable', {'error': type(e).__name__})
    try:
        positions = adapter.list_positions()
    except Exception as e:
        raise OrderRejected(503, 'risk_info_unavailable', 'Broker positions are unavailable', {'error': type(e).__name__})
    if str(account.status).upper() != 'ACTIVE':
        raise OrderRejected(409, 'account_not_active', f'Broker account status is {account.status}')
    equity = float(account.equity or 0.0)
    if not equity > 0:
        raise OrderRejected(409, 'account_equity_invalid', 'Broker account equity is not positive')
    if not account.paper:
        raise OrderRejected(409, 'live_account_refused', 'The broker reports a live account; only paper accounts are allowed')
    return {'account': account, 'positions': positions, 'equity': equity,
            'drawdown_pct': observe_drawdown(workspace_id, connection_id, equity)}


def fresh_quote(symbol: str, quote_fn: Callable | None = None):
    try:
        q = (quote_fn or _hub.quote)(symbol)
    except Exception as e:
        raise OrderRejected(503, 'market_data_unavailable', f'No quote for {symbol}', {'error': type(e).__name__})
    age = max(0.0, time.time() - float(q.ts))
    if q.stale or age > max_quote_age() or not float(q.price) > 0:
        raise OrderRejected(503, 'market_data_stale', f'Quote for {symbol} is stale or synthetic',
                            {'source': q.source, 'age_seconds': round(age, 1), 'stale': bool(q.stale)})
    return q


def exposure(positions, equity: float, symbol: str, signed_qty: float, price: float, pending: dict | None = None) -> dict:
    """Current and post-trade gross and single-symbol exposure in percent of equity. ``pending``
    adds orders that are not in the broker's positions yet (see pending_exposure)."""
    sym = symbol.upper()
    pend = pending or {'symbol_qty': 0.0, 'notional_by_symbol': {}}
    gross = sum(abs(float(p.market_value)) for p in positions) + sum(n for s, n in pend.get('notional_by_symbol', {}).items() if s != sym)
    cur_qty = sum(float(p.quantity) for p in positions if p.symbol.upper() == sym) + pend['symbol_qty']
    cur_sym = abs(sum(float(p.market_value) for p in positions if p.symbol.upper() == sym))
    post_qty = cur_qty + signed_qty
    post_sym = abs(post_qty) * price
    post_gross = gross - cur_sym + post_sym
    reducing = abs(post_qty) < abs(cur_qty) - 1e-12 and (cur_qty == 0 or post_qty * cur_qty >= 0)
    return {'gross_pct': gross / equity * 100.0, 'post_gross_pct': post_gross / equity * 100.0,
            'post_symbol_pct': post_sym / equity * 100.0, 'current_qty': cur_qty, 'post_qty': post_qty,
            'risk_reducing': reducing}


def evaluate(intent: OrderIntent, adapter, *, quote_fn: Callable | None = None, governor: RiskGovernor | None = None) -> dict:
    """All pre-trade checks on live state. Returns the evidence; raises OrderRejected on any failure."""
    require_clear(intent.workspace_id)
    q = fresh_quote(intent.symbol, quote_fn)
    st = live_state(adapter, intent.workspace_id, intent.connection_id)
    side = intent.side.lower()
    ref_price = float(q.price)
    if intent.limit_price and side == 'buy':
        ref_price = max(ref_price, float(intent.limit_price))
    signed = intent.quantity if side == 'buy' else -intent.quantity
    pend = pending_exposure(intent.workspace_id, intent.connection_id, intent.symbol, intent.idempotency_key)
    ex = exposure(st['positions'], st['equity'], intent.symbol, signed, ref_price, pend)
    m = intent.model
    gov = governor or _governor
    decision = gov.evaluate(
        kill_switch=False,  # checked above and again immediately before sending
        strategy_active=True,
        confidence=m.confidence if m else 1.0,
        requested_risk_pct=m.requested_risk_pct if m else 0.0,
        # A risk-reducing order is not blocked by exposure or drawdown limits; it lowers both.
        gross_exposure=0.0 if ex['risk_reducing'] else ex['post_gross_pct'],
        drawdown=0.0 if ex['risk_reducing'] else st['drawdown_pct'],
        market_data_fresh=True,  # fresh_quote above refused stale data
        quantity=intent.quantity,
        regime_fit=m.regime_fit if m else 1.0,
        net_edge_bps=m.net_edge_bps if m else 999.0,
        correlation_penalty=m.correlation_penalty if m else 0.0,
        strategy_health=m.strategy_health if m else 100.0,
        health_state=m.health_state if m else 'NORMAL',
        symbol_exposure=0.0 if ex['risk_reducing'] else ex['post_symbol_pct'],
    )
    evidence = {
        'equity': round(st['equity'], 2), 'drawdown_pct': round(st['drawdown_pct'], 4),
        'gross_pct': round(ex['gross_pct'], 4), 'post_gross_pct': round(ex['post_gross_pct'], 4),
        'post_symbol_pct': round(ex['post_symbol_pct'], 4), 'risk_reducing': ex['risk_reducing'],
        'reference_price': ref_price, 'quote_source': q.source, 'quote_age_seconds': round(max(0.0, time.time() - q.ts), 2),
        'policy_checks': decision['policy_checks'], 'model_checks_applied': m is not None,
    }
    if not decision['approved']:
        raise OrderRejected(409, 'risk_governor_blocked', decision['reason'], evidence)
    return evidence


# ------------------------------------------------------------------ submission

def _validate(intent: OrderIntent, connection: dict, adapter) -> None:
    if intent.side.lower() not in ('buy', 'sell'):
        raise OrderRejected(400, 'invalid_side', 'side must be buy or sell')
    if not intent.quantity or intent.quantity <= 0:
        raise OrderRejected(400, 'invalid_quantity', 'quantity must be positive')
    if intent.order_type in {'limit', 'stop_limit'} and not intent.limit_price:
        raise OrderRejected(400, 'limit_price_required', 'limit_price is required')
    if intent.order_type in {'stop', 'stop_limit'} and not intent.stop_price:
        raise OrderRejected(400, 'stop_price_required', 'stop_price is required')
    if not intent.idempotency_key or len(intent.idempotency_key) > 160:
        raise OrderRejected(400, 'idempotency_key_required', 'An idempotency key is required')
    if intent.source not in ('manual', 'automation'):
        raise OrderRejected(400, 'invalid_source', 'Unknown order source')
    if not connection or not connection.get('enabled'):
        raise OrderRejected(404, 'connection_unavailable', 'Broker connection not found or disabled')
    if connection.get('workspace_id') not in (None, intent.workspace_id) or connection.get('id') != intent.connection_id:
        raise OrderRejected(404, 'connection_unavailable', 'Broker connection not found or disabled')
    if not connection.get('execution_enabled'):
        raise OrderRejected(409, 'execution_disabled', 'Execution is disabled for this broker connection')
    if not getattr(adapter, 'paper_only', False):
        raise OrderRejected(409, 'live_execution_disabled', 'Real-money execution is disabled in this build')


def _result(intent: OrderIntent, cid: str, order_dict: dict, local_id: str | None, **extra) -> dict:
    return {'local_order_id': local_id, 'client_order_id': cid, 'order': order_dict, 'paper': True,
            'source': intent.source, **extra}


def _audit(intent: OrderIntent, kind: str, payload: dict, actor: dict | None) -> None:
    try:
        tenant_store.event(intent.workspace_id, kind, {**payload, 'source': intent.source,
                                                       'idempotency_key': intent.idempotency_key, **(actor or {})})
    except Exception:
        pass  # an audit failure never turns a refusal into an order; the intent row is the record


def _record_submitted(intent, cid, owner, order, evidence, extra) -> dict:
    data = asdict(order)
    local_id = tenant_store.save_order(intent.workspace_id, intent.connection_id, data, intent.strategy_id)
    res = _result(intent, cid, data, local_id, **extra, **({'checks': evidence} if evidence else {}))
    _update_intent(intent.workspace_id, intent.idempotency_key, owner, status='submitted', response_json=json.dumps(res, default=str), detail='')
    return res


def _authorizer_from_env():
    from . import aegis_client
    return aegis_client.AegisClient.from_env() if aegis_client.enabled() else None


def _authorizer_or_none():
    try:
        return _authorizer_from_env()
    except OrderRejected:
        return None


def _aegis_report(authorizer, auth, intent, outcome: str, order=None, note: str = '') -> bool:
    if not (authorizer and auth):
        return False
    summary = {'client_order_id': auth.params.get('reference'), 'source': intent.source}
    if order is not None:
        summary.update({'broker_status': order.status, 'filled_qty': order.filled_quantity, 'filled_avg_price': order.filled_avg_price})
    if note:
        summary['note'] = note
    ok = authorizer.report(auth, outcome, order.broker_order_id if order is not None else None, summary)
    _audit(intent, 'aegis_outcome_reported' if ok else 'aegis_report_failed', {'aegis_request_id': auth.request_id, 'outcome': outcome}, None)
    return ok


def _stored_auth(row: dict):
    if not row.get('aegis_json'):
        return None
    from .aegis_client import Authorization
    d = json.loads(row['aegis_json'])
    return Authorization(**d)


def _submit_leased(intent: OrderIntent, cid: str, owner: str, row: dict, adapter, connection: dict, quote_fn, governor, authorizer, actor) -> dict:
    """submit_order after the idempotency lease and the account lock are held."""
    row = _get_intent(intent.workspace_id, intent.idempotency_key) or row
    if row['status'] == 'submitted':
        return {**json.loads(row['response_json']), 'idempotent_replay': True}
    if row['status'] in UNRESOLVED:
        # An earlier attempt may have reached the broker. Find out before sending anything.
        try:
            found = adapter.get_order_by_client_order_id(cid)
        except Exception as e:
            _audit(intent, 'order_reconcile_failed', {'client_order_id': cid, 'error': type(e).__name__}, actor)
            raise OrderRejected(503, 'reconciliation_pending',
                                'The outcome of an earlier attempt is unknown and the broker cannot confirm it yet; nothing was sent')
        prior_auth = _stored_auth(row)
        prior_authorizer = authorizer or (_authorizer_or_none() if prior_auth else None)
        if found is not None:
            res = _record_submitted(intent, cid, owner, found, None, {'reconciled': True})
            _audit(intent, 'order_reconciled', {'client_order_id': cid, 'broker_order_id': found.broker_order_id, 'found': True}, actor)
            _aegis_report(prior_authorizer, prior_auth, intent, 'succeeded', found, 'reconciled after an unknown outcome')
            return res
        _audit(intent, 'order_reconciled', {'client_order_id': cid, 'found': False}, actor)
        # The broker confirms the earlier attempt never arrived. Its AEGIS grant was consumed, so close
        # that request as failed; a new attempt needs a new authorization (and AEGIS will refuse a
        # second grant for the same request).
        _aegis_report(prior_authorizer, prior_auth, intent, 'failed', None, 'not at broker after an unknown outcome')

    auth = None
    try:
        evidence = evaluate(intent, adapter, quote_fn=quote_fn, governor=governor)  # Gate 1: Quant OS's own controls
        if authorizer is None:
            authorizer = _authorizer_from_env()
        if authorizer is not None:
            auth = authorizer.authorize(intent, cid, evidence)  # Gate 2: AEGIS decision and grant
            evidence = evaluate(intent, adapter, quote_fn=quote_fn, governor=governor)  # own controls again, on fresh state
            authorizer.verify(auth, intent, cid)  # consumes the grant for exactly these parameters
            _update_intent(intent.workspace_id, intent.idempotency_key, owner, aegis_json=json.dumps(auth.__dict__))
        require_clear(intent.workspace_id)  # recheck immediately before sending
    except OrderRejected as e:
        _update_intent(intent.workspace_id, intent.idempotency_key, owner, status='blocked', detail=f'{e.code}: {e.message}'[:500])
        _audit(intent, 'order_blocked', {'client_order_id': cid, 'code': e.code, 'reason': e.message, **intent.material()}, actor)
        if auth is not None and auth.verified:
            _aegis_report(authorizer, auth, intent, 'failed', None, f'blocked by Quant OS after verification: {e.code}')
        raise
    except Exception as e:  # an unexpected error in a gate is a refusal, never a pass
        _update_intent(intent.workspace_id, intent.idempotency_key, owner, status='blocked', detail=f'internal: {type(e).__name__}')
        raise OrderRejected(503, 'safety_check_failed', 'An order-safety check failed unexpectedly; nothing was sent', {'error': type(e).__name__})

    _update_intent(intent.workspace_id, intent.idempotency_key, owner, status='submitting', attempts=int(row['attempts']) + 1,
                   ref_price=float(evidence['reference_price']))
    m = intent.material()
    order_req = SubmitOrder(symbol=m['symbol'], quantity=intent.quantity, side=m['side'], order_type=intent.order_type,
                            time_in_force=intent.time_in_force, limit_price=intent.limit_price, stop_price=intent.stop_price,
                            client_order_id=cid)
    try:
        order = adapter.submit_order(order_req)
    except BrokerRejected as e:
        _update_intent(intent.workspace_id, intent.idempotency_key, owner, status='rejected', detail=str(e)[:500])
        _audit(intent, 'order_rejected_by_broker', {'client_order_id': cid, 'reason': str(e)[:300]}, actor)
        _aegis_report(authorizer, auth, intent, 'failed', None, 'rejected by broker: ' + str(e)[:200])
        raise OrderRejected(422, 'broker_rejected', str(e)[:300])
    except Exception as e:  # BrokerOutcomeUnknown, BrokerUnavailable and anything unexpected
        _update_intent(intent.workspace_id, intent.idempotency_key, owner, status='unknown', detail=f'{type(e).__name__}: {e}'[:500])
        _audit(intent, 'order_outcome_unknown', {'client_order_id': cid, 'error': type(e).__name__}, actor)
        raise OrderRejected(504, 'outcome_unknown',
                            'The broker did not confirm the order. Retry with the same idempotency key to reconcile; it will not be sent twice.',
                            {'client_order_id': cid})
    extra = {'authorization': auth.evidence()} if auth else {}
    res = _record_submitted(intent, cid, owner, order, evidence, extra)
    if auth:
        res['authorization']['outcome_reported'] = _aegis_report(authorizer, auth, intent, 'succeeded', order)
    _audit(intent, 'broker_order_submitted', {'local_order_id': res['local_order_id'], 'client_order_id': cid,
                                              'broker_order_id': order.broker_order_id, **m}, actor)
    return res


def submit_order(intent: OrderIntent, *, adapter, connection: dict, quote_fn: Callable | None = None,
                 governor: RiskGovernor | None = None, authorizer=None, actor: dict | None = None) -> dict:
    """The only function in Quant OS that sends an order to a broker. See the module docstring."""
    _validate(intent, connection, adapter)
    h = request_hash(intent)
    cid = client_order_id(intent.workspace_id, intent.idempotency_key)
    row = _create_intent(intent, h, cid)
    if row['request_hash'] != h:
        raise OrderRejected(409, 'idempotency_conflict', 'Idempotency key was already used with a different order')
    if row['status'] == 'submitted':
        return {**json.loads(row['response_json']), 'idempotent_replay': True}
    if row['status'] == 'rejected':
        raise OrderRejected(422, 'broker_rejected', row['detail'] or 'The broker rejected this order', {'idempotent_replay': True})

    owner = _acquire_lease(intent.workspace_id, intent.idempotency_key)
    if owner is None:
        raise OrderRejected(409, 'order_in_progress', 'This order is already being processed; retry with the same key shortly')
    try:
        with account_lock(intent.workspace_id, intent.connection_id):
            return _submit_leased(intent, cid, owner, row, adapter, connection, quote_fn, governor, authorizer, actor)
    finally:
        _update_lease_release(intent.workspace_id, intent.idempotency_key, owner)


def reconcile_pending(workspace_id: str, connection_id: str, adapter) -> list[dict]:
    """Resolve intents whose outcome is unknown. Returns the intents that are still unresolved."""
    still = []
    for row in unresolved_intents(workspace_id, connection_id):
        owner = _acquire_lease(workspace_id, row['idem_key'])
        if owner is None:
            still.append(row)
            continue
        try:
            found = adapter.get_order_by_client_order_id(row['client_order_id'])
            if found is not None:
                data = asdict(found)
                local_id = tenant_store.save_order(workspace_id, connection_id, data, json.loads(row['params_json']).get('strategy_id'))
                res = {'local_order_id': local_id, 'client_order_id': row['client_order_id'], 'order': data, 'paper': True,
                       'source': row['source'], 'reconciled': True}
                _update_intent(workspace_id, row['idem_key'], owner, status='submitted', response_json=json.dumps(res, default=str))
                tenant_store.event(workspace_id, 'order_reconciled', {'client_order_id': row['client_order_id'], 'found': True})
            else:
                _update_intent(workspace_id, row['idem_key'], owner, status='blocked', detail='reconciled: not at broker')
                tenant_store.event(workspace_id, 'order_reconciled', {'client_order_id': row['client_order_id'], 'found': False})
            auth = _stored_auth(row)
            if auth:
                stub = OrderIntent(workspace_id, connection_id, '', '', 0, row['idem_key'], row['source'])
                _aegis_report(_authorizer_or_none(), auth, stub, 'succeeded' if found is not None else 'failed', found,
                              'reconciled after an unknown outcome' if found is not None else 'not at broker after an unknown outcome')
        except Exception:
            still.append(row)
        finally:
            _update_lease_release(workspace_id, row['idem_key'], owner)
    return still


def _update_lease_release(workspace_id: str, idem: str, owner: str) -> None:
    try:
        with tenant_store._lock:
            c = tenant_store.connect()
            try:
                c.execute('UPDATE order_intents SET lease_owner=NULL, lease_until=NULL WHERE workspace_id=? AND idem_key=? AND lease_owner=?',
                          (workspace_id, idem, owner))
                c.commit()
            finally:
                c.close()
    except Exception:
        pass
