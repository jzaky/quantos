# Quant OS + AEGIS: safety and authorization report

Branch: `claude/quantos-safety-aegis`, from `8c27f61`. Date: 2026-10-14.

**Status vocabulary:**
- **tested:** a test demonstrates the property;
- **implemented:** code exists but no test demonstrates it;
- **not verified:** needs a real broker or production.

**Nothing here has touched Alpaca.** No paper or live order was sent, and nothing was deployed.

## 1. Vulnerabilities fixed

| ID | Defect at 8c27f61 | Fix | Status |
|---|---|---|---|
| Q1 | Manual broker orders (`POST /api/v1/orders`) skipped the kill switch and the risk governor | One order path, `order_safety.submit_order`, used by manual and automated orders | tested |
| Q2 | Automation passed `kill_switch=False`, `drawdown=0.0`, `market_data_fresh=True` | Kill switch checked at cycle start and in `order_safety`; live drawdown from a persisted high-water mark; real freshness | tested |
| Q3 | Kill switch held in memory only; reset to off on restart | Persisted platform and workspace switches; unreadable state = engaged; `QOS_KILL_SWITCH=1` env hard stop | tested |
| Q4 | Kill-switch, engine and strategy endpoints unauthenticated | Operator token for platform controls; workspace switch with role checks | tested |
| Q5 | Random `client_order_id` per attempt; idempotency saved only after success, so a retry after a timeout placed a second order | Intent recorded first; stable `client_order_id` from the idempotency key; broker lookup before any resend | tested |
| Q6 | Synthetic quote fallback looked fresh | Stale or synthetic quotes refuse broker orders; the simulator honours the stale flag | tested (broker path) |
| Q7 | Console showed "halted" before the server confirmed | Console reflects the server's state and shows refusals | implemented (typechecked, not browser-tested) |
| New | Risk inputs unavailable were not handled for manual orders | Account or positions error, non-ACTIVE account, non-positive equity, non-paper account: refused | tested |
| New | Concurrent orders could jointly exceed exposure limits (found by the failure matrix: 10 concurrent 3% orders reached 30% against a 12% limit) | Account lock across check and send; exposure counts in-flight and unfilled orders | tested |
| New | `max_symbol_exposure_pct` (12%) existed but was never enforced | Enforced by the governor on post-trade exposure | tested |
| New | `secrets.py` shadowed the standard library module | Renamed to `secret_store.py` | tested (suite imports) |

## 2. Exact files changed (`git diff --stat 8c27f61..HEAD`, before this report and docs)

```
.gitignore, QuantOS.tsx, __init__.py, aegis_client.py (new), alpaca.py, api_saas.py, base.py,
brokers/__init__.py, main.py, mock.py, order_safety.py (new), risk_engine.py, saas_engine.py,
secrets.py => secret_store.py, store.py, tenant_store.py,
tests/aegis_standin.py, tests/fakes.py, tests/run.py, tests/support.py,
tests/test_aegis_authorization.py, tests/test_aegis_live.py, tests/test_failure_matrix.py,
tests/test_safety_regressions.py (all new),
docs/safety/regression-baseline-8c27f61.txt, docs/safety/aegis-live-run.txt,
docs/safety/full-run-with-live-aegis.txt (test evidence)
```

Plus this report, `docs/SAFETY_ARCHITECTURE.md`, `docs/SUPPLY_CHAIN.md` and `docs/PAPER_TRADING_TEST_PLAN.md`.

AEGIS repository (`jzaky/School`, `aegis/`): `packages/core/scripts/quantos-tenant-setup.ts` (new) and `docs/QUANTOS_INTEGRATION.md` (status update). No AEGIS product code changed.

## 3. Test results

- **Failing first.** The 17 regression tests were committed before any fix (`05ee9bb`).
  - Against `8c27f61`, 16 fail for the stated reasons (`docs/safety/regression-baseline-8c27f61.txt`).
  - The 17th covers behaviour that was already correct (automation stops when the account cannot be read).
  - Two tests were revised before their fix and still fail at `8c27f61`:
    - **kill-switch authorization:** workspace keys may not change the platform switch;
    - **drawdown:** the test moves to a new signal bar and checks the block reason, so it cannot pass through duplicate suppression.
