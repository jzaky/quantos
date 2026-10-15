# Order safety and AEGIS authorization

Status: implemented and tested on branch `claude/quantos-safety-aegis` (from `8c27f61`). Tested against fakes, a local AEGIS stand-in, and a real AEGIS gateway running locally. **Not deployed. No Alpaca order, paper or live, has been sent.**

## 1. One order path

`order_safety.submit_order` is the only code in Quant OS that calls `adapter.submit_order`. Callers:

- **manual orders:** `POST /api/v1/orders` (`api_saas.py`);
- **automated orders:** `saas_engine.cycle_workspace`.

The in-process simulator (`main.py`, `/api/paper/orders/submit` and the engine loop) never reaches a broker. It uses the same persisted platform kill switch and the same quote-freshness rule.

```mermaid
sequenceDiagram
  participant C as Caller (manual API or automation)
  participant S as order_safety
  participant DB as SQLite (intents, switches, marks, locks)
  participant A as AEGIS (optional, QOS_AEGIS_URL)
  participant B as Broker adapter (Alpaca paper)
  C->>S: OrderIntent (exact parameters, idempotency key, source)
  S->>DB: record intent (request hash, client_order_id = qos-sha256(ws|key))
  alt earlier attempt outcome unknown
    S->>B: GET order by client_order_id
    B-->>S: found: record and return. absent: continue
  end
  S->>DB: account lock (one check-and-send per broker account)
  S->>DB: kill switches (platform + workspace; unreadable = engaged)
  S->>B: account, positions (unavailable = refuse)
  S->>S: fresh non-synthetic quote; governor on live state
  opt AEGIS enabled
    S->>A: POST /v1/gateway/actions (agent key, agent mode, exact params)
    A-->>S: allow + single-use grant / hold / deny (any failure = refuse)
    S->>B: account, positions again; governor again
    S->>A: POST /grants/verify (integration key, params rebuilt from the order)
    A-->>S: ok, grant consumed (replayed, expired, voided, mismatched = refuse)
  end
  S->>DB: kill switches again
  S->>B: submit exactly these parameters, client_order_id
  B-->>S: accepted / rejected / unknown
  S->>DB: intent state, order row, audit event
  opt AEGIS enabled
    S->>A: POST /actions/:id/execute (outcome, broker order id)
  end
```

## 2. Controls

| Control | Mechanism | Fails |
|---|---|---|
| Kill switch, platform | `safety_state` row `platform`, persisted; env `QOS_KILL_SWITCH=1` hard stop | closed: unreadable state counts as engaged |
| Kill switch, workspace | `safety_state` row `ws:<id>` | closed |
| Who may change it | Platform: `X-QOS-Admin-Token` only (401 without, 403 for workspace keys). Workspace: admin or trader keys engage, only admin keys release | |
| When it is checked | Automation cycle start; before evaluation; again just before sending | |
| Risk governor | `RiskGovernor.evaluate` on live broker state: drawdown from a persisted high-water mark, post-trade gross exposure, post-trade single-symbol exposure (now enforced, 12%), plus model checks for automated orders | closed: any exception refuses |
| Risk inputs unavailable | Account or positions error, account not ACTIVE, equity not positive, non-paper account, stale or synthetic quote: refused (503 or 409) | closed |
| Risk-reducing orders | An order that only reduces an existing position is not blocked by drawdown or exposure limits; kill switch and data checks still apply | |
| Concurrency | Account lock in SQLite (cross-thread and cross-process on one database). Exposure includes in-flight and unfilled orders | closed: lock wait timeout refuses (`account_busy`) |
| Idempotency | Intent keyed by (workspace, idempotency key) with a parameter hash; same key + different order = 409; stable `client_order_id` | |
| Duplicate broker orders | Unknown outcome (timeout, 5xx, transport error, crash) is looked up at the broker by `client_order_id` before anything is resent; Alpaca also rejects a duplicate `client_order_id` | closed: lookup failure refuses (`reconciliation_pending`) |
| Automation dedupe | Key `auto:<strategy>:<symbol>:<side>:<bar timestamp>`; unresolved intents reconciled at cycle start; cooldown set on unknown outcomes | |
| Quantity | Never changed inside `order_safety`. Automation sizes first; manual orders are refused, not resized | |

