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
    # profile_field_validators/extraction_profile_fields are guarded
    # immutable once their parent profile is PUBLISHED
    # (guard_extraction_profile_child, 0001_initial_schema.py) -- a direct
    # write against an already-published profile's children raises
    # "published/retired extraction profile children are immutable"
    # outright. Confirmed live: an earlier version of this migration tried
    # exactly that in-place INSERT and every test failed at fixture setup
    # (alembic upgrade head aborting). This must instead clone each
    # affected profile into a new DRAFT version (copying its fields,
    # normalizers and validators verbatim), attach the new validator to
    # the clone's DATE fields, then retire the old version and publish the
    # clone -- same versioned-publish shape 0041 uses for one document
    # type, generalized here across every profile that needs it.
    assert "INSERT INTO docintel.extraction_profiles" in source
    assert "INSERT INTO docintel.extraction_profile_fields" in source
    assert "status = 'RETIRED'" in source
    assert "status = 'PUBLISHED'" in source


@pytest.mark.asyncio
async def test_every_published_date_field_has_the_validator_wired(
    db_session: AsyncSession,
) -> None:
    version = (
        await db_session.execute(text("SELECT version_num FROM docintel.alembic_version"))
    ).scalar_one()
    assert version == "0043"

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

    # The clone must carry forward every rule the original profile already
    # had (normalizers and other validators), not just the new one --
    # otherwise cloning to work around the immutability guard would have
    # silently dropped existing quality gates for every profile it touched.
    # Scoped to profiles this migration itself created (created_by_actor_id)
    # and the specific profile it actually retired, not every historical
    # retired/published pair for the same document type -- an unrelated,
    # legitimately-changed field set between two much older versions is not
    # this migration's concern.
    #
    # Identifying "the specific profile it retired" by new_ep.version_no - 1
    # is unreliable: a document type can already carry older DRAFT/RETIRED
    # rows with gaps in their version numbers (confirmed live -- one
    # document type's version_no - 1 landed on an unrelated pre-existing
    # row, not the profile this migration actually cloned from, making
    # every one of that unrelated row's normalizers look "dropped"). The
    # migration always retires exactly the one profile that was PUBLISHED
    # immediately before creating the clone, so among every RETIRED profile
    # with a version_no below the clone's own, that retired profile is
    # unambiguously the one with the *highest* such version_no -- nothing
    # else could be closer without being the clone itself.
    dropped_normalizers = (
        await db_session.execute(
            text(
                """
                SELECT new_ep.document_type_id, cf.field_key, old_pfn.rule_key
                FROM docintel.extraction_profiles new_ep
                JOIN docintel.extraction_profiles old_ep
                  ON old_ep.document_type_id = new_ep.document_type_id
                 AND old_ep.scope_tenant_id IS NOT DISTINCT FROM new_ep.scope_tenant_id
                 AND old_ep.status = 'RETIRED'
                 AND old_ep.version_no = (
                     SELECT MAX(o2.version_no)
                     FROM docintel.extraction_profiles o2
                     WHERE o2.document_type_id = new_ep.document_type_id
                       AND o2.scope_tenant_id IS NOT DISTINCT FROM new_ep.scope_tenant_id
                       AND o2.status = 'RETIRED'
                       AND o2.version_no < new_ep.version_no
                 )
                JOIN docintel.extraction_profile_fields old_epf
                  ON old_epf.profile_id = old_ep.profile_id
                JOIN docintel.profile_field_normalizers old_pfn
                  ON old_pfn.profile_field_id = old_epf.profile_field_id
                JOIN docintel.canonical_fields cf
                  ON cf.canonical_field_id = old_epf.canonical_field_id
                WHERE new_ep.created_by_actor_id = :actor
                  AND NOT EXISTS (
                      SELECT 1
                      FROM docintel.extraction_profile_fields new_epf
                      JOIN docintel.profile_field_normalizers new_pfn
                        ON new_pfn.profile_field_id = new_epf.profile_field_id
                      WHERE new_epf.profile_id = new_ep.profile_id
                        AND new_epf.canonical_field_id = old_epf.canonical_field_id
                        AND new_pfn.rule_key = old_pfn.rule_key
                  )
                """
            ),
            {"actor": "migration.0042.date-plausibility-validation"},
        )
    ).mappings().all()
    assert dropped_normalizers == [], f"Normalizers lost during clone: {dropped_normalizers}"
