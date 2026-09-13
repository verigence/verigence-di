"""Provider-neutral observability for Verigence DI.

Logs, metrics and traces are independent capabilities.  Each capability is
fail-open: telemetry configuration/export failures must never block DI business
processing.  Remote export uses standard OTLP/HTTP variables, so Axiom can be the
backend without introducing an Axiom-specific runtime dependency.

Tracing is deliberately disabled by default.  When disabled, DI does not create a
TracerProvider and does not install FastAPI, HTTPX or SQLAlchemy trace
instrumentation.
"""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
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

from verigence.di.settings import Settings

_SAFE_REMOTE_LOG_ATTRIBUTES = frozenset(
    {
        "adapter",
        "attempt",
        "audit_requirement_ref",
        "classification_job_id",
        "correlation_id",
        "document_id",
        "document_type_key",
        "duration_ms",
        "env",
        "error_category",
        "error_class",
        "error_code",
        "event",
        "fallback",
        "fast_retry_scheduled",
        "fields_extracted",
        "fields_low_confidence",
        "fields_null",
        "fields_with_evidence_region",
        "fields_with_page",
        "gemini_model",
        "http_status",
        "job_type",
        "level",
        "method",
        "operation",
        "path",
        "physical_form_type",
        "processing_job_id",
        "processing_lane",
        "provider",
        "replica_id",
        "replica_region",
        "response_tokens",
        "retryable",
        "route",
        "schema_field_count",
        "status",
        "status_code",
        "tenant_id",
        "timestamp",
        "total_duration_ms",
        "worker_id",
        "worker_mode",
    }
)

_FORBIDDEN_METRIC_LABELS = frozenset(
    {
        "actor_id",
        "classification_job_id",
        "correlation_id",
        "customer_id",
        "document_id",
        "journey_id",
        "processing_job_id",
        "subject_id",
        "tenant_id",
        "trace_id",
        "span_id",
    }
)

_SEVERITY = {
    "debug": SeverityNumber.DEBUG,
    "info": SeverityNumber.INFO,
    "warning": SeverityNumber.WARN,
    "error": SeverityNumber.ERROR,
    "critical": SeverityNumber.FATAL,
    "exception": SeverityNumber.ERROR,
}


@dataclass(frozen=True)
class ObservabilityState:
    """Effective DI telemetry state after fail-open initialization."""

    logs_enabled: bool
    metrics_enabled: bool
    traces_enabled: bool


_otel_logger: Any | None = None
_meter_provider: MeterProvider | None = None
_tracer_provider: TracerProvider | None = None
_meter: Any | None = None
_instruments: dict[tuple[str, str], Any] = {}
_httpx_instrumented = False
_sqlalchemy_instrumented = False
_fastapi_instrumented = False


def _service_version() -> str:
    return (
        os.getenv("VERIGENCE_GIT_SHA")
        or os.getenv("RAILWAY_GIT_COMMIT_SHA")
        or os.getenv("VERIGENCE_RELEASE")
        or "unknown"
    )


def _resource(settings: Settings) -> Resource:
    return Resource.create(
        {
            "service.namespace": "verigence",
            "service.name": settings.observability_service_name,
            "service.version": _service_version(),
            "deployment.environment.name": settings.env.value,
        }
    )


def _signal_endpoint_configured(signal: str) -> bool:
    specific = os.getenv(f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT", "").strip()
    generic = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return bool(specific or generic)


def _bootstrap_warning(capability: str, reason: str, exc: BaseException | None = None) -> None:
    payload: dict[str, str] = {
        "severity": "WARNING",
        "event": "di_observability_capability_disabled",
        "capability": capability,
        "reason": reason,
        "service_name": "verigence-di",
    }
    if exc is not None:
        payload["exception_type"] = type(exc).__name__
    sys.stderr.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _export_timeout_ms(settings: Settings) -> int:
    return int(settings.observability_export_timeout_seconds * 1000)


def _configure_logs(settings: Settings, resource: Resource) -> bool:
    global _otel_logger
    if not settings.observability_logs_enabled:
        return False
    if not _signal_endpoint_configured("logs"):
        _bootstrap_warning("logs", "missing_otlp_endpoint")
        return False
    try:
        provider = LoggerProvider(resource=resource)
        provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(timeout=settings.observability_export_timeout_seconds),
                max_queue_size=settings.observability_max_queue_size,
                max_export_batch_size=settings.observability_max_export_batch_size,
                schedule_delay_millis=settings.observability_batch_delay_ms,
                export_timeout_millis=_export_timeout_ms(settings),
            )
        )
        _otel_logger = provider.get_logger("verigence.di")
        # Keep a strong reference for shutdown via the logger provider itself.
        setattr(_otel_logger, "_verigence_provider", provider)
        return True
    except Exception as exc:  # noqa: BLE001 -- observability must fail open
        _otel_logger = None
        _bootstrap_warning("logs", "initialization_failed", exc)
        return False


