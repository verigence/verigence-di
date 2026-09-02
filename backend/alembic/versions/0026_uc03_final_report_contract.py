"""Publish UC03 final-report DI contract Package 1.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-02

This migration is deliberately additive and evidence-first:
- every existing invoice document key remains stable, but published profiles are
  extended to one common commercial + vehicle evidence superset;
- Gate Pass gains only delivery date and printed vehicle-number evidence;
- Aadhaar gains explicit printed address components without geography inference;
- the already-reviewed GST Certificate Wave-1 profile is published;
- historical profiles and extracted facts are never deleted.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

_ACTOR = "migration.0026.uc03-final-report-contract-v1"
_WAVE1_PROFILE_NAME = "Schema V2 Wave 1 Draft"

F = tuple[str, str, str, int, str, list[str]]

_INVOICE_KEYS = (
    "wholesale_invoice",
    "customer_invoice_dms",
    "tax_invoice_tally",
    "accessory_invoice_dms",
    "accessory_invoice_tally",
    "ew_invoice",
    "rsa_invoice",
    "invoice_generic",
)

# These are deliberately supplied to every invoice profile. Existing children are
# skipped by canonical field id; only missing evidence fields are added.
_INVOICE_SUPERSET_ADDITIONS: list[F] = [
    (
        "invoice_heading_as_printed",
        "Invoice Heading As Printed",
        "STRING",
        420,
        "Extract the invoice heading/title exactly as printed, for example TAX INVOICE or Retail Invoice.",
        ["tax invoice", "retail invoice", "invoice", "bill"],
    ),
    (
        "buyer_gstin_status",
        "Buyer GSTIN Status",
        "STRING",
        430,
        "Return REGISTERED, UNREGISTERED, NOT_STATED or UNKNOWN only from visible buyer-GST evidence; never infer registration from a missing GSTIN.",
        ["buyer gst status", "customer gst status", "gstin unregistered", "unregistered"],
    ),
    (
        "vehicle_description_raw",
        "Vehicle Description Raw",
        "STRING",
        440,
        "Extract the complete vehicle description exactly as printed when present on any invoice.",
        ["vehicle description", "description of goods", "particulars"],
    ),
    (
        "sku_code",
        "SKU Code",
        "IDENTIFIER",
        450,
        "Extract explicit SKU/product/model code only when printed; never infer it.",
        ["sku", "product code", "model code"],
    ),
    (
        "model_name_raw",
        "Model Name Raw",
        "STRING",
        460,
        "Extract vehicle model text exactly as printed; do not map to a master.",
        ["model", "vehicle model"],
    ),
    (
        "variant_raw",
        "Variant Raw",
        "STRING",
        470,
        "Extract vehicle variant/trim text exactly as printed; do not map to a master.",
        ["variant", "trim"],
    ),
    (
        "vin_number",
        "VIN Number",
        "IDENTIFIER",
        480,
        "Extract VIN exactly as printed; never reconstruct missing characters.",
        ["vin", "vin no"],
    ),
    (
        "chassis_number",
        "Chassis Number",
        "IDENTIFIER",
        490,
        "Extract chassis number exactly as printed.",
        ["chassis no", "chassis number"],
    ),
    (
        "engine_number",
        "Engine Number",
        "IDENTIFIER",
        500,
        "Extract engine number exactly as printed.",
        ["engine no", "engine number"],
    ),
    (
        "key_number",
        "Key Number",
        "IDENTIFIER",
        510,
        "Extract vehicle key number only when explicitly printed.",
        ["key no", "key number"],
    ),
    (
        "vehicle_color",
        "Vehicle Color",
        "STRING",
        520,
        "Extract vehicle colour exactly as printed.",
        ["color", "colour"],
    ),
    (
        "vehicle_registration_number",
        "Vehicle Registration Number",
        "IDENTIFIER",
        530,
        "Extract vehicle registration number only when printed.",
        ["registration no", "regn no", "vehicle no"],
    ),
    (
        "vehicle_hsn_code",
        "Vehicle HSN Code",
        "IDENTIFIER",
        540,
        "Extract vehicle HSN code exactly as printed.",
        ["hsn", "hsn code", "hsn/sac"],
    ),
]

_AADHAAR_ADDITIONS: list[F] = [
    (
        "address_pincode",
        "Address Pincode",
        "IDENTIFIER",
        80,
        "Extract PIN code only when explicitly identifiable in the printed Aadhaar address; never infer or repair digits.",
        ["pin", "pincode", "postal code"],
    ),
    (
        "address_state",
        "Address State",
        "STRING",
        90,
        "Extract State/UT only when explicitly identifiable in the printed Aadhaar address; do not derive it from PIN code.",
        ["state", "state/ut"],
    ),
    (
        "address_district",
        "Address District",
        "STRING",
        100,
        "Extract district only when explicitly identifiable in the printed Aadhaar address; do not infer it from city, state, PIN code or outside geography knowledge.",
        ["district", "dist"],
    ),
]

_GATE_PASS_FIELDS: list[F] = [
    (
        "delivery_date",
        "Delivery Date",
        "DATE",
        10,
        "Extract the delivery/gate-pass date exactly as printed; normalize only when unambiguous.",
        ["delivery date", "gate pass date", "date"],
    ),
    (
        "car_number_as_printed",
        "Car Number As Printed",
        "STRING",
        20,
        "Extract the car/vehicle number exactly as printed without assuming what identifier type it is.",
        ["car no", "car number", "vehicle no", "vehicle number"],
    ),
    (
        "vehicle_registration_number",
        "Vehicle Registration Number",
        "IDENTIFIER",
        30,
        "Populate only when the document explicitly identifies a registration number or the printed value is unambiguously a registration number; otherwise leave null.",
        ["registration no", "registration number", "regn no"],
    ),
]


def _ensure_canonical_field(
    conn: Any,
    field_key: str,
    display_name: str,
    data_type: str,
) -> None:
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
        if existing != data_type:
            raise RuntimeError(
                f"Canonical type conflict for {field_key}: existing={existing}, requested={data_type}"
            )
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


def _add_profile_field(
    conn: Any,
    *,
    profile_id: Any,
    field: F,
) -> None:
    field_key, _display_name, _data_type, sequence, instruction, aliases = field
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
                display_sequence, created_at_utc, updated_at_utc,
                extraction_key, fact_role_override
            )
            SELECT gen_random_uuid(), :profile_id, :canonical_field_id,
                   true, false, :instruction, CAST(:aliases AS jsonb),
                   false, 0.0, false, NULL, true,
                   :sequence, now(), now(), :field_key, 'UNSPECIFIED'
            WHERE NOT EXISTS (
                SELECT 1 FROM docintel.extraction_profile_fields epf
                WHERE epf.profile_id=:profile_id
                  AND epf.canonical_field_id=:canonical_field_id
            )
            """
        ),
        {
            "profile_id": profile_id,
            "canonical_field_id": canonical_field_id,
            "instruction": instruction,
            "aliases": json.dumps(aliases),
            "sequence": sequence,
            "field_key": field_key,
        },
    )


