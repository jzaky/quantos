# Quant OS Phase 5 — SaaS Broker Platform

## What changed

Phase 5 adds a multi-tenant execution control plane around the Phase 2 paper/shadow engine.

Each workspace has its own:

- API key
- broker connections
- external secret references
- broker orders
- reconciled broker positions
- automation policy
- audit events

The strategy layer emits normalized signals. The execution router selects the workspace's broker adapter. No strategy contains broker-specific order code.

## First workspace

Copy `.env.example` to `.env`, set a long random `QOS_BOOTSTRAP_TOKEN`, and start Quant OS.

Create a workspace:

```bash
curl -X POST http://localhost:8000/api/v1/workspaces/bootstrap \
  -H 'Content-Type: application/json' \
  -H 'X-QOS-Bootstrap-Token: YOUR_BOOTSTRAP_TOKEN' \
  -d '{"name":"My Trading Workspace","plan":"developer"}'
```

The response contains a `qos_...` API key once. Subsequent `/api/v1` calls use:

```
X-QOS-API-Key: qos_...
```

## Connect Alpaca Paper

Set broker credentials in the server environment:

```bash
QOS_SECRET_ALPACA_MAIN_API_KEY=...
QOS_SECRET_ALPACA_MAIN_API_SECRET=...
```

Then create the connection:

```bash
curl -X POST http://localhost:8000/api/v1/broker-connections \
  -H 'Content-Type: application/json' \
  -H 'X-QOS-API-Key: qos_...' \
  -d '{
    "adapter_slug":"alpaca_paper",
    "name":"Alpaca Paper",
    "secret_ref":"ALPACA_MAIN",
    "config":{},
    "execution_enabled":false
  }'
```

Check `/health` for that connection, then explicitly arm paper execution using `/api/v1/broker-connections/{id}/execution`.

## Autonomous routing

Configure `/api/v1/automation` with:

- broker connection
- allowed strategy/symbol pairs
- confidence floor
- max order notional
- requested risk percentage
- trade cooldown

The server scans enabled tenant automation configs every 15 seconds. A signal is routed only if:

1. the broker connection is enabled,
2. paper execution is explicitly armed,
3. the adapter is marked paper-only,
4. market data is fresh,
5. strategy confidence clears the tenant floor,
6. the deterministic risk governor approves the order,
7. the per-strategy cooldown has expired.

Synthetic/stale fallback market data is never eligible for autonomous broker routing.

## Current safety boundary

Phase 5 supports broker-connected **paper** autonomous trading. It intentionally blocks real-money adapters even if one is installed. Production live-money activation should add stronger authentication, billing/entitlements, per-tenant limits, immutable audit retention, broker streaming reconciliation, idempotent order recovery and operational monitoring before the `paper_only` boundary is relaxed.
