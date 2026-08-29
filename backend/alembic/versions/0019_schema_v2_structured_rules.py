"""Seed Schema V2 deterministic structured-value rules.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-29

The migration only registers implementation keys.  Profile-specific row shapes
remain immutable configuration on profile_field_normalizers / validators.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    normalization_schema = {
        "type": "object",
        "properties": {
            "container": {"enum": ["array", "object"]},
        },
    }
    validation_schema = {
        "type": "object",
        "properties": {
            "container": {"const": "array"},
            "item_type": {"enum": ["string", "object"]},
            "properties": {"type": "object"},
            "required_keys": {"type": "array"},
            "allow_extra_keys": {"type": "boolean"},
            "min_items": {"type": "integer", "minimum": 0},
        },
    }

    bind.execute(
        sa.text("""
            INSERT INTO docintel.normalization_rule_catalog (
                rule_key, description, implementation_key, parameter_schema, status
            ) VALUES (
                'schema_v2.structured_literal_parse',
                'Parse an extracted JSON/collection literal into a typed JSON value without repairing or dropping rows.',
                'di.norm.structured_literal_parse',
                CAST(:parameter_schema AS jsonb),
                'ACTIVE'
            )
            ON CONFLICT (rule_key) DO NOTHING
        """),
        {"parameter_schema": json.dumps(normalization_schema)},
    )
    bind.execute(
        sa.text("""
            INSERT INTO docintel.validation_rule_catalog (
                rule_key, description, implementation_key, parameter_schema,
                result_scope, status
            ) VALUES (
                'schema_v2.structured_shape',
                'Validate typed structured arrays/rows deterministically and surface every malformed row as a validation result.',
                'di.val.structured_shape',
                CAST(:parameter_schema AS jsonb),
                'FIELD',
                'ACTIVE'
            )
            ON CONFLICT (rule_key) DO NOTHING
        """),
        {"parameter_schema": json.dumps(validation_schema)},
    )


def downgrade() -> None:
    # Catalog rows may be referenced by immutable/published profile children.
    # Do not delete them in place; rollback via the pre-Schema-V2 Neon branch.
    raise RuntimeError(
        "0019 is safety-nonreversible in place; restore the pre-schema-v2 Neon branch"
    )
