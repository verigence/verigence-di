from __future__ import annotations

from typing import Any

import pytest

from verigence.di import observability
from verigence.di.settings import Settings


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "secret_key": "x" * 32,
        "database_url": "postgresql://user:pass@localhost:5432/test",
    }
    values.update(overrides)
    return Settings(**values)


def test_observability_capabilities_are_off_by_default() -> None:
    settings = _settings()

    assert settings.observability_logs_enabled is False
    assert settings.observability_errors_enabled is False
    assert settings.observability_metrics_enabled is False
    assert settings.observability_traces_enabled is False

    state = observability.configure_observability(None, settings)
    assert state.logs_enabled is False
    assert state.errors_enabled is False
    assert state.metrics_enabled is False
    assert state.traces_enabled is False


def test_trace_switch_is_independent_from_other_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        observability_logs_enabled=True,
        observability_errors_enabled=True,
        observability_metrics_enabled=True,
        observability_traces_enabled=False,
    )
    real_configure_traces = observability._configure_traces
    monkeypatch.setattr(observability, "_configure_logs", lambda *_args: (True, True))
    monkeypatch.setattr(observability, "_configure_metrics", lambda *_args: True)

    trace_called = False

    def _trace_probe(*_args: Any) -> bool:
        nonlocal trace_called
        trace_called = True
        return False

    monkeypatch.setattr(observability, "_configure_traces", _trace_probe)
    state = observability.configure_observability(None, settings)

    # The trace capability remains independently disabled even when logs/errors
    # and metrics are enabled.
    assert trace_called is True
    assert state.logs_enabled is True
    assert state.errors_enabled is True
    assert state.metrics_enabled is True
    assert state.traces_enabled is False

    real_settings = _settings(observability_traces_enabled=False)
    assert real_configure_traces(
        None,
        real_settings,
        observability._resource(real_settings),
    ) is False


def test_errors_only_is_a_distinct_remote_log_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted: list[dict[str, Any]] = []

    class _Logger:
        def emit(self, **kwargs: Any) -> None:
            emitted.append(kwargs)

    monkeypatch.setattr(observability, "_otel_logger", _Logger())
    monkeypatch.setattr(observability, "_export_all_logs", False)
    monkeypatch.setattr(observability, "_export_errors", True)

    observability.emit_otel_log({"event": "job_completed", "level": "info"})
    observability.emit_otel_log(
        {
            "event": "job_failed_backout",
            "level": "warning",
            "error_code": "WORKER_INTERNAL_ERROR",
            "correlation_id": "corr-1",
        }
    )

    assert len(emitted) == 1
    assert emitted[0]["body"] == "job_failed_backout"
    assert emitted[0]["attributes"]["error_code"] == "WORKER_INTERNAL_ERROR"


def test_remote_log_allowlist_drops_unapproved_values(monkeypatch: pytest.MonkeyPatch) -> None:
    emitted: list[dict[str, Any]] = []

    class _Logger:
        def emit(self, **kwargs: Any) -> None:
            emitted.append(kwargs)

    monkeypatch.setattr(observability, "_otel_logger", _Logger())
    monkeypatch.setattr(observability, "_export_all_logs", True)
    monkeypatch.setattr(observability, "_export_errors", False)

    observability.emit_otel_log(
        {
            "event": "gemini_response",
            "level": "info",
            "correlation_id": "corr-2",
            "document_id": "doc-2",
            "response_tokens": 12,
            "raw_response": "must-not-be-exported",
            "prompt": "must-not-be-exported",
        }
    )

    attributes = emitted[0]["attributes"]
    assert attributes["correlation_id"] == "corr-2"
    assert attributes["document_id"] == "doc-2"
    assert attributes["response_tokens"] == 12
    assert "raw_response" not in attributes
    assert "prompt" not in attributes


def test_metric_labels_reject_business_identifiers() -> None:
    with pytest.raises(ValueError, match="High-cardinality metric labels"):
        observability._safe_metric_labels({"route": "/v1/documents", "document_id": "doc-1"})

    assert observability._safe_metric_labels(
        {"route": "/v1/documents/{document_id}", "status_class": "2xx"}
    ) == {"route": "/v1/documents/{document_id}", "status_class": "2xx"}


def test_observability_batch_size_cannot_exceed_queue_size() -> None:
    with pytest.raises(ValueError, match="MAX_EXPORT_BATCH_SIZE"):
        _settings(
            observability_max_queue_size=100,
            observability_max_export_batch_size=101,
        )
