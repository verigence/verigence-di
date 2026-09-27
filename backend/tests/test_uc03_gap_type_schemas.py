"""Dedicated schemas for the UC03 types migration 0046 profiled.

Each schema must keep exactly the published profile's field keys (the D25
startup consistency check) and its required flags must match the profile's
"expected" flags, so confidence scoring is unchanged in meaning."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from verigence.di.document_ai.schemas import FALLBACK_SCHEMA, get_schema

pytestmark = pytest.mark.no_docker

_MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0046_uc03_delivery_extraction_profile_gaps.py"
_TYPES = (
    "vehicle_rc", "transfer_letter", "authorization_letter", "cost_sheet",
    "value_added_service_document", "no_dues_certificate",
)


def _profiles() -> dict:
    spec = importlib.util.spec_from_file_location("di_migration_0046", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module._PROFILES


@pytest.mark.parametrize("document_type_key", _TYPES)
def test_gap_type_has_a_dedicated_schema(document_type_key: str) -> None:
    schema = get_schema(document_type_key)
    assert schema is not FALLBACK_SCHEMA
    assert schema.document_type_key == document_type_key
    assert schema.system_prompt and schema.prompt_notes


@pytest.mark.parametrize("document_type_key", _TYPES)
def test_schema_matches_the_published_profile(document_type_key: str) -> None:
    _, _, profile_fields = _profiles()[document_type_key]
    expected = {key: required for key, required, *_ in profile_fields}
    schema = get_schema(document_type_key)
    assert {f.key: f.required for f in schema.fields} == expected


def test_amounts_and_dates_are_normalised() -> None:
    for document_type_key in _TYPES:
        for field in get_schema(document_type_key).fields:
            if field.key.endswith("_date"):
                assert field.field_type == "date" and field.normalization == "date_dd_mm_yyyy", field.key
            if field.key.endswith(("_amount", "_price")):
                assert field.field_type == "number" and field.normalization == "indian_currency", field.key
