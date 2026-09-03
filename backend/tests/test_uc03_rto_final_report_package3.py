from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.document_ai.schemas import get_schema

RTO_FIELDS = {
    "registration_number",
    "registration_state",
    "registration_territory",
    "registration_district",
    "ex_showroom_amount",
    "registration_type",
    "hp_charges_amount",
}


@pytest.mark.no_docker
def test_package3_rto_schema_is_registered_and_fail_closed() -> None:
    schema = get_schema("rto_challan")
    assert schema.document_type_key == "rto_challan"
    assert schema.display_name == "RTO Challan"
    assert schema.schema_version == "1.0"

    fields = {field.key: field for field in schema.fields}
    assert set(fields) == RTO_FIELDS
    assert fields["registration_number"].field_type == "string"
    assert fields["ex_showroom_amount"].field_type == "number"
    assert fields["hp_charges_amount"].field_type == "number"

    assert "never infer" in fields["registration_state"].description.lower()
    assert "never derive" in fields["registration_territory"].description.lower()
    assert "never infer" in fields["registration_district"].description.lower()
    assert "never calculate" in fields["ex_showroom_amount"].description.lower()
    assert "never classify" in fields["registration_type"].description.lower()
    assert "never derive" in fields["hp_charges_amount"].description.lower()


@pytest.mark.no_docker
def test_package3_migration_only_activates_existing_rto_challan_contract() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0028_uc03_rto_final_report_contract.py"
    ).read_text(encoding="utf-8")

    assert "document_type_key='rto_challan'" in source
    assert "requires_processing=true" in source
    assert "_activate_for_existing_tenants" in source
    assert "vehicle_rc" not in source
    assert "never infer" in source.lower()
    assert "never calculate" in source.lower()

    for field_key in RTO_FIELDS:
        assert f'"{field_key}"' in source


@pytest.mark.asyncio
async def test_package3_is_head_and_rto_profile_is_published(
    db_session: AsyncSession,
) -> None:
    version = (
        await db_session.execute(text("SELECT version_num FROM docintel.alembic_version"))
    ).scalar_one()
    assert version == "0028"

    published_count = (
        await db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM docintel.extraction_profiles ep
                JOIN docintel.document_types dt
                  ON dt.document_type_id=ep.document_type_id
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key='rto_challan'
                  AND ep.scope_tenant_id IS NULL
                  AND ep.status='PUBLISHED'
                """
            )
        )
    ).scalar_one()
    assert published_count == 1

    rows = await db_session.execute(
        text(
            """
            SELECT COALESCE(epf.extraction_key, cf.field_key) AS field_key,
                   cf.data_type,
                   COALESCE(epf.extraction_instruction, '') AS instruction
            FROM docintel.extraction_profiles ep
            JOIN docintel.document_types dt
              ON dt.document_type_id=ep.document_type_id
            JOIN docintel.extraction_profile_fields epf
              ON epf.profile_id=ep.profile_id
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id=epf.canonical_field_id
            WHERE dt.owner_tenant_id IS NULL
              AND dt.document_type_key='rto_challan'
              AND ep.scope_tenant_id IS NULL
              AND ep.status='PUBLISHED'
            ORDER BY epf.display_sequence, epf.profile_field_id
            """
        )
    )
    fields = {row[0]: (row[1], row[2]) for row in rows.all()}
    assert fields.keys() == RTO_FIELDS

    assert fields["registration_number"][0] == "IDENTIFIER"
    assert fields["registration_state"][0] == "STRING"
    assert fields["registration_territory"][0] == "STRING"
    assert fields["registration_district"][0] == "STRING"
    assert fields["ex_showroom_amount"][0] == "CURRENCY"
    assert fields["registration_type"][0] == "STRING"
    assert fields["hp_charges_amount"][0] == "CURRENCY"

    assert "never infer" in fields["registration_state"][1].lower()
    assert "never derive" in fields["registration_territory"][1].lower()
    assert "never infer" in fields["registration_district"][1].lower()
    assert "never calculate" in fields["ex_showroom_amount"][1].lower()
    assert "never classify" in fields["registration_type"][1].lower()
    assert "never calculate" in fields["hp_charges_amount"][1].lower()

    disabled_count = (
        await db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM docintel.tenant_document_types tdt
                JOIN docintel.document_types dt
                  ON dt.document_type_id=tdt.document_type_id
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key='rto_challan'
                  AND (tdt.requires_processing IS NOT TRUE OR tdt.is_active IS NOT TRUE)
                """
            )
        )
    ).scalar_one()
    assert disabled_count == 0
