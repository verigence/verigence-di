"""Seed baseline global extraction profiles for core document types.

Configuration-only migration. No DI API contract or worker flow is changed.
The existing worker resolves global ACTIVE Document Types with global PUBLISHED
Extraction Profiles for every tenant unless a tenant-scoped profile overrides it.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-24
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_MIGRATION_ACTOR = "migration.0011.baseline-profiles"

# field_key, display_name, data_type, expected, score_included, score_weight,
# display_sequence, extraction_instruction, aliases
_PROFILE_DEFINITIONS: dict[str, tuple[str, list[tuple[Any, ...]]]] = {
    "booking_form": (
        "Booking Form Baseline Extraction",
        [
            ("dealer_name", "Dealer Name", "STRING", True, True, 1.0, 10, "Extract the dealership name.", ["dealer", "dealership"]),
            ("dealer_branch", "Dealer Branch", "STRING", False, False, 0.0, 20, "Extract the dealer branch or location if present.", ["branch", "location"]),
            ("booking_reference_number", "Booking Reference Number", "IDENTIFIER", True, True, 1.0, 30, "Extract the booking, order, enquiry, or reference number assigned to this booking.", ["booking no", "booking number", "order no", "reference no"]),
            ("booking_date", "Booking Date", "DATE", True, True, 1.0, 40, "Extract the booking date and return YYYY-MM-DD when the complete date is available.", ["date", "booking date"]),
            ("customer_name", "Customer Name", "STRING", True, True, 1.0, 50, "Extract the full customer name.", ["name", "customer", "customer name"]),
            ("customer_phone", "Customer Phone", "PHONE", True, True, 1.0, 60, "Extract the customer's contact or mobile number.", ["mobile", "mobile no", "phone", "contact no"]),
            ("customer_email", "Customer Email", "EMAIL", False, False, 0.0, 70, "Extract the customer email address if present.", ["email", "e-mail"]),
            ("customer_address", "Customer Address", "STRING", False, False, 0.0, 80, "Extract the customer postal or residential address if present.", ["address", "customer address"]),
            ("vehicle_model", "Vehicle Model", "STRING", True, True, 1.0, 90, "Extract the booked vehicle model.", ["model", "vehicle model"]),
            ("vehicle_variant", "Vehicle Variant", "STRING", True, True, 1.0, 100, "Extract the booked vehicle variant or trim.", ["variant", "trim"]),
            ("vehicle_color", "Vehicle Color", "STRING", True, True, 1.0, 110, "Extract the booked or preferred vehicle colour.", ["color", "colour"]),
            ("sales_person", "Sales Person", "STRING", False, False, 0.0, 120, "Extract the sales executive or sales person name if present.", ["sales executive", "sales consultant", "sales person"]),
            ("ex_showroom_price", "Ex-showroom Price", "CURRENCY", False, False, 0.0, 130, "Extract the ex-showroom price as a numeric amount without currency symbols or separators.", ["ex showroom", "ex-showroom", "ex showroom price"]),
            ("insurance_amount", "Insurance Amount", "CURRENCY", False, False, 0.0, 140, "Extract the insurance charge as a numeric amount.", ["insurance", "insurance amount"]),
            ("road_tax_registration", "Road Tax and Registration", "CURRENCY", False, False, 0.0, 150, "Extract road tax and registration charges as a numeric amount.", ["road tax", "registration", "rto"]),
            ("accessories_cost", "Accessories Cost", "CURRENCY", False, False, 0.0, 160, "Extract accessories charges as a numeric amount.", ["accessories", "accessory cost"]),
            ("other_charges", "Other Charges", "CURRENCY", False, False, 0.0, 170, "Extract other charges as a numeric amount if explicitly stated.", ["other charges", "misc charges"]),
            ("total_price", "Total Price", "CURRENCY", True, True, 1.0, 180, "Extract the grand total or on-road price as a numeric amount without currency symbols or separators.", ["total", "grand total", "on road price", "on-road price"]),
            ("booking_amount_paid", "Booking Amount Paid", "CURRENCY", True, True, 1.0, 190, "Extract the booking advance or booking amount paid as a numeric amount.", ["booking amount", "advance", "amount paid"]),
            ("balance_amount", "Balance Amount", "CURRENCY", False, False, 0.0, 200, "Extract the remaining or balance amount due as a numeric amount.", ["balance", "balance amount", "amount due"]),
            ("mode_of_payment", "Mode of Payment", "STRING", False, False, 0.0, 210, "Extract the payment mode used for the booking amount.", ["payment mode", "mode of payment"]),
            ("payment_reference_no", "Payment Reference Number", "IDENTIFIER", False, False, 0.0, 220, "Extract the cheque, DD, NEFT, RTGS, UTR, or other payment reference number if present.", ["payment reference", "utr", "transaction id", "cheque no"]),
            ("expected_delivery", "Expected Delivery", "STRING", False, False, 0.0, 230, "Extract the expected delivery date or delivery timeframe if present.", ["expected delivery", "delivery date"]),
        ],
    ),
    "pan_card": (
        "PAN Card Baseline Extraction",
        [
            ("pan_number", "PAN Number", "IDENTIFIER", True, True, 1.0, 10, "Extract the 10-character Permanent Account Number: five letters, four digits, one letter.", ["permanent account number", "pan"]),
            ("pan_name", "PAN Holder Name", "STRING", True, True, 1.0, 20, "Extract the PAN card holder's name. Do not return the father's name.", ["name", "card holder name"]),
            ("date_of_birth", "Date of Birth", "DATE", True, True, 1.0, 30, "Extract date of birth and return YYYY-MM-DD when the complete date is visible.", ["dob", "date of birth"]),
        ],
    ),
    "aadhaar": (
        "Aadhaar Card Baseline Extraction",
        [
            ("aadhaar_number", "Aadhaar Number", "IDENTIFIER", True, True, 1.0, 10, "Extract the Aadhaar number exactly as visible. Preserve masking if masked; never infer hidden digits.", ["aadhaar no", "aadhaar number", "uid"]),
            ("aadhaar_name", "Aadhaar Holder Name", "STRING", True, True, 1.0, 20, "Extract the Aadhaar holder's full name.", ["name", "holder name"]),
            ("date_of_birth", "Date of Birth", "DATE", False, False, 0.0, 30, "Extract the complete date of birth if printed. If only year of birth is printed, do not invent month or day.", ["dob", "date of birth", "year of birth", "yob"]),
            ("gender", "Gender", "STRING", False, False, 0.0, 40, "Extract gender exactly as printed if present.", ["gender", "male", "female"]),
            ("aadhaar_address", "Aadhaar Address", "STRING", False, False, 0.0, 50, "Extract the postal address from the Aadhaar document if present.", ["address"]),
        ],
    ),
}


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str, data_type: str) -> None:
    conn.execute(
        sa.text("""
            INSERT INTO docintel.canonical_fields (
                canonical_field_id, owner_tenant_id, field_key, display_name,
                data_type, description, status, created_at_utc, updated_at_utc
            )
            SELECT gen_random_uuid(), NULL, :field_key, :display_name,
                   :data_type, NULL, 'ACTIVE', now(), now()
            WHERE NOT EXISTS (
                SELECT 1 FROM docintel.canonical_fields
                WHERE owner_tenant_id IS NULL AND field_key=:field_key
            )
        """),
        {"field_key": field_key, "display_name": display_name, "data_type": data_type},
    )


def _ensure_profile(
    conn: Any,
    document_type_key: str,
    profile_name: str,
    fields: list[tuple[Any, ...]],
) -> None:
    dt_id = conn.execute(
        sa.text("""
            SELECT document_type_id
            FROM docintel.document_types
            WHERE owner_tenant_id IS NULL
              AND document_type_key=:key
              AND status='ACTIVE'
        """),
        {"key": document_type_key},
    ).scalar_one_or_none()
    if dt_id is None:
        raise RuntimeError(f"Missing ACTIVE global Document Type: {document_type_key}")

    published_id = conn.execute(
        sa.text("""
            SELECT profile_id
            FROM docintel.extraction_profiles
            WHERE document_type_id=:dt_id
              AND scope_tenant_id IS NULL
              AND status='PUBLISHED'
        """),
        {"dt_id": dt_id},
    ).scalar_one_or_none()
    if published_id is not None:
        return

    version_no = conn.execute(
        sa.text("""
            SELECT COALESCE(MAX(version_no),0)+1
            FROM docintel.extraction_profiles
            WHERE document_type_id=:dt_id AND scope_tenant_id IS NULL
        """),
        {"dt_id": dt_id},
    ).scalar_one()

    profile_id = conn.execute(
        sa.text("""
            INSERT INTO docintel.extraction_profiles (
                profile_id, document_type_id, scope_tenant_id, version_no,
                profile_name, status, classification_hint,
                created_by_actor_id, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), :dt_id, NULL, :version_no,
                :profile_name, 'DRAFT', :classification_hint,
                :actor_id, now(), now()
            )
            RETURNING profile_id
        """),
        {
            "dt_id": dt_id,
            "version_no": version_no,
            "profile_name": profile_name,
            "classification_hint": document_type_key,
            "actor_id": _MIGRATION_ACTOR,
        },
    ).scalar_one()

    for (
        field_key, _display_name, _data_type, expected, score_included,
        score_weight, display_sequence, instruction, aliases,
    ) in fields:
        canonical_field_id = conn.execute(
            sa.text("""
                SELECT canonical_field_id
                FROM docintel.canonical_fields
                WHERE owner_tenant_id IS NULL AND field_key=:field_key
            """),
            {"field_key": field_key},
        ).scalar_one()
        conn.execute(
            sa.text("""
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
            """),
            {
                "profile_id": profile_id,
                "canonical_field_id": canonical_field_id,
                "expected": expected,
                "instruction": instruction,
                "aliases": __import__("json").dumps(aliases),
                "score_included": score_included,
                "score_weight": score_weight,
                "display_sequence": display_sequence,
            },
        )

    conn.execute(
        sa.text("""
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED',
                published_by_actor_id=:actor_id,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:profile_id AND status='DRAFT'
        """),
        {"actor_id": _MIGRATION_ACTOR, "profile_id": profile_id},
    )


def upgrade() -> None:
    conn = op.get_bind()
    seen: set[str] = set()
    for _document_type_key, (_profile_name, fields) in _PROFILE_DEFINITIONS.items():
        for field_key, display_name, data_type, *_rest in fields:
            if field_key in seen:
                continue
            seen.add(field_key)
            _ensure_canonical_field(conn, field_key, display_name, data_type)

    for document_type_key, (profile_name, fields) in _PROFILE_DEFINITIONS.items():
        _ensure_profile(conn, document_type_key, profile_name, fields)


def downgrade() -> None:
    # Configuration is immutable after publication. Retire only profiles created
    # by this migration; never delete historical field definitions or evidence.
    op.get_bind().execute(
        sa.text("""
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE created_by_actor_id=:actor_id AND status='PUBLISHED'
        """),
        {"actor_id": _MIGRATION_ACTOR},
    )
