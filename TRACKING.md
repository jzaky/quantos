# Quant OS Forward-Test Tracker (v0.7)

Quant OS now records every actionable BUY/SELL candidate before execution. The record is independent of the trading strategy so filters can be audited later.

## What is recorded

Each candidate stores strategy, symbol, side, timestamp, regime, confidence, signal score, reference price, estimated edge/cost, regime fit, correlation penalty, volatility sizing, health state, statistical-validation context, the final decision, and the reason for blocking if applicable.

Decision classes include:

- `TRADED`
- `SHADOW_ONLY`
- `QUARANTINED`
- `BLOCKED_BY_CONFIDENCE`
- `BLOCKED_BY_DATA`
- `BLOCKED_BY_REGIME`
- `BLOCKED_BY_COST`
- `BLOCKED_BY_CORRELATION`
- `BLOCKED_BY_STAT_VALIDATION`
- `BLOCKED_BY_COOLDOWN`
- `BLOCKED_BY_RISK`

## Fixed-horizon shadow outcome

After `QOS_TRACKING_HORIZON_SECONDS` (default 1800 seconds / 30 minutes), the tracker marks the signal against the new market price whether it was traded or blocked.

For BUY signals:

`forward_return_bps = (settle_price / reference_price - 1) * 10,000`

For SELL signals the sign is reversed.

`net_forward_bps = forward_return_bps - estimated_cost_bps`

This is intentionally separate from realized strategy P&L. It answers a different question: **was the decision/filter directionally useful over the configured horizon?**

## Dashboard

Open **Forward Test** in the sidebar. It shows:

- traded-signal forward win rate
- average net forward bps
- filter precision
- blocked losers avoided
- blocked winners missed
- decision attribution
- strategy forward scoreboard
- pending vs settled observations

## APIs

Local engine:

- `GET /api/tracking/scoreboard`
- `GET /api/tracking/decisions?limit=200`
- `POST /api/tracking/settle`

SaaS workspace (requires `X-QOS-API-Key`):

- `GET /api/v1/tracking/scoreboard`
- `GET /api/v1/tracking/decisions?limit=200`

## What to look for during the first 500-2,000 observations

Do not optimize on raw P&L alone. Compare:

1. `TRADED` average net bps and win rate.
2. `BLOCKED_BY_REGIME`: ideally negative net outcome on average.
3. `BLOCKED_BY_COST`: gross signals may be positive, but should fail after modeled cost.
4. `SHADOW_ONLY` / `QUARANTINED`: determines whether health logic is too aggressive.
5. `blockedWinners` vs `blockedLosers`: this is the false-block / saved-loss tradeoff.
6. Strategy and symbol segmentation: identify where forward edge is concentrated.
7. Regime segmentation: identify strategy/regime combinations worth capital.

A filter that blocks many trades is not automatically good. Its blocked cohort should perform worse than the accepted cohort after costs.
