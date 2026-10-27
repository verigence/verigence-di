"""Publish the insurance_cover profile with the policy's hypothecation (financier).

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-27

Product owner rule 2026-10-27: a deal is financed only when the RTO challan, the
insurance hypothecation or a receipt from the financier shows it. Policies print
"Hypothecated to / Financier / HPA: <bank>", which DI never read. insurance_cover
schema 1.3 adds hypothecated_to; this publishes the matching profile -- the
published fields copied verbatim (aliases, flags, normalizers, validators) plus
the new optional field -- and retires the old one. Published profiles are
immutable, hence a new version. Nothing is re-extracted here. Forward-only.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

_ACTOR = "migration.0057.insurance-hypothecation"
_TYPE_KEY = "insurance_cover"
_NEW_KEY = "hypothecated_to"
_NEW_INSTRUCTION = (
    "Name of the financier (bank / finance company) the vehicle is hypothecated to, exactly as printed against "
    "'Hypothecation', 'Hypothecated to', 'Financier', 'Agreement with', 'HPA' or 'Lease/Hire Purchase with'; "
    "null when the policy prints no financier, 'NA', 'Nil' or 'Cash'. Never the insurer, intermediary or dealer."
)
_NEW_ALIASES = ["hypothecation", "hypothecated to", "financier", "hpa", "agreement with", "hire purchase"]


def upgrade() -> None:
    conn = op.get_bind()
    document_type_id = conn.execute(
        sa.text("SELECT document_type_id FROM docintel.document_types "
                "WHERE owner_tenant_id IS NULL AND document_type_key=:k AND status='ACTIVE'"),
        {"k": _TYPE_KEY},
    ).scalar_one_or_none()
    if document_type_id is None:
        return
    old = conn.execute(
        sa.text("SELECT profile_id, profile_name, classification_hint FROM docintel.extraction_profiles "
                "WHERE document_type_id=:d AND scope_tenant_id IS NULL AND status='PUBLISHED'"),
        {"d": document_type_id},
    ).mappings().one_or_none()
    if old is None:
        return
    already = conn.execute(
        sa.text("SELECT 1 FROM docintel.extraction_profile_fields epf "
                "JOIN docintel.canonical_fields cf ON cf.canonical_field_id = epf.canonical_field_id "
                "WHERE epf.profile_id=:p AND COALESCE(epf.extraction_key, cf.field_key)=:k"),
        {"p": old["profile_id"], "k": _NEW_KEY},
    ).scalar_one_or_none()
    if already:
        return

    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.canonical_fields (canonical_field_id, owner_tenant_id, field_key, display_name,
                                                   data_type, description, status, created_at_utc, updated_at_utc)
            SELECT gen_random_uuid(), NULL, :k, 'Hypothecated To', 'STRING', NULL, 'ACTIVE', now(), now()
            WHERE NOT EXISTS (SELECT 1 FROM docintel.canonical_fields WHERE owner_tenant_id IS NULL AND field_key=:k)
            """
        ),
        {"k": _NEW_KEY},
    )
    new_profile_id = conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profiles (profile_id, document_type_id, scope_tenant_id, version_no,
                                                      profile_name, status, classification_hint,
                                                      created_by_actor_id, created_at_utc, updated_at_utc)
            SELECT gen_random_uuid(), :d, NULL,
                   COALESCE((SELECT MAX(version_no) FROM docintel.extraction_profiles
                             WHERE document_type_id=:d AND scope_tenant_id IS NULL), 0) + 1,
                   :name, 'DRAFT', :hint, :actor, now(), now()
            RETURNING profile_id
            """
        ),
        {"d": document_type_id, "name": old["profile_name"], "hint": old["classification_hint"], "actor": _ACTOR},
    ).scalar_one()

    old_fields = conn.execute(
        sa.text("SELECT profile_field_id FROM docintel.extraction_profile_fields WHERE profile_id=:p "
                "ORDER BY display_sequence, profile_field_id"),
        {"p": old["profile_id"]},
    ).scalars().all()
    max_seq = 0
    for old_field_id in old_fields:
        new_field_id, seq = conn.execute(
            sa.text(
                """
                INSERT INTO docintel.extraction_profile_fields (
                    profile_field_id, profile_id, canonical_field_id, enabled, expected, extraction_instruction,
                    aliases, score_included, score_weight, use_for_subject_matching, subject_identifier_type,
                    manual_correction_allowed, display_sequence, created_at_utc, updated_at_utc,
                    extraction_key, fact_role_override)
                SELECT gen_random_uuid(), :new_profile, canonical_field_id, enabled, expected, extraction_instruction,
                       aliases, score_included, score_weight, use_for_subject_matching, subject_identifier_type,
                       manual_correction_allowed, display_sequence, now(), now(),
                       extraction_key, fact_role_override
                FROM docintel.extraction_profile_fields WHERE profile_field_id=:old
                RETURNING profile_field_id, display_sequence
                """
            ),
            {"new_profile": new_profile_id, "old": old_field_id},
        ).one()
        max_seq = max(max_seq, int(seq or 0))
        for table, pk, extra in (
            ("profile_field_normalizers", "profile_field_normalizer_id", ""),
            ("profile_field_validators", "profile_field_validator_id", ", severity"),
        ):
            conn.execute(
                sa.text(
                    f"""
                    INSERT INTO docintel.{table} ({pk}, profile_field_id, sequence_no, rule_key, parameters{extra})
                    SELECT gen_random_uuid(), :new_id, sequence_no, rule_key, parameters{extra}
                    FROM docintel.{table} WHERE profile_field_id = :old_id
                    """
                ),
                {"new_id": new_field_id, "old_id": old_field_id},
            )

    canonical_field_id = conn.execute(
        sa.text("SELECT canonical_field_id FROM docintel.canonical_fields WHERE owner_tenant_id IS NULL AND field_key=:k"),
        {"k": _NEW_KEY},
    ).scalar_one()
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profile_fields (
                profile_field_id, profile_id, canonical_field_id, enabled, expected, extraction_instruction, aliases,
                score_included, score_weight, use_for_subject_matching, subject_identifier_type,
                manual_correction_allowed, display_sequence, created_at_utc, updated_at_utc,
                extraction_key, fact_role_override)
            VALUES (gen_random_uuid(), :p, :cf, true, false, :instruction, CAST(:aliases AS jsonb),
                    false, 0.0, false, NULL, true, :seq, now(), now(), :k, 'UNSPECIFIED')
            """
        ),
        {"p": new_profile_id, "cf": canonical_field_id, "instruction": _NEW_INSTRUCTION,
         "aliases": json.dumps(_NEW_ALIASES), "seq": max_seq + 10, "k": _NEW_KEY},
    )

    conn.execute(
        sa.text("UPDATE docintel.extraction_profiles SET status='RETIRED', updated_at_utc=now() WHERE profile_id=:p"),
        {"p": old["profile_id"]},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED', published_by_actor_id=:actor, published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:p AND status='DRAFT'
            """
        ),
        {"p": new_profile_id, "actor": _ACTOR},
    )


def downgrade() -> None:
    # Published configuration is immutable; forward-only (as 0037/0051/0055).
    pass
