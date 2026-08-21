"""UC02 Audit-originated storage context.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-21
"""
from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE docintel.audit_storage_contexts (
            storage_context_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id varchar(128) NOT NULL
                REFERENCES docintel.tenant_settings(tenant_id),
            external_context_ref text NOT NULL,
            subject_id uuid NOT NULL,
            dealer_id uuid NOT NULL,
            dealer_outlet_id uuid NOT NULL,
            customer_id uuid NOT NULL,
            project_slug varchar(40) NOT NULL,
            dealer_slug varchar(30) NOT NULL,
            dealer_outlet_slug varchar(30) NOT NULL,
            customer_slug varchar(30) NOT NULL,
            created_by_service_principal varchar(160) NOT NULL,
            created_at_utc timestamptz NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, external_context_ref),
            UNIQUE (tenant_id, storage_context_id),
            FOREIGN KEY (tenant_id, subject_id)
                REFERENCES docintel.subjects(tenant_id, subject_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_audit_storage_contexts_scope
        ON docintel.audit_storage_contexts
            (tenant_id, dealer_id, dealer_outlet_id, customer_id)
        """
    )
    op.execute(
        """
        ALTER TABLE docintel.audit_storage_contexts ENABLE ROW LEVEL SECURITY;
        CREATE POLICY audit_storage_contexts_tenant_isolation
        ON docintel.audit_storage_contexts
        USING (tenant_id = docintel.current_tenant_id())
        WITH CHECK (tenant_id = docintel.current_tenant_id());
        """
    )
    op.execute(
        """
        ALTER TABLE docintel.documents
        ADD COLUMN audit_storage_context_id uuid;
        ALTER TABLE docintel.documents
        ADD CONSTRAINT fk_documents_audit_storage_context
        FOREIGN KEY (tenant_id, audit_storage_context_id)
        REFERENCES docintel.audit_storage_contexts(tenant_id, storage_context_id);
        CREATE INDEX ix_documents_audit_storage_context
        ON docintel.documents (tenant_id, audit_storage_context_id)
        WHERE audit_storage_context_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS docintel.ix_documents_audit_storage_context")
    op.execute(
        "ALTER TABLE docintel.documents "
        "DROP CONSTRAINT IF EXISTS fk_documents_audit_storage_context"
    )
    op.execute(
        "ALTER TABLE docintel.documents "
        "DROP COLUMN IF EXISTS audit_storage_context_id"
    )
    op.execute("DROP TABLE IF EXISTS docintel.audit_storage_contexts")
