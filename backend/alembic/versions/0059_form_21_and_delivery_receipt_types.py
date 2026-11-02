"""Register the form_21 and delivery_receipt global document types.

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-02

Two kinds of page on the live tenant had no type of their own, so the V2
classifier filed them as the nearest wrong one:

- form_21 "Form 21 (Sale Certificate)": the RTO sale certificate ("FORM 21
  {See Rule 47(a) and (d)}"). It prints the invoice number, chassis, engine,
  model, buyer, dealer and date of sale, and no prices; it was read as
  customer_invoice_dms / wholesale_invoice. Audit Core's template "Form 21
  (Sale Certificate)" names form_21 as its DI type; a candidate key with no
  document_types row is dropped from the classifier's candidates.
- delivery_receipt "Vehicle Delivery Receipt": the customer's acknowledgement
  of taking delivery (model, chassis, engine, date, financier), no amount by
  nature; it was read as payment_receipt / dealer_receipt with no amount.

For each: the global row (ACTIVE, PRINTABLE) with its classifier definition in
description, a published v1 extraction profile matching
document_ai/schemas/{form_21,delivery_receipt}.py (date plausibility validator
wired on its DATE fields, as 0046/0048), and a tenant_document_types row for
every tenant (as 0036/0038/0048; tenant_session() provisions every ACTIVE
global type for a tenant on its next session anyway).

supporting_document's definition (0058) named both pages as its examples; it
now sends them to form_21 / delivery_receipt when those are candidates. The
0058 invoice and money-receipt definitions already say "not a Form 21" / "not a
New Vehicle Delivery Receipt" and are unchanged.

_DEFINITIONS and _PROFILES are snapshots (a migration must not import app
code); tests/test_document_type_definitions.py pins _DEFINITIONS (over 0058's)
to GLOBAL_DOCUMENT_TYPE_DEFINITIONS and tests/test_form_21_delivery_receipt_types.py
pins _PROFILES to the schemas. Nothing is re-classified or
re-extracted here. Forward-only, like 0055/0058.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

_ACTOR = "migration.0059.form-21-delivery-receipt-types"
_DATE_VALIDATOR_RULE_KEY = "date_plausible_range"

# key, display name, category (tenant physical form)
_NEW_DOCUMENT_TYPES: tuple[tuple[str, str, str], ...] = (
    ("form_21", "Form 21 (Sale Certificate)", "PRINTABLE"),
    ("delivery_receipt", "Vehicle Delivery Receipt", "PRINTABLE"),
)
_TYPE_KEYS = tuple(key for key, _, _ in _NEW_DOCUMENT_TYPES)

# Written onto the global rows; supporting_document's replaces its 0058 text.
_DEFINITIONS: dict[str, str] = {
    'supporting_document': (
        'Any page that is none of the other candidates, e.g. an email or approval note printout '
        'or a covering letter. A Form 21 (Sale Certificate, "See Rule 47") is form_21 and a New '
        'Vehicle Delivery Receipt (vehicle handed over, no amount) is delivery_receipt when those '
        'are candidates; otherwise they are supporting_document.'
    ),
    'form_21': (
        'The RTO Form 21 Sale Certificate ("FORM 21, See Rule 47(a) and (d)", or titled only '
        "Sale(s) Certificate) a dealer issues to register the vehicle: delivery to the buyer on "
        "a date, the buyer's name and address, any financier (hypothecation), maker, model, "
        'chassis and engine numbers, colour, month/year of manufacture. It may print the '
        'invoice number but has no prices, tax or total.'
    ),
    'delivery_receipt': (
        "The customer's acknowledgement of taking delivery of the new vehicle, titled e.g. New "
        'Vehicle Delivery Receipt or Delivery Note: receipt or note number, delivery date, '
        'customer, model, chassis and engine numbers and any financier. It records the vehicle '
        "handed over and no amount: not a money receipt, not the dealer's delivery order (DO) "
        'cover sheet listing attached documents, not a gate pass.'
    ),
}

# sale_date is new; the rest exist (0014/0022/0036/0038/0046/0048/0055) and
# are listed so the existence check, not this comment, decides.
_CANONICAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("sale_date", "Sale Date", "DATE"),
    ("certificate_number", "Certificate Number", "IDENTIFIER"),
    ("invoice_number", "Invoice Number", "IDENTIFIER"),
    ("buyer_name", "Buyer Name", "STRING"),
    ("buyer_address", "Buyer Address", "STRING"),
    ("dealer_name", "Dealer Name", "STRING"),
    ("vin_number", "VIN Number", "IDENTIFIER"),
    ("engine_number", "Engine Number", "IDENTIFIER"),
    ("vehicle_make", "Vehicle Make", "STRING"),
    ("vehicle_model", "Vehicle Model", "STRING"),
    ("vehicle_color", "Vehicle Color", "STRING"),
    ("vehicle_manufacture_month_year", "Vehicle Manufacture Month Year", "STRING"),
    ("financed_by", "Financed By", "STRING"),
    ("receipt_number", "Receipt Number", "IDENTIFIER"),
    ("delivery_date", "Delivery Date", "DATE"),
    ("customer_name", "Customer Name", "STRING"),
)

# document_type_key -> (profile_name, fields)
# fields: field_key, expected, instruction, aliases, score_included, score_weight, display_sequence
_PROFILES: dict[str, tuple[str, list[tuple[str, bool, str, list[str], bool, float, int]]]] = {
    "form_21": (
        "Form 21 (Sale Certificate) Extraction v1",
        [
            ("certificate_number", False, "The certificate's own number, only when printed.", ["sale certificate no", "certificate no", "form 21 no"], False, 0.0, 10),
            ("invoice_number", False, "The invoice number the certificate refers to.", ["invoice no", "inv no", "bill no"], False, 0.0, 20),
            ("sale_date", False, "The date of sale / delivery the certificate certifies.", ["date of sale", "delivered on", "date of delivery", "sale date"], False, 0.0, 30),
            ("buyer_name", True, "The buyer the vehicle was delivered to.", ["name of the buyer", "buyer", "purchaser"], True, 1.0, 40),
            ("buyer_address", False, "The buyer's address.", ["address", "permanent address"], False, 0.0, 50),
            ("dealer_name", False, "The dealer issuing the certificate.", ["dealer", "manufacturer/dealer"], False, 0.0, 60),
            ("vin_number", True, "The chassis number / VIN.", ["chassis no", "chassis number", "vin"], True, 1.0, 70),
            ("engine_number", False, "The engine / motor number.", ["engine no", "engine number", "motor no"], False, 0.0, 80),
            ("vehicle_make", False, "The maker's name.", ["maker's name", "make", "manufacturer"], False, 0.0, 90),
            ("vehicle_model", False, "The model / brand name.", ["model", "brand name"], False, 0.0, 100),
            ("vehicle_color", False, "The body colour.", ["colour", "color", "colour of body"], False, 0.0, 110),
            ("vehicle_manufacture_month_year", False, "The month and year of manufacture.", ["month and year of manufacture", "year of manufacture", "mfg"], False, 0.0, 120),
            ("financed_by", False, "The hire-purchase / lease / hypothecation party, when one is named.", ["hypothecation", "hire purchase", "lease", "agreement with", "hpa", "financier"], False, 0.0, 130),
        ],
    ),
    "delivery_receipt": (
        "Vehicle Delivery Receipt Extraction v1",
        [
            ("receipt_number", False, "The delivery receipt / note's own number.", ["delivery receipt no", "delivery note no", "receipt no", "dn no"], False, 0.0, 10),
            ("delivery_date", False, "The date of delivery.", ["delivery date", "date of delivery", "date"], False, 0.0, 20),
            ("customer_name", True, "The customer taking delivery.", ["customer", "customer name", "received by", "name"], True, 1.0, 30),
            ("vehicle_model", False, "The vehicle model.", ["model", "vehicle"], False, 0.0, 40),
            ("vin_number", True, "The chassis number / VIN.", ["chassis no", "chassis number", "vin"], True, 1.0, 50),
            ("engine_number", False, "The engine number.", ["engine no", "engine number"], False, 0.0, 60),
            ("financed_by", False, "The financier / hypothecation, when one is named.", ["financier", "financed by", "hypothecation", "hpa"], False, 0.0, 70),
        ],
    ),
}


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str, data_type: str) -> None:
    conn.execute(
        sa.text(
            """
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
            """
        ),
        {"field_key": field_key, "display_name": display_name, "data_type": data_type},
    )


def _document_type_id(conn: Any, key: str) -> Any:
    return conn.execute(
        sa.text(
            "SELECT document_type_id FROM docintel.document_types "
            "WHERE owner_tenant_id IS NULL AND document_type_key=:key AND status='ACTIVE'"
        ),
        {"key": key},
    ).scalar_one()


def _has_published(conn: Any, document_type_id: Any) -> bool:
    return conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM docintel.extraction_profiles "
            "WHERE document_type_id=:dtid AND scope_tenant_id IS NULL AND status='PUBLISHED')"
        ),
        {"dtid": document_type_id},
    ).scalar_one()


def _add_field(conn: Any, profile_id: Any, field_key: str, *, expected: bool, instruction: str,
               aliases: list[str], score_included: bool, score_weight: float, display_sequence: int) -> None:
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
            "profile_id": profile_id, "canonical_field_id": canonical_field_id,
            "expected": expected, "instruction": instruction, "aliases": json.dumps(aliases),
            "score_included": score_included, "score_weight": score_weight,
            "display_sequence": display_sequence, "field_key": field_key,
        },
    )


def _wire_date_plausibility_validator(conn: Any, profile_id: Any) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_validators (
                profile_field_validator_id, profile_field_id,
                sequence_no, rule_key, parameters, severity
            )
            SELECT gen_random_uuid(), epf.profile_field_id, 1, :rule_key, '{}'::jsonb, 'ERROR'
            FROM docintel.extraction_profile_fields epf
            JOIN docintel.canonical_fields cf ON cf.canonical_field_id = epf.canonical_field_id
            WHERE epf.profile_id = :profile_id AND cf.data_type = 'DATE' AND epf.enabled = true
            """
        ),
        {"profile_id": profile_id, "rule_key": _DATE_VALIDATOR_RULE_KEY},
    )


