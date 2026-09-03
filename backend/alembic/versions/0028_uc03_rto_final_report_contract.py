"""Publish UC03 RTO Challan final-report extraction contract Package 3.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-03

`rto_challan` already exists in the UC03 document catalogue but was deliberately
manual-review-only because no extraction contract had been published. This
migration publishes the smallest RTO final-report evidence contract and activates
processing for existing tenants. It does not decode registration numbers, infer
geography, derive amounts, or redesign classification/orchestration.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_ACTOR = "migration.0028.uc03-rto-final-report"
_PROFILE_NAME = "UC03 RTO Final Report Contract v1"

# field_key, display_name, data_type, display_sequence, instruction, aliases
F = tuple[str, str, str, int, str, list[str]]

_RTO_FIELDS: list[F] = [
    (
        "registration_number",
        "Registration Number",
        "IDENTIFIER",
        10,
        "Extract the vehicle registration number only when explicitly printed or labelled on the RTO paper/challan. Never reconstruct or decode it.",
        ["registration no", "registration number", "regn no", "vehicle registration no"],
    ),
    (
        "registration_state",
        "Registration State",
        "STRING",
        20,
        "Extract the Registration/RTO State only when explicitly printed. Return null when not stated; never infer State from registration number, RTO code, district, PIN code, or outside geography knowledge.",
        ["state", "registration state", "rto state"],
    ),
    (
        "registration_territory",
        "Registration Territory",
        "STRING",
        30,
        "Extract Territory or Union Territory only when explicitly printed. Return null when not stated; never derive it from State, registration number, RTO code, or outside geography knowledge.",
        ["territory", "union territory", "ut", "registration territory"],
    ),
    (
        "registration_district",
        "Registration District",
        "STRING",
        40,
        "Extract the Registration/RTO District only when explicitly printed. Return null when not stated; never infer it from RTO code, city, State, registration number, or outside geography knowledge.",
        ["district", "registration district", "rto district"],
    ),
    (
        "ex_showroom_amount",
        "Ex Showroom Amount",
        "CURRENCY",
        50,
        "Extract the ex-showroom monetary amount only when explicitly labelled and printed on the RTO paper/challan. Never calculate it from taxable value, invoice value, taxes, registration fees, or totals.",
        ["ex showroom", "ex-showroom", "ex showroom price", "ex-showroom price"],
    ),
    (
        "registration_type",
        "Registration Type",
        "STRING",
        60,
        "Extract registration type/category exactly as printed. Return null when absent; never classify or infer it from vehicle, customer, finance, tax, usage, or registration-number context.",
        ["registration type", "regn type", "type of registration", "registration category"],
    ),
    (
        "hp_charges_amount",
        "HP Charges Amount",
        "CURRENCY",
        70,
        "Extract hypothecation/HP charges only when explicitly labelled and printed. Never calculate or derive the amount from finance details, loan amount, registration fee, or another charge.",
        ["hp charges", "hypothecation charges", "hypothecation fee", "hp fee"],
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
            ) VALUES (
                gen_random_uuid(), :profile_id, :canonical_field_id,
                true, false, :instruction, CAST(:aliases AS jsonb),
                false, 0.0, false, NULL, true,
                :sequence, now(), now(), :field_key, 'UNSPECIFIED'
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


def _publish_rto_profile(conn: Any) -> None:
    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id
            FROM docintel.document_types
            WHERE owner_tenant_id IS NULL
              AND document_type_key='rto_challan'
              AND status='ACTIVE'
            """
        )
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
                'Automobile RTO Challan or RTO registration/fee paper.',
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

    for field in _RTO_FIELDS:
        _add_profile_field(conn, profile_id=profile_id, field=field)

    # Historical profiles remain immutable, but at most one global profile may be published.
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
              AND status='PUBLISHED'
              AND profile_id<>:profile_id
            """
        ),
        {"document_type_id": document_type_id, "profile_id": profile_id},
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


def _activate_for_existing_tenants(conn: Any) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.tenant_document_types (
                tenant_id, document_type_id, physical_form_type,
                requires_processing, is_active, display_order,
                created_at_utc, updated_at_utc
            )
            SELECT ts.tenant_id, dt.document_type_id, 'PRINTABLE',
                   true, true, 100, now(), now()
            FROM docintel.tenant_settings ts
            JOIN docintel.document_types dt
              ON dt.owner_tenant_id IS NULL
             AND dt.document_type_key='rto_challan'
            ON CONFLICT (tenant_id, document_type_id) DO UPDATE
            SET requires_processing=true,
                is_active=true,
                updated_at_utc=now()
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    for field_key, display_name, data_type, *_rest in _RTO_FIELDS:
        _ensure_canonical_field(
            conn,
            field_key=field_key,
            display_name=display_name,
            data_type=data_type,
        )
    _publish_rto_profile(conn)
    _activate_for_existing_tenants(conn)


def downgrade() -> None:
    conn = op.get_bind()

    # Preserve historical profile/fact rows; only retire this package's profile.
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles ep
            SET status='RETIRED', updated_at_utc=now()
            FROM docintel.document_types dt
            WHERE ep.document_type_id=dt.document_type_id
              AND dt.owner_tenant_id IS NULL
              AND dt.document_type_key='rto_challan'
              AND ep.scope_tenant_id IS NULL
              AND ep.created_by_actor_id=:actor
              AND ep.status IN ('DRAFT','PUBLISHED')
            """
        ),
        {"actor": _ACTOR},
    )

    # `0016` created RTO as manual-review evidence; restore that processing posture.
    conn.execute(
        sa.text(
            """
            UPDATE docintel.tenant_document_types tdt
            SET requires_processing=false, updated_at_utc=now()
            FROM docintel.document_types dt
            WHERE tdt.document_type_id=dt.document_type_id
              AND dt.owner_tenant_id IS NULL
              AND dt.document_type_key='rto_challan'
            """
        )
    )