## 3. AEGIS integration (agent mode)

- AEGIS is the independent authorization layer and evidence record. **It holds no broker credentials and places no orders.** On the AEGIS side, the `quantos-broker` integration has no stored credential; its key has only the `grants:verify` scope.
- **Authorization binding.** The grant is bound by AEGIS to sha256 of canonical `{toolKey, action, params}`. The params are `symbol, side, type, qty, notional, timeInForce, reference (= client_order_id), reason, limitPrice`. At verification time, Quant OS rebuilds them from the order it is about to send, so any change to instrument, side, quantity, type, limit price, time in force or broker reference fails verification. The broker order is built from the same intent.
- **Decisions.**
  - `restrict`: refused. Quant OS never sends parameters other than the ones it decided on.
  - `require_approval`, `quarantine`, `request_more_information`: refused with `aegis_approval_pending`. A retry with the same idempotency key after approval fetches the grant.
  - `stop` and `stop_limit`: refused while AEGIS is enabled, because the AEGIS tool schema covers market and limit only.
- **Failure handling** (refused, nothing sent):
  - URL set but keys missing;
  - plain HTTP to a non-loopback host;
  - timeout, connection error, 5xx or malformed JSON;
  - a missing request id;
  - a 409;
  - verify not `ok`, or ok for a different request.
- **Independence.** Quant OS checks its own controls before asking AEGIS and again after the grant, so an AEGIS "allow" never overrides a Quant OS refusal.
- **Unknown broker outcome with AEGIS.**
  - The grant was already consumed. On retry, the broker lookup decides.
  - Found: report `succeeded`.
  - Absent: report `failed` to AEGIS. A new attempt then needs a new decision, because AEGIS refuses a second grant for an executing request.
- **Configuration** (environment only): `QOS_AEGIS_URL`, `QOS_AEGIS_AGENT_KEY`, `QOS_AEGIS_INTEGRATION_KEY`, `QOS_AEGIS_TOOL` (default `place-order`), `QOS_AEGIS_TIMEOUT_SECONDS` (default 5).

## 4. Data

New SQLite tables, created by `tenant_store.migrate_production_schema` (migration 5):

| Table | Purpose |
|---|---|
| `safety_state` | Kill switches |
| `order_intents` | Order intents and their state |
| `account_marks` | High-water marks |
| `account_locks` | Account locks |

`QOS_DATA_DIR` selects the database directory.

## 5. Endpoint changes

| Endpoint | Change |
|---|---|
| `GET /api/risk/kill-switch` | New: persisted platform state |
| `POST /api/risk/kill-switch` | Requires `X-QOS-Admin-Token` |
| `POST /api/engine`, `POST /api/strategies/{id}/toggle` | Require `X-QOS-Admin-Token` |
| `GET/POST /api/v1/kill-switch` | New: workspace switch |
| `POST /api/v1/orders` | Goes through `order_safety`. New refusal codes: `kill_switch_engaged`, `risk_governor_blocked`, `risk_info_unavailable`, `market_data_stale`, `account_busy`, `outcome_unknown`, `reconciliation_pending`, `broker_rejected`, `aegis_*` |

The console shows the server's kill switch state, asks for the operator token, and shows refusals instead of an optimistic "halted".

## 6. Known limits

These are listed again in `docs/safety/REPORT.md`.

- **Single database.** The account lock and kill switches assume all Quant OS processes share one SQLite database. Several hosts with separate databases would need a shared lock (for example PostgreSQL advisory locks).
- **Exposure accounting.** Exposure counts unfilled orders placed through Quant OS. Orders placed outside Quant OS, for example in the Alpaca dashboard, are seen only once they appear in positions.
- **High-water mark.** It is per broker connection and does not adjust for deposits or withdrawals.
- **Quant OS audit log.** `tenant_events` is not tamper-evident. The tamper-evident record is AEGIS's hash-chained ledger, and only when AEGIS is enabled.
