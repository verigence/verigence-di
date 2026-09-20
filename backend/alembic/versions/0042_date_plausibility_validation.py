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
di.val.date_plausible_range (rules/validators.py) and attaches it to
every DATE-typed field on every currently-published, tenant-agnostic
extraction profile.

This adds a validator, not a new extraction contract -- unlike a field
addition (which changes what gets extracted and republishes a whole new
profile version, e.g. migration 0041), profile_field_validators/
profile_field_normalizers are runtime quality-gate configuration:
adding one to an already-published profile only changes future
extraction runs' validation_results, never past ones. A FAIL here
already has real teeth end-to-end with no further wiring: job_runner.py
already forces human_verification_status=MANDATORY on ANY ERROR-severity
validator FAILure for the document (deterministic_rules_force_review),
which is what already routes a document into the existing PC-review
Task Queue -- this migration is the only piece that was missing.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

_RULE_KEY = "date_plausible_range"


def upgrade() -> None:
    conn = op.get_bind()

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
            JOIN docintel.extraction_profiles ep
              ON ep.profile_id = epf.profile_id
            WHERE cf.data_type = 'DATE'
              AND ep.status = 'PUBLISHED'
              AND ep.scope_tenant_id IS NULL
              AND epf.enabled = true
              AND NOT EXISTS (
                  SELECT 1 FROM docintel.profile_field_validators already
                  WHERE already.profile_field_id = epf.profile_field_id
                    AND already.rule_key = :rule_key
              )
            """
        ),
        {"rule_key": _RULE_KEY},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM docintel.profile_field_validators
            WHERE rule_key = :rule_key
            """
        ),
        {"rule_key": _RULE_KEY},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.validation_rule_catalog
            SET status = 'RETIRED'
            WHERE rule_key = :rule_key
            """
        ),
        {"rule_key": _RULE_KEY},
    )
