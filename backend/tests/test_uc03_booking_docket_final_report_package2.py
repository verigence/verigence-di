from pathlib import Path

import pytest
from sqlalchemy import text

BASELINE_BOOKING_DOCKET_FIELDS = {
    "dealer_name",
    "dealer_branch",
    "booking_reference_number",
    "booking_date",
    "customer_name",
    "customer_phone",
    "vehicle_model",
    "vehicle_variant",
    "vehicle_color",
    "booking_amount_paid",
    "total_price",
    "sales_person",
}

PACKAGE2_FIELDS = {
    "deal_type",
    "out_of_scope_reasons",
    "dsa_commission_amount",
    "exchange_applicable",
}


@pytest.mark.no_docker
def test_package2_migration_is_booking_docket_only_and_preserves_profile_rules() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0027_uc03_booking_docket_final_report.py"
    ).read_text(encoding="utf-8")
    compact = source.replace(" ", "")

    assert "document_type_key='booking_docket'" in source
    assert "profile_field_normalizers" in source
    assert "profile_field_validators" in source
    assert "new_epf.canonical_field_id=old_epf.canonical_field_id" in compact
    assert "booking_form" not in source
    assert "classifier" in source.lower()


@pytest.mark.no_docker
def test_package2_source_contract_is_explicit_and_fail_closed() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0027_uc03_booking_docket_final_report.py"
    ).read_text(encoding="utf-8")

    for field_key in PACKAGE2_FIELDS:
        assert f'"{field_key}"' in source

    lowered = source.lower()
    assert "never infer" in lowered
    assert "never calculate" in lowered
    assert "return null" in lowered
    assert "explicitly" in lowered


async def _published_booking_docket_fields(db_session):
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
              AND dt.document_type_key='booking_docket'
              AND ep.scope_tenant_id IS NULL
              AND ep.status='PUBLISHED'
            ORDER BY epf.display_sequence, epf.profile_field_id
            """
        )
    )
    return {row[0]: (row[1], row[2]) for row in rows.all()}


@pytest.mark.asyncio
async def test_package2_migration_is_head_and_booking_docket_profile_is_published(
    db_session,
) -> None:
    version = (
        await db_session.execute(text("SELECT version_num FROM docintel.alembic_version"))
    ).scalar_one()
    assert version == "0027"

    published_count = (
        await db_session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM docintel.extraction_profiles ep
                JOIN docintel.document_types dt
                  ON dt.document_type_id=ep.document_type_id
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key='booking_docket'
                  AND ep.scope_tenant_id IS NULL
                  AND ep.status='PUBLISHED'
                """
            )
        )
    ).scalar_one()
    assert published_count == 1

    fields = await _published_booking_docket_fields(db_session)
    assert fields.keys() >= BASELINE_BOOKING_DOCKET_FIELDS
    assert fields.keys() >= PACKAGE2_FIELDS

    assert fields["deal_type"][0] == "STRING"
    assert fields["out_of_scope_reasons"][0] == "STRING"
    assert fields["dsa_commission_amount"][0] == "CURRENCY"
    assert fields["exchange_applicable"][0] == "BOOLEAN"

    assert "never infer" in fields["deal_type"][1].lower()
    assert "never manufacture" in fields["out_of_scope_reasons"][1].lower()
    assert "never calculate" in fields["dsa_commission_amount"][1].lower()
    assert "never infer" in fields["exchange_applicable"][1].lower()
