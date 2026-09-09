"""Publish Booking Docket scrappage discount/bonus extraction (parity with 0033).

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-09

0033 added Scrappage Discount/Bonus (``scrappage_discount_amount``) to the
Booking Form profile, but not to Booking Docket -- breaking the business
parity 0029 deliberately established between the two profiles (a Booking
Docket must be a superset of Booking Form: every fact a booking form can
carry, the docket can carry too). Caught by
``test_uc03_booking_docket_business_parity.py``'s own live parity assertion.

Same publish-a-new-immutable-profile-version pattern as 0025/0029/0033: clone
the current published Booking Docket profile, add the one new field.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

_ACTOR = "migration.0034.booking-docket-scrappage-discount-parity"

_FIELD_KEY = "scrappage_discount_amount"
_DISPLAY_NAME = "Scrappage Discount Amount"
_DISPLAY_SEQUENCE = 485  # between corporate_discount_amount (480) and loyalty_discount_amount (490)
_INSTRUCTION = (
    "Extract Scrappage Discount/Scrappage Bonus only when explicitly labelled "
    "and a monetary value is shown. Never allocate a total scheme/discount "
    "into this field."
)
_ALIASES = ["scrappage discount", "scrappage bonus", "scrappage benefit", "vehicle scrappage discount"]
_PROFILE_NAME = "UC03 Booking Docket Business Evidence Parity v4"


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
              AND document_type_key='booking_docket'
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
                :profile_name, 'DRAFT',
                'booking_docket', :actor_id, now(), now()
            )
            RETURNING profile_id
            """
        ),
        {
            "document_type_id": document_type_id,
            "version_no": version_no,
            "profile_name": _PROFILE_NAME,
            "actor_id": _ACTOR,
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

    canonical_field_id = _ensure_canonical_field(conn, _FIELD_KEY, _DISPLAY_NAME)
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
            "instruction": _INSTRUCTION,
            "aliases": json.dumps(_ALIASES),
            "display_sequence": _DISPLAY_SEQUENCE,
            "field_key": _FIELD_KEY,
        },
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