def _clone_and_extend_published_profile(
    conn: Any,
    *,
    document_type_key: str,
    profile_name: str,
    additions: list[F],
) -> None:
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
    previous_profile_id = conn.execute(
        sa.text(
            """
            SELECT profile_id FROM docintel.extraction_profiles
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
              AND status='PUBLISHED'
            ORDER BY version_no DESC
            LIMIT 1
            """
        ),
        {"document_type_id": document_type_id},
    ).scalar_one()
    version_no = conn.execute(
        sa.text(
            """
            SELECT COALESCE(MAX(version_no), 0) + 1
            FROM docintel.extraction_profiles
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
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
                :actor, now(), now()
            ) RETURNING profile_id
            """
        ),
        {
            "document_type_id": document_type_id,
            "version_no": version_no,
            "profile_name": profile_name,
            "classification_hint": document_type_key,
            "actor": _ACTOR,
        },
    ).scalar_one()

    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profile_fields (
                profile_field_id, profile_id, canonical_field_id,
                enabled, expected, extraction_instruction, aliases,
                score_included, score_weight, use_for_subject_matching,
                subject_identifier_type, manual_correction_allowed,
                display_sequence, created_at_utc, updated_at_utc,
                extraction_key, fact_role_override
            )
            SELECT gen_random_uuid(), :profile_id, epf.canonical_field_id,
                   epf.enabled, epf.expected, epf.extraction_instruction, epf.aliases,
                   epf.score_included, epf.score_weight, epf.use_for_subject_matching,
                   epf.subject_identifier_type, epf.manual_correction_allowed,
                   epf.display_sequence, now(), now(),
                   COALESCE(epf.extraction_key, cf.field_key),
                   COALESCE(epf.fact_role_override, 'UNSPECIFIED')
            FROM docintel.extraction_profile_fields epf
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id=epf.canonical_field_id
            WHERE epf.profile_id=:previous_profile_id
            ORDER BY epf.display_sequence, epf.profile_field_id
            """
        ),
        {"profile_id": profile_id, "previous_profile_id": previous_profile_id},
    )

    for field in additions:
        _add_profile_field(conn, profile_id=profile_id, field=field)

    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE profile_id=:previous_profile_id AND status='PUBLISHED'
            """
        ),
        {"previous_profile_id": previous_profile_id},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED', published_by_actor_id=:actor,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:profile_id AND status='DRAFT'
            """
        ),
        {"profile_id": profile_id, "actor": _ACTOR},
    )


def _publish_gate_pass(conn: Any) -> None:
    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id FROM docintel.document_types
            WHERE owner_tenant_id IS NULL
              AND document_type_key='gate_pass'
              AND status='ACTIVE'
            """
        )
    ).scalar_one()
    version_no = conn.execute(
        sa.text(
            """
            SELECT COALESCE(MAX(version_no), 0) + 1
            FROM docintel.extraction_profiles
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
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
                'UC03 Gate Pass Extraction v1', 'DRAFT',
                'Automobile dealership Gate Pass used as Delivery evidence.',
                :actor, now(), now()
            ) RETURNING profile_id
            """
        ),
        {"document_type_id": document_type_id, "actor": _ACTOR},
    ).scalar_one()
    for field in _GATE_PASS_FIELDS:
        _add_profile_field(conn, profile_id=profile_id, field=field)
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED', published_by_actor_id=:actor,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:profile_id AND status='DRAFT'
            """
        ),
        {"profile_id": profile_id, "actor": _ACTOR},
    )


def _activate_for_existing_tenants(conn: Any, document_type_key: str) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.tenant_document_types (
                tenant_id, document_type_id, physical_form_type,
                requires_processing, is_active, display_order,
                created_at_utc, updated_at_utc
            )
            SELECT ts.tenant_id, dt.document_type_id, 'PRINTABLE',
                   true, true, 100, now(), now()
            FROM docintel.tenant_settings ts
            JOIN docintel.document_types dt
              ON dt.owner_tenant_id IS NULL AND dt.document_type_key=:key
            ON CONFLICT (tenant_id, document_type_id) DO UPDATE
            SET requires_processing=true, is_active=true, updated_at_utc=now()
            """
        ),
        {"key": document_type_key},
    )


