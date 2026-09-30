"""main.py — FastAPI application factory for Verigence DI.

Creates the FastAPI app, registers middleware, includes routers,
and exposes /health and /ready endpoints.

Lifespan: starts/stops the ProcessingWorker background task.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from verigence.di.errors import (
    ErrorCode,
    ProblemException,
    error_for_app_status,
    error_for_code,
    error_for_http_status,
    problem_response,
)
from verigence.di.logging_config import is_probe_path
from verigence.di.observability import (
    attach_correlation_to_current_span,
    configure_observability,
    current_trace_context,
    record_metric,
    shutdown_observability,
)
from verigence.di.runtime_errors import (
    correlation_id_or_new,
    safe_exception_context,
    technical_failure,
    validation_problem_detail,
)
from verigence.di.settings import get_settings

logger = structlog.get_logger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-ID"
TRACE_ID_HEADER = "X-Trace-ID"
PROBLEM_MEDIA_TYPE = "application/problem+json"
_CORRELATION_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-")


def _is_valid_correlation_id(value: str) -> bool:
    return 1 <= len(value) <= 128 and all(c in _CORRELATION_SAFE for c in value)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


_PATH_CONTEXT_KEYS = ("tenant_id", "subject_id", "document_id", "external_context_ref", "job_id")


def _path_context(request: Request) -> dict[str, str]:
    """The business ids in the matched route's path, so a request line can be
    read per tenant or document without parsing the path."""
    params = getattr(request, "path_params", None) or {}
    return {key: str(params[key]) for key in _PATH_CONTEXT_KEYS if params.get(key) is not None}


def _problem_json(
    status_code: int,
    body: dict[str, Any],
    correlation_id: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    merged = dict(headers or {})
    merged[CORRELATION_ID_HEADER] = correlation_id
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers=merged,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def _complete_problem_body(detail: Mapping[str, Any], status_code: int) -> dict[str, Any]:
    """Fill missing Problem members for a dict detail built outside problem_response."""
    body = dict(detail)
    error = error_for_code(body.get("code"))
    if error is not None:
        reference = problem_response(error)
    else:
        fallback = error_for_http_status(status_code)
        reference = problem_response(fallback)
        reference["type"] = f"https://docs.verigence.app/errors/{str(body['code']).lower()}"
        reference["status"] = status_code
    for key, value in reference.items():
        body.setdefault(key, value)
    return body


def _is_framework_default_detail(exc: StarletteHTTPException) -> bool:
    try:
        phrase = HTTPStatus(exc.status_code).phrase
    except ValueError:
        return False
    return exc.detail is None or exc.detail == phrase


def _log_problem(
    request: Request,
    *,
    status_code: int,
    body: Mapping[str, Any],
    correlation_id: str,
    cause: BaseException | None = None,
) -> None:
    """Log one rejected request at a level matching its business/technical class."""
    fields: dict[str, Any] = {
        "error_code": body.get("code"),
        "error_category": body.get("errorCategory"),
        "retryable": body.get("retryable"),
        "http_status": status_code,
        "method": request.method,
        "route": _route_template(request),
        "correlation_id": correlation_id,
    }
    if status_code >= 500:
        if cause is not None:
            fields.update(safe_exception_context(cause))
        logger.error("di_technical_error", **fields)
    elif status_code in (401, 403):
        logger.warning("di_security_rejection", **fields)
    else:
        logger.info("di_business_error", **fields)


async def _validate_schema_profile_consistency() -> None:
    """D25 — warn if published extraction fields diverge from SCHEMA_REGISTRY.

    This is a non-blocking startup check.  Failure diagnostics intentionally do
    not include database/provider exception messages or query/input values.
    """
    startup_correlation_id = correlation_id_or_new()
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
                            SELECT COALESCE(epf.extraction_key, cf.field_key) AS extraction_key
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
                    continue
                profile_keys = {r["extraction_key"] for r in rows}
                schema_only = sorted(schema_keys - profile_keys)
                profile_only = sorted(profile_keys - schema_keys)
                if schema_only or profile_only:
                    logger.warning(
                        "schema_profile_mismatch",
                        correlation_id=startup_correlation_id,
                        document_type_key=dtkey,
                        schema_only=schema_only,
                        profile_only=profile_only,
                    )
    except Exception as exc:  # noqa: BLE001
        failure = technical_failure(exc, operation="processing")
        logger.warning(
            "schema_profile_consistency_check_failed",
            correlation_id=startup_correlation_id,
            error_code="STARTUP_VALIDATION_FAILED",
            technical_class=failure.code,
            **safe_exception_context(exc),
        )


def create_app() -> FastAPI:
    from verigence.di.logging_config import configure_logging  # noqa: PLC0415

    configure_logging(process="api")
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
        """Start background workers + EOD scheduler on startup; stop on shutdown."""
        del fastapi_app
        from verigence.di.scheduler.beat import get_eod_scheduler  # noqa: PLC0415
        from verigence.di.workers.capture_v2_classifier import (  # noqa: PLC0415
            get_capture_v2_classifier_worker,
        )
        from verigence.di.workers.processor import get_worker  # noqa: PLC0415

        worker = get_worker()
        capture_v2_worker = get_capture_v2_classifier_worker()
        scheduler = get_eod_scheduler()
        if settings.worker_enabled:
            worker.start()
            capture_v2_worker.start()
            scheduler.start()
        try:
            await _validate_schema_profile_consistency()
            yield
        finally:
            if settings.worker_enabled:
                await capture_v2_worker.stop()
                await worker.stop()
                scheduler.stop()
            shutdown_observability()

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

    observability_state = configure_observability(app, settings)
    logger.info(
        "di_observability_configured",
        logs_enabled=observability_state.logs_enabled,
        errors_enabled=observability_state.errors_enabled,
        metrics_enabled=observability_state.metrics_enabled,
        traces_enabled=observability_state.traces_enabled,
    )

    def custom_openapi() -> dict[str, Any]:
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=(
            ["*"] if not settings.is_production
            else ["https://di-ops.verigence.app"]
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[CORRELATION_ID_HEADER, TRACE_ID_HEADER],
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        correlation_id = correlation_id_or_new()
        detail, issues = validation_problem_detail(exc.errors())
        body = problem_response(
            ErrorCode.INVALID_REQUEST,
            detail=detail,
            correlation_id=correlation_id,
            extensions={"validationIssues": issues} if issues else None,
        )
        logger.info(
            "di_validation_error",
            error_code=ErrorCode.INVALID_REQUEST.code,
            error_category=ErrorCode.INVALID_REQUEST.error_category,
            validation_issue_count=len(issues),
            http_status=400,
            method=request.method,
            route=_route_template(request),
            correlation_id=correlation_id,
        )
        return _problem_json(400, body, correlation_id)

    # Register against Starlette's base HTTPException so framework-generated
    # routing failures (404/405) receive the same business error contract as
    # FastAPI/application HTTPExceptions.
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        correlation_id = correlation_id_or_new()
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            body = _complete_problem_body(exc.detail, exc.status_code)
        elif _is_framework_default_detail(exc):
            # Router-generated 404/405 etc. carry only the status phrase.
            mapped = error_for_http_status(exc.status_code)
            body = problem_response(mapped, detail=mapped.title)
        else:
            # Application-raised HTTPException(status, "caller-safe message").
            mapped = error_for_app_status(exc.status_code)
            body = problem_response(mapped, detail=str(exc.detail))
        # The response body/header pair must always use the correlation id
        # created/bound for this request, even if a caller supplied another.
        body["correlationId"] = correlation_id
        _log_problem(
            request,
            status_code=exc.status_code,
            body=body,
            correlation_id=correlation_id,
            cause=exc.__cause__,
        )
        return _problem_json(exc.status_code, body, correlation_id, exc.headers)

    @app.exception_handler(ProblemException)
    async def _problem_exception_handler(
        request: Request, exc: ProblemException
    ) -> JSONResponse:
        correlation_id = correlation_id_or_new()
        body = problem_response(exc.error, detail=exc.detail, correlation_id=correlation_id)
        _log_problem(
            request,
            status_code=exc.error.http_status,
            body=body,
            correlation_id=correlation_id,
            cause=exc.__cause__,
        )
        return _problem_json(exc.error.http_status, body, correlation_id)

    @app.middleware("http")
    async def correlation_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(CORRELATION_ID_HEADER, "")
        correlation_id = (
            incoming
            if incoming and _is_valid_correlation_id(incoming)
            else str(uuid.uuid4())
        )
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        attach_correlation_to_current_span(correlation_id)

        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            failure = technical_failure(exc, operation="api")
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.error(
                "api_request_failed",
                error_code=failure.code,
                error_category=ErrorCode.INTERNAL_ERROR.error_category,
                http_status=500,
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                **safe_exception_context(exc),
            )
            body = problem_response(
                ErrorCode.INTERNAL_ERROR,
                detail=failure.detail,
                correlation_id=correlation_id,
            )
            response = _problem_json(500, body, correlation_id)

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        trace_id, _span_id = current_trace_context()
        if trace_id:
            response.headers[TRACE_ID_HEADER] = trace_id

        status_class = f"{response.status_code // 100}xx"
        route = _route_template(request)
        metric_labels = {
            "method": request.method,
            "route": route,
            "status_class": status_class,
        }
        record_metric("di.http.requests", labels=metric_labels)
        record_metric(
            "di.http.duration_ms",
            duration_ms,
            kind="histogram",
            labels=metric_labels,
        )
        if response.status_code >= 400:
            record_metric("di.http.errors", labels=metric_labels)

        if not is_probe_path(request.url.path):
            # One line per request with its response time (2026-09-30), plus
            # the business ids from the path.
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                route=route,
                status=response.status_code,
                duration_ms=duration_ms,
                **_path_context(request),
            )
        return response

    from verigence.di.api.health import router as health_router  # noqa: PLC0415
    from verigence.di.api.v1.admin_provisioning import (  # noqa: PLC0415
        router as admin_provisioning_router,
    )
    from verigence.di.api.v1.analyse import router as analyse_router  # noqa: PLC0415
    from verigence.di.api.v1.audit_storage_contexts import (  # noqa: PLC0415
        router as audit_storage_contexts_router,
    )
    from verigence.di.api.v1.configuration_proposals import (
        router as configuration_proposals_router,  # noqa: PLC0415
    )
    from verigence.di.api.v1.documents import router as documents_router  # noqa: PLC0415
    from verigence.di.api.v1.entity_links import router as entity_links_router  # noqa: PLC0415
    from verigence.di.api.v1.extraction_profiles import (
        router as extraction_profiles_router,  # noqa: PLC0415
    )
    from verigence.di.api.v1.field_lineage import router as field_lineage_router  # noqa: PLC0415
    from verigence.di.api.v1.operations import router as operations_router  # noqa: PLC0415
    from verigence.di.api.v1.pc_booking_documents import (  # noqa: PLC0415
        router as pc_booking_documents_router,
    )
    from verigence.di.api.v1.project_masters import (
        router as project_masters_router,  # noqa: PLC0415
    )
    from verigence.di.api.v1.requirement_profiles import (
        router as requirement_profiles_router,  # noqa: PLC0415
    )
    from verigence.di.api.v1.subject_matching import (
        router as subject_matching_router,  # noqa: PLC0415
    )
    from verigence.di.api.v1.subjects import router as subjects_router  # noqa: PLC0415
    from verigence.di.api.v1.tenant_config import router as tenant_config_router  # noqa: PLC0415
    from verigence.di.api.v1.tenant_housekeeping import (  # noqa: PLC0415
        router as tenant_housekeeping_router,
    )
    from verigence.di.api.v1.unassigned import router as unassigned_router  # noqa: PLC0415
    from verigence.di.api.v1.verification import router as verification_router  # noqa: PLC0415
    from verigence.di.api.v1.whatsapp_system import (
        router as whatsapp_system_router,  # noqa: PLC0415
    )
    from verigence.di.api.v2.capture_documents import (  # noqa: PLC0415
        router as capture_v2_router,
    )

    app.include_router(health_router)
    app.include_router(subjects_router)
    app.include_router(documents_router)
    app.include_router(field_lineage_router)
    app.include_router(audit_storage_contexts_router)
    app.include_router(pc_booking_documents_router)
    app.include_router(admin_provisioning_router)
    app.include_router(tenant_housekeeping_router)
    app.include_router(project_masters_router)
    app.include_router(verification_router)
    app.include_router(operations_router)
    app.include_router(entity_links_router)
    app.include_router(requirement_profiles_router)
    app.include_router(extraction_profiles_router)
    app.include_router(configuration_proposals_router)
    app.include_router(tenant_config_router)
    app.include_router(subject_matching_router)
    app.include_router(unassigned_router)
    app.include_router(whatsapp_system_router)
    app.include_router(analyse_router)
    app.include_router(capture_v2_router)

    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                environment=settings.env.value,
                traces_sample_rate=(0.1 if settings.observability_traces_enabled else 0.0),
            )
        except ImportError:
            logger.warning(
                "sentry_sdk_unavailable",
                correlation_id=correlation_id_or_new(),
                reason="package_not_installed",
            )

    return app


app = create_app()
