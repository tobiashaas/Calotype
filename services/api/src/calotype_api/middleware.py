"""FastAPI middleware: request-id propagation and rate limiting."""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from calotype_observability import new_request_id, set_request_id

_REQUEST_ID_HEADER = "X-Request-ID"

# Rate-limit config (override via env vars)
_RATE_LIMIT_PATHS = {"/v1/jobs/train", "/v1/jobs/edit"}
_RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "60"))
_RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Read or generate a request-id and attach it to logs + response headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get(_REQUEST_ID_HEADER) or new_request_id()
        set_request_id(rid)
        response = await call_next(request)
        response.headers[_REQUEST_ID_HEADER] = rid
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-IP rate limiter backed by Redis.

    Applied only to paths in _RATE_LIMIT_PATHS.
    Falls back to allowing the request if Redis is unavailable.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path not in _RATE_LIMIT_PATHS:
            return await call_next(request)

        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        key = f"rl:{request.url.path}:{client_ip}"

        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, _RATE_LIMIT_WINDOW)
            count, _ = pipe.execute()
            if count > _RATE_LIMIT_REQUESTS:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"rate limit exceeded ({_RATE_LIMIT_REQUESTS} req/{_RATE_LIMIT_WINDOW}s)"},
                    headers={
                        "Retry-After": str(_RATE_LIMIT_WINDOW),
                        "X-RateLimit-Limit": str(_RATE_LIMIT_REQUESTS),
                        "X-RateLimit-Remaining": "0",
                    },
                )
        except Exception:
            pass  # degrade gracefully — don't block requests if Redis is down

        return await call_next(request)
