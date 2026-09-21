# Railway Quick Start - v0.7.1

This release fixes the Railway build failure caused by a missing nested `backend/app` upload.

## Railway settings

- Root Directory: **leave blank** (repository root)
- Builder: Dockerfile (auto-detected)
- Start Command: leave blank
- Health Check: `/health`

**Do not set Root Directory to `backend` for v0.7.1.**

The root deployment uses `railway_backend_bundle.tar.gz`, a single file containing the complete backend `app/` package. The Dockerfile extracts it automatically during build.

## Alpaca paper credentials

In Railway > your service > Variables, add:

- `QOS_SECRET_ALPACA_MAIN_API_KEY`
- `QOS_SECRET_ALPACA_MAIN_API_SECRET`

In Quant OS Broker Cloud, the Secret Reference field should contain only:

`ALPACA_MAIN`

Never commit the actual API secret to GitHub or put it in the frontend.
