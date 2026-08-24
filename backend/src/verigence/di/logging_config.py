"""Structured DI logging with safe optional OpenTelemetry mirroring.

stdout remains the local/runtime diagnostic channel. Axiom/OTLP export is handled by the
shared OTel batch processors in ``verigence.di.otel``; logging never performs network I/O.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from verigence.di.otel import otel_log_processor

_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


class _LevelFilter:
    """Drop events below the configured minimum level."""

    def __init__(self, min_level: str) -> None:
        self._min = _LEVEL_ORDER.get(min_level.upper(), 20)

    def __call__(
        self,
        logger: Any,
        method: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        del logger
        level = method.upper()
        if _LEVEL_ORDER.get(level, 20) < self._min:
            raise structlog.DropEvent
        return event_dict


def configure_logging() -> None:
    """Configure structlog. Remote telemetry remains optional and fail-open."""
    from verigence.di.settings import get_settings

    settings = get_settings()
    level_str = settings.log_level.upper()
    use_stdout = settings.log_stdout
    is_dev = settings.env.value in ("local", "dev")

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _LevelFilter(level_str),
        otel_log_processor,
    ]

    if use_stdout:
        if is_dev:
            processors.append(structlog.dev.ConsoleRenderer())
        else:
            processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    output = sys.stdout if use_stdout else open("/dev/null", "w")  # noqa: SIM115
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            _LEVEL_ORDER.get(level_str, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=output),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=_LEVEL_ORDER.get(level_str, logging.INFO),
        force=True,
    )

    if not is_dev:
        for noisy in ("sqlalchemy.engine", "httpx", "httpcore", "apscheduler"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.get_logger(__name__).info(
        "logging_configured",
        log_level=level_str,
        stdout=use_stdout,
        env=settings.env.value,
    )
