"""logging_config.py — Structured logging pipeline (D27).

Single output channel:
  - stdout: always safe; JSON in production/uat, pretty in local/dev

Call configure_logging() once at process startup — before any log emission.

Security/diagnostic guarantees:
  - request/document/provider input values are removed from structured events;
  - ``logger.exception`` cannot render a full traceback;
  - exception messages are not emitted by the central logging pipeline;
  - warning/error events always carry a correlation id;
  - stdlib exception formatting is reduced to a bounded code-location summary.

Configuration (all DI_ prefixed env vars, read from Settings):
  DI_LOG_LEVEL      DEBUG | INFO | WARNING | ERROR  (default: INFO)
  DI_LOG_STDOUT     true | false                    (default: true)
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from verigence.di.runtime_errors import correlation_id_or_new, safe_exception_context

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

        level = method.lower()
        if level in {"warning", "error", "critical", "exception"}:
            correlation_id = sanitized.get("correlation_id")
            sanitized["correlation_id"] = correlation_id_or_new(correlation_id)
        return sanitized


class _SafeStdlibFormatter(logging.Formatter):
    """Prevent stdlib/third-party ``exc_info`` from printing a full traceback."""

    def formatException(  # noqa: N802
        self,
        ei: tuple[type[BaseException], BaseException, object],
    ) -> str:
        exc = ei[1]
        context = safe_exception_context(exc)
        frames = context["stack_summary"]
        rendered = " <- ".join(frames) if frames else "no-python-frames"
        suffix = " [truncated]" if context["stack_truncated"] else ""
        return f"{context['exception_type']}: {rendered}{suffix}"


# ── Public API ────────────────────────────────────────────────────────────────
def configure_logging() -> None:
    """Configure the safe structlog + stdlib logging pipeline."""
    from verigence.di.settings import get_settings

    settings = get_settings()

    level_str = settings.log_level.upper()
    use_stdout = settings.log_stdout
    is_dev = settings.env.value in ("local", "dev")

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _LevelFilter(level_str),
        _SafeEventProcessor(),
    ]

    output_processors: list[Any] = list(shared_processors)
    if use_stdout:
        if is_dev:
            output_processors.append(structlog.dev.ConsoleRenderer())
        else:
            output_processors.append(structlog.processors.JSONRenderer())
    else:
        output_processors.append(structlog.processors.JSONRenderer())

    null_stream = None
    if use_stdout:
        output_file = sys.stdout
    else:
        null_stream = open("/dev/null", "w")  # noqa: SIM115
        output_file = null_stream

    structlog.configure(
        processors=output_processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            _LEVEL_ORDER.get(level_str, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=output_file),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib explicitly rather than basicConfig's default formatter:
    # logging.Formatter otherwise appends the complete traceback for exc_info.
    handler = logging.StreamHandler(sys.stdout if use_stdout else null_stream)
    handler.setFormatter(_SafeStdlibFormatter("%(message)s"))
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(_LEVEL_ORDER.get(level_str, logging.INFO))

    # SQL text/parameters and APScheduler internals are operational noise in every
    # environment. Keep application-level DI events, warnings and errors visible,
    # but suppress these framework loggers unless explicitly overridden at runtime.
    for noisy in ("sqlalchemy.engine", "sqlalchemy.pool", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Keep HTTP client diagnostics available in local/dev, but quiet in UAT/prod.
    if not is_dev:
        for noisy in ("httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.get_logger(__name__).info(
        "logging_configured",
        log_level=level_str,
        stdout=use_stdout,
        env=settings.env.value,
    )
