"""Add a date-plausibility validator to every DATE-typed field.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-20

Confirmed live: OCR/LLM date extraction on dealership documents
occasionally misreads a year (a 2-digit year expanded to the wrong
century, a smudged digit, a transposition), landing an invoice/receipt/
delivery date years away from reality -- di.val.date_not_future only
catches a date after today, nothing catches one implausibly far in the
past. Registers a new validation_rule_catalog rule backed by
di.val.date_plausible_range (rules/validators.py).

profile_field_validators/extraction_profile_fields are guarded immutable
once their parent profile is PUBLISHED (docintel.guard_extraction_
profile_child(), 0001_initial_schema.py) -- a direct INSERT against an
already-published profile's fields raises
"published/retired extraction profile children are immutable" outright.
So this cannot attach the new validator to existing published profiles
in place; it has to clone each currently-published, tenant-agnostic
profile that has at least one DATE field into a new DRAFT version
(fields + normalizers + validators copied verbatim), attach the new
validator to that clone's DATE fields, then retire the old version and
publish the clone -- the same versioned-publish shape 0041 uses for a
single document type, generalized here across every profile that needs
it.

A FAIL already has real teeth end-to-end with no further wiring beyond
this: job_runner.py's deterministic_rules_force_review already forces
human_verification_status=MANDATORY on any ERROR-severity validator
FAILure for the document, which already routes into the existing
PC-review Task Queue.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

_ACTOR = "migration.0042.date-plausibility-validation"
_RULE_KEY = "date_plausible_range"

_FIELD_COLUMNS = (
    "canonical_field_id", "enabled", "expected", "extraction_instruction",
    "aliases", "score_included", "score_weight", "use_for_subject_matching",
    "subject_identifier_type", "manual_correction_allowed", "display_sequence",
    "extraction_key", "fact_role_override",
)


def _register_rule(conn: Any) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.validation_rule_catalog (
                rule_key, description, implementation_key, parameter_schema,
                result_scope, status
            ) VALUES (
                :rule_key,
                'Flags a date field whose value falls outside a plausible window '
                'around today (default: up to 3 years in the past, 1 year in the '
                'future) -- catches OCR/LLM year misreads that date_not_future '
                'alone cannot, since a date years in the past is still "not the '
                'future".',
                'di.val.date_plausible_range',
                CAST(:parameter_schema AS jsonb),
                'FIELD',
                'ACTIVE'
            )
            ON CONFLICT (rule_key) DO NOTHING
            """
        ),
        {
            "rule_key": _RULE_KEY,
            "parameter_schema": json.dumps({
                "type": "object",
                "properties": {
                    "max_years_past": {"type": "integer", "default": 3},
                    "max_years_future": {"type": "integer", "default": 1},
                },
            }),
        },
    )


def _profiles_with_a_date_field(conn: Any) -> list[Any]:
    return list(conn.execute(
        sa.text(
            """
            SELECT DISTINCT ep.profile_id
            FROM docintel.extraction_profiles ep
            JOIN docintel.extraction_profile_fields epf
              ON epf.profile_id = ep.profile_id
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id = epf.canonical_field_id
            WHERE ep.status = 'PUBLISHED'
              AND ep.scope_tenant_id IS NULL
              AND epf.enabled = true
              AND cf.data_type = 'DATE'
              AND NOT EXISTS (
                  SELECT 1 FROM docintel.profile_field_validators pfv
                  WHERE pfv.profile_field_id = epf.profile_field_id
                    AND pfv.rule_key = :rule_key
              )
            """
        ),
        {"rule_key": _RULE_KEY},
    ).scalars().all())


