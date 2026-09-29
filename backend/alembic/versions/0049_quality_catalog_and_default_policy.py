"""Seed the quality rule catalogue and give every tenant a scan-quality policy.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-29

The upload validator runs only the rules a tenant's quality_policy names,
and only when the catalogue lists them as ACTIVE. No migration seeded the
catalogue and every tenant started with an empty policy, so no quality rule
ever ran: a blurred or cut-off page went straight to the paid classification
and extraction calls and failed there, unnamed.

This seeds the six rule implementations (quality/rules.py REGISTRY) into the
catalogue, and gives every tenant whose policy is still empty the default
scan-quality policy (quality/policy.py): not empty, minimum dimensions, blur
score, page count. A tenant that already set its own policy is untouched.
Forward-only: the catalogue rows and policies are data a tenant may have
edited since.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

# Mirrors verigence/di/quality/policy.py (a migration does not import app code).
_CATALOG = [
    (
        "di.quality.file_not_empty",
        "di.quality.file_not_empty",
        "The upload holds at least one byte.",
        {"type": "object", "properties": {}},
    ),
    (
        "di.quality.file_size_max",
        "di.quality.file_size_max",
        "The upload is no larger than max_bytes (default 30 MiB).",
        {"type": "object", "properties": {"max_bytes": {"type": "integer"}}},
    ),
    (
        "di.quality.mime_type_allowed",
        "di.quality.mime_type_allowed",
        "The detected file type is one of allowed_types (default PDF, JPEG, PNG, WebP, TIFF).",
        {
            "type": "object",
            "properties": {"allowed_types": {"type": "array", "items": {"type": "string"}}},
        },
    ),
    (
        "di.quality.image_min_dimensions",
        "di.quality.image_min_dimensions",
        "The page image (or the scan inside a PDF page) is at least min_width x min_height pixels.",
        {
            "type": "object",
            "properties": {"min_width": {"type": "integer"}, "min_height": {"type": "integer"}},
        },
    ),
    (
        "di.quality.image_blur_score",
        "di.quality.image_blur_score",
        "The page image (or the scan inside a PDF page) is sharp: Laplacian variance at least min_variance.",
        {"type": "object", "properties": {"min_variance": {"type": "number"}}},
    ),
    (
        "di.quality.pdf_page_count",
        "di.quality.pdf_page_count",
        "A PDF has at most max_pages pages.",
        {"type": "object", "properties": {"max_pages": {"type": "integer"}}},
    ),
]
_DEFAULT_POLICY = [
    {"rule_key": "di.quality.file_not_empty", "enabled": True, "parameters": {}},
    {
        "rule_key": "di.quality.image_min_dimensions",
        "enabled": True,
        "parameters": {"min_width": 800, "min_height": 600},
    },
    {
        "rule_key": "di.quality.image_blur_score",
        "enabled": True,
        "parameters": {"min_variance": 80.0},
    },
    {"rule_key": "di.quality.pdf_page_count", "enabled": True, "parameters": {"max_pages": 100}},
]


def upgrade() -> None:
    conn = op.get_bind()
    for rule_key, implementation_key, description, schema in _CATALOG:
        conn.execute(
            sa.text(
                """
                INSERT INTO docintel.quality_rule_catalog
                    (rule_key, description, implementation_key, parameter_schema, status)
                VALUES (:rule_key, :description, :implementation_key, CAST(:schema AS jsonb), 'ACTIVE')
                ON CONFLICT (rule_key) DO UPDATE
                    SET description=EXCLUDED.description,
                        implementation_key=EXCLUDED.implementation_key,
                        parameter_schema=EXCLUDED.parameter_schema,
                        status='ACTIVE'
                """
            ),
            {
                "rule_key": rule_key,
                "implementation_key": implementation_key,
                "description": description,
                "schema": json.dumps(schema),
            },
        )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.tenant_settings
            SET quality_policy = CAST(:policy AS jsonb), updated_at_utc = now()
            WHERE quality_policy IS NULL OR jsonb_array_length(quality_policy) = 0
            """
        ),
        {"policy": json.dumps(_DEFAULT_POLICY)},
    )


def downgrade() -> None:
    # Forward-only: catalogue rows and tenant policies are data by now.
    pass
