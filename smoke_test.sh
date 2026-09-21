#!/usr/bin/env sh
set -eu
BASE="${BASE_URL:-http://127.0.0.1:8000}"

echo "[1/5] health"
curl -fsS "$BASE/health"; echo

echo "[2/5] readiness"
curl -fsS "$BASE/ready"; echo

echo "[3/5] snapshot"
curl -fsS "$BASE/api/snapshot"; echo

echo "[4/5] risk evaluation"
curl -fsS -X POST "$BASE/api/paper/orders/evaluate" \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"NVDA","side":"BUY","quantity":100,"strategy_id":"vector-momentum","confidence":0.82,"requested_risk_pct":0.32}'; echo

echo "[5/5] strategies"
curl -fsS "$BASE/api/strategies"; echo
