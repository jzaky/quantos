# Quant OS v0.4 — Production-Beta Deployment Notes

## Deployment posture

This release is hardened for a **private paper-trading SaaS beta**, not for customer live capital. The code refuses live-money adapters.

### Required environment settings

Use a long random `QOS_BOOTSTRAP_TOKEN`, restrict `QOS_CORS_ORIGINS` to your deployed frontend, and provide broker credentials only through `QOS_SECRET_<REF>_API_KEY` / `QOS_SECRET_<REF>_API_SECRET` or a future external secret-store implementation.

Do not expose the bootstrap token to the browser.

## Security controls included

- hashed workspace API keys
- roles and optional expiry
- key rotation/revocation APIs
- request IDs
- no-store API responses
- frame/nosniff/referrer/permissions headers
- read/write request rate limits
- max request-body size
- explicit paper arming phrase
- idempotency keys on broker order submission
- tenant audit event stream
- secrets referenced rather than persisted in broker records
- live-money execution blocked

## Order idempotency

Every `POST /api/v1/orders` must include:

```text
X-QOS-Idempotency-Key: <unique client-generated value>
```

Retrying the same key with the same body returns the original response. Reusing it with a different order returns `409`.

## API-key lifecycle

Use:

- `GET /api/v1/api-keys`
- `POST /api/v1/api-keys`
- `DELETE /api/v1/api-keys/{key_id}`

Browser Broker Cloud stores a workspace key in `sessionStorage`, not persistent `localStorage`.

## Readiness

- `/health` — process health and release identity
- `/ready` — deployment config readiness
- `/api/v1/readiness` — tenant DB / connector / automation readiness

## Database

SQLite uses WAL + busy timeout and is suitable for single-node beta deployments. Before multi-instance/public scale, move control-plane persistence to a managed relational database with migrations, backups, point-in-time recovery, and HA.

## Still required before live-money launch

- managed DB / HA storage
- external secret manager (KMS/Vault/cloud secret manager)
- user login + MFA / organization membership instead of browser API keys as the primary UI session
- billing/entitlements
- centralized distributed rate limiting
- immutable external audit retention
- broker streaming fills/order updates + recovery after disconnects
- alerting/on-call and SLOs
- security review / penetration test
- jurisdiction-specific legal/compliance review
- documented incident response and disaster recovery
- a validated strategy process with enough paper/shadow history
