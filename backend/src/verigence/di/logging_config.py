"""logging_config.py — Structured logging pipeline (D27).

Single local output channel:
  - stdout: always safe; JSON on every deployed environment (including dev),
    human-readable console output only for ``DI_ENV=local`` or
    ``DI_LOG_FORMAT=console``.

Both structlog events and stdlib ``logging`` records (auth, alembic, uvicorn,
third-party libraries) pass through the same sanitiser and renderer, so every
line carries level, timestamp, service/environment/version/process and the
bound correlation id.

When DI observability is enabled, the already-sanitized structured event is also
queued for OTLP log/error export and low-cardinality metric derivation. Remote
telemetry never sees request/document/provider values removed by this pipeline.
Only structlog events are exported remotely; stdlib records are rendered to
stdout only, because their free-text messages (e.g. uvicorn access lines with
paths) are unsuitable as metric labels.

Call configure_logging() once at process startup — before any log emission.

Security/diagnostic guarantees:
  - request/document/provider input values are removed from structured events;
  - ``logger.exception`` cannot render a full traceback;
  - exception messages are not emitted by the central logging pipeline;
  - a correlation id is emitted whenever one is bound (request/job scope); none
    is invented for events outside such a scope;
  - stdlib exception formatting is reduced to a bounded code-location summary.

Configuration (all DI_ prefixed env vars, read from Settings):
  DI_LOG_LEVEL      DEBUG | INFO | WARNING | ERROR  (default: INFO)
  DI_LOG_STDOUT     true | false                    (default: true)
  DI_LOG_FORMAT     json | console                  (default: console for local, json otherwise)
Version is read from VERIGENCE_GIT_SHA / RAILWAY_GIT_COMMIT_SHA / VERIGENCE_RELEASE.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

from verigence.di.observability import emit_otel_log, record_event_metrics
from verigence.di.runtime_errors import safe_exception_context

# ── Level filtering ───────────────────────────────────────────────────────────

_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

# Values under these keys can contain caller input, document contents, extracted
# values, credentials or raw downstream responses. Keep metadata (counts,
# status, field keys, ids, timings) but never the value itself.
_SENSITIVE_LOG_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "artifact_bytes",
        "authorization",
        "body",
        "content",
        "cookie",
        "cookies",
        "current_value",
        "detail",
        "document_bytes",
        "error",
        "error_detail",
        "error_message",
        "error_summary",
        "exc_msg",
        "field_value",
        "filename",
        "file_name",
        "headers",
        "input",
        "inputs",
        "left_value",
        "new_value",
        "normalized_value",
        "old_value",
        "parse_error",
        "password",
        "payload",
        "prompt",
        "provider_detail",
        "provider_raw",
        "provider_response",
        "query",
        "query_params",
        "raw_provider_response",
        "raw_response",
        "raw_snippet",
        "raw_text",
        "raw_value",
        "request_body",
        "response_body",
        "response_text",
        "right_value",
        "secret",
        "token",
        "value",
    }
)


class _LevelFilter:
    """Drop events below the configured minimum level."""

    def __init__(self, min_level: str) -> None:
        self._min = _LEVEL_ORDER.get(min_level.upper(), 20)

    def __call__(
        self,
        logger: Any,  # noqa: ANN401
        method: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        del logger
        level = method.upper()
        if _LEVEL_ORDER.get(level, 20) < self._min:
            raise structlog.DropEvent
        return event_dict


def _sanitize_nested(value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, dict):
        return {
            key: _sanitize_nested(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_LOG_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_nested(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_nested(item) for item in value)
    return value


class _SafeEventProcessor:
    """Remove sensitive values and replace exception tracebacks with a short summary."""

    def __call__(
        self,
        logger: Any,  # noqa: ANN401
        method: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        del logger
        exc_info = event_dict.pop("exc_info", None)
        exc: BaseException | None = None
        if isinstance(exc_info, tuple) and len(exc_info) == 3:
            candidate = exc_info[1]
            if isinstance(candidate, BaseException):
                exc = candidate
        elif exc_info:
            candidate = sys.exc_info()[1]
            if isinstance(candidate, BaseException):
                exc = candidate

        # Never pass renderer-native traceback fields downstream. A bounded
        # location-only summary is sufficient to locate the failing code.
        event_dict.pop("traceback", None)
        event_dict.pop("stack", None)
        event_dict.pop("stack_info", None)
        if exc is not None:
            event_dict.update(safe_exception_context(exc))

        sanitized = _sanitize_nested(event_dict)
        if not isinstance(sanitized, dict):  # defensive; event_dict is always dict
            sanitized = {"event": "invalid_log_event"}
        del method
        return sanitized


class _ObservabilityProcessor:
    """Fan out only sanitized DI events to enabled remote telemetry capabilities."""

    def __call__(
        self,
        logger: Any,  # noqa: ANN401
        method: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        del logger, method
        emit_otel_log(event_dict)
        record_event_metrics(event_dict)
        return event_dict


class _ServiceContextProcessor:
    """Stamp every line with the emitting service, environment, version and process."""

    def __init__(self, *, service: str, environment: str, version: str, process: str) -> None:
        self._fields = {
            "service": service,
            "environment": environment,
            "version": version,
            "process": process,
            "pid": os.getpid(),
        }

    def __call__(
        self,
        logger: Any,  # noqa: ANN401
        method: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        del logger, method
        for key, value in self._fields.items():
            event_dict.setdefault(key, value)
        return event_dict


def _drop_stdlib_noise(
    logger: Any,  # noqa: ANN401
    method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Remove stdlib-only attributes that duplicate the rendered message."""
    del logger, method
    # uvicorn attaches an ANSI-coloured copy of every message.
    event_dict.pop("color_message", None)
    return event_dict


