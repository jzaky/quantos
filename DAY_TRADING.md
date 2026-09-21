# Quant OS v0.6 — Day Trader Quant Layer

This release adds an intraday research/execution intelligence layer for liquid US stocks and ETFs. It is designed for paper/shadow validation first. Real-money routing remains disabled.

## Scout → Executor

The Scout ranks a broad universe every cycle using:

- Shannon entropy on direction states
- conditional entropy and entropy rate
- permutation entropy
- lagged mutual information
- return autocorrelation
- variance ratio
- Hurst R/S estimate
- realized volatility / ATR regime
- relative volume
- modeled spread + slippage cost

The Executor only wakes for sufficiently structured opportunities. A Scout score never authorizes a trade by itself.

## Intraday strategies

- `vwap-reclaim` — VWAP cross/reclaim/rejection logic
- `opening-range` — opening-range breakout logic
- `rvol-momentum` — short-horizon momentum gated by relative volume

These are candidate alpha generators, not proven edges. Each is forced through the validation chain below.

## Bayesian edge gate

For win probability `p`, the system maintains a Beta posterior:

`p | data ~ Beta(alpha + wins, beta + losses)`

It computes `P(p > p_breakeven)` and refuses to trust the estimate until the effective sample size and posterior confidence threshold are met.

Break-even probability includes transaction costs.

## Uncertainty-adjusted fractional Kelly

The sizing engine does not plug the posterior mean into Kelly. It uses the lower 95% posterior bound, then shrinks by:

- posterior confidence
- regime fit
- strategy health
- fractional Kelly factor
- absolute maximum capital fraction

The default hard cap is 5% of equity before the normal tenant/risk limits are applied.

## Overfitting defense

Research reports include:

- Deflated Sharpe Ratio
- bootstrap probability of positive mean return
- change-point / edge decay status
- Monte Carlo drawdown distribution
- adaptive memory half-life
- crowding state

The execution eligibility flag requires all major validation checks to pass.

## Distribution-shift detection

CUSUM and Page-Hinkley style change detectors are included. A formerly profitable strategy can be marked `DECAYING` or `BROKEN` if recent trade returns deteriorate relative to prior behavior.

## Adaptive memory

Instead of one fixed exponential decay constant for all strategies, the engine estimates a strategy-specific memory half-life from the persistence of its return sequence.

## Crowding proxy

The crowding score does **not** infer crowding from a high win rate. It uses deterioration in recent edge, execution/slippage pressure, and alpha half-life compression. States are:

- NORMAL
- WATCH
- CROWDED

Crowded strategies are sized down or blocked by validation.

## Monte Carlo risk

The research report bootstraps trade sequences to estimate:

- median path return
- 5th percentile path return
- 95th percentile max drawdown
- probability of 10% drawdown
- probability of 20% drawdown
- probability of ending negative

## New API

### Universe Scout

`GET /api/scout?universe=AAPL,NVDA,SPY,QQQ`

### Full intelligence report

`GET /api/intelligence/rvol-momentum/AAPL?period=5d&interval=5m&trials=25`

The report includes signal state, regime/cost intelligence, strategy health, backtest metrics, Bayesian posterior, fractional Kelly, Deflated Sharpe, edge decay, crowding, adaptive memory, and Monte Carlo risk.

## Important limitation

No formula can guarantee profit. The purpose of this architecture is to reject weak, stale, overfit, expensive, crowded, or statistically uncertain trades before capital is exposed. Profitability still depends on discovering an alpha process that remains positive after costs in live conditions.