def _clone_and_republish(conn: Any, *, old_profile_id: Any) -> None:
    old = conn.execute(
        sa.text(
            """
            SELECT document_type_id, scope_tenant_id, profile_name, classification_hint
            FROM docintel.extraction_profiles WHERE profile_id = :pid
            """
        ),
        {"pid": old_profile_id},
    ).mappings().one()

    version_no = conn.execute(
        sa.text(
            """
            SELECT COALESCE(MAX(version_no), 0) + 1
            FROM docintel.extraction_profiles
            WHERE document_type_id = :dtid
              AND scope_tenant_id IS NOT DISTINCT FROM :stid
            """
        ),
        {"dtid": old["document_type_id"], "stid": old["scope_tenant_id"]},
    ).scalar_one()

    new_profile_id = conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profiles (
                profile_id, document_type_id, scope_tenant_id, version_no,
                profile_name, status, classification_hint,
                created_by_actor_id, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), :dtid, :stid, :vno, :name, 'DRAFT', :hint,
                :actor, now(), now()
            )
            RETURNING profile_id
            """
        ),
        {
            "dtid": old["document_type_id"],
            "stid": old["scope_tenant_id"],
            "vno": version_no,
            "name": old["profile_name"],
            "hint": old["classification_hint"],
            "actor": _ACTOR,
        },
    ).scalar_one()

    # aliases is explicitly cast to text in the SELECT so this always gets a
    # raw JSON string back from Postgres regardless of how the driver would
    # otherwise deserialize a jsonb column -- passed straight into
    # CAST(:aliases AS jsonb) below with no Python-side re-encoding, which
    # would silently double-encode it if the driver had already handed back
    # a native dict/list instead of text.
    select_columns = [c if c != "aliases" else "aliases::text AS aliases" for c in _FIELD_COLUMNS]
    fields = conn.execute(
        sa.text(
            f"""
            SELECT profile_field_id, {', '.join(select_columns)}
            FROM docintel.extraction_profile_fields
            WHERE profile_id = :pid
            ORDER BY display_sequence, profile_field_id
            """
        ),
        {"pid": old_profile_id},
    ).mappings().all()

    field_id_map: dict[Any, Any] = {}
    for row in fields:
        params = {col: row[col] for col in _FIELD_COLUMNS}
        params["new_profile_id"] = new_profile_id
        new_field_id = conn.execute(
            sa.text(
                f"""
                INSERT INTO docintel.extraction_profile_fields (
                    profile_field_id, profile_id, {', '.join(_FIELD_COLUMNS)},
                    created_at_utc, updated_at_utc
                ) VALUES (
                    gen_random_uuid(), :new_profile_id,
                    {', '.join(
                        f"CAST(:{col} AS jsonb)" if col == "aliases" else f":{col}"
                        for col in _FIELD_COLUMNS
                    )},
                    now(), now()
                )
                RETURNING profile_field_id
                """
            ),
            params,
        ).scalar_one()
        field_id_map[row["profile_field_id"]] = new_field_id

    for old_field_id, new_field_id in field_id_map.items():
        conn.execute(
            sa.text(
                """
                INSERT INTO docintel.profile_field_normalizers (
                    profile_field_normalizer_id, profile_field_id,
                    sequence_no, rule_key, parameters
                )
                SELECT gen_random_uuid(), :new_field_id, sequence_no, rule_key, parameters
                FROM docintel.profile_field_normalizers
                WHERE profile_field_id = :old_field_id
                """
            ),
            {"new_field_id": new_field_id, "old_field_id": old_field_id},
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO docintel.profile_field_validators (
                    profile_field_validator_id, profile_field_id,
                    sequence_no, rule_key, parameters, severity
                )
                SELECT gen_random_uuid(), :new_field_id, sequence_no, rule_key, parameters, severity
                FROM docintel.profile_field_validators
                WHERE profile_field_id = :old_field_id
                """
            ),
            {"new_field_id": new_field_id, "old_field_id": old_field_id},
        )

    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_validators (
                profile_field_validator_id, profile_field_id,
                sequence_no, rule_key, parameters, severity
            )
            SELECT
                gen_random_uuid(),
                epf.profile_field_id,
                COALESCE(
                    (SELECT MAX(existing.sequence_no) + 1
                     FROM docintel.profile_field_validators existing
                     WHERE existing.profile_field_id = epf.profile_field_id),
                    1
                ),
                :rule_key,
                '{}'::jsonb,
                'ERROR'
            FROM docintel.extraction_profile_fields epf
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id = epf.canonical_field_id
            WHERE epf.profile_id = :new_profile_id
              AND cf.data_type = 'DATE'
              AND epf.enabled = true
            """
        ),
        {"new_profile_id": new_profile_id, "rule_key": _RULE_KEY},
    )

    # Retire old, then publish new -- never both PUBLISHED at once
    # (uq_extraction_profile_published is a partial unique index on
    # status='PUBLISHED'). Only status/updated_at_utc change on retire;
    # every other column must stay byte-identical to satisfy
    # guard_extraction_profile_header's PUBLISHED->RETIRED transition check.
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status = 'RETIRED', updated_at_utc = now()
            WHERE profile_id = :pid
            """
        ),
        {"pid": old_profile_id},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status = 'PUBLISHED',
                published_by_actor_id = :actor,
                published_at_utc = now(),
                updated_at_utc = now()
            WHERE profile_id = :pid AND status = 'DRAFT'
            """
        ),
        {"pid": new_profile_id, "actor": _ACTOR},
    )


def upgrade() -> None:
    conn = op.get_bind()
    _register_rule(conn)
    for profile_id in _profiles_with_a_date_field(conn):
        _clone_and_republish(conn, old_profile_id=profile_id)


def downgrade() -> None:
    conn = op.get_bind()
    # Historical profiles remain immutable by design; downgrading the schema
    # doesn't un-clone the profiles this created. Just retire this
    # migration's own rule so it stops being ACTIVE for anything still
    # published.
    conn.execute(
        sa.text(
            "UPDATE docintel.validation_rule_catalog SET status = 'RETIRED' WHERE rule_key = :rule_key"
        ),
        {"rule_key": _RULE_KEY},
    )
