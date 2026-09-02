from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.document_ai.schemas import get_schema


@pytest.mark.no_docker
def test_gate_pass_schema_is_minimal_and_fail_closed() -> None:
    schema = get_schema("gate_pass")
    fields = {field.key: field for field in schema.fields}
    assert set(fields) == {
        "delivery_date",
        "car_number_as_printed",
        "vehicle_registration_number",
    }
    assert "only when" in fields["vehicle_registration_number"].description.lower()


@pytest.mark.no_docker
def test_aadhaar_keeps_raw_address_and_explicit_components() -> None:
    fields = {field.key: field for field in get_schema("aadhaar").fields}
    assert {
        "aadhaar_address",
        "address_pincode",
        "address_state",
        "address_district",
    } <= fields.keys()
    assert "do not derive" in fields["address_state"].description.lower()
    assert "do not infer" in fields["address_district"].description.lower()


@pytest.mark.no_docker
def test_every_invoice_schema_exposes_the_consolidated_vehicle_superset() -> None:
    keys = (
        "wholesale_invoice",
        "customer_invoice_dms",
        "tax_invoice_tally",
        "accessory_invoice_dms",
        "accessory_invoice_tally",
        "ew_invoice",
        "rsa_invoice",
        "invoice_generic",
    )
    required = {
        "invoice_heading_as_printed",
        "buyer_gstin",
        "buyer_gstin_status",
        "financed_by",
        "grand_total_amount",
        "model_name_raw",
        "variant_raw",
        "vin_number",
        "chassis_number",
        "engine_number",
        "key_number",
        "vehicle_color",
        "vehicle_hsn_code",
    }
    for key in keys:
        fields = {field.key for field in get_schema(key).fields}
        assert required <= fields, key


async def _published_field_keys(db_session: AsyncSession, document_type_key: str) -> set[str]:
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
              AND dt.document_type_key=:key
              AND ep.scope_tenant_id IS NULL
              AND ep.status='PUBLISHED'
            ORDER BY ep.version_no DESC, epf.display_sequence
            """
        ),
        {"key": document_type_key},
    )
    return {row[0] for row in rows.all()}


@pytest.mark.asyncio
async def test_package1_migration_is_head_and_profiles_are_published(
    db_session: AsyncSession,
) -> None:
    version = (await db_session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert version == "0026"

    published = await db_session.execute(
        text(
            """
            SELECT dt.document_type_key, COUNT(*)
            FROM docintel.extraction_profiles ep
            JOIN docintel.document_types dt
              ON dt.document_type_id=ep.document_type_id
            WHERE dt.owner_tenant_id IS NULL
              AND dt.document_type_key IN ('gate_pass', 'gst_certificate')
              AND ep.scope_tenant_id IS NULL
              AND ep.status='PUBLISHED'
            GROUP BY dt.document_type_key
            """
        )
    )
    assert dict(published.all()) == {"gate_pass": 1, "gst_certificate": 1}

    gate_pass_fields = await _published_field_keys(db_session, "gate_pass")
    assert gate_pass_fields == {
        "delivery_date",
        "car_number_as_printed",
        "vehicle_registration_number",
    }

    aadhaar_fields = await _published_field_keys(db_session, "aadhaar")
    assert {"address_pincode", "address_state", "address_district"} <= aadhaar_fields

    invoice_fields = await _published_field_keys(db_session, "invoice_generic")
    assert {
        "invoice_heading_as_printed",
        "buyer_gstin_status",
        "model_name_raw",
        "variant_raw",
        "key_number",
        "vehicle_color",
        "vehicle_hsn_code",
    } <= invoice_fields