def _publish(conn: Any, profile_id: Any) -> None:
    scoreable = conn.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1 FROM docintel.extraction_profile_fields
                WHERE profile_id=:pid AND enabled=true AND expected=true
                  AND score_included=true AND score_weight > 0
            )
            """
        ),
        {"pid": profile_id},
    ).scalar_one()
    if not scoreable:
        raise RuntimeError(f"Profile {profile_id} has no scoreable field; refusing to publish")
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


def enable_for_every_tenant(conn: Any) -> None:
    """Every tenant gets both types with processing on (as 0048 step 3); a
    tenant's existing row, e.g. one an admin switched off, is left alone."""
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.tenant_document_types (
                tenant_id, document_type_id, physical_form_type,
                requires_processing, is_active, display_order,
                created_at_utc, updated_at_utc
            )
            SELECT ts.tenant_id, dt.document_type_id, dt.category, true, true, 100, now(), now()
            FROM docintel.tenant_settings ts
            JOIN docintel.document_types dt
              ON dt.owner_tenant_id IS NULL AND dt.status='ACTIVE'
             AND dt.document_type_key = ANY(:keys)
            ON CONFLICT (tenant_id, document_type_id) DO NOTHING
            """
        ),
        {"keys": list(_TYPE_KEYS)},
    )


def upgrade() -> None:
    conn = op.get_bind()

    # 1. The global rows, each with its definition (mirrors 0038 step 1).
    for key, display_name, category in _NEW_DOCUMENT_TYPES:
        conn.execute(
            sa.text(
                """
                INSERT INTO docintel.document_types (
                    document_type_id, owner_tenant_id, document_type_key,
                    display_name, description, category, status,
                    created_at_utc, updated_at_utc
                )
                SELECT gen_random_uuid(), NULL, :key, :display_name, :description,
                       :category, 'ACTIVE', now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM docintel.document_types
                    WHERE owner_tenant_id IS NULL AND document_type_key = :key
                )
                """
            ),
            {"key": key, "display_name": display_name, "description": _DEFINITIONS[key],
             "category": category},
        )

    # 2. Definitions onto the global rows (as 0058): the two new ones and
    #    supporting_document's rewrite. Tenant-owned rows are never touched.
    for key, definition in _DEFINITIONS.items():
        conn.execute(
            sa.text(
                "UPDATE docintel.document_types SET description=:d, updated_at_utc=now() "
                "WHERE owner_tenant_id IS NULL AND document_type_key=:k "
                "AND description IS DISTINCT FROM :d"
            ),
            {"k": key, "d": definition},
        )

    # 3. A fresh published profile per type (mirrors 0048 step 2).
    for field_key, display_name, data_type in _CANONICAL_FIELDS:
        _ensure_canonical_field(conn, field_key, display_name, data_type)
    for document_type_key, (profile_name, fields) in _PROFILES.items():
        document_type_id = _document_type_id(conn, document_type_key)
        if _has_published(conn, document_type_id):
            continue
        profile_id = conn.execute(
            sa.text(
                """
                INSERT INTO docintel.extraction_profiles (
                    profile_id, document_type_id, scope_tenant_id, version_no,
                    profile_name, status, classification_hint,
                    created_by_actor_id, created_at_utc, updated_at_utc
                )
                SELECT gen_random_uuid(), :dtid, NULL,
                       COALESCE((SELECT MAX(version_no) FROM docintel.extraction_profiles
                                 WHERE document_type_id=:dtid AND scope_tenant_id IS NULL), 0) + 1,
                       :profile_name, 'DRAFT', :hint, :actor_id, now(), now()
                RETURNING profile_id
                """
            ),
            {"dtid": document_type_id, "profile_name": profile_name, "hint": document_type_key,
             "actor_id": _ACTOR},
        ).scalar_one()
        for field_key, expected, instruction, aliases, score_included, score_weight, seq in fields:
            _add_field(conn, profile_id, field_key, expected=expected, instruction=instruction,
                       aliases=aliases, score_included=score_included, score_weight=score_weight,
                       display_sequence=seq)
        _wire_date_plausibility_validator(conn, profile_id)
        _publish(conn, profile_id)

    # 4. Every tenant has both types, with processing on.
    enable_for_every_tenant(conn)


def downgrade() -> None:
    # Published configuration is immutable; forward-only (as 0046/0048/0055/0058).
    pass
