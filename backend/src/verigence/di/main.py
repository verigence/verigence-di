"""main.py — FastAPI application factory for Verigence DI.

Creates the FastAPI app, registers middleware, includes routers,
and exposes /health and /ready endpoints.
"""
from __future__ import annotations

import logging
import time
import uuid

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from verigence.di.settings import get_settings

logger = structlog.get_logger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-ID"
# Safe character validation per architecture spec
_CORRELATION_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")


def _is_valid_correlation_id(value: str) -> bool:
    return 1 <= len(value) <= 128 and all(c in _CORRELATION_SAFE for c in value)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Verigence Document Intelligence API",
        version="2.1.0",
        description=(
            "Standalone Document Intelligence. "
            "Primary lookup: tenantId + subjectId. "
            "Machine lifecycle: Upload → Process → Confirm."
        ),
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=(
            ["*"] if not settings.is_production
            else ["https://di-ops.verigence.app"]
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[CORRELATION_ID_HEADER],
    )

    # ── Correlation ID middleware ────────────────────────────────────────────
    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next) -> Response:  # type: ignore[type-arg]
        incoming = request.headers.get(CORRELATION_ID_HEADER, "")
        correlation_id = (
            incoming
            if incoming and _is_valid_correlation_id(incoming)
            else str(uuid.uuid4())
        )
        # Bind to structlog context for this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        start = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        response.headers[CORRELATION_ID_HEADER] = correlation_id
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    # ── Routers ─────────────────────────────────────────────────────────────
    # Import here to avoid circular imports; routers are added incrementally
    from verigence.di.api.health import router as health_router  # noqa: PLC0415
    app.include_router(health_router)

    # Remaining routers are wired in as each module is implemented:
    # from verigence.di.api.v1 import subjects, documents, ...
    # app.include_router(subjects.router, prefix="/v1")

    # ── Sentry ───────────────────────────────────────────────────────────────
    if settings.sentry_dsn:
        try:
            import sentry_sdk  # type: ignore[import]
            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                environment=settings.env.value,
                traces_sample_rate=0.1,
            )
        except ImportError:
            logger.warning("sentry_sdk not installed; error tracking disabled")

    return app


# Module-level app instance used by uvicorn
app = create_app()
