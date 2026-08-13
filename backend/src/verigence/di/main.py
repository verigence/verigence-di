"""main.py — FastAPI application factory for Verigence DI.

Creates the FastAPI app, registers middleware, includes routers,
and exposes /health and /ready endpoints.

Lifespan: starts/stops the ProcessingWorker background task.
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import traceback

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from verigence.di.settings import get_settings

logger = structlog.get_logger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-ID"
# Safe character validation per architecture spec
_CORRELATION_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")


def _is_valid_correlation_id(value: str) -> bool:
    return 1 <= len(value) <= 128 and all(c in _CORRELATION_SAFE for c in value)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):  # type: ignore[arg-type]
        """Start background worker + EOD scheduler on startup; stop on shutdown."""
        from verigence.di.scheduler.beat import get_eod_scheduler  # noqa: PLC0415
        from verigence.di.workers.processor import get_worker  # noqa: PLC0415
        worker = get_worker()
        scheduler = get_eod_scheduler()
        if settings.worker_enabled:
            worker.start()
            scheduler.start()
        yield
        if settings.worker_enabled:
            await worker.stop()
            scheduler.stop()

    app = FastAPI(
        title="Verigence Document Intelligence API",
        version="2.2.0",
        description=(
            "Standalone Document Intelligence. "
            "Primary lookup: tenantId + subjectId. "
            "Machine lifecycle: Upload → Process → Confirm."
        ),
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
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
        try:
            response: Response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            correlation_id_val = structlog.contextvars.get_contextvars().get("correlation_id", "unknown")
            logger.error(
                "unhandled_exception",
                exc_type=type(exc).__name__,
                exc_msg=str(exc),
                traceback=traceback.format_exc(),
            )
            return JSONResponse(
                status_code=500,
                content={"detail": {"code": "INTERNAL_ERROR", "title": str(exc), "type": type(exc).__name__}},
                headers={CORRELATION_ID_HEADER: correlation_id_val},
            )
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
    # Import here to avoid circular imports
    from verigence.di.api.health import router as health_router  # noqa: PLC0415
    from verigence.di.api.v1.documents import router as documents_router  # noqa: PLC0415
    from verigence.di.api.v1.entity_links import router as entity_links_router  # noqa: PLC0415
    from verigence.di.api.v1.extraction_profiles import (
        router as extraction_profiles_router,  # noqa: PLC0415
    )
    from verigence.di.api.v1.operations import router as operations_router  # noqa: PLC0415
    from verigence.di.api.v1.requirement_profiles import (
        router as requirement_profiles_router,  # noqa: PLC0415
    )
    from verigence.di.api.v1.subject_matching import (
        router as subject_matching_router,  # noqa: PLC0415
    )
    from verigence.di.api.v1.subjects import router as subjects_router  # noqa: PLC0415
    from verigence.di.api.v1.tenant_config import router as tenant_config_router  # noqa: PLC0415
    from verigence.di.api.v1.unassigned import router as unassigned_router  # noqa: PLC0415
    from verigence.di.api.v1.verification import router as verification_router  # noqa: PLC0415
    from verigence.di.api.v1.whatsapp_system import (
        router as whatsapp_system_router,  # noqa: PLC0415
    )

    app.include_router(health_router)
    app.include_router(subjects_router)
    app.include_router(documents_router)
    app.include_router(verification_router)
    app.include_router(operations_router)
    app.include_router(entity_links_router)
    app.include_router(requirement_profiles_router)
    app.include_router(extraction_profiles_router)
    app.include_router(tenant_config_router)
    app.include_router(subject_matching_router)
    app.include_router(unassigned_router)
    app.include_router(whatsapp_system_router)

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
