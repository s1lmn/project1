import json
import logging
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import engine
from .errors import http_error, validation_error
from .routes import activities, auth_profiles, safety_metrics

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(message)s")
logger = logging.getLogger("sports_mate")
rate_windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)

if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.app_env, send_default_pii=False)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env in {"staging", "production"}:
        if len(settings.session_secret) < 32 or settings.session_secret.startswith("development-"):
            raise RuntimeError("Задайте уникальный SESSION_SECRET длиной не менее 32 символов")
        if len(settings.internal_api_key) < 24:
            raise RuntimeError("Задайте уникальный INTERNAL_API_KEY длиной не менее 24 символов")
    yield


app = FastAPI(
    title="SPORTS MATE API",
    version="0.1.0",
    description="API Telegram Mini App для поиска партнёров по спорту.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Internal-Key",
        "X-Request-ID",
    ],
)
app.add_exception_handler(HTTPException, http_error)
app.add_exception_handler(RequestValidationError, validation_error)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:80]
    request.state.request_id = request_id
    started = time.monotonic()
    category = None
    limit = settings.write_rate_limit_per_minute
    if request.url.path.startswith("/auth/"):
        category, limit = "auth", settings.auth_rate_limit_per_minute
    elif request.url.path == "/reports":
        category, limit = "report", settings.report_rate_limit_per_minute
    elif request.url.path == "/analytics/events":
        category, limit = "analytics", settings.analytics_rate_limit_per_minute
    elif request.method in {"POST", "PATCH", "DELETE"}:
        category = "write"
    if category and request.method != "OPTIONS":
        client = request.client.host if request.client else "unknown"
        bucket = rate_windows[(client, category)]
        cutoff = started - 60
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            response_headers = {"X-Request-ID": request_id, "Retry-After": "60"}
            origin = request.headers.get("origin")
            if origin in settings.allowed_origins:
                response_headers["Access-Control-Allow-Origin"] = origin
                response_headers["Vary"] = "Origin"
            return JSONResponse(
                {
                    "error": {
                        "code": "rate_limited",
                        "message": "Слишком много запросов. Попробуйте через минуту.",
                        "request_id": request_id,
                    }
                },
                status_code=429,
                headers=response_headers,
            )
        bucket.append(started)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            json.dumps(
                {"event": "request_failed", "request_id": request_id, "path": request.url.path}
            )
        )
        response = JSONResponse(
            {
                "error": {
                    "code": "internal_error",
                    "message": "Внутренняя ошибка",
                    "request_id": request_id,
                }
            },
            status_code=500,
        )
    response.headers["X-Request-ID"] = request_id
    logger.info(
        json.dumps(
            {
                "event": "request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
    )
    return response


@app.get("/health")
def health():
    try:
        with Session(engine) as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except Exception:
        return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)


app.include_router(auth_profiles.router)
app.include_router(activities.router)
app.include_router(safety_metrics.router)
