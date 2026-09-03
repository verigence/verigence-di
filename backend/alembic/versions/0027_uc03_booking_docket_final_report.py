"""Publish UC03 Booking Docket final-report extraction contract Package 2.

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-03

The UC03 Journey requires ``booking_docket`` as the Booking sales-contract
identity.  The existing global published profile already extracts the core
booking/customer/vehicle fields.  This migration clones that immutable profile
and adds only the final-report evidence gaps proven by stabilization Step 2.

No classifier, worker orchestration, document identity, or historical fact is
changed.  Every new field is fail-closed: extract only explicitly visible source
content and never derive a value from other deal data.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_ACTOR = "migration.0027.uc03-booking-docket-final-report"
_PROFILE_NAME = "Booking Docket Final Report Contract v2"

# field_key, display_name, data_type, display_sequence, instruction, aliases
F = tuple[str, str, str, int, str, list[str]]

_ADDITIONS: list[F] = [
    (
        "deal_type",
        "Deal Type",
        "STRING",
        130,
        "Extract the deal type/category exactly as printed, written, selected, "
        "or marked on the Booking Docket. Return null when it is not explicitly "
        "stated; never infer it from finance, exchange, discount, customer, or "
        "vehicle information.",
        ["deal type", "deal category", "type of deal"],
    ),
    (
        "out_of_scope_reasons",
        "Out Of Scope Reasons",
        "STRING",
        140,
        "Extract out-of-scope reason text only when explicitly printed or written "
        "on the Booking Docket. If several reasons are visible, preserve their "
        "source text in this field; never manufacture, classify, or summarize a "
        "reason that the document does not state.",
        ["out of scope reason", "out of scope reasons", "oos reason"],
    ),
    (
        "dsa_commission_amount",
        "DSA Commission Amount",
        "CURRENCY",
        150,
        "Extract the DSA commission monetary value only when an amount is "
        "explicitly shown and labelled as DSA commission. Never calculate it "
        "from finance amount, payout, percentage, discount, or any other value.",
        ["dsa commission", "dsa commission amount", "dsa comm"],
    ),
    (
        "exchange_applicable",
        "Exchange Applicable",
        "BOOLEAN",
        160,
        "Return true or false only when exchange/trade-in is explicitly marked "
        "Yes/No, selected, ticked, checked, or otherwise unambiguously indicated "
        "on the Booking Docket. Return null when there is no explicit selection; "
        "never infer it from exchange value, discount, valuation, or trade-in "
        "documents.",
        ["exchange", "exchange applicable", "trade in", "trade-in"],
    ),
]


def _ensure_canonical_field(
    conn: Any,
    *,
    field_key: str,
    display_name: str,
    data_type: str,
) -> None:
    existing = conn.execute(
        sa.text(
            """
            SELECT data_type
            FROM docintel.canonical_fields
            WHERE owner_tenant_id IS NULL
              AND field_key=:field_key
            """
        ),
        {"field_key": field_key},
    ).scalar_one_or_none()
    if existing is not None:
        if existing != data_type:
            raise RuntimeError(
                f"Canonical type conflict for {field_key}: "
                f"existing={existing}, requested={data_type}"
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
        {
            "field_key": field_key,
            "display_name": display_name,
            "data_type": data_type,
        },
    )


def _add_profile_field(conn: Any, *, profile_id: Any, field: F) -> None:
    field_key, _display_name, _data_type, sequence, instruction, aliases = field
    canonical_field_id = conn.execute(
        sa.text(
            """
            SELECT canonical_field_id
            FROM docintel.canonical_fields
            WHERE owner_tenant_id IS NULL
              AND field_key=:field_key
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
                SELECT 1
                FROM docintel.extraction_profile_fields epf
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


def _publish_booking_docket_profile(conn: Any) -> None:
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
                :profile_name, 'DRAFT', 'booking_docket',
                :actor, now(), now()
            )
            RETURNING profile_id
            """
        ),
        {
            "document_type_id": document_type_id,
            "version_no": version_no,
            "profile_name": _PROFILE_NAME,
            "actor": _ACTOR,
        },
    ).scalar_one()

    # Preserve the complete currently-published field contract and explicit
    # extraction-role metadata before adding the four Package-2 fields.
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
                   epf.enabled, epf.expected, epf.extraction_instruction,
                   epf.aliases, epf.score_included, epf.score_weight,
                   epf.use_for_subject_matching, epf.subject_identifier_type,
                   epf.manual_correction_allowed, epf.display_sequence,
                   now(), now(), COALESCE(epf.extraction_key, cf.field_key),
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

    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_normalizers (
                profile_field_normalizer_id, profile_field_id,
                sequence_no, rule_key, parameters
            )
            SELECT gen_random_uuid(), new_epf.profile_field_id,
                   pfn.sequence_no, pfn.rule_key, pfn.parameters
            FROM docintel.profile_field_normalizers pfn
            JOIN docintel.extraction_profile_fields old_epf
              ON old_epf.profile_field_id=pfn.profile_field_id
            JOIN docintel.extraction_profile_fields new_epf
              ON new_epf.profile_id=:profile_id
             AND new_epf.canonical_field_id=old_epf.canonical_field_id
            WHERE old_epf.profile_id=:previous_profile_id
            ORDER BY old_epf.profile_field_id, pfn.sequence_no
            """
        ),
        {"profile_id": profile_id, "previous_profile_id": previous_profile_id},
    )

    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_validators (
                profile_field_validator_id, profile_field_id,
                sequence_no, rule_key, parameters, severity
            )
            SELECT gen_random_uuid(), new_epf.profile_field_id,
                   pfv.sequence_no, pfv.rule_key, pfv.parameters, pfv.severity
            FROM docintel.profile_field_validators pfv
            JOIN docintel.extraction_profile_fields old_epf
              ON old_epf.profile_field_id=pfv.profile_field_id
            JOIN docintel.extraction_profile_fields new_epf
              ON new_epf.profile_id=:profile_id
             AND new_epf.canonical_field_id=old_epf.canonical_field_id
            WHERE old_epf.profile_id=:previous_profile_id
            ORDER BY old_epf.profile_field_id, pfv.sequence_no
            """
        ),
        {"profile_id": profile_id, "previous_profile_id": previous_profile_id},
    )

    for field in _ADDITIONS:
        _add_profile_field(conn, profile_id=profile_id, field=field)

    # Never leave two global published profiles for the same canonical document
    # type. Historical profile rows remain retained as immutable audit history.
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE profile_id=:previous_profile_id
              AND status='PUBLISHED'
            """
        ),
        {"previous_profile_id": previous_profile_id},
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
    conn = op.get_bind()
    for field_key, display_name, data_type, *_rest in _ADDITIONS:
        _ensure_canonical_field(
            conn,
            field_key=field_key,
            display_name=display_name,
            data_type=data_type,
        )
    _publish_booking_docket_profile(conn)


def downgrade() -> None:
    # Published extraction configuration is immutable. Rollback must be a future
    # replacement profile rather than deletion/mutation of historical profiles.
    pass