class _HealthAccessFilter(logging.Filter):
    """Drop uvicorn access lines for liveness/readiness probes."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn.access: (client_addr, method, full_path, http_version, status_code)
        if isinstance(args, tuple) and len(args) >= 3:
            path = str(args[2])
            if is_probe_path(path):
                return False
        return True


def is_probe_path(path: str) -> bool:
    """Return True for health/readiness probe paths that must not be logged per call."""
    bare = path.split("?", 1)[0]
    return bare == "/ready" or bare == "/health" or bare.startswith("/health/")


def service_version() -> str:
    """Deployed build identifier (short git SHA when available)."""
    sha = os.getenv("VERIGENCE_GIT_SHA") or os.getenv("RAILWAY_GIT_COMMIT_SHA")
    if sha and sha.strip():
        return sha.strip()[:12]
    release = os.getenv("VERIGENCE_RELEASE")
    if release and release.strip():
        return release.strip()[:40]
    return "unknown"


def use_console_renderer(env: str, log_format: str | None) -> bool:
    """Console output only for local runs or an explicit ``DI_LOG_FORMAT=console``."""
    requested = (log_format or "").strip().lower()
    if requested == "console":
        return True
    if requested == "json":
        return False
    return env == "local"


_NOISY_LIBRARIES = (
    "sqlalchemy.engine",
    "sqlalchemy.pool",
    "apscheduler",
    "httpx",
    "httpcore",
    "botocore",
    "boto3",
    "urllib3",
    "s3transfer",
)
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


# ── Public API ────────────────────────────────────────────────────────────────
def configure_logging(process: str | None = None) -> None:
    """Configure the safe structlog + stdlib logging pipeline.

    ``process`` names the runtime role (``api`` for the FastAPI service); when
    omitted, the DI worker topology from ``DI_WORKER_MODE`` is used.
    """
    from verigence.di.settings import get_settings

    settings = get_settings()

    level_str = settings.log_level.upper()
    level_no = _LEVEL_ORDER.get(level_str, logging.INFO)
    use_stdout = settings.log_stdout
    env = settings.env.value
    console = use_console_renderer(env, settings.log_format)
    process_name = process or f"worker-{settings.worker_mode.value}"

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    service_context = _ServiceContextProcessor(
        service=settings.observability_service_name,
        environment=env,
        version=service_version(),
        process=process_name,
    )
    renderer: Any = (
        structlog.dev.ConsoleRenderer() if console else structlog.processors.JSONRenderer()
    )

    structlog_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
        service_context,
        _LevelFilter(level_str),
        _SafeEventProcessor(),
        _ObservabilityProcessor(),
        renderer,
    ]

    null_stream = None
    if use_stdout:
        output_file = sys.stdout
    else:
        null_stream = open("/dev/null", "w")  # noqa: SIM115
        output_file = null_stream

    structlog.configure(
        processors=structlog_processors,
        wrapper_class=structlog.make_filtering_bound_logger(level_no),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=output_file),
        cache_logger_on_first_use=True,
    )

    # stdlib records (auth, alembic, uvicorn, boto, ...) get the same fields,
    # the same sanitiser and the same renderer as structlog events. The
    # sanitiser also replaces exc_info with a bounded code-location summary.
    foreign_pre_chain: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        _drop_stdlib_noise,
        timestamper,
        service_context,
        _SafeEventProcessor(),
    ]
    stdlib_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=foreign_pre_chain,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout if use_stdout else null_stream)
    handler.setFormatter(stdlib_formatter)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level_no)

    # SQL text/parameters, scheduler internals and HTTP/S3 client chatter are
    # operational noise in every environment; keep their warnings and errors.
    for noisy in _NOISY_LIBRARIES:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # uvicorn installs its own handlers before importing the app. Route its
    # records through the root pipeline instead, without probe access lines.
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _HealthAccessFilter) for item in access_logger.filters):
        access_logger.addFilter(_HealthAccessFilter())

    structlog.get_logger(__name__).info(
        "logging_configured",
        log_level=level_str,
        stdout=use_stdout,
        log_format="console" if console else "json",
    )
