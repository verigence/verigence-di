"""Add insurance agent/intermediary and MISP fields to insurance_cover.

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-10

Business ask: capture Agent/Intermediary Details, Agent/Intermediary Code,
and MISP (Motor Insurance Service Provider) code from an insurance cover
note, alongside the add-ons (zero dep, engine protection, etc.) the profile
already captures via its existing add_ons field.

Clones insurance_cover's current published profile fields (same technique
as 0036's payment_receipt clone) and adds three new fields, matching
document_ai/schemas/insurance_cover.py's updated field list exactly.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

_ACTOR = "migration.0037.insurance-agent-misp-fields"

_NEW_CANONICAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("agent_intermediary_name", "Agent/Intermediary Name", "STRING"),
    ("agent_intermediary_code", "Agent/Intermediary Code", "IDENTIFIER"),
    ("misp_code", "MISP Code", "IDENTIFIER"),
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


def upgrade() -> None:
    conn = op.get_bind()

    for field_key, display_name, data_type in _NEW_CANONICAL_FIELDS:
        _ensure_canonical_field(conn, field_key, display_name, data_type)

    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id FROM docintel.document_types
            WHERE owner_tenant_id IS NULL AND document_type_key='insurance_cover' AND status='ACTIVE'
            """
        )
    ).scalar_one()
    previous_profile_id = conn.execute(
        sa.text(
            """
            SELECT profile_id FROM docintel.extraction_profiles
            WHERE document_type_id=:dtid AND scope_tenant_id IS NULL AND status='PUBLISHED'
            ORDER BY version_no DESC LIMIT 1
            """
        ),
        {"dtid": document_type_id},
    ).scalar_one()
    version_no = conn.execute(
        sa.text(
            "SELECT COALESCE(MAX(version_no), 0) + 1 FROM docintel.extraction_profiles "
            "WHERE document_type_id=:dtid AND scope_tenant_id IS NULL"
        ),
        {"dtid": document_type_id},
    ).scalar_one()
    profile_id = conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profiles (
                profile_id, document_type_id, scope_tenant_id, version_no,
                profile_name, status, classification_hint,
                created_by_actor_id, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), :dtid, NULL, :version_no,
                'Insurance Cover Note India Extraction v3', 'DRAFT', 'insurance_cover',
                :actor_id, now(), now()
            ) RETURNING profile_id
            """
        ),
        {"dtid": document_type_id, "version_no": version_no, "actor_id": _ACTOR},
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
            JOIN docintel.canonical_fields cf ON cf.canonical_field_id=epf.canonical_field_id
            WHERE epf.profile_id=:previous_profile_id
            ORDER BY epf.display_sequence, epf.profile_field_id
            """
        ),
        {"profile_id": profile_id, "previous_profile_id": previous_profile_id},
    )

    new_fields = (
        ("agent_intermediary_name", False, "Extract the agent/intermediary/broker name exactly as printed, only when the policy was sold through one.", ["agent", "intermediary", "broker"], 150),
        ("agent_intermediary_code", False, "Extract the agent/intermediary/broker code or license number exactly as printed.", ["agent code", "intermediary code", "broker code", "license no"], 160),
        ("misp_code", False, "Extract the MISP (Motor Insurance Service Provider) code exactly as printed, when the dealership itself is registered as the selling MISP.", ["misp", "misp code"], 170),
    )
    for field_key, expected, instruction, aliases, seq in new_fields:
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
                    false, 0.0, false, NULL, true, :seq, now(), now(), :field_key, 'UNSPECIFIED'
                )
                """
            ),
            {
                "profile_id": profile_id,
                "canonical_field_id": canonical_field_id,
                "expected": expected,
                "instruction": instruction,
                "aliases": json.dumps(aliases),
                "seq": seq,
                "field_key": field_key,
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
        {"actor_id": _ACTOR, "profile_id": profile_id},
    )


def downgrade() -> None:
    # Published configuration is immutable; forward-only (same as every
    # other profile-publishing migration in this repo).
    pass
