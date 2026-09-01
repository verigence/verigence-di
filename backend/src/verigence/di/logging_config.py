"""logging_config.py — Structured logging pipeline (D27).

Single output channel:
  - stdout: always safe; JSON in production/uat, pretty in local/dev

Call configure_logging() once at process startup — before any log emission.

Configuration (all DI_ prefixed env vars, read from Settings):
  DI_LOG_LEVEL      DEBUG | INFO | WARNING | ERROR  (default: INFO)
  DI_LOG_STDOUT     true | false                    (default: true)
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


# ── Level filtering ───────────────────────────────────────────────────────────

_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


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
        level = method.upper()
        if _LEVEL_ORDER.get(level, 20) < self._min:
            raise structlog.DropEvent
        return event_dict


# ── Public API ────────────────────────────────────────────────────────────────
def configure_logging() -> None:
    """Configure the structlog pipeline. Call once at process startup."""
    from verigence.di.settings import get_settings
    settings = get_settings()

    level_str   = settings.log_level.upper()
    use_stdout  = settings.log_stdout
    is_dev      = settings.env.value in ("local", "dev")

    # ── Shared pre-processors (run before any output) ─────────────────────────
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _LevelFilter(level_str),
    ]

    # ── Output processors ────────────────────────────────────────────────────
    output_processors: list[Any] = list(shared_processors)

    if use_stdout:
        if is_dev:
            output_processors.append(structlog.dev.ConsoleRenderer())
        else:
            output_processors.append(structlog.processors.JSONRenderer())
    else:
        # At least keep a no-op renderer so structlog doesn't crash
        output_processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=output_processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            _LEVEL_ORDER.get(level_str, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout if use_stdout else open(  # noqa: WPS515, SIM115
            "/dev/null", "w"
        )),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging so third-party libraries use the same root sink.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=_LEVEL_ORDER.get(level_str, logging.INFO),
        force=True,
    )

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
