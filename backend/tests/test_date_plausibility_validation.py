"""Tests for migration 0042 -- the date-plausibility validator.

Confirmed live: OCR/LLM date extraction on dealership documents
occasionally misreads a year, landing an invoice/receipt/delivery date
years away from reality with nothing catching it (di.val.date_not_future
only ever catches a date after today). See rules/validators.py's
_val_date_plausible_range for the deterministic check itself (unit-tested
in test_rules.py) -- this file covers the migration that actually wires
it to every DATE-typed field on every published, tenant-agnostic profile.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_RULE_KEY = "date_plausible_range"


@pytest.mark.no_docker
def test_migration_source_registers_the_rule_and_wires_every_date_field() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0042_date_plausibility_validation.py"
    ).read_text(encoding="utf-8")
    assert "di.val.date_plausible_range" in source
    assert "cf.data_type = 'DATE'" in source
    assert "ep.status = 'PUBLISHED'" in source
    # Runtime-config addition, not a new extraction contract -- must not
    # touch extraction_profile_fields (what gets extracted) or publish a
    # new profile version, only profile_field_validators (a quality gate).
    assert "INSERT INTO docintel.extraction_profile_fields" not in source
    assert "INSERT INTO docintel.extraction_profiles" not in source


@pytest.mark.asyncio
async def test_every_published_date_field_has_the_validator_wired(
    db_session: AsyncSession,
) -> None:
    version = (
        await db_session.execute(text("SELECT version_num FROM docintel.alembic_version"))
    ).scalar_one()
    assert version == "0042"

    catalog_row = (
        await db_session.execute(
            text(
                """
                SELECT implementation_key, result_scope, status
                FROM docintel.validation_rule_catalog
                WHERE rule_key = :rule_key
                """
            ),
            {"rule_key": _RULE_KEY},
        )
    ).mappings().one()
    assert catalog_row["implementation_key"] == "di.val.date_plausible_range"
    assert catalog_row["result_scope"] == "FIELD"
    assert catalog_row["status"] == "ACTIVE"

    unwired = (
        await db_session.execute(
            text(
                """
                SELECT cf.field_key, ep.document_type_id
                FROM docintel.extraction_profile_fields epf
                JOIN docintel.canonical_fields cf
                  ON cf.canonical_field_id = epf.canonical_field_id
                JOIN docintel.extraction_profiles ep
                  ON ep.profile_id = epf.profile_id
                WHERE cf.data_type = 'DATE'
                  AND ep.status = 'PUBLISHED'
                  AND ep.scope_tenant_id IS NULL
                  AND epf.enabled = true
                  AND NOT EXISTS (
                      SELECT 1 FROM docintel.profile_field_validators pfv
                      WHERE pfv.profile_field_id = epf.profile_field_id
                        AND pfv.rule_key = :rule_key
                  )
                """
            ),
            {"rule_key": _RULE_KEY},
        )
    ).mappings().all()
    assert unwired == [], f"DATE fields missing the plausibility validator: {unwired}"

    # Severity must be ERROR -- job_runner.py's deterministic_rules_force_
    # review only reacts to ERROR-severity FAILs (FieldValidationOutput.
    # has_error_fail); a WARNING/INFO severity would silently never route
    # a bad date to PC review at all.
    severities = (
        await db_session.execute(
            text(
                "SELECT DISTINCT severity FROM docintel.profile_field_validators "
                "WHERE rule_key = :rule_key"
            ),
            {"rule_key": _RULE_KEY},
        )
    ).scalars().all()
    assert severities == ["ERROR"]
