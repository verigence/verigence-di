from pathlib import Path

import pytest
from sqlalchemy import text

SCREENSHOT_REQUIRED_FIELDS = {
    "customer_email",
    "ex_showroom_price",
    "road_tax_registration",
    "insurance_amount",
    "accessories_cost",
    "additional_warranty_amount",
    "balance_amount",
    "bonus_amount",
    "mode_of_payment",
    "payment_reference_no",
    "buffer_discount_amount",
    "corporate_discount_amount",
    "discount_amount",
    "dealer_name",
}


@pytest.mark.no_docker
def test_booking_docket_parity_migration_copies_form_contract_and_rules() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0029_uc03_booking_docket_business_parity.py"
    ).read_text(encoding="utf-8")
    compact = source.replace(" ", "")

    assert '"booking_docket"' in source
    assert '"booking_form"' in source
    assert "profile_field_normalizers" in source
    assert "profile_field_validators" in source
    assert "form.canonical_field_id" in source
    assert "old.canonical_field_id=form.canonical_field_id" in compact
    assert "form.extraction_instruction" in source
    assert "form.aliases" in source
    assert "form.fact_role_override" in source
    assert "never invent" in source.lower()


async def _published_fields(db_session, document_type_key: str) -> set[str]:
    rows = await db_session.execute(
        text(
            """
            SELECT COALESCE(epf.extraction_key, cf.field_key) AS field_key
            FROM docintel.extraction_profiles ep
            JOIN docintel.document_types dt
              ON dt.document_type_id=ep.document_type_id
            JOIN docintel.extraction_profile_fields epf
              ON epf.profile_id=ep.profile_id
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id=epf.canonical_field_id
            WHERE dt.owner_tenant_id IS NULL
              AND dt.document_type_key=:document_type_key
              AND ep.scope_tenant_id IS NULL
              AND ep.status='PUBLISHED'
            """
        ),
        {"document_type_key": document_type_key},
    )
    return {str(row[0]) for row in rows.all()}


@pytest.mark.asyncio
async def test_booking_docket_published_profile_has_booking_form_business_parity(
    db_session,
) -> None:
    booking_form = await _published_fields(db_session, "booking_form")
    booking_docket = await _published_fields(db_session, "booking_docket")

    assert booking_form >= SCREENSHOT_REQUIRED_FIELDS
    assert booking_docket >= SCREENSHOT_REQUIRED_FIELDS
    assert booking_docket >= booking_form


@pytest.mark.asyncio
async def test_booking_docket_keeps_docket_specific_fields_after_parity(db_session) -> None:
    booking_docket = await _published_fields(db_session, "booking_docket")
    assert booking_docket >= {
        "deal_type",
        "out_of_scope_reasons",
        "dsa_commission_amount",
        "exchange_applicable",
    }