- **Full suite** (`python tests/run.py`): **66 tests, all pass**, including 7 against a real AEGIS gateway running locally (`docs/safety/full-run-with-live-aegis.txt`). Two consecutive full runs passed.
  - `test_safety_regressions.py`: 17
  - `test_aegis_authorization.py`: 26 (local AEGIS stand-in)
  - `test_failure_matrix.py`: 16
  - `test_aegis_live.py`: 7 (real AEGIS; opt-in, skipped without configuration)
- **UI:** `QuantOS.tsx` typechecks with `tsc --noEmit` (strict).
- **Test bugs found and fixed while testing.** Each is recorded so that a passing result is not overstated:
  1. A concurrency test passed because of wrong percentage arithmetic. After the fix it failed and exposed the real concurrent-exposure defect, which was then fixed.
  2. The harness reset the fake broker on a simulated restart, which could hide a duplicate. Broker state now survives restarts.
  3. A time-dependent bar timestamp made one test flaky at 5-minute boundaries. The test clock is now frozen.
  4. Two live-test expectations were wrong about AEGIS:
     - its final status name is `executed`;
     - the downstream verification evidence is attached by subject, not by correlation id.
     The tests were corrected to AEGIS's actual behaviour.

### Priority 3 matrix

| Scenario | Test(s) | Result |
|---|---|---|
| Kill switch enabled | `test_manual_broker_order_blocked_by_platform_kill_switch`, `..._workspace_kill_switch`, `test_automation_blocked_by_kill_switch`, `test_kill_switch_blocks_before_aegis_is_asked` | pass |
| Persistence after restart | `test_kill_switch_persists_across_restart`, `test_simulator_honours_persisted_kill_switch` | pass |
| Unauthorized kill-switch changes | `test_kill_switch_changes_require_authentication`, `test_kill_switch_authorization` | pass |
| Manual-order bypass | `test_manual_order_enforces_risk_governor`, `test_manual_and_automated_orders_use_the_same_safety_checks` | pass |
| Automated-order bypass | `test_automation_uses_live_drawdown`, `test_automation_blocked_by_kill_switch`, `test_automation_is_authorized_too` | pass |
| Risk governor failure | `test_risk_governor_exception_refuses_the_order`, `test_automation_survives_governor_exception_without_trading` | pass |
| Missing account info | `test_manual_order_rejected_when_account_unavailable` / `_positions_unavailable`, `test_account_unavailable_blocks_even_if_aegis_allows` | pass |
| Gateway timeout | `test_gateway_timeout` | pass |
| Gateway unavailable | `test_gateway_unavailable`, `test_gateway_server_error`, `test_gateway_malformed_response`, `test_unavailable_during_verification`, `test_misconfigured_keys_fail_closed` | pass |
| Expired authorization | `test_expired_grant`, `test_voided_grant_after_aegis_pause` | pass (stand-in) |
| Replayed authorization | `test_replayed_grant_is_refused` (stand-in), `test_replayed_grant_is_refused_by_aegis` (real AEGIS) | pass |
| Changed parameters | `test_changed_parameters_invalidate_the_grant` (stand-in), `test_changed_parameters_are_refused_by_aegis` (real AEGIS), `test_same_key_different_order_is_refused` | pass |
| Duplicate requests | `test_same_request_twice_places_one_order`, `test_automation_repeats_on_the_same_signal_bar_place_one_order` | pass |
| Broker timeout after submission | `test_manual_retry_after_broker_timeout_does_not_duplicate`, `test_retry_reconciles_before_resubmitting`, `test_broker_timeout_after_submission_is_reconciled_once` | pass |
| Concurrent requests | `test_concurrent_requests_with_one_key_place_one_order`, `..._different_keys_respect_exposure_limit`, `test_concurrent_automation_cycles_place_one_order`, `test_concurrent_requests_get_one_grant` | pass (threads in one process; multi-process not tested) |
| Database restart | `test_restart_after_an_unknown_outcome_reconciles_instead_of_resubmitting`, `test_crash_between_send_and_record_is_reconciled_after_restart`, `test_automation_after_restart_reconciles_pending_orders_first` | pass |
| Partial system failure | `test_outcome_report_failure_does_not_hide_a_placed_order`, `test_broker_positions_down_with_aegis_up`, `test_kill_switch_state_unreadable_fails_closed`, `test_database_unavailable_refuses_the_order` | pass |
| Audit tampering | `test_tampered_trading_record_is_detected` (real AEGIS: a database owner rewrites a Quant OS order's evidence; verification reports the exact sequence; restored afterwards) | pass. Quant OS's own event log is not tamper-evident (risk R4) |

## 4. AEGIS integration status

- **Implemented and tested** against a local stand-in (26 tests) and a real AEGIS gateway on localhost (7 tests): all nine steps of the approved flow, in agent mode.
- **AEGIS holds no Alpaca credentials.** Its `quantos-broker` integration has no stored credential, and its key has only `grants:verify`. A test confirms no Quant OS request to AEGIS contains broker credentials.
- **Off by default.** It is enabled only when `QOS_AEGIS_URL` is set. Once set, failures refuse orders.
- **Not done:**
  - AEGIS-side detection of broker orders that bypass AEGIS. This needs AEGIS to read the paper account, i.e. a read-only key, and is listed for approval.
  - Stop and stop-limit orders under AEGIS (refused).

## 5. Remaining risks

| # | Risk | Mitigation or next step |
|---|---|---|
| R1 | Alpaca behaviour assumed, not verified: duplicate `client_order_id` rejection, lookup endpoint, error classes | Paper test plan, steps 7 and 8 |
| R2 | The account lock and kill switch assume one shared SQLite database; several hosts with separate databases would not be serialized | Run one instance, or move these tables to PostgreSQL with advisory locks |
| R3 | Orders placed outside Quant OS count toward exposure only once they show in positions | AEGIS-side broker reconciliation (approval item) or broker open-orders query |
| R4 | `tenant_events` (Quant OS audit) is not tamper-evident | Rely on AEGIS's ledger when enabled; or hash-chain Quant OS events |
| R5 | High-water mark ignores deposits and withdrawals | Reset procedure for operators |
| R6 | `/api/paper/orders/submit` (simulator only, no broker) is still unauthenticated | Add operator auth if the simulator is exposed publicly |
| R7 | Operator token held in browser `sessionStorage` | Acceptable for an operator console; replace with real sign-in before wider use |
| R8 | `safety` runtime dependency unpinned and unused; other dependencies use ranges | See SUPPLY_CHAIN.md |
| R9 | The simulator now refuses synthetic or stale quotes, so with no market data the demo engine stops trading | Intended; it is a behaviour change worth knowing |
| R10 | Unknown outcome followed by a broker-confirmed absence closes the AEGIS request as failed, so a retry needs a new idempotency key | Documented response code `aegis_not_executable` |

## 6. Dependency and licence assessment

See `docs/SUPPLY_CHAIN.md`.
- No dependency was added.
- Syft: recommended for SBOMs (Apache-2.0, cosign-signed checksums, update check disabled), not installed.
- Trivy: deferred because of GHSA-69fq-xp46-6x23 (the March 2026 compromise). Adoption would be allowed only as a verified, pinned binary run offline, never through `trivy-action` or `setup-trivy`. OSV-Scanner or `pip-audit` are proposed as lower-risk options.

## 7. Updated architecture documentation

- `docs/SAFETY_ARCHITECTURE.md` (Quant OS).
- `aegis/docs/QUANTOS_INTEGRATION.md` gains an implementation status section (AEGIS repository).

## 8. Paper-trading readiness

**Ready to request approval for a controlled paper test; not ready for unattended paper automation or anything live.**
- Every control the plan depends on is tested against fakes and a real AEGIS gateway.
- What only a real paper account can show is listed in R1, and in `docs/PAPER_TRADING_TEST_PLAN.md` section 0.

## 9. Items requiring your approval

1. Running `docs/PAPER_TRADING_TEST_PLAN.md`: SPY, 1 share, at most 10 orders, keys set by you in the shell and revoked afterwards.
2. Merging `claude/quantos-safety-aegis` into Quant OS `main`. This changes API behaviour:
   - operator token required;
   - new refusal codes;
   - simulator refuses stale quotes.
3. Deploying the merged build to Railway. Not done. Requires `QOS_ADMIN_TOKEN` to be set in Railway.
4. Removing the unused, unpinned `safety` package from `requirements.txt`, and pinning runtime dependencies with hashes.
5. Adding Syft to CI as specified, and choosing OSV-Scanner or `pip-audit` (or a hardened Trivy) for vulnerability scanning.
6. Giving AEGIS a **read-only** Alpaca paper key for bypass detection (AEGIS compares broker orders with its receipts). This changes the "AEGIS holds no Alpaca credentials" position for read-only access, so it is your decision.
7. Whether automation may later run on paper with AEGIS required (`QOS_AEGIS_URL` set), after the manual paper test.
