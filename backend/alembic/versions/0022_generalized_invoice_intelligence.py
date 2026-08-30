"""Publish generalized invoice intelligence without changing journey requirement keys.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-30

The migration is deliberately additive:
- existing UC03/UC04 invoice document keys remain unchanged;
- one generic invoice fallback type is added for previously unseen/dealer formats;
- invoice extraction profiles are non-scoring, so activation does not introduce a
  new PC verification gate;
- historical profiles/evidence are never deleted.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_MIGRATION_ACTOR = "migration.0022.generalized-invoice-v1"
_GENERIC_KEY = "invoice_generic"
_SPECIFIC_KEYS = (
    "wholesale_invoice",
    "customer_invoice_dms",
    "tax_invoice_tally",
    "accessory_invoice_dms",
    "accessory_invoice_tally",
    "ew_invoice",
    "rsa_invoice",
)
_ALL_KEYS = (*_SPECIFIC_KEYS, _GENERIC_KEY)
F = tuple[Any, ...]


def _f(
    key: str,
    display: str,
    data_type: str,
    sequence: int,
    instruction: str,
    aliases: list[str],
) -> F:
    # Invoice extraction is evidence capture only in this increment. Nothing here
    # changes journey completion or quality scoring.
    return (key, display, data_type, False, False, 0.0, sequence, instruction, aliases)


def _common_fields() -> list[F]:
    return [
        _f("invoice_purpose", "Invoice Purpose", "STRING", 10, "Classify the business purpose from visible invoice content; use UNKNOWN when unclear.", ["purpose"]),
        _f("invoice_nature", "Invoice Nature", "STRING", 20, "Extract/derive the invoice nature from visible content; use UNKNOWN when unclear.", ["tax invoice", "retail invoice", "proforma", "credit note", "debit note"]),
        _f("source_system", "Source System", "STRING", 30, "Return DMS, TALLY, DEALER_GENERATED, OEM, THIRD_PARTY or UNKNOWN only when supported by the document.", ["source", "system"]),
        _f("issuer_role", "Issuer Role", "STRING", 40, "Return the visible issuer role; use UNKNOWN when it cannot be established reliably.", ["issuer", "seller role"]),
        _f("invoice_number", "Invoice Number", "IDENTIFIER", 50, "Extract invoice/reference number exactly as printed.", ["invoice no", "invoice number", "bill no"]),
        _f("invoice_date", "Invoice Date", "DATE", 60, "Extract invoice date exactly as printed.", ["invoice date", "date"]),
        _f("seller_name", "Seller Name", "STRING", 70, "Extract seller/issuer name exactly as printed.", ["seller", "dealer", "supplier", "issued by"]),
        _f("seller_gstin", "Seller GSTIN", "IDENTIFIER", 80, "Extract seller GSTIN exactly as printed.", ["seller gstin", "gstin", "gst no"]),
        _f("seller_address", "Seller Address", "STRING", 90, "Extract seller/issuer address exactly as printed.", ["seller address", "supplier address"]),
        _f("buyer_name", "Buyer Name", "STRING", 100, "Extract buyer/customer name exactly as printed.", ["buyer", "customer name", "bill to"]),
        _f("buyer_customer_id", "Buyer Customer ID", "IDENTIFIER", 110, "Extract customer ID only when explicitly printed.", ["customer id", "customer code"]),
        _f("buyer_gstin", "Buyer GSTIN", "IDENTIFIER", 120, "Extract buyer/customer GSTIN only when printed.", ["buyer gstin", "customer gstin"]),
        _f("buyer_address", "Buyer Address", "STRING", 130, "Extract buyer/customer address exactly as printed.", ["buyer address", "customer address", "bill to address"]),
        _f("financed_by", "Financed By", "STRING", 140, "Extract financier/hypothecation institution only when printed.", ["financed by", "hypothecation", "hypothecated to"]),
        _f("gross_amount_before_discount", "Gross Amount Before Discount", "CURRENCY", 150, "Extract the explicitly stated gross/base amount before discount; do not calculate it.", ["price of one", "gross amount", "rate", "base value"]),
        _f("invoice_discount_amount", "Invoice Discount Amount", "CURRENCY", 160, "Extract invoice-level discount exactly as stated; do not calculate it.", ["discount", "discount amount"]),
        _f("taxable_amount", "Taxable Amount", "CURRENCY", 170, "Extract taxable/net selling value exactly as stated; do not derive it.", ["taxable value", "net selling price", "taxable amount"]),
        _f("cgst_rate", "CGST Rate", "STRING", 180, "Extract CGST rate exactly as printed, including percent sign when present.", ["cgst rate", "cgst %"]),
        _f("cgst_amount", "CGST Amount", "CURRENCY", 190, "Extract CGST amount exactly as printed.", ["cgst", "central tax"]),
        _f("sgst_rate", "SGST Rate", "STRING", 200, "Extract SGST rate exactly as printed, including percent sign when present.", ["sgst rate", "sgst %"]),
        _f("sgst_amount", "SGST Amount", "CURRENCY", 210, "Extract SGST amount exactly as printed.", ["sgst", "state tax"]),
        _f("igst_rate", "IGST Rate", "STRING", 220, "Extract IGST rate exactly as printed, including percent sign when present.", ["igst rate", "igst %"]),
        _f("igst_amount", "IGST Amount", "CURRENCY", 230, "Extract IGST amount exactly as printed.", ["igst", "integrated tax"]),
        _f("cess_amount", "Cess Amount", "CURRENCY", 240, "Extract cess amount only when explicitly printed.", ["cess", "compensation cess"]),
        _f("tcs_amount", "TCS Amount", "CURRENCY", 250, "Extract TCS only when explicitly printed; return null for N/A.", ["tcs"]),
        _f("round_off_amount", "Round Off Amount", "CURRENCY", 260, "Extract the signed round-off exactly as printed; preserve negative values.", ["round off", "rounding"]),
        _f("grand_total_amount", "Grand Total Amount", "CURRENCY", 270, "Extract final invoice/grand total exactly as printed; never recompute it.", ["grand total", "invoice total", "total"]),
        _f("amount_in_words", "Amount in Words", "STRING", 280, "Extract amount-in-words text exactly as printed.", ["amount in words", "rupees"]),
        _f("narration", "Narration", "STRING", 290, "Extract narration/remarks exactly as printed.", ["narration", "remarks"]),
        _f("line_items", "Invoice Line Items", "JSON", 300, "Extract every visible invoice line item as JSON with raw description and only explicitly printed item code, HSN/SAC, quantity, rate, gross, discount, taxable, tax and net values.", ["particulars", "description of goods", "items", "line items"]),
    ]


def _vehicle_fields() -> list[F]:
    return [
        _f("vehicle_description_raw", "Vehicle Description Raw", "STRING", 310, "Extract the complete vehicle description exactly as printed.", ["description of goods", "particulars", "vehicle description"]),
        _f("sku_code", "SKU Code", "IDENTIFIER", 320, "Extract SKU/product/model code only when explicitly printed; never infer it.", ["sku", "product code", "model code"]),
        _f("model_name_raw", "Model Name Raw", "STRING", 330, "Extract model text exactly as printed; do not map it to a master.", ["model", "vehicle model"]),
        _f("variant_raw", "Variant Raw", "STRING", 340, "Extract variant/trim text exactly as printed; do not map it to a master.", ["variant", "trim"]),
        _f("vin_number", "VIN Number", "IDENTIFIER", 350, "Extract VIN exactly as printed; never reconstruct missing characters.", ["vin", "vin no"]),
        _f("chassis_number", "Chassis Number", "IDENTIFIER", 360, "Extract chassis number exactly as printed.", ["chassis no", "chassis number"]),
        _f("engine_number", "Engine Number", "IDENTIFIER", 370, "Extract engine number exactly as printed.", ["engine no", "engine number"]),
        _f("key_number", "Key Number", "IDENTIFIER", 380, "Extract key number only when explicitly printed.", ["key no", "key number"]),
        _f("vehicle_color", "Vehicle Color", "STRING", 390, "Extract vehicle colour exactly as printed.", ["color", "colour"]),
        _f("vehicle_registration_number", "Vehicle Registration Number", "IDENTIFIER", 400, "Extract registration number only when printed.", ["registration no", "regn no", "vehicle no"]),
        _f("vehicle_hsn_code", "Vehicle HSN Code", "IDENTIFIER", 410, "Extract vehicle HSN code exactly as printed.", ["hsn", "hsn code", "hsn/sac"]),
    ]


def _generic_link_fields() -> list[F]:
    return [
        _f("vehicle_description_raw", "Vehicle Description Raw", "STRING", 310, "Extract vehicle description when this invoice concerns a vehicle.", ["vehicle description", "description of goods"]),
        _f("sku_code", "SKU Code", "IDENTIFIER", 320, "Extract an explicit SKU/product code only when printed; never infer it.", ["sku", "product code"]),
        _f("vin_number", "VIN Number", "IDENTIFIER", 330, "Extract linked VIN only when printed.", ["vin", "vin no"]),
        _f("chassis_number", "Chassis Number", "IDENTIFIER", 340, "Extract linked chassis number only when printed.", ["chassis no"]),
        _f("engine_number", "Engine Number", "IDENTIFIER", 350, "Extract linked engine number only when printed.", ["engine no"]),
        _f("vehicle_registration_number", "Vehicle Registration Number", "IDENTIFIER", 360, "Extract linked vehicle registration only when printed.", ["registration no", "regn no", "vehicle no"]),
    ]


def _service_fields() -> list[F]:
    return [
        _f("plan_name", "Plan Name", "STRING", 310, "Extract plan/product/service name exactly as printed.", ["plan", "product", "service"]),
        _f("coverage_start_date", "Coverage Start Date", "DATE", 320, "Extract coverage/service start date only when printed.", ["valid from", "start date", "coverage from"]),
        _f("coverage_end_date", "Coverage End Date", "DATE", 330, "Extract coverage/service end date only when printed.", ["valid till", "end date", "coverage to"]),
        _f("tenure_months", "Tenure Months", "STRING", 340, "Extract printed tenure/duration without calculating it.", ["tenure", "duration", "months"]),
        _f("vin_number", "VIN Number", "IDENTIFIER", 350, "Extract linked VIN only when printed.", ["vin", "vin no"]),
        _f("vehicle_registration_number", "Vehicle Registration Number", "IDENTIFIER", 360, "Extract linked registration number only when printed.", ["registration no", "regn no"]),
    ]


def _fields_for(key: str) -> list[F]:
    fields = _common_fields()
    if key in {"wholesale_invoice", "customer_invoice_dms", "tax_invoice_tally"}:
        return fields + _vehicle_fields()
    if key in {"ew_invoice", "rsa_invoice"}:
        return fields + _service_fields()
    return fields + _generic_link_fields()


_PROFILE_NAMES = {
    "wholesale_invoice": "Generalized Wholesale Invoice Extraction v1",
    "customer_invoice_dms": "Generalized Customer Vehicle Invoice DMS Extraction v1",
    "tax_invoice_tally": "Generalized Vehicle Tax Invoice Tally Extraction v1",
    "accessory_invoice_dms": "Generalized Accessory Invoice DMS Extraction v1",
    "accessory_invoice_tally": "Generalized Accessory Invoice Tally Extraction v1",
    "ew_invoice": "Generalized Extended Warranty Invoice Extraction v1",
    "rsa_invoice": "Generalized RSA Invoice Extraction v1",
    _GENERIC_KEY: "Generalized Other Invoice Extraction v1",
}


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str, data_type: str) -> None:
    existing = conn.execute(
        sa.text(
            """
            SELECT data_type FROM docintel.canonical_fields
            WHERE owner_tenant_id IS NULL AND field_key=:field_key
            """
        ),
        {"field_key": field_key},
    ).scalar_one_or_none()
    if existing is not None:
        return
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.canonical_fields (
                canonical_field_id, owner_tenant_id, field_key, display_name,
                data_type, description, status, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), NULL, :field_key, :display_name,
                :data_type, NULL, 'ACTIVE', now(), now()
            )
            """
        ),
        {"field_key": field_key, "display_name": display_name, "data_type": data_type},
    )


