# Quant OS v0.4 — Production-Beta Paper Trading SaaS

Quant OS is a multi-tenant autonomous **paper/shadow trading platform** with a broker-plugin execution layer. v0.4 hardens the Phase 3 control plane and redesigns Broker Cloud for customer-facing SaaS onboarding.

## What is built

### Trading engine
- real/synthetic market-data adapter layer with stale-data blocking
- autonomous strategy cycles
- deterministic risk governor and master kill switch
- persistent paper ledger, positions, orders and equity history
- backtesting + walk-forward evaluation
- shadow/reference execution comparison
- WebSocket telemetry

### SaaS control plane
- tenant workspaces and tenant-scoped data
- hashed workspace API keys
- API-key roles: `admin`, `trader`, `read_only`
- API-key expiry, rotation and revocation endpoints
- per-workspace broker connections
- Alpaca Paper + deterministic Mock Paper adapters
- external broker secret references; broker secrets are not stored in connection rows
- explicit paper-execution arm/disarm
- per-workspace automation policies
- tenant audit-event feed
- broker reconciliation
- idempotent broker order submission
- request IDs and security headers
- API body limits and in-process read/write rate limits
- restricted CORS configuration
- SQLite WAL, busy timeout, foreign keys and DB integrity readiness check
- `/health`, `/ready`, and tenant `/api/v1/readiness` endpoints

### UI redesign
- high-tech command-center design system
- redesigned Broker Cloud customer onboarding
- workspace-session panel
- launch-readiness score
- connector health/reconcile/arm controls
- automation envelope summary
- audit activity stream
- session-only browser API-key storage
- explicit real-money-disabled status throughout the broker experience

## Run

```bash
cp .env.example .env
# configure QOS_BOOTSTRAP_TOKEN and broker secrets if needed

docker compose up --build
```

- UI: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`
- Readiness: `http://localhost:8000/ready`

## Test

```bash
python scripts/phase4_production_smoke.py
python scripts/phase3_saas_smoke.py
python scripts/phase2_smoke.py
```

## Release boundary

v0.4 is intended for **private beta / broker-connected paper trading SaaS**. Real-money routing remains hard-disabled. SQLite is acceptable for a single-node private beta, but a public multi-instance SaaS deployment should migrate the tenant/control-plane store to a managed transactional database before horizontal scaling.

See `PRODUCTION.md`, `SAAS.md`, and `BROKER_PLUGIN.md`.

## v0.5 Day Trader Quant Layer

The automated paper/SaaS engine now evaluates every executable signal with a deterministic intelligence stack before risk approval:

- Market regime classification from realized volatility, ATR and normalized trend strength.
- Strategy/regime compatibility gates.
- Expected gross edge in basis points.
- Estimated fees + spread + volatility-sensitive slippage.
- Net edge after execution costs; trades below the minimum safety margin are blocked.
- Volatility-targeted position sizing (0.25x to 1.50x multiplier).
- Cross-strategy return correlation concentration penalty.
- Strategy health score using Sharpe, expectancy, profit factor, drawdown, regime fit and execution quality.
- Health states: FULL, NORMAL, REDUCED, SHADOW_ONLY, QUARANTINED.
- Automatic size reduction or execution block based on the health state.
- Backtest metrics now include Sortino, Calmar, profit factor and expectancy.
- `/api/intelligence` exposes the current smart-quant decision packet for the UI.

This is still a paper/shadow system. The formulas improve selectivity and risk discipline; they do not guarantee profitability or prove a durable trading edge.


## v0.7 Day Trader Quant

This release adds the Scout → Executor intraday layer for liquid stocks/ETFs, plus entropy-rate and mutual-information diagnostics, Bayesian edge confidence, uncertainty-adjusted fractional Kelly, Deflated Sharpe, distribution-shift detection, adaptive memory, crowding proxies, and Monte Carlo drawdown analysis. See `DAY_TRADING.md`.

New APIs:
- `GET /api/scout`
- `GET /api/intelligence/{strategy_id}/{symbol}`

Real-money execution remains disabled. Use paper/shadow validation before connecting live capital.

## v0.7 Forward-Test Tracking

The engine now self-audits every actionable signal, including rejected trades. Each candidate is persisted and later scored at a fixed forward horizon so Quant OS can measure whether its regime, cost, health, statistical-validation and risk filters are actually helping.

Open **Forward Test** in the UI or see [`TRACKING.md`](./TRACKING.md). The default scoring horizon is 30 minutes and can be changed with `QOS_TRACKING_HORIZON_SECONDS`.

Key endpoints: `GET /api/tracking/scoreboard`, `GET /api/tracking/decisions`, plus tenant-scoped `/api/v1/tracking/*` equivalents.
