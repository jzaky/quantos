# Quant OS Broker Plugin Contract

Phase 5 routes every broker through one normalized interface. Strategies do not import Alpaca, IBKR, Binance, or any venue SDK directly.

## Required adapter methods

Implement `BrokerAdapter` from `backend/app/brokers/base.py`:

- `account()`
- `submit_order(order)`
- `cancel_order(broker_order_id)`
- `get_order(broker_order_id)`
- `list_positions()`
- `close_position(symbol)`

Return only normalized `BrokerAccount`, `BrokerOrder`, and `BrokerPosition` objects.

## Register an adapter

Add the adapter class to `backend/app/brokers/registry.py` with `register(MyAdapter)`.

Each adapter declares:

- `slug`
- `label`
- `paper_only`

Phase 5 refuses autonomous routing to any adapter whose `paper_only` flag is false. This is deliberate; live-money activation is a separate production phase.

## Secrets

Broker connections store a `secret_ref`, not raw broker credentials. The default secret provider reads environment variables:

```
QOS_SECRET_<REF>_API_KEY
QOS_SECRET_<REF>_API_SECRET
```

For example, `secret_ref=ALPACA_MAIN` resolves:

```
QOS_SECRET_ALPACA_MAIN_API_KEY
QOS_SECRET_ALPACA_MAIN_API_SECRET
```

Replace `EnvSecretStore` with an AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, Doppler, Vault, or platform-specific provider without changing broker or strategy code.

## SaaS tenancy

All Phase 5 public platform routes are under `/api/v1`. Workspace API keys are SHA-256 hashed before persistence. Orders, positions, connections, automation settings and events are scoped by `workspace_id`.
