"""Publish detailed Booking Form commercial component extraction.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-31

The runtime worker is database-profile driven, so the Python schema change alone is
not sufficient. This migration publishes a new immutable Booking Form profile that
preserves the existing fields and adds separately visible discount, accessory and
other commercial components. No component is inferred from a lump-sum value.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

_ACTOR = "migration.0025.booking-commercial-components"

# field_key, display_name, display_sequence, instruction, aliases
_ADDITIONS: list[tuple[str, str, int, str, list[str]]] = [
    ("extended_warranty_amount", "Extended Warranty (EW) Amount", 380, "Extract Extended Warranty/EW amount only when explicitly shown as a separate monetary charge. Never derive it from a package or total.", ["extended warranty", "ew", "ew amount", "extended warranty amount"]),
    ("essential_kit_amount", "Essential Kit Amount", 390, "Extract Essential Kit/accessory kit amount only when explicitly shown as a separate monetary line. Never split it from a total accessories amount.", ["essential kit", "essential accessory kit", "accessory kit"]),
    ("genuine_accessories_amount", "Genuine Accessories Amount", 400, "Extract genuine/OEM accessories amount only when explicitly shown as a separate monetary line. Never split it from a total accessories amount.", ["genuine accessories", "oem accessories", "genuine accessory"]),
    ("non_genuine_accessories_amount", "Non-Genuine Accessories Amount", 410, "Extract non-genuine/non-OEM accessories amount only when explicitly shown as a separate monetary line. Never split it from a total accessories amount.", ["non genuine accessories", "non-genuine accessories", "non oem accessories", "local accessories"]),
    ("fastag_amount", "FASTag Amount", 420, "Extract FASTag/Fast Tag charge only when explicitly shown. Do not include it in other charges when separately labelled.", ["fastag", "fast tag", "fastag charges", "fastag amount"]),
    ("green_tax_amount", "Green Tax Amount", 430, "Extract Green Tax/Green Cess amount only when explicitly shown. Do not calculate it from vehicle price or tax rates.", ["green tax", "green cess", "green tax amount"]),
    ("service_package_amount", "Service Package Amount", 440, "Extract Service Package/Service Plan/Maintenance Package amount only when explicitly shown as a monetary line.", ["service package", "service plan", "maintenance package", "service pack"]),
    ("sales_discount_amount", "Sales Discount Amount", 450, "Extract Sales Discount only when explicitly labelled and a monetary value is shown. Never allocate a total scheme/discount into this field.", ["sales discount", "sale discount"]),
    ("buffer_discount_amount", "Buffer Discount Amount", 460, "Extract Buffer Discount only when explicitly labelled and a monetary value is shown. Never allocate a total scheme/discount into this field.", ["buffer discount", "buffer"]),
    ("exchange_discount_amount", "Exchange Discount Amount", 470, "Extract Exchange Discount/Exchange Benefit only when explicitly labelled and a monetary value is shown. Keep this separate from exchange vehicle value.", ["exchange discount", "exchange benefit", "exchange scheme"]),
    ("corporate_discount_amount", "Corporate Discount Amount", 480, "Extract Corporate Discount/Corporate Benefit only when explicitly labelled and a monetary value is shown.", ["corporate discount", "corporate benefit", "corporate scheme"]),
    ("loyalty_discount_amount", "Loyalty Discount Amount", 490, "Extract Loyalty Discount/Loyalty Benefit only when explicitly labelled and a monetary value is shown.", ["loyalty discount", "loyalty benefit", "loyalty scheme"]),
    ("inhouse_insurance_discount_amount", "In-house Insurance Discount Amount", 500, "Extract In-house Insurance Discount/Benefit only when explicitly labelled and a monetary value is shown.", ["inhouse insurance discount", "in-house insurance discount", "insurance benefit", "inhouse insurance benefit"]),
    ("mr_discount_amount", "MR Discount Amount", 510, "Extract MR Discount/Benefit only when the document explicitly uses the MR label and shows a monetary value. Do not infer what MR means.", ["mr discount", "mr benefit", "mr"]),
    ("oem_referral_discount_amount", "OEM Referral Discount Amount", 520, "Extract OEM Referral Discount/Benefit only when explicitly labelled and a monetary value is shown.", ["oem referral", "oem referral discount", "referral discount", "oem referral benefit"]),
    ("other_discount_amount", "Other Discount Amount", 530, "Extract a separately labelled Other Discount only when a monetary value is explicitly shown. Do not use this field for an unlabelled aggregate discount.", ["other discount", "other scheme discount"]),
    ("free_accessory_discount_amount", "Free Accessory Discount Amount", 540, "Extract Free Accessory/Accessory Benefit monetary value only when explicitly shown. Do not invent a value for a free item with no amount printed.", ["free accessory", "free accessories", "accessory benefit", "free accessory discount"]),
]


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str) -> Any:
    existing = conn.execute(
        sa.text(
            """
            SELECT canonical_field_id
            FROM docintel.canonical_fields
            WHERE owner_tenant_id IS NULL AND field_key=:field_key
            """
        ),
        {"field_key": field_key},
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return conn.execute(
        sa.text(
            """
            INSERT INTO docintel.canonical_fields (
                canonical_field_id, owner_tenant_id, field_key, display_name,
                data_type, description, status, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), NULL, :field_key, :display_name,
                'CURRENCY', NULL, 'ACTIVE', now(), now()
            )
            RETURNING canonical_field_id
            """
        ),
        {"field_key": field_key, "display_name": display_name},
    ).scalar_one()


def upgrade() -> None:
    conn = op.get_bind()
    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id
            FROM docintel.document_types
            WHERE owner_tenant_id IS NULL
              AND document_type_key='booking_form'
              AND status='ACTIVE'
            """
        )
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
                'Booking Form Commercial Components Extraction v1.5', 'DRAFT',
                'booking_form', :actor_id, now(), now()
            )
            RETURNING profile_id
            """
        ),
        {"document_type_id": document_type_id, "version_no": version_no, "actor_id": _ACTOR},
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

    for field_key, display_name, display_sequence, instruction, aliases in _ADDITIONS:
        canonical_field_id = _ensure_canonical_field(conn, field_key, display_name)
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
                    true, false, :instruction, CAST(:aliases AS jsonb),
                    false, 0.0, false, NULL, true,
                    :display_sequence, now(), now(), :field_key, 'UNSPECIFIED'
                )
                """
            ),
            {
                "profile_id": profile_id,
                "canonical_field_id": canonical_field_id,
                "instruction": instruction,
                "aliases": json.dumps(aliases),
                "display_sequence": display_sequence,
                "field_key": field_key,
            },
        )

    # Keep aggregate legacy fields, but make their boundaries explicit so the
    # extractor never manufactures component values from a single total.
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profile_fields epf
            SET extraction_instruction = CASE cf.field_key
                WHEN 'discount_amount' THEN
                    'Extract only an explicitly shown total/lump-sum discount or scheme amount. Never calculate it and never allocate it across individual discount types.'
                WHEN 'accessories_cost' THEN
                    'Extract only an explicitly shown total/combined accessories amount. Never split it into Essential Kit, Genuine or Non-Genuine components unless those component amounts are separately shown.'
                WHEN 'other_charges' THEN
                    'Extract only an explicitly labelled other/miscellaneous charge. Do not absorb separately labelled TCS, RSA, warranty, FASTag, green tax, service package, registration, road tax, insurance, accessories, discount or bonus amounts.'
                ELSE epf.extraction_instruction
            END,
            updated_at_utc=now()
            FROM docintel.canonical_fields cf
            WHERE epf.profile_id=:profile_id
              AND cf.canonical_field_id=epf.canonical_field_id
              AND cf.field_key IN ('discount_amount','accessories_cost','other_charges')
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
            SET status='PUBLISHED', published_by_actor_id=:actor_id,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:profile_id AND status='DRAFT'
            """
        ),
        {"profile_id": profile_id, "actor_id": _ACTOR},
    )


def downgrade() -> None:
    # Published configuration is immutable. Rollback is a forward publication of a
    # replacement profile, not mutation/deletion of historical published profiles.
    pass
