"""Tests for dedicated legacy/V2 worker topology configuration."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from verigence.di.settings import Settings, WorkerMode


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "secret_key": "x" * 32,
        "database_url": "postgresql://user:pass@localhost:5432/di",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_worker_topology_defaults_preserve_combined_local_mode() -> None:
    settings = _settings()

    assert settings.worker_mode is WorkerMode.COMBINED
    assert settings.v2_classification_concurrency == 6
    assert settings.v2_extraction_concurrency == 4


def test_v2_worker_topology_accepts_bounded_four_by_four_pool() -> None:
    settings = _settings(
        worker_mode="v2",
        v2_classification_concurrency=4,
        v2_extraction_concurrency=4,
    )

    assert settings.worker_mode is WorkerMode.V2
    assert settings.v2_classification_concurrency == 4
    assert settings.v2_extraction_concurrency == 4


def test_v2_worker_topology_rejects_unbounded_zero_pool() -> None:
    with pytest.raises(ValidationError):
        _settings(v2_extraction_concurrency=0)
