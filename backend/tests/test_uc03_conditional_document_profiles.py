"""Migration 0048's new profiles must ask for the fields the Gemini schema
defines -- a profile key the schema does not know loses its description and
normalisation in the prompt."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from verigence.di.document_ai.schemas import get_schema

pytestmark = pytest.mark.no_docker

_MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0048_uc03_conditional_document_profiles.py"


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0048", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("document_type_key", ["debit_note", "purchase_order"])
def test_new_profile_fields_match_the_gemini_schema(document_type_key: str) -> None:
    _, fields = _migration()._NEW_PROFILES[document_type_key]
    schema_keys = {f.key for f in get_schema(document_type_key).fields}
    profile_keys = [f[0] for f in fields]
    assert set(profile_keys) == schema_keys
    assert len(profile_keys) == len(set(profile_keys))
    assert any(expected and scored and weight > 0 for _, expected, _, _, scored, weight, _ in fields)


def test_wave1_promoted_fields_exist_in_the_gemini_schema() -> None:
    for document_type_key, promoted in _migration()._WAVE1_PROMOTE.items():
        schema_keys = {f.key for f in get_schema(document_type_key).fields}
        assert set(promoted) <= schema_keys
