"""OpenTelemetry bootstrap for Verigence DI.

The telemetry backend is never part of the DI transaction path. Export uses bounded SDK
queues/batches and initialization/export failures are fail-open.
"""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import SeverityNumber, set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_REQUIRED_OTLP_ENDPOINTS = (
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
)

_OTEL_LOGGER: Any | None = None
_PROCESSING_COUNTER: Any | None = None
_PROCESSING_DURATION: Any | None = None
_EXTRACTION_DURATION: Any | None = None

_SAFE_LOG_EVENTS = frozenset(
    {
        "http_request_failed",
        "schema_profile_mismatch",
        "schema_profile_consistency_check_failed",
        "upload_rejected",
        "intake_error",
        "processing_job_created",
        "classification_failed",
        "extraction_result",
        "processing_run_failed",
        "processing_run_unexpected_error",
        "job_completed",
        "job_retry_pending",
        "job_failed_backout",
        "job_runner_unexpected_escape",
        "processing_worker_loop_error",
        "notify_listener_failed",
    }
)

_SAFE_LOG_ATTRIBUTES = frozenset(
    {
        "correlation_id",
        "actor_id",
        "user_id",
        "tenant_id",
        "project_id",
        "journey_id",
        "evidence_id",
        "document_id",
        "processing_job_id",
        "processing_run_id",
        "document_type_key",
        "physical_form_type",
        "job_type",
        "attempt_no",
        "worker_id",
        "method",
        "path",
        "route",
        "status",
        "status_code",
        "duration_ms",
        "total_duration_ms",
        "extract_duration_ms",
        "error_code",
        "error_class",
        "retryable",
        "reason",
        "result",
        "fields_found",
        "fields_null",
        "fields_low_confidence",
        "schema_field_count",
        "confidence_score",
        "human_verification_status",
        "upload_status",
        "rules_run",
        "rules_failed",
        "ttl_hours",
        "exc_type",
    }
)

_SEVERITY = {
    "debug": SeverityNumber.DEBUG,
    "info": SeverityNumber.INFO,
    "warning": SeverityNumber.WARN,
    "error": SeverityNumber.ERROR,
    "critical": SeverityNumber.FATAL,
}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _service_version() -> str:
    return (
        os.getenv("VERIGENCE_GIT_SHA")
        or os.getenv("RAILWAY_GIT_COMMIT_SHA")
        or os.getenv("VERIGENCE_RELEASE")
        or "unknown"
    )


def _otlp_endpoints_configured() -> bool:
    return all(os.getenv(name, "").strip() for name in _REQUIRED_OTLP_ENDPOINTS)


def _bootstrap_warning(reason: str, exception_type: str | None = None) -> None:
    payload = {
        "severity": "WARNING",
        "event_name": "observability_bootstrap_disabled",
        "service_name": "verigence-di",
        "reason": reason,
    }
    if exception_type:
        payload["exception_type"] = exception_type
    sys.stderr.write(json.dumps(payload, separators=(",", ":")) + "\n")


def emit_otel_log(event_dict: Mapping[str, Any]) -> None:
    """Queue one allow-listed operational event for asynchronous OTLP export."""
    if _OTEL_LOGGER is None:
        return
    event_name = str(event_dict.get("event", ""))
    if event_name not in _SAFE_LOG_EVENTS:
        return
    try:
        level = str(event_dict.get("level", "info")).lower()
        attributes = {
            key: value
            for key, value in event_dict.items()
            if key in _SAFE_LOG_ATTRIBUTES and value is not None
        }
        _OTEL_LOGGER.emit(
            severity_number=_SEVERITY.get(level, SeverityNumber.INFO),
            severity_text=level.upper(),
            body=event_name,
            event_name=event_name,
            attributes=attributes,
        )
    except Exception:
        return


