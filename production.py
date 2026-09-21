from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def cors_origins() -> list[str]:
    raw = os.getenv("QOS_CORS_ORIGINS", "http://localhost:3000")
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class RuntimeConfig:
    environment: str = os.getenv("QOS_ENV", "development").strip().lower()
    max_body_bytes: int = int(os.getenv("QOS_MAX_BODY_BYTES", "1048576"))
    rate_limit_per_minute: int = int(os.getenv("QOS_RATE_LIMIT_PER_MINUTE", "180"))
    write_rate_limit_per_minute: int = int(os.getenv("QOS_WRITE_RATE_LIMIT_PER_MINUTE", "60"))
    trusted_proxy: bool = _bool("QOS_TRUST_PROXY", False)


config = RuntimeConfig()


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            q = self._hits[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(window_seconds - (now - q[0]))) if q else 1
                return False, retry
            q.append(now)
            return True, 0


_limiter = SlidingWindowLimiter()


def _identity(request: Request) -> str:
    api_key = request.headers.get("X-QOS-API-Key", "")
    if api_key:
        return "key:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]
    host = request.client.host if request.client else "unknown"
    return "ip:" + host


async def production_guard(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or "req_" + uuid.uuid4().hex[:20]
    request.state.request_id = request_id

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > config.max_body_bytes:
                return JSONResponse({"detail": "Request body too large", "request_id": request_id}, status_code=413)
        except ValueError:
            pass

    if request.url.path.startswith("/api/"):
        is_write = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
        limit = config.write_rate_limit_per_minute if is_write else config.rate_limit_per_minute
        allowed, retry = _limiter.allow(f"{_identity(request)}:{'w' if is_write else 'r'}", limit)
        if not allowed:
            return JSONResponse(
                {"detail": "Rate limit exceeded", "request_id": request_id},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )

    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["Server-Timing"] = f"app;dur={elapsed_ms}"
    return response


def readiness_payload() -> dict:
    checks = {
        "bootstrap_token_configured": bool(os.getenv("QOS_BOOTSTRAP_TOKEN", "").strip()),
        "cors_restricted": "*" not in cors_origins(),
        "environment": config.environment,
        "real_money_enabled": False,
    }
    ready = checks["cors_restricted"] and config.environment in {"development", "staging", "production", "test"}
    return {"ready": ready, "checks": checks}
