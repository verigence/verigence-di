"""Backfill newly-active global Document Types into existing Tenants.

This is configuration-only and mirrors provision_tenant_document_types().
It does not change any REST API or processing workflow. Existing tenant-specific
mappings are preserved because ON CONFLICT performs no update.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("""
            INSERT INTO docintel.tenant_document_types (
                tenant_id,
                document_type_id,
                physical_form_type,
                requires_processing,
                is_active,
                display_order,
                created_at_utc,
                updated_at_utc
            )
            SELECT
                ts.tenant_id,
                dt.document_type_id,
                COALESCE(dt.category, 'ADDITIONAL'),
                true,
                true,
                100,
                now(),
                now()
            FROM docintel.tenant_settings ts
            CROSS JOIN docintel.document_types dt
            WHERE dt.owner_tenant_id IS NULL
              AND dt.status = 'ACTIVE'
            ON CONFLICT (tenant_id, document_type_id) DO NOTHING
        """)
    )


def downgrade() -> None:
    # No destructive downgrade: once a Tenant has used a Document Type, its
    # mapping is operational configuration/evidence. Existing mappings are also
    # indistinguishable from rows created by normal provisioning, by design.
    pass
