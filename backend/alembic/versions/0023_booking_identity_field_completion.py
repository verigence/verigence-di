"""Publish completed Booking Form and identity extraction profiles.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-30

The processing worker is database-profile driven. Updating only the Python schema
registry would therefore not change runtime extraction. This migration publishes
new immutable global profile versions for booking_form, pan_card and aadhaar,
cloning every currently-published field and adding only the verified field gaps.

No value is inferred by this migration. The extraction instructions explicitly
forbid splitting combined charges, deriving commercial totals, or inventing
identity relationships. PAN and Aadhaar relationship fields use source-specific
canonical keys so two documents cannot be accidentally combined into one pair.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_MIGRATION_ACTOR = "migration.0023.booking-identity-field-completion"
F = tuple[Any, ...]

# field_key, display_name, data_type, expected, score_included, score_weight,
# display_sequence, extraction_instruction, aliases
_ADDITIONS: dict[str, tuple[str, list[F]]] = {
    "booking_form": (
        "Booking Form Complete Extraction v1.4",
        [
            ("registration_by", "Registration By", "STRING", False, False, 0.0, 240, "Extract the person, party, dealer, customer, or agency explicitly shown as responsible for registration. Return the printed/written text only; never infer responsibility.", ["registration by", "registered by", "rto by"]),
            ("registration_type", "Registration Type", "STRING", False, False, 0.0, 250, "Extract registration type/category only when explicitly printed or written. Do not infer it from customer or vehicle details.", ["registration type", "reg type", "registration category"]),
            ("insurance_by", "Insurance By", "STRING", False, False, 0.0, 260, "Extract the person, party, dealer, customer, insurer, or agency explicitly shown as arranging/providing insurance. Return the printed/written text only; never infer responsibility.", ["insurance by", "insured by", "insurance through"]),
            ("exchange_applicable", "Exchange Applicable", "BOOLEAN", False, False, 0.0, 270, "Return true or false only when exchange/trade-in is explicitly marked Yes/No, selected, ticked, or checked. Return null when there is no explicit selection; never infer it from an exchange amount.", ["exchange", "exchange applicable", "trade in", "trade-in"]),
            ("exchange_value", "Exchange Value", "CURRENCY", False, False, 0.0, 280, "Extract exchange/trade-in value only when explicitly printed or written. Never infer it from discounts or net price.", ["exchange value", "trade in value", "trade-in value", "old vehicle value"]),
            ("registration_charges", "Registration Charges", "CURRENCY", False, False, 0.0, 290, "Extract registration charges only when shown as a distinct amount. Do not derive them from a combined road-tax/registration amount.", ["registration charges", "registration amount", "reg charges"]),
            ("road_tax_amount", "Road Tax Amount", "CURRENCY", False, False, 0.0, 300, "Extract road tax only when shown as a distinct amount. Do not derive it from a combined road-tax/registration amount.", ["road tax", "road tax amount"]),
            ("tcs_amount", "TCS Amount", "CURRENCY", False, False, 0.0, 310, "Extract Tax Collected at Source (TCS) only when explicitly shown. Do not calculate it from vehicle value or a tax rate.", ["tcs", "tax collected at source"]),
            ("rsa_amount", "RSA Amount", "CURRENCY", False, False, 0.0, 320, "Extract Roadside Assistance (RSA) amount only when explicitly shown.", ["rsa", "roadside assistance"]),
            ("additional_warranty_amount", "Additional Warranty Amount", "CURRENCY", False, False, 0.0, 330, "Extract additional/extended warranty amount only when explicitly shown.", ["additional warranty", "extended warranty", "ew"]),
            ("discount_amount", "Discount Amount", "CURRENCY", False, False, 0.0, 340, "Extract discount amount only when explicitly shown. Do not calculate it from list and net prices.", ["discount", "discount amount"]),
            ("bonus_amount", "Bonus Amount", "CURRENCY", False, False, 0.0, 350, "Extract bonus amount only when explicitly shown.", ["bonus", "bonus amount"]),
            ("net_amount", "Net Amount", "CURRENCY", False, False, 0.0, 360, "Extract net amount/net deal only when explicitly shown. Never calculate it from total, discounts, bonus, exchange, or payments.", ["net amount", "net deal", "net price"]),
            ("expected_delivery_date", "Expected Delivery Date", "DATE", False, False, 0.0, 370, "Extract a complete expected delivery calendar date only when explicitly visible. Return null for vague periods such as '2 weeks', 'October', or 'next month'.", ["expected delivery date", "delivery date"]),
        ],
    ),
    "pan_card": (
        "PAN Card Identity Relations Extraction v1.1",
        [
            ("pan_father_name", "PAN Father Name", "STRING", False, False, 0.0, 40, "Extract the father's name only from a separately identifiable PAN father-name line or label. Do not return the PAN holder name here.", ["father name", "father's name"]),
            ("pan_relationship_type", "PAN Relationship Type", "STRING", False, False, 0.0, 50, "Extract only an explicitly visible W/O, S/O, or D/O marker associated with a related person's name on PAN evidence. Never infer S/O from an unlabeled father-name line.", ["w/o", "s/o", "d/o"]),
            ("pan_relationship_name", "PAN Relationship Name", "STRING", False, False, 0.0, 60, "Extract the name immediately associated with an explicitly visible PAN W/O, S/O, or D/O marker. Return null when no such explicit marker is present.", ["wife of", "son of", "daughter of"]),
        ],
    ),
    "aadhaar": (
        "Aadhaar Identity Relations Extraction v1.1",
        [
            ("aadhaar_relationship_type", "Aadhaar Relationship Type", "STRING", False, False, 0.0, 60, "Extract only an explicitly visible W/O, S/O, or D/O marker associated with a related person's name on Aadhaar evidence. Never infer a relationship from address text, surname, gender, or context.", ["w/o", "s/o", "d/o"]),
            ("aadhaar_relationship_name", "Aadhaar Relationship Name", "STRING", False, False, 0.0, 70, "Extract the name immediately associated with an explicitly visible Aadhaar W/O, S/O, or D/O marker. Return null when no such explicit marker is present.", ["wife of", "son of", "daughter of"]),
        ],
    ),
}


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str, data_type: str) -> None:
    existing = conn.execute(
        sa.text(
            """
            SELECT data_type
            FROM docintel.canonical_fields
            WHERE owner_tenant_id IS NULL AND field_key=:field_key
            """
        ),
        {"field_key": field_key},
    ).scalar_one_or_none()
    if existing is not None:
        # Canonical vocabulary is immutable. Reuse an existing definition rather
        # than silently changing its type in a configuration migration.
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


def _publish_extended_profile(
    conn: Any,
    document_type_key: str,
    profile_name: str,
    additions: list[F],
) -> None:
    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id
            FROM docintel.document_types
            WHERE owner_tenant_id IS NULL
              AND document_type_key=:document_type_key
              AND status='ACTIVE'
            """
        ),
        {"document_type_key": document_type_key},
    ).scalar_one()

    previous_profile_id = conn.execute(
        sa.text(
            """
            SELECT profile_id
            FROM docintel.extraction_profiles
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
                :actor_id, now(), now()
            )
            RETURNING profile_id
            """
        ),
        {
            "document_type_id": document_type_id,
            "version_no": version_no,
            "profile_name": profile_name,
            "classification_hint": document_type_key,
            "actor_id": _MIGRATION_ACTOR,
        },
    ).scalar_one()

    # Clone the complete published profile first. For historical V1 children,
    # extraction_key is NULL; Schema V2 runtime already falls back to the
    # canonical field key. New profile children make that key explicit.
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
            SELECT
                gen_random_uuid(), :profile_id, epf.canonical_field_id,
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
    ) in additions:
        canonical_field_id = conn.execute(
            sa.text(
                """
                SELECT canonical_field_id
                FROM docintel.canonical_fields
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
                SELECT
                    gen_random_uuid(), :profile_id, :canonical_field_id,
                    true, :expected, :instruction, CAST(:aliases AS jsonb),
                    :score_included, :score_weight, false,
                    NULL, true, :display_sequence, now(), now(),
                    :field_key, 'UNSPECIFIED'
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM docintel.extraction_profile_fields epf
                    WHERE epf.profile_id=:profile_id
                      AND epf.canonical_field_id=:canonical_field_id
                      AND epf.fact_role_override='UNSPECIFIED'
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

    if document_type_key == "booking_form":
        # Clarify legacy fields without removing them. These children are still
        # DRAFT here, so changing their instructions is allowed.
        conn.execute(
            sa.text(
                """
                UPDATE docintel.extraction_profile_fields epf
                SET extraction_instruction = CASE cf.field_key
                    WHEN 'road_tax_registration' THEN
                        'Extract only an explicitly combined road-tax/registration amount. Do not sum separately shown registration and road-tax amounts.'
                    WHEN 'expected_delivery' THEN
                        'Extract the raw expected-delivery value/timeframe exactly as stated. Do not convert a vague timeframe into a calendar date.'
                    WHEN 'other_charges' THEN
                        'Extract only an explicitly labelled other/miscellaneous charge. Do not absorb separately labelled TCS, RSA, warranty, registration, road tax, insurance, discount, or bonus amounts.'
                    ELSE epf.extraction_instruction
                END,
                updated_at_utc=now()
                FROM docintel.canonical_fields cf
                WHERE epf.profile_id=:profile_id
                  AND cf.canonical_field_id=epf.canonical_field_id
                  AND cf.field_key IN ('road_tax_registration','expected_delivery','other_charges')
                """
            ),
            {"profile_id": profile_id},
        )

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
            SET status='PUBLISHED',
                published_by_actor_id=:actor_id,
                published_at_utc=now(),
                updated_at_utc=now()
            WHERE profile_id=:profile_id AND status='DRAFT'
            """
        ),
        {"profile_id": profile_id, "actor_id": _MIGRATION_ACTOR},
    )


def upgrade() -> None:
    conn = op.get_bind()
    for _document_type_key, (_profile_name, additions) in _ADDITIONS.items():
        for field_key, display_name, data_type, *_rest in additions:
            _ensure_canonical_field(conn, field_key, display_name, data_type)

    for document_type_key, (profile_name, additions) in _ADDITIONS.items():
        _publish_extended_profile(conn, document_type_key, profile_name, additions)


def downgrade() -> None:
    # Published profile definitions are immutable. Follow the repository's
    # existing configuration-migration convention and retire the versions created
    # here rather than deleting historical profile children or extracted facts.
    op.get_bind().execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE created_by_actor_id=:actor_id AND status='PUBLISHED'
            """
        ),
        {"actor_id": _MIGRATION_ACTOR},
    )
