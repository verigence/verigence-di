"""Scan-quality: reject a faded page (contrast rule) for every tenant.

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-20

Product owner, 2026-10-20: a faded, low-contrast phone photo of a
handwritten Gate Pass passed the scan-quality check (the printed form lines
are sharp, so the blur score passed) and its date was read as 2020 instead
of 2026. Such a page is now rejected at upload and never classified or
extracted: the person who uploaded it is asked to re-scan it.

Adds di.quality.image_contrast to the catalogue and appends it to every
tenant's policy that does not name it yet (a tenant's other rules and their
parameters are left as they are). Forward-only, like 0049.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

# Mirrors verigence/di/quality/policy.py (a migration does not import app code).
_RULE_KEY = "di.quality.image_contrast"
_DESCRIPTION = (
    "The page is not faded: its writing is dark against the paper (ink level at most "
    "max_ink_level, or stroke contrast at least min_stroke_contrast)."
)
_SCHEMA = {
    "type": "object",
    "properties": {"max_ink_level": {"type": "number"}, "min_stroke_contrast": {"type": "number"}},
}
_POLICY_ENTRY = {
    "rule_key": _RULE_KEY,
    "enabled": True,
    "parameters": {"max_ink_level": 90.0, "min_stroke_contrast": 160.0},
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.quality_rule_catalog
                (rule_key, description, implementation_key, parameter_schema, status)
            VALUES (:rule_key, :description, :rule_key, CAST(:schema AS jsonb), 'ACTIVE')
            ON CONFLICT (rule_key) DO UPDATE
                SET description=EXCLUDED.description,
                    implementation_key=EXCLUDED.implementation_key,
                    parameter_schema=EXCLUDED.parameter_schema,
                    status='ACTIVE'
            """
        ),
        {"rule_key": _RULE_KEY, "description": _DESCRIPTION, "schema": json.dumps(_SCHEMA)},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.tenant_settings
            SET quality_policy = COALESCE(quality_policy, '[]'::jsonb) || CAST(:entry AS jsonb),
                updated_at_utc = now()
            WHERE NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(COALESCE(quality_policy, '[]'::jsonb)) AS rule
                WHERE rule ->> 'rule_key' = :rule_key
            )
            """
        ),
        {"entry": json.dumps([_POLICY_ENTRY]), "rule_key": _RULE_KEY},
    )


def downgrade() -> None:
    # Forward-only: tenant policies are data by now.
    pass
