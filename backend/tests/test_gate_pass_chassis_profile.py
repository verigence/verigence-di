"""Migration 0068: the gate pass reads the chassis number (gate_pass schema 1.1;
closing list item 5, 2026-11-16)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from verigence.di.document_ai.schemas import get_schema
from verigence.di.document_ai.schemas.form_21 import FORM_21_SCHEMA
from verigence.di.document_ai.schemas.gate_pass import GATE_PASS_SCHEMA


def _migration() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0068_gate_pass_chassis_number.py"
    spec = importlib.util.spec_from_file_location("mig_0068", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.no_docker
def test_the_snapshot_equals_the_schema() -> None:
    fields = _migration()._FIELDS
    assert [f[0] for f in fields] == [f.key for f in GATE_PASS_SCHEMA.fields]
    by_key = {f[0]: f for f in fields}
    for spec in GATE_PASS_SCHEMA.fields:
        assert by_key[spec.key][2] == spec.description, spec.key
        assert by_key[spec.key][3] is spec.required, spec.key
    assert get_schema("gate_pass") is GATE_PASS_SCHEMA and GATE_PASS_SCHEMA.schema_version == "1.1"


@pytest.mark.no_docker
def test_0068_follows_0067_and_reuses_the_publisher() -> None:
    module = _migration()
    assert module.down_revision == "0067"
    publisher = module._publisher()
    assert publisher._TYPE_KEY == "gate_pass" and publisher._FIELDS == module._FIELDS


@pytest.mark.no_docker
def test_form_21_asks_for_the_full_vin() -> None:
    vin = next(f for f in FORM_21_SCHEMA.fields if f.key == "vin_number")
    assert "full 17-character VIN" in vin.description and FORM_21_SCHEMA.schema_version == "1.1"