def _configure_metrics(settings: Settings, resource: Resource) -> bool:
    global _meter_provider, _meter
    if not settings.observability_metrics_enabled:
        return False
    if not _signal_endpoint_configured("metrics"):
        _bootstrap_warning("metrics", "missing_otlp_endpoint")
        return False
    try:
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(timeout=settings.observability_export_timeout_seconds),
            export_interval_millis=settings.observability_metric_export_interval_ms,
            export_timeout_millis=_export_timeout_ms(settings),
        )
        _meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        _meter = _meter_provider.get_meter("verigence.di")
        return True
    except Exception as exc:  # noqa: BLE001 -- observability must fail open
        _meter_provider = None
        _meter = None
        _bootstrap_warning("metrics", "initialization_failed", exc)
        return False


def _configure_traces(
    app: FastAPI | None,
    settings: Settings,
    resource: Resource,
) -> bool:
    global _tracer_provider, _httpx_instrumented, _sqlalchemy_instrumented
    global _fastapi_instrumented

    if not settings.observability_traces_enabled:
        return False
    if not _signal_endpoint_configured("traces"):
        _bootstrap_warning("traces", "missing_otlp_endpoint")
        return False
    try:
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(timeout=settings.observability_export_timeout_seconds),
                max_queue_size=settings.observability_max_queue_size,
                max_export_batch_size=settings.observability_max_export_batch_size,
                schedule_delay_millis=settings.observability_batch_delay_ms,
                export_timeout_millis=_export_timeout_ms(settings),
            )
        )
        trace.set_tracer_provider(provider)
        _tracer_provider = provider

        if app is not None:
            FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls="/health,/ready")
            _fastapi_instrumented = True
        HTTPXClientInstrumentor().instrument(
            tracer_provider=provider,
            request_hook=_httpx_request_hook,
            async_request_hook=_httpx_async_request_hook,
        )
        _httpx_instrumented = True
        SQLAlchemyInstrumentor().instrument(tracer_provider=provider)
        _sqlalchemy_instrumented = True
        return True
    except Exception as exc:  # noqa: BLE001 -- observability must fail open
        _bootstrap_warning("traces", "initialization_failed", exc)
        return False


def configure_observability(app: FastAPI | None, settings: Settings) -> ObservabilityState:
    """Initialize only the DI telemetry capabilities explicitly enabled."""
    resource = _resource(settings)
    return ObservabilityState(
        logs_enabled=_configure_logs(settings, resource),
        metrics_enabled=_configure_metrics(settings, resource),
        traces_enabled=_configure_traces(app, settings, resource),
    )


def _primitive_attribute(value: Any) -> Any | None:
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)) and all(
        isinstance(item, (str, bool, int, float)) for item in value
    ):
        return tuple(value)
    return None


def emit_otel_log(event_dict: Mapping[str, Any]) -> None:
    """Export one already-sanitized DI structured event when log export is active."""
    if _otel_logger is None:
        return
    try:
        event_name = str(event_dict.get("event", "di_event"))
        level = str(event_dict.get("level", "info")).lower()
        attributes: dict[str, Any] = {}
        for key, value in event_dict.items():
            if key not in _SAFE_REMOTE_LOG_ATTRIBUTES or value is None:
                continue
            safe_value = _primitive_attribute(value)
            if safe_value is not None:
                attributes[key] = safe_value
        trace_id, span_id = current_trace_context()
        if trace_id:
            attributes["trace_id"] = trace_id
        if span_id:
            attributes["span_id"] = span_id
        _otel_logger.emit(
            severity_number=_SEVERITY.get(level, SeverityNumber.INFO),
            severity_text=level.upper(),
            body=event_name,
            event_name=event_name,
            attributes=attributes,
        )
    except Exception:
        # Remote observability is never allowed to affect business processing.
        return


def _safe_metric_labels(labels: Mapping[str, str]) -> dict[str, str]:
    forbidden = _FORBIDDEN_METRIC_LABELS.intersection(labels)
    if forbidden:
        names = ", ".join(sorted(forbidden))
        raise ValueError(f"High-cardinality metric labels are forbidden: {names}")
    return {str(key): str(value) for key, value in labels.items()}