def _publish_profile(conn: Any, document_type_key: str, fields: list[F]) -> None:
    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id FROM docintel.document_types
            WHERE owner_tenant_id IS NULL
              AND document_type_key=:key
              AND status='ACTIVE'
            """
        ),
        {"key": document_type_key},
    ).scalar_one()
    version_no = conn.execute(
        sa.text(
            """
            SELECT COALESCE(MAX(version_no), 0) + 1
            FROM docintel.extraction_profiles
            WHERE document_type_id=:document_type_id AND scope_tenant_id IS NULL
            """
        ),
        {"document_type_id": document_type_id},
    ).scalar_one()
    profile_id = conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profiles (
                profile_id, document_type_id, scope_tenant_id, version_no,
                profile_name, status, classification_hint,
                created_by_actor_id, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), :document_type_id, NULL, :version_no,
                :profile_name, 'DRAFT', :classification_hint,
                :actor_id, now(), now()
            ) RETURNING profile_id
            """
        ),
        {
            "document_type_id": document_type_id,
            "version_no": version_no,
            "profile_name": _PROFILE_NAMES[document_type_key],
            "classification_hint": document_type_key,
            "actor_id": _MIGRATION_ACTOR,
        },
    ).scalar_one()

    for (
        field_key,
        _display_name,
        _data_type,
        expected,
        score_included,
        score_weight,
        display_sequence,
        instruction,
        aliases,
    ) in fields:
        canonical_field_id = conn.execute(
            sa.text(
                """
                SELECT canonical_field_id FROM docintel.canonical_fields
                WHERE owner_tenant_id IS NULL AND field_key=:field_key
                """
            ),
            {"field_key": field_key},
        ).scalar_one()
        conn.execute(
            sa.text(
                """
                INSERT INTO docintel.extraction_profile_fields (
                    profile_field_id, profile_id, canonical_field_id,
                    enabled, expected, extraction_instruction, aliases,
                    score_included, score_weight, use_for_subject_matching,
                    subject_identifier_type, manual_correction_allowed,
                    display_sequence, created_at_utc, updated_at_utc
                ) VALUES (
                    gen_random_uuid(), :profile_id, :canonical_field_id,
                    true, :expected, :instruction, CAST(:aliases AS jsonb),
                    :score_included, :score_weight, false,
                    NULL, true, :display_sequence, now(), now()
                )
                """
            ),
            {
                "profile_id": profile_id,
                "canonical_field_id": canonical_field_id,
                "expected": expected,
                "instruction": instruction,
                "aliases": json.dumps(aliases),
                "score_included": score_included,
                "score_weight": score_weight,
                "display_sequence": display_sequence,
            },
        )

    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
              AND status='PUBLISHED'
            """
        ),
        {"document_type_id": document_type_id},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED', published_by_actor_id=:actor_id,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:profile_id AND status='DRAFT'
            """
        ),
        {"actor_id": _MIGRATION_ACTOR, "profile_id": profile_id},
    )


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.document_types (
                document_type_id, owner_tenant_id, document_type_key,
                display_name, description, category, status,
                created_at_utc, updated_at_utc
            )
            SELECT gen_random_uuid(), NULL, :key, 'Other Invoice',
                   'Generic invoice fallback when no configured invoice subtype is reliable',
                   'PRINTABLE', 'ACTIVE', now(), now()
            WHERE NOT EXISTS (
                SELECT 1 FROM docintel.document_types
                WHERE owner_tenant_id IS NULL AND document_type_key=:key
            )
            """
        ),
        {"key": _GENERIC_KEY},
    )

    # Existing tenants gain the generic fallback. Future tenants automatically
    # receive it through normal global document-type provisioning.
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.tenant_document_types (
                tenant_id, document_type_id, physical_form_type,
                requires_processing, is_active, display_order,
                created_at_utc, updated_at_utc
            )
            SELECT ts.tenant_id, dt.document_type_id, 'PRINTABLE',
                   true, true, 190, now(), now()
            FROM docintel.tenant_settings ts
            JOIN docintel.document_types dt
              ON dt.owner_tenant_id IS NULL AND dt.document_type_key=:key
            ON CONFLICT (tenant_id, document_type_id) DO UPDATE
            SET requires_processing=true, is_active=true, updated_at_utc=now()
            """
        ),
        {"key": _GENERIC_KEY},
    )

    # 0016 introduced these invoice types as evidence-only. Activate processing
    # now that a published extraction profile exists; no requirement/scoring state changes.
    conn.execute(
        sa.text(
            """
            UPDATE docintel.tenant_document_types tdt
            SET requires_processing=true, updated_at_utc=now()
            FROM docintel.document_types dt
            WHERE tdt.document_type_id=dt.document_type_id
              AND dt.owner_tenant_id IS NULL
              AND dt.document_type_key = ANY(:keys)
            """
        ),
        {"keys": list(_SPECIFIC_KEYS)},
    )

    seen: set[str] = set()
    for key in _ALL_KEYS:
        fields = _fields_for(key)
        for field_key, display_name, data_type, *_rest in fields:
            if field_key in seen:
                continue
            seen.add(field_key)
            _ensure_canonical_field(conn, field_key, display_name, data_type)
        _publish_profile(conn, key, fields)


