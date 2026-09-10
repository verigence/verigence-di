"""Register scrappage_certificate_of_deposit as a new document type.

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-10

Real uploaded Vehicle Scrappage Certificates of Deposit (both the plain
"Certificate of Deposit" issued by an RVSF and the "Transfer Certificate of
Deposit" recording a resale of one) had nowhere to land -- Audit Core's own
Booking checkpoint rules have referenced this evidence since migration 0033
(``uc03_booking_confirmation_rules.py``'s cross-check of the Booking Form's
``scrappage_discount_amount``) but could never verify it, because no document
type or extraction profile existed. See
document_ai/schemas/scrappage_certificate.py for the full field rationale.

Brand new document type (mirrors 0036's step 1 for credit_note/
gst_declaration): registered, tenant_document_types enabled with
requires_processing=true directly (no prior "registered but disabled"
period), and a fresh published profile (no prior profile to clone from).
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

_ACTOR = "migration.0038.scrappage-certificate-of-deposit"
_DOCUMENT_TYPE = "scrappage_certificate_of_deposit"
_DISPLAY_NAME = "Scrappage Certificate of Deposit"

_NEW_CANONICAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("certificate_variant", "Certificate Variant", "STRING"),
    ("certificate_number", "Certificate Number", "IDENTIFIER"),
    ("old_vehicle_registration_number", "Old Vehicle Registration Number", "IDENTIFIER"),
    ("old_vehicle_make", "Old Vehicle Make", "STRING"),
    ("old_vehicle_model", "Old Vehicle Model", "STRING"),
    ("old_vehicle_category", "Old Vehicle Category", "STRING"),
    ("old_vehicle_type", "Old Vehicle Type", "STRING"),
    ("old_vehicle_fuel_type", "Old Vehicle Fuel Type", "STRING"),
    ("old_vehicle_cubic_capacity", "Old Vehicle Cubic Capacity", "NUMBER"),
    ("old_vehicle_seating_capacity", "Old Vehicle Seating Capacity", "NUMBER"),
    ("old_vehicle_year_of_manufacturing", "Old Vehicle Year of Manufacturing", "STRING"),
    ("old_vehicle_unladen_weight_kg", "Old Vehicle Unladen Weight (kg)", "NUMBER"),
    ("old_vehicle_number_of_cylinders", "Old Vehicle Number of Cylinders", "NUMBER"),
    ("old_vehicle_gross_vehicle_weight_kg", "Old Vehicle Gross Vehicle Weight (kg)", "NUMBER"),
    ("old_vehicle_wheelbase_mm", "Old Vehicle Wheelbase (mm)", "NUMBER"),
    ("original_owner_name", "Original Owner Name", "STRING"),
    ("current_holder_name", "Current Holder Name", "STRING"),
    ("current_holder_mobile", "Current Holder Mobile", "STRING"),
    ("current_holder_pan", "Current Holder PAN", "IDENTIFIER"),
    ("trade_date", "Trade Date", "DATE"),
    ("trade_number", "Trade Number", "IDENTIFIER"),
    ("certificate_issue_date", "Certificate Issue Date", "DATE"),
    ("certificate_valid_until_date", "Certificate Valid Until Date", "DATE"),
    ("scrapping_facility_name", "Scrapping Facility Name", "STRING"),
    ("rvsf_registration_number", "RVSF Registration Number", "IDENTIFIER"),
    ("state_of_scrapping", "State of Scrapping", "STRING"),
)

# field_key, expected, instruction, aliases, score_included, score_weight, display_sequence
_FIELDS: tuple[tuple[str, bool, str, list[str], bool, float, int], ...] = (
    ("certificate_variant", True, "ORIGINAL for a plain Certificate of Deposit, TRANSFERRED for a Transfer Certificate of Deposit.", ["certificate type"], True, 1.0, 10),
    ("certificate_number", True, "Extract the Certificate/CD number exactly as printed.", ["certificate no", "cod no"], True, 1.0, 20),
    ("old_vehicle_registration_number", True, "Extract the OLD (scrapped) vehicle's registration number.", ["registration no", "vehicle registration no"], True, 1.0, 30),
    ("old_vehicle_make", False, "Extract the old vehicle's Make/Maker exactly as printed.", ["make", "maker"], False, 0.0, 40),
    ("old_vehicle_model", False, "Extract the old vehicle's Model exactly as printed.", ["model"], False, 0.0, 50),
    ("old_vehicle_category", False, "Extract the old vehicle's Category/Class exactly as printed.", ["category", "class"], False, 0.0, 60),
    ("old_vehicle_type", False, "Extract the old vehicle's Vehicle Type exactly as printed.", ["vehicle type"], False, 0.0, 70),
    ("old_vehicle_fuel_type", False, "Extract the old vehicle's Fuel Type exactly as printed.", ["fuel type"], False, 0.0, 80),
    ("old_vehicle_cubic_capacity", False, "Extract the old vehicle's Cubic Capacity exactly as printed.", ["cubic capacity", "cc"], False, 0.0, 90),
    ("old_vehicle_seating_capacity", False, "Extract the old vehicle's Seating Capacity exactly as printed.", ["seating capacity"], False, 0.0, 100),
    ("old_vehicle_year_of_manufacturing", False, "Extract the old vehicle's Year of Manufacturing exactly as printed.", ["year of manufacturing", "manufacturing year"], False, 0.0, 110),
    ("old_vehicle_unladen_weight_kg", False, "Extract the old vehicle's Unladen Weight in kg exactly as printed.", ["unladen weight"], False, 0.0, 120),
    ("old_vehicle_number_of_cylinders", False, "Extract the old vehicle's Number of Cylinders exactly as printed.", ["number of cylinders", "cylinders"], False, 0.0, 130),
    ("old_vehicle_gross_vehicle_weight_kg", False, "Extract the old vehicle's Registered Gross Vehicle Weight in kg exactly as printed.", ["gross vehicle weight", "gvw"], False, 0.0, 140),
    ("old_vehicle_wheelbase_mm", False, "Extract the old vehicle's Wheelbase in mm exactly as printed.", ["wheelbase"], False, 0.0, 150),
    ("original_owner_name", False, "Extract who the certificate was originally issued to / traded from.", ["from", "original owner"], False, 0.0, 160),
    ("current_holder_name", True, "Extract who the certificate currently belongs to / is traded to.", ["transferred to", "in the name of"], True, 1.0, 170),
    ("current_holder_mobile", False, "Extract the current holder's mobile number exactly as printed.", ["mobile no"], False, 0.0, 180),
    ("current_holder_pan", False, "Extract the current holder's PAN exactly as printed.", ["pan no"], False, 0.0, 190),
    ("trade_date", False, "Extract the trade/transfer date, only present on a Transfer certificate.", ["trade date"], False, 0.0, 200),
    ("trade_number", False, "Extract the trade/transaction number, only present on a Transfer certificate.", ["trade no"], False, 0.0, 210),
    ("certificate_issue_date", False, "Extract the date the certificate itself was issued.", ["date of issuance", "issued on"], False, 0.0, 220),
    ("certificate_valid_until_date", False, "Extract the date the certificate is valid until.", ["valid until", "valid till"], False, 0.0, 230),
    ("scrapping_facility_name", False, "Extract the RVSF name, only present on an Original certificate.", ["scrapping facility"], False, 0.0, 240),
    ("rvsf_registration_number", False, "Extract the RVSF's own registration number, only present on an Original certificate.", ["rvsf no"], False, 0.0, 250),
    ("state_of_scrapping", False, "Extract the State/UT where the vehicle was scrapped, only present on an Original certificate.", ["state of scrapping", "state/ut of scrapping"], False, 0.0, 260),
)


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str, data_type: str) -> None:
    existing = conn.execute(
        sa.text(
            "SELECT 1 FROM docintel.canonical_fields WHERE owner_tenant_id IS NULL AND field_key=:field_key"
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


def _add_field(
    conn: Any,
    profile_id: Any,
    field_key: str,
    *,
    expected: bool,
    instruction: str,
    aliases: list[str],
    score_included: bool,
    score_weight: float,
    display_sequence: int,
) -> None:
    canonical_field_id = conn.execute(
        sa.text(
            "SELECT canonical_field_id FROM docintel.canonical_fields "
            "WHERE owner_tenant_id IS NULL AND field_key=:field_key"
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
            ) VALUES (
                gen_random_uuid(), :profile_id, :canonical_field_id,
                true, :expected, :instruction, CAST(:aliases AS jsonb),
                :score_included, :score_weight, false,
                NULL, true, :display_sequence, now(), now(), :field_key, 'UNSPECIFIED'
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
            "field_key": field_key,
        },
    )


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Register the document type (mirrors 0036's step 1) ───────────────
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.document_types (
                document_type_id, owner_tenant_id, document_type_key,
                display_name, description, category, status,
                created_at_utc, updated_at_utc
            )
            SELECT gen_random_uuid(), NULL, :key, :display_name, NULL,
                   'PRINTABLE', 'ACTIVE', now(), now()
            WHERE NOT EXISTS (
                SELECT 1 FROM docintel.document_types
                WHERE owner_tenant_id IS NULL AND document_type_key = :key
            )
            """
        ),
        {"key": _DOCUMENT_TYPE, "display_name": _DISPLAY_NAME},
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.tenant_document_types (
                tenant_id, document_type_id, physical_form_type,
                requires_processing, is_active, display_order,
                created_at_utc, updated_at_utc
            )
            SELECT ts.tenant_id, dt.document_type_id, dt.category,
                   true, true, 100, now(), now()
            FROM docintel.tenant_settings ts
            JOIN docintel.document_types dt
              ON dt.owner_tenant_id IS NULL AND dt.status='ACTIVE'
             AND dt.document_type_key = :key
            ON CONFLICT (tenant_id, document_type_id) DO NOTHING
            """
        ),
        {"key": _DOCUMENT_TYPE},
    )

    # ── 2. Canonical fields ──────────────────────────────────────────────────
    for field_key, display_name, data_type in _NEW_CANONICAL_FIELDS:
        _ensure_canonical_field(conn, field_key, display_name, data_type)

    # ── 3. Fresh profile, brand new type ────────────────────────────────────
    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id FROM docintel.document_types
            WHERE owner_tenant_id IS NULL AND document_type_key=:key AND status='ACTIVE'
            """
        ),
        {"key": _DOCUMENT_TYPE},
    ).scalar_one()
    profile_id = conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profiles (
                profile_id, document_type_id, scope_tenant_id, version_no,
                profile_name, status, classification_hint,
                created_by_actor_id, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), :dtid, NULL, 1,
                'Scrappage Certificate of Deposit Extraction v1', 'DRAFT',
                'scrappage_certificate_of_deposit', :actor_id, now(), now()
            ) RETURNING profile_id
            """
        ),
        {"dtid": document_type_id, "actor_id": _ACTOR},
    ).scalar_one()

    for field_key, expected, instruction, aliases, score_included, score_weight, seq in _FIELDS:
        _add_field(
            conn, profile_id, field_key,
            expected=expected, instruction=instruction, aliases=aliases,
            score_included=score_included, score_weight=score_weight, display_sequence=seq,
        )

    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED', published_by_actor_id=:actor_id,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:pid AND status='DRAFT'
            """
        ),
        {"actor_id": _ACTOR, "pid": profile_id},
    )


def downgrade() -> None:
    # Published configuration is immutable; forward-only (same as every other
    # profile-publishing migration in this repo).
    pass
