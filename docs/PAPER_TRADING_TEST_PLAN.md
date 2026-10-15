# Controlled Alpaca paper-trading test plan (for approval, NOT executed)

Nothing in this plan has been run. It needs your explicit approval before step 1. Live trading, fund transfers and live execution stay out of scope: the Alpaca adapter is locked to `https://paper-api.alpaca.markets`, and orders are refused unless the broker reports a paper account.

## 0. What this test must prove (not provable with fakes)

1. The real Alpaca paper API behaves as the adapter assumes:
   - a duplicate `client_order_id` is rejected;
   - `GET /v2/orders:by_client_order_id` finds an order and returns 404 when it is absent;
   - 4xx versus 5xx and timeout classification is correct.
2. Account, positions and quotes from real services pass the freshness and plausibility checks during market hours and are refused outside them.
3. The full AEGIS flow works with a real broker: decision, grant, verify, order, report, receipt and chain verification.
4. The kill switch stops a real paper order path.

## 1. Preconditions (all must hold)

- [ ] You approve this plan in writing, including the date and time window.
- [ ] Branch `claude/quantos-safety-aegis` reviewed. The test runs from that commit, on a local machine or a private, non-public instance. No public deployment.
- [ ] Alpaca **paper** account. The keys are created by you and set by you as environment variables in the test shell: `QOS_SECRET_ALPACA_PAPER_API_KEY` and `QOS_SECRET_ALPACA_PAPER_API_SECRET`. Never pasted into chat, never committed. They are revoked after the test.
- [ ] AEGIS runs locally, set up with `packages/core/scripts/quantos-tenant-setup.ts`. AEGIS holds no Alpaca credential.
- [ ] `QOS_ADMIN_TOKEN` set (at least 16 characters) and `QOS_DATA_DIR` set to a fresh directory.
- [ ] The automation engine stays off (`POST /api/engine {enabled:false}`). Automation is not part of the first test.
- [ ] Market data source confirmed reachable; quotes not synthetic.

## 2. Limits for the test

| Limit | Value |
|---|---|
| Instruments | SPY only |
| Order size | 1 share, market or marketable limit, time in force `day` |
| Orders | At most 10 in the session, at most 1 open at a time |
| AEGIS policy | Auto-approve below USD 1,000; above needs approval; anything not SPY denied |
| Quant OS limits | Unchanged (12% symbol, 75% gross, 3% drawdown) |

## 3. Steps

Each step records request, response, Quant OS intent row, tenant events, AEGIS request and receipt.

| # | Step | Expected |
|---|---|---|
| 1 | Health: `GET /api/v1/broker-connections/{id}/health` | `ok: true`, `paper: true`, status ACTIVE |
| 2 | Kill switch engaged (operator token), submit 1 SPY | 409 `kill_switch_engaged`; no AEGIS call; no Alpaca order (check Alpaca order list) |
| 3 | Release, submit 1 SPY with AEGIS enabled | 200; AEGIS request `executed`; receipt reference = Alpaca order id; `client_order_id` = AEGIS `reference` |
| 4 | Repeat step 3 with the same idempotency key | `idempotent_replay`; no new Alpaca order |
| 5 | Same key, quantity 2 | 409; no order |
| 6 | Submit MSFT | `aegis_denied`; no order |
| 7 | Adapter check, outside the order path: submit a direct duplicate `client_order_id` via the adapter in a Python shell | Alpaca rejects; classified `BrokerRejected` |
| 8 | Adapter check: `get_order_by_client_order_id` for the step 3 id and for a random id | Order returned; `None` for the random id |
| 9 | Outside market hours (if in window), submit 1 SPY | Refused if quotes are stale; otherwise the order is accepted and stays open. Exposure then counts it as pending |
| 10 | Close the position with 1 SPY sell | Allowed as risk-reducing; AEGIS approves under the mandate |
| 11 | AEGIS `POST /v1/assurance/evidence/verify` | `valid: true` |

## 4. Abort criteria (stop, engage the kill switch, report)

- Any Alpaca order that has no matching Quant OS intent, or no AEGIS receipt when AEGIS is enabled.
- Any second order for the same `client_order_id`.
- Any response from a non-paper host or a non-paper account.
- Any unexpected exception in `order_safety`.

## 5. After the test

- Revoke the Alpaca paper keys.
- Delete the test data directory and the local AEGIS test organization.
- Write `docs/safety/paper-test-<date>.md` with the observed results only.
- Only then decide whether automation may be tested on paper. That needs a separate approval.