def otel_log_processor(
    logger: Any,
    method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor that mirrors only safe events to the OTel batch queue."""
    del logger, method
    emit_otel_log(event_dict)
    return event_dict


def attach_request_context(correlation_id: str) -> None:
    """Attach the Verigence logical transaction ID to the active API span."""
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("verigence.correlation_id", correlation_id)


def attach_identity_context(*, actor_id: str, tenant_id: str) -> None:
    """Attach trusted opaque Security identity context after JWT verification."""
    structlog.contextvars.bind_contextvars(actor_id=actor_id, tenant_id=tenant_id)
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("verigence.user.id", actor_id)
        span.set_attribute("verigence.tenant.id", tenant_id)


def attach_business_context(context: Mapping[str, str]) -> None:
    """Attach opaque business IDs to logs/traces only, never metric labels."""
    safe_context = {key: value for key, value in context.items() if value}
    if not safe_context:
        return
    structlog.contextvars.bind_contextvars(**safe_context)
    span = trace.get_current_span()
    if span.is_recording():
        for key, value in safe_context.items():
            span.set_attribute(f"verigence.{key.replace('_', '.')}", value)


def _current_correlation_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("correlation_id")
    return str(value) if value else None


def _httpx_request_hook(span: Any, request: Any) -> None:
    correlation_id = _current_correlation_id()
    if not correlation_id:
        return
    if request.headers is not None:
        request.headers["X-Correlation-ID"] = correlation_id
    if span is not None and span.is_recording():
        span.set_attribute("verigence.correlation_id", correlation_id)


async def _httpx_async_request_hook(span: Any, request: Any) -> None:
    _httpx_request_hook(span, request)


def record_processing_job(*, outcome: str, job_type: str, duration_ms: float) -> None:
    """Record bounded-cardinality DI processing health metrics."""
    if _PROCESSING_COUNTER is None or _PROCESSING_DURATION is None:
        return
    attributes = {"outcome": outcome, "job_type": job_type}
    _PROCESSING_COUNTER.add(1, attributes)
    _PROCESSING_DURATION.record(duration_ms, attributes)


def record_extraction_duration(*, outcome: str, document_type_key: str, duration_ms: float) -> None:
    """Record extraction duration without document/customer identifiers."""
    if _EXTRACTION_DURATION is None:
        return
    _EXTRACTION_DURATION.record(
        duration_ms,
        {"outcome": outcome, "document_type": document_type_key},
    )


@contextmanager
def processing_job_span(
    *,
    correlation_id: str,
    tenant_id: str,
    document_id: str,
    processing_job_id: str,
    job_type: str,
) -> Iterator[Any]:
    """Create the worker-side trace for one persisted asynchronous processing job."""
    tracer = trace.get_tracer("verigence.di.worker")
    with tracer.start_as_current_span("di.process_document") as span:
        if span.is_recording():
            span.set_attribute("verigence.correlation_id", correlation_id)
            span.set_attribute("verigence.tenant.id", tenant_id)
            span.set_attribute("verigence.document.id", document_id)
            span.set_attribute("verigence.processing.job.id", processing_job_id)
            span.set_attribute("verigence.job.type", job_type)
        with structlog.contextvars.bound_contextvars(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            document_id=document_id,
            processing_job_id=processing_job_id,
            job_type=job_type,
        ):
            yield span


@contextmanager
def provider_span(
    operation: str,
    *,
    document_type_key: str | None = None,
) -> Iterator[Any]:
    """Create a concise span around a Document AI provider operation."""
    tracer = trace.get_tracer("verigence.di.worker")
    with tracer.start_as_current_span(f"di.document_ai.{operation}") as span:
        if span.is_recording() and document_type_key:
            span.set_attribute("verigence.document.type", document_type_key)
        yield span


def configure_otel(*, service_name: str, app: FastAPI | None = None) -> bool:
    """Configure Phase-1 non-blocking OTel export for API or worker processes."""
    global _EXTRACTION_DURATION, _OTEL_LOGGER, _PROCESSING_COUNTER, _PROCESSING_DURATION

    if not _env_bool("OBSERVABILITY_ENABLED"):
        return False
    if not _otlp_endpoints_configured():
        _bootstrap_warning("missing_otlp_endpoint_configuration")
        return False

    try:
        export_timeout_seconds = _env_float("OBSERVABILITY_EXPORT_TIMEOUT_SECONDS", 2.0)
        export_timeout_ms = int(export_timeout_seconds * 1000)
        batch_delay_ms = _env_int("OBSERVABILITY_BATCH_DELAY_MS", 1000)
        max_queue_size = _env_int("OBSERVABILITY_MAX_QUEUE_SIZE", 2048)
        max_export_batch_size = _env_int("OBSERVABILITY_MAX_EXPORT_BATCH_SIZE", 512)
        metric_interval_ms = _env_int("OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS", 60000)

        resource = Resource.create(
            {
                "service.namespace": "verigence",
                "service.name": service_name,
                "service.version": _service_version(),
                "deployment.environment.name": os.getenv("DI_ENV", "local"),
            }
        )

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(timeout=export_timeout_seconds),
                max_queue_size=max_queue_size,
                max_export_batch_size=max_export_batch_size,
                schedule_delay_millis=batch_delay_ms,
                export_timeout_millis=export_timeout_ms,
            )
        )

        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(timeout=export_timeout_seconds),
            export_interval_millis=metric_interval_ms,
            export_timeout_millis=export_timeout_ms,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])

        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(timeout=export_timeout_seconds),
                max_queue_size=max_queue_size,
                max_export_batch_size=max_export_batch_size,
                schedule_delay_millis=batch_delay_ms,
                export_timeout_millis=export_timeout_ms,
            )
        )

        trace.set_tracer_provider(tracer_provider)
        metrics.set_meter_provider(meter_provider)
        set_logger_provider(logger_provider)
        _OTEL_LOGGER = logger_provider.get_logger("verigence.di")

        meter = meter_provider.get_meter("verigence.di")
        _PROCESSING_COUNTER = meter.create_counter(
            "verigence.di.processing.jobs",
            unit="{job}",
            description="DI processing jobs by bounded outcome and job type",
        )
        _PROCESSING_DURATION = meter.create_histogram(
            "verigence.di.processing.duration_ms",
            unit="ms",
            description="DI end-to-end worker processing duration",
        )
        _EXTRACTION_DURATION = meter.create_histogram(
            "verigence.di.extraction.duration_ms",
            unit="ms",
            description="DI document extraction provider duration",
        )

        if app is not None:
            FastAPIInstrumentor.instrument_app(
                app,
                tracer_provider=tracer_provider,
                meter_provider=meter_provider,
                excluded_urls="/health,/ready",
            )
        HTTPXClientInstrumentor().instrument(
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            request_hook=_httpx_request_hook,
            async_request_hook=_httpx_async_request_hook,
        )
        SQLAlchemyInstrumentor().instrument(tracer_provider=tracer_provider)
        return True
    except Exception as exc:
        _OTEL_LOGGER = None
        _PROCESSING_COUNTER = None
        _PROCESSING_DURATION = None
        _EXTRACTION_DURATION = None
        _bootstrap_warning("initialization_failed", type(exc).__name__)
        return False
