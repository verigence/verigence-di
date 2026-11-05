"""Migration 0061: the published cost_sheet profile reads every priced row and
the title (cost_sheet schema 1.1; product owner 2026-11-05: "the cost sheet
should add up")."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.document_ai.schemas import get_schema
from verigence.di.document_ai.schemas.cost_sheet import COST_SHEET_SCHEMA


def _migration() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0061_cost_sheet_rows.py"
    spec = importlib.util.spec_from_file_location("mig_0061", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.no_docker
def test_the_snapshot_equals_the_schema() -> None:
    fields = _migration()._FIELDS
    assert [f[0] for f in fields] == [f.key for f in COST_SHEET_SCHEMA.fields]
    by_key = {f[0]: f for f in fields}
    for spec in COST_SHEET_SCHEMA.fields:
        assert by_key[spec.key][2] == spec.description, spec.key
        assert by_key[spec.key][3] is spec.required, spec.key
    assert by_key["line_items"][1] == "JSON" and by_key["document_title"][1] == "STRING"
    assert get_schema("cost_sheet") is COST_SHEET_SCHEMA and COST_SHEET_SCHEMA.schema_version == "1.1"


@pytest.mark.no_docker
def test_the_rows_are_read_as_printed_and_never_added_up() -> None:
    notes = " ".join(COST_SHEET_SCHEMA.prompt_notes)
    assert "never added together" in notes and "TCS" in notes and "extended warranty" in notes
    assert "never compute" in COST_SHEET_SCHEMA.system_prompt.lower() or "never add up" in COST_SHEET_SCHEMA.system_prompt


@pytest.mark.no_docker
def test_0061_renames_nothing_and_follows_0060() -> None:
    module = _migration()
    assert module._OLD_KEY_FOR == {} and module.down_revision == "0060"


@pytest.mark.asyncio
async def test_the_published_profile_carries_the_rows_and_the_title(db_session: AsyncSession) -> None:
    keys = set((await db_session.execute(text(
        """
        SELECT COALESCE(epf.extraction_key, cf.field_key)
        FROM docintel.extraction_profile_fields epf
        JOIN docintel.extraction_profiles ep ON ep.profile_id = epf.profile_id
        JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
        JOIN docintel.canonical_fields cf ON cf.canonical_field_id = epf.canonical_field_id
        WHERE dt.document_type_key = 'cost_sheet' AND ep.status = 'PUBLISHED' AND epf.enabled = true
        """
    ))).scalars())
    assert keys == {f.key for f in COST_SHEET_SCHEMA.fields}


@pytest.mark.no_docker
def test_the_reader_checks_its_rows_against_the_printed_totals_and_never_changes_a_total() -> None:
    """Product owner 2026-11-05: the NDC's and the cost sheet's rows add up to
    their printed totals; the reading is checked against them, never fitted."""
    from verigence.di.document_ai.schemas import get_schema

    for key in ("customer_ledger", "cost_sheet"):
        notes = " ".join(get_schema(key).prompt_notes)
        assert "CHECK YOUR READING AGAINST" in notes, key
        assert "Never change" in notes and "return them as written" in notes, key