def _publish_existing_wave1_gst_profile(conn: Any) -> None:
    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id FROM docintel.document_types
            WHERE owner_tenant_id IS NULL
              AND document_type_key='gst_certificate'
              AND status='ACTIVE'
            """
        )
    ).scalar_one()
    profile_id = conn.execute(
        sa.text(
            """
            SELECT profile_id FROM docintel.extraction_profiles
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
              AND profile_name=:profile_name
              AND status='DRAFT'
            ORDER BY version_no DESC
            LIMIT 1
            """
        ),
        {"document_type_id": document_type_id, "profile_name": _WAVE1_PROFILE_NAME},
    ).scalar_one()
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
            SET status='PUBLISHED', published_by_actor_id=:actor,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:profile_id AND status='DRAFT'
            """
        ),
        {"profile_id": profile_id, "actor": _ACTOR},
    )


def upgrade() -> None:
    conn = op.get_bind()

    for field in _INVOICE_SUPERSET_ADDITIONS + _AADHAAR_ADDITIONS + _GATE_PASS_FIELDS:
        _ensure_canonical_field(conn, field[0], field[1], field[2])

    for key in _INVOICE_KEYS:
        _clone_and_extend_published_profile(
            conn,
            document_type_key=key,
            profile_name="UC03 Consolidated Invoice Evidence v2",
            additions=_INVOICE_SUPERSET_ADDITIONS,
        )

    _clone_and_extend_published_profile(
        conn,
        document_type_key="aadhaar",
        profile_name="Aadhaar Address Components Extraction v1.2",
        additions=_AADHAAR_ADDITIONS,
    )

    _publish_gate_pass(conn)
    _activate_for_existing_tenants(conn, "gate_pass")

    _publish_existing_wave1_gst_profile(conn)
    _activate_for_existing_tenants(conn, "gst_certificate")


def _restore_previous_published_profile(conn: Any, document_type_key: str) -> None:
    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id FROM docintel.document_types
            WHERE owner_tenant_id IS NULL AND document_type_key=:key
            """
        ),
        {"key": document_type_key},
    ).scalar_one_or_none()
    if document_type_id is None:
        return
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
              AND created_by_actor_id=:actor
              AND status IN ('DRAFT','PUBLISHED')
            """
        ),
        {"document_type_id": document_type_id, "actor": _ACTOR},
    )
    previous_profile_id = conn.execute(
        sa.text(
            """
            SELECT profile_id FROM docintel.extraction_profiles
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
              AND created_by_actor_id<>:actor
              AND status='RETIRED'
            ORDER BY version_no DESC
            LIMIT 1
            """
        ),
        {"document_type_id": document_type_id, "actor": _ACTOR},
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


def downgrade() -> None:
    conn = op.get_bind()

    for key in (*_INVOICE_KEYS, "aadhaar", "gate_pass"):
        _restore_previous_published_profile(conn, key)

    # Restore the Wave-1 GST profile to its pre-0026 draft state.
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles ep
            SET status='DRAFT', published_by_actor_id=NULL,
                published_at_utc=NULL, updated_at_utc=now()
            FROM docintel.document_types dt
            WHERE ep.document_type_id=dt.document_type_id
              AND dt.owner_tenant_id IS NULL
              AND dt.document_type_key='gst_certificate'
              AND ep.scope_tenant_id IS NULL
              AND ep.profile_name=:profile_name
              AND ep.published_by_actor_id=:actor
            """
        ),
        {"profile_name": _WAVE1_PROFILE_NAME, "actor": _ACTOR},
    )

    for key in ("gate_pass", "gst_certificate"):
        conn.execute(
            sa.text(
                """
                UPDATE docintel.tenant_document_types tdt
                SET requires_processing=false, updated_at_utc=now()
                FROM docintel.document_types dt
                WHERE tdt.document_type_id=dt.document_type_id
                  AND dt.owner_tenant_id IS NULL
                  AND dt.document_type_key=:key
                """
            ),
            {"key": key},
        )