def record_metric(
    name: str,
    value: float = 1,
    *,
    kind: str = "counter",
    labels: Mapping[str, str] | None = None,
) -> None:
    """Record one bounded-cardinality DI metric when metric export is active."""
    if _meter is None:
        return
    safe_labels = _safe_metric_labels(labels or {})
    try:
        key = (name, kind)
        instrument = _instruments.get(key)
        if instrument is None:
            if kind == "histogram":
                instrument = _meter.create_histogram(name)
            elif kind == "gauge":
                instrument = _meter.create_gauge(name)
            else:
                instrument = _meter.create_counter(name)
            _instruments[key] = instrument

        if kind == "histogram":
            instrument.record(float(value), safe_labels)
        elif kind == "gauge":
            instrument.set(float(value), safe_labels)
        else:
            instrument.add(float(value), safe_labels)
    except Exception:
        return


def record_event_metrics(event_dict: Mapping[str, Any]) -> None:
    """Derive low-cardinality operational metrics from existing safe DI events."""
    if _meter is None:
        return
    event = str(event_dict.get("event", "di_event"))
    level = str(event_dict.get("level", "info")).lower()
    record_metric("di.events", labels={"event": event, "level": level})

    error_code = event_dict.get("error_code")
    if level in {"error", "critical", "exception"} or error_code:
        labels = {"event": event}
        if isinstance(error_code, str) and error_code:
            labels["error_code"] = error_code
        record_metric("di.errors", labels=labels)

    duration = event_dict.get("duration_ms", event_dict.get("total_duration_ms"))
    if isinstance(duration, (int, float)):
        record_metric(
            "di.event.duration_ms",
            float(duration),
            kind="histogram",
            labels={"event": event},
        )

    dedicated_counter = {
        "capture_v2_classification_started": "di.classification.started",
        "capture_v2_classification_result": "di.classification.completed",
        "capture_v2_classification_unknown": "di.classification.unknown",
        "capture_v2_classification_attempt_failed": "di.classification.failed",
        "job_claimed": "di.processing.claimed",
        "job_completed": "di.processing.completed",
        "job_retry_pending": "di.processing.retry_pending",
        "job_failed_backout": "di.processing.failed",
        "gemini_request": "di.gemini.requests",
        "gemini_response": "di.gemini.responses",
        "gemini_api_error": "di.gemini.errors",
        "gemini_retry": "di.gemini.retries",
    }.get(event)
    if dedicated_counter:
        record_metric(dedicated_counter)

    if event == "gemini_response":
        prompt_tokens = event_dict.get("prompt_tokens")
        response_tokens = event_dict.get("response_tokens")
        if isinstance(prompt_tokens, (int, float)):
            record_metric("di.gemini.input_tokens", float(prompt_tokens))
        if isinstance(response_tokens, (int, float)):
            record_metric("di.gemini.output_tokens", float(response_tokens))


def current_trace_context() -> tuple[str | None, str | None]:
    """Return active W3C trace/span IDs, or ``None`` when tracing is disabled."""
    span = trace.get_current_span()
    context = span.get_span_context()
    if not context.is_valid:
        return None, None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")


def attach_correlation_to_current_span(correlation_id: str) -> None:
    """Attach the always-on DI correlation ID to an optional active trace."""
    if not correlation_id:
        return
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("verigence.correlation_id", correlation_id)


def _current_correlation_id() -> str | None:
    try:
        import structlog

        value = structlog.contextvars.get_contextvars().get("correlation_id")
        return str(value) if value else None
    except Exception:
        return None


def _httpx_request_hook(span: Any, request: Any) -> None:
    correlation_id = _current_correlation_id()
    if correlation_id and request.headers is not None:
        request.headers["X-Correlation-ID"] = correlation_id
    if correlation_id and span is not None and span.is_recording():
        span.set_attribute("verigence.correlation_id", correlation_id)


async def _httpx_async_request_hook(span: Any, request: Any) -> None:
    _httpx_request_hook(span, request)


def shutdown_observability() -> None:
    """Flush active DI telemetry providers without raising into the business path."""
    global _otel_logger, _meter_provider, _tracer_provider, _meter
    global _httpx_instrumented, _sqlalchemy_instrumented, _fastapi_instrumented

    if _otel_logger is not None:
        provider = getattr(_otel_logger, "_verigence_provider", None)
        if provider is not None:
            try:
                provider.shutdown()
            except Exception:
                pass
    if _meter_provider is not None:
        try:
            _meter_provider.shutdown()
        except Exception:
            pass
    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
        except Exception:
            pass

    _otel_logger = None
    _meter_provider = None
    _tracer_provider = None
    _meter = None
    _instruments.clear()
    _httpx_instrumented = False
    _sqlalchemy_instrumented = False
    _fastapi_instrumented = False
