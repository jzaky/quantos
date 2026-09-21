# Quant OS v0.7 — Forward-Tracked Day Trader

## Added
- persistent forward-decision ledger
- tracking of TRADED, SHADOW_ONLY, QUARANTINED, and every major block reason
- fixed-horizon shadow scoring for accepted and rejected signals
- filter precision: losers avoided vs winners incorrectly blocked
- per-strategy, per-symbol, per-regime decision attribution
- execution slippage attachment to tracked decisions
- tenant/workspace-scoped tracking for SaaS automation
- `Forward Test` UI module
- local and SaaS tracking APIs
- configurable `QOS_TRACKING_HORIZON_SECONDS` (default 30 minutes)

## Verified
- Phase 7 tracking smoke test
- Phase 6 day-trader smoke test
- Phase 5 smart-quant smoke test
- Phase 4 production smoke test
- Phase 3 SaaS smoke test
- Phase 2 paper-engine smoke test
- live FastAPI boot /health and /api/tracking/scoreboard

## Safety
- real-money execution remains disabled
- broker automation remains paper-only