def downgrade() -> None:
    conn = op.get_bind()

    for key in _ALL_KEYS:
        document_type_id = conn.execute(
            sa.text(
                """
                SELECT document_type_id FROM docintel.document_types
                WHERE owner_tenant_id IS NULL AND document_type_key=:key
                """
            ),
            {"key": key},
        ).scalar_one_or_none()
        if document_type_id is None:
            continue
        conn.execute(
            sa.text(
                """
                UPDATE docintel.extraction_profiles
                SET status='RETIRED', updated_at_utc=now()
                WHERE document_type_id=:document_type_id
                  AND scope_tenant_id IS NULL
                  AND created_by_actor_id=:actor_id
                  AND status IN ('DRAFT','PUBLISHED')
                """
            ),
            {"document_type_id": document_type_id, "actor_id": _MIGRATION_ACTOR},
        )
        previous_profile_id = conn.execute(
            sa.text(
                """
                SELECT profile_id FROM docintel.extraction_profiles
                WHERE document_type_id=:document_type_id
                  AND scope_tenant_id IS NULL
                  AND created_by_actor_id<>:actor_id
                  AND status='RETIRED'
                ORDER BY version_no DESC
                LIMIT 1
                """
            ),
            {"document_type_id": document_type_id, "actor_id": _MIGRATION_ACTOR},
        ).scalar_one_or_none()
        if previous_profile_id is not None:
            conn.execute(
                sa.text(
                    """
                    UPDATE docintel.extraction_profiles
                    SET status='PUBLISHED', updated_at_utc=now()
                    WHERE profile_id=:profile_id
                    """
                ),
                {"profile_id": previous_profile_id},
            )

    conn.execute(
        sa.text(
            """
            UPDATE docintel.tenant_document_types tdt
            SET requires_processing=false, updated_at_utc=now()
            FROM docintel.document_types dt
            WHERE tdt.document_type_id=dt.document_type_id
              AND dt.owner_tenant_id IS NULL
              AND dt.document_type_key = ANY(:keys)
            """
        ),
        {"keys": list(_SPECIFIC_KEYS)},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.tenant_document_types tdt
            SET requires_processing=false, is_active=false, updated_at_utc=now()
            FROM docintel.document_types dt
            WHERE tdt.document_type_id=dt.document_type_id
              AND dt.owner_tenant_id IS NULL
              AND dt.document_type_key=:key
            """
        ),
        {"key": _GENERIC_KEY},
    )
