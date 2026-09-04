"""Publish Booking Docket business-field parity with Booking Form.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-04

UC03 Audit Core treats ``booking_form`` and ``booking_docket`` as equivalent
Booking sales-contract evidence sources for shared business attributes.  The
Booking Docket profile must therefore be able to extract every business field
that the current published Booking Form profile can extract.  The earlier
Booking Docket profile preserved a much smaller historical contract, which left
valid Audit Core attributes permanently source-empty whenever the uploaded
sales contract classified as ``booking_docket``.

This migration is additive and fail-closed:
- preserve every field/rule already published for Booking Docket;
- copy only missing canonical fields from the current published Booking Form;
- preserve extraction instructions, aliases, scoring, matching metadata,
  normalizers and validators exactly from Booking Form;
- never invent or derive values; extraction still returns null when source
  evidence is not present on the document.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

_ACTOR = "migration.0029.uc03-booking-docket-business-parity"
_PROFILE_NAME = "UC03 Booking Docket Business Evidence Parity v3"


def _global_document_type_id(conn: Any, document_type_key: str):
    return conn.execute(
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


def _published_profile_id(conn: Any, document_type_id: Any):
    return conn.execute(
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


def _publish_parity_profile(conn: Any) -> None:
    docket_type_id = _global_document_type_id(conn, "booking_docket")
    form_type_id = _global_document_type_id(conn, "booking_form")
    previous_docket_profile_id = _published_profile_id(conn, docket_type_id)
    booking_form_profile_id = _published_profile_id(conn, form_type_id)

    version_no = conn.execute(
        sa.text(
            """
            SELECT COALESCE(MAX(version_no), 0) + 1
            FROM docintel.extraction_profiles
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
            """
        ),
        {"document_type_id": docket_type_id},
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
                :profile_name, 'DRAFT', 'booking_docket',
                :actor, now(), now()
            )
            RETURNING profile_id
            """
        ),
        {
            "document_type_id": docket_type_id,
            "version_no": version_no,
            "profile_name": _PROFILE_NAME,
            "actor": _ACTOR,
        },
    ).scalar_one()

    # Preserve the complete existing Booking Docket contract first, including its
    # docket-only fields (deal_type, out_of_scope_reasons, DSA commission, etc.).
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
            SELECT gen_random_uuid(), :new_profile_id, old.canonical_field_id,
                   old.enabled, old.expected, old.extraction_instruction, old.aliases,
                   old.score_included, old.score_weight, old.use_for_subject_matching,
                   old.subject_identifier_type, old.manual_correction_allowed,
                   old.display_sequence, now(), now(),
                   COALESCE(old.extraction_key, cf.field_key),
                   COALESCE(old.fact_role_override, 'UNSPECIFIED')
            FROM docintel.extraction_profile_fields old
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id=old.canonical_field_id
            WHERE old.profile_id=:old_profile_id
            ORDER BY old.display_sequence, old.profile_field_id
            """
        ),
        {
            "new_profile_id": profile_id,
            "old_profile_id": previous_docket_profile_id,
        },
    )

    # Copy every Booking Form business field that the prior Docket profile lacked.
    # Metadata is copied exactly; no looser extraction rule is introduced here.
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
            SELECT gen_random_uuid(), :new_profile_id, form.canonical_field_id,
                   form.enabled, form.expected, form.extraction_instruction, form.aliases,
                   form.score_included, form.score_weight, form.use_for_subject_matching,
                   form.subject_identifier_type, form.manual_correction_allowed,
                   form.display_sequence, now(), now(),
                   COALESCE(form.extraction_key, cf.field_key),
                   COALESCE(form.fact_role_override, 'UNSPECIFIED')
            FROM docintel.extraction_profile_fields form
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id=form.canonical_field_id
            WHERE form.profile_id=:booking_form_profile_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM docintel.extraction_profile_fields old
                  WHERE old.profile_id=:old_docket_profile_id
                    AND old.canonical_field_id=form.canonical_field_id
              )
            ORDER BY form.display_sequence, form.profile_field_id
            """
        ),
        {
            "new_profile_id": profile_id,
            "booking_form_profile_id": booking_form_profile_id,
            "old_docket_profile_id": previous_docket_profile_id,
        },
    )

    # Preserve normalizers/validators from the old Docket profile for retained
    # fields, then copy Booking Form rules for newly-added parity fields.
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_normalizers (
                profile_field_normalizer_id, profile_field_id,
                sequence_no, rule_key, parameters
            )
            SELECT gen_random_uuid(), new.profile_field_id,
                   rule.sequence_no, rule.rule_key, rule.parameters
            FROM docintel.profile_field_normalizers rule
            JOIN docintel.extraction_profile_fields old
              ON old.profile_field_id=rule.profile_field_id
            JOIN docintel.extraction_profile_fields new
              ON new.profile_id=:new_profile_id
             AND new.canonical_field_id=old.canonical_field_id
            WHERE old.profile_id=:old_docket_profile_id
            ORDER BY old.profile_field_id, rule.sequence_no
            """
        ),
        {
            "new_profile_id": profile_id,
            "old_docket_profile_id": previous_docket_profile_id,
        },
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_validators (
                profile_field_validator_id, profile_field_id,
                sequence_no, rule_key, parameters, severity
            )
            SELECT gen_random_uuid(), new.profile_field_id,
                   rule.sequence_no, rule.rule_key, rule.parameters, rule.severity
            FROM docintel.profile_field_validators rule
            JOIN docintel.extraction_profile_fields old
              ON old.profile_field_id=rule.profile_field_id
            JOIN docintel.extraction_profile_fields new
              ON new.profile_id=:new_profile_id
             AND new.canonical_field_id=old.canonical_field_id
            WHERE old.profile_id=:old_docket_profile_id
            ORDER BY old.profile_field_id, rule.sequence_no
            """
        ),
        {
            "new_profile_id": profile_id,
            "old_docket_profile_id": previous_docket_profile_id,
        },
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_normalizers (
                profile_field_normalizer_id, profile_field_id,
                sequence_no, rule_key, parameters
            )
            SELECT gen_random_uuid(), new.profile_field_id,
                   rule.sequence_no, rule.rule_key, rule.parameters
            FROM docintel.profile_field_normalizers rule
            JOIN docintel.extraction_profile_fields form
              ON form.profile_field_id=rule.profile_field_id
            JOIN docintel.extraction_profile_fields new
              ON new.profile_id=:new_profile_id
             AND new.canonical_field_id=form.canonical_field_id
            WHERE form.profile_id=:booking_form_profile_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM docintel.extraction_profile_fields old
                  WHERE old.profile_id=:old_docket_profile_id
                    AND old.canonical_field_id=form.canonical_field_id
              )
            ORDER BY form.profile_field_id, rule.sequence_no
            """
        ),
        {
            "new_profile_id": profile_id,
            "booking_form_profile_id": booking_form_profile_id,
            "old_docket_profile_id": previous_docket_profile_id,
        },
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_validators (
                profile_field_validator_id, profile_field_id,
                sequence_no, rule_key, parameters, severity
            )
            SELECT gen_random_uuid(), new.profile_field_id,
                   rule.sequence_no, rule.rule_key, rule.parameters, rule.severity
            FROM docintel.profile_field_validators rule
            JOIN docintel.extraction_profile_fields form
              ON form.profile_field_id=rule.profile_field_id
            JOIN docintel.extraction_profile_fields new
              ON new.profile_id=:new_profile_id
             AND new.canonical_field_id=form.canonical_field_id
            WHERE form.profile_id=:booking_form_profile_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM docintel.extraction_profile_fields old
                  WHERE old.profile_id=:old_docket_profile_id
                    AND old.canonical_field_id=form.canonical_field_id
              )
            ORDER BY form.profile_field_id, rule.sequence_no
            """
        ),
        {
            "new_profile_id": profile_id,
            "booking_form_profile_id": booking_form_profile_id,
            "old_docket_profile_id": previous_docket_profile_id,
        },
    )

    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE profile_id=:previous_profile_id
              AND status='PUBLISHED'
            """
        ),
        {"previous_profile_id": previous_docket_profile_id},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED',
                published_by_actor_id=:actor,
                published_at_utc=now(),
                updated_at_utc=now()
            WHERE profile_id=:profile_id
              AND status='DRAFT'
            """
        ),
        {"profile_id": profile_id, "actor": _ACTOR},
    )


def upgrade() -> None:
    _publish_parity_profile(op.get_bind())


def downgrade() -> None:
    # Published extraction profiles are immutable audit history. A rollback must
    # publish a future replacement profile rather than mutate/delete history.
    pass
