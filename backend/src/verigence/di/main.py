"""main.py — FastAPI application factory for Verigence DI.

Creates the FastAPI app, registers middleware, includes routers,
and exposes /health and /ready endpoints.

Lifespan: starts/stops the ProcessingWorker background task.
"""
from __future__ import annotations

import time
import traceback
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from verigence.di.errors import ErrorCode, problem_response
from verigence.di.settings import get_settings

logger = structlog.get_logger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-ID"
# Safe character validation per architecture spec
_CORRELATION_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")


def _is_valid_correlation_id(value: str) -> bool:
    return 1 <= len(value) <= 128 and all(c in _CORRELATION_SAFE for c in value)


async def _validate_schema_profile_consistency() -> None:
    """D25 — startup check: warn if published extraction profile fields diverge from SCHEMA_REGISTRY.

    Runs once at startup after the worker starts. Never blocks startup.
    DB unavailability → warning only.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: PLC0415

        from verigence.di.document_ai.schemas import SCHEMA_REGISTRY  # noqa: PLC0415
        from verigence.di.repositories.database import get_engine  # noqa: PLC0415

        engine = get_engine()
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as session:
            for dtkey, schema in SCHEMA_REGISTRY.items():
                schema_keys = {f.key for f in schema.fields}

                rows = (
                    await session.execute(
                        text("""
                            SELECT cf.field_key
                            FROM docintel.extraction_profile_fields epf
                            JOIN docintel.extraction_profiles ep
                              ON ep.profile_id = epf.profile_id
                            JOIN docintel.document_types dt
                              ON dt.document_type_id = ep.document_type_id
                            JOIN docintel.canonical_fields cf
                              ON cf.canonical_field_id = epf.canonical_field_id
                            WHERE dt.document_type_key = :dtkey
                              AND ep.status = 'PUBLISHED'
                              AND epf.enabled = true
                        """),
                        {"dtkey": dtkey},
                    )
                ).mappings().all()

                if not rows:
                    # No published profile for this schema key — not an error
                    continue

                profile_keys = {r["field_key"] for r in rows}
                schema_only = sorted(schema_keys - profile_keys)
                profile_only = sorted(profile_keys - schema_keys)

                if schema_only or profile_only:
                    logger.warning(
                        "schema_profile_mismatch",
                        document_type_key=dtkey,
                        schema_only=schema_only,
                        profile_only=profile_only,
                    )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "schema_profile_consistency_check_failed",
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )


def create_app() -> FastAPI:
    from verigence.di.logging_config import configure_logging  # noqa: PLC0415
    configure_logging()
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
        await _validate_schema_profile_consistency()
        yield
        if settings.worker_enabled:
            await worker.stop()
            scheduler.stop()

    app = FastAPI(
        title="Verigence Document Intelligence API",
        version="2.4.0",
        description=(
            "Verigence Document Intelligence (DI) — standalone document ingestion, "
            "extraction, verification, and reconciliation platform. "
            "Primary lookup key: tenantId + subjectId. "
            "Machine document lifecycle: Upload → Process → Confirm → Verify. "
            "All protected endpoints require a Bearer JWT issued by the Verigence Security module "
            "(iss=verigence-security, aud=verigence-platform). "
            "Use mock tokens (mock.<tenantId>.<actorId>.<ROLE>) for local dev and CI. "
            "Response envelope (D8): {\"errorCode\":\"000\",\"errorMessage\":\"Success\",\"data\":{...}}. "
            "Non-zero errorCode values indicate business errors; HTTP 4xx/5xx indicate transport errors."
        ),
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── OpenAPI security scheme (D8 Bearer JWT) ──────────────────────────────
    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        from fastapi.openapi.utils import get_openapi  # noqa: PLC0415
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {})["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "Security-module-issued JWT. "
                    "Claims: iss=verigence-security, aud=verigence-platform, permissions[]. "
                    "Dev/CI mock format: mock.<tenantId>.<actorId>.<ROLE>[.<ROLE>...]"
                ),
            }
        }
        schema["security"] = [{"BearerAuth": []}]
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

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

    # ── Layer 1: RequestValidationError → Problem INVALID_REQUEST ────────────
    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        correlation_id = structlog.contextvars.get_contextvars().get(
            "correlation_id", str(uuid.uuid4())
        )
        body = problem_response(
            ErrorCode.INVALID_REQUEST,
            detail=str(exc.errors()),
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=400,
            content=body,
            headers={CORRELATION_ID_HEADER: correlation_id},
        )

    # ── Layer 2: HTTPException → Problem (pass-through if already Problem) ───
    @app.exception_handler(HTTPException)
    async def _http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        correlation_id = structlog.contextvars.get_contextvars().get(
            "correlation_id", str(uuid.uuid4())
        )
        # If detail is already a Problem dict (has a 'code' key), attach correlationId
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            body = dict(exc.detail)
            body.setdefault("correlationId", correlation_id)
        else:
            # Wrap plain string or unexpected dict in a canonical Problem body
            body = problem_response(
                ErrorCode.INTERNAL_ERROR,
                detail=str(exc.detail),
                correlation_id=correlation_id,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers={CORRELATION_ID_HEADER: correlation_id},
        )

    # ── Layer 3: Correlation ID middleware + catch-all ───────────────────────
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
            # Layer 3 catch-all: exceptions that escaped both registered handlers.
            # Must return Problem JSON — never text/plain.
            logger.error(
                "unhandled_exception",
                exc_type=type(exc).__name__,
                exc_msg=str(exc),
                traceback=traceback.format_exc(),
            )
            body = problem_response(
                ErrorCode.INTERNAL_ERROR,
                detail=f"{type(exc).__name__}: {exc}",
                correlation_id=correlation_id,
            )
            return JSONResponse(
                status_code=500,
                content=body,
                headers={CORRELATION_ID_HEADER: correlation_id},
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
    from verigence.di.api.v1.admin_provisioning import (  # noqa: PLC0415
        router as admin_provisioning_router,
    )
    from verigence.di.api.v1.analyse import router as analyse_router  # noqa: PLC0415
    from verigence.di.api.v1.audit_storage_contexts import (  # noqa: PLC0415
        router as audit_storage_contexts_router,
    )
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
    app.include_router(audit_storage_contexts_router)
    app.include_router(admin_provisioning_router)
    app.include_router(verification_router)
    app.include_router(operations_router)
    app.include_router(entity_links_router)
    app.include_router(requirement_profiles_router)
    app.include_router(extraction_profiles_router)
    app.include_router(tenant_config_router)
    app.include_router(subject_matching_router)
    app.include_router(unassigned_router)
    app.include_router(whatsapp_system_router)
    app.include_router(analyse_router)

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
