"""UC02 DI-owned Project Master Excel import staging.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-21
"""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE docintel.config_imports (
            import_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id varchar(128) NOT NULL
                REFERENCES docintel.tenant_settings(tenant_id),
            master_key varchar(80) NOT NULL
                CHECK (master_key IN (
                    'DOCUMENT_TYPES','EXTRACTION_PROFILES','REQUIREMENT_PROFILES'
                )),
            idempotency_key varchar(200) NOT NULL,
            file_name varchar(255) NOT NULL,
            file_hash_sha256 char(64) NOT NULL,
            template_version varchar(40) NOT NULL,
            status varchar(30) NOT NULL
                CHECK (status IN (
                    'PREVIEW_READY','VALIDATION_FAILED','CONFIRMED','CANCELLED','FAILED'
                )),
            rows_parsed integer NOT NULL DEFAULT 0,
            valid_rows integer NOT NULL DEFAULT 0,
            warning_rows integer NOT NULL DEFAULT 0,
            error_rows integer NOT NULL DEFAULT 0,
            result_reference jsonb,
            created_by_user_id varchar(160) NOT NULL,
            created_at_utc timestamptz NOT NULL DEFAULT now(),
            confirmed_by_user_id varchar(160),
            confirmed_at_utc timestamptz,
            UNIQUE (tenant_id, idempotency_key),
            UNIQUE (tenant_id, import_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE docintel.config_import_rows (
            tenant_id varchar(128) NOT NULL,
            import_id uuid NOT NULL,
            row_number integer NOT NULL CHECK (row_number > 1),
            parsed_data jsonb NOT NULL,
            validation_status varchar(20) NOT NULL
                CHECK (validation_status IN ('VALID','WARNING','ERROR')),
            validation_messages jsonb NOT NULL DEFAULT '[]'::jsonb,
            PRIMARY KEY (tenant_id, import_id, row_number),
            FOREIGN KEY (tenant_id, import_id)
                REFERENCES docintel.config_imports(tenant_id, import_id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        ALTER TABLE docintel.config_imports ENABLE ROW LEVEL SECURITY;
        CREATE POLICY config_imports_tenant_isolation ON docintel.config_imports
        USING (tenant_id = docintel.current_tenant_id())
        WITH CHECK (tenant_id = docintel.current_tenant_id());

        ALTER TABLE docintel.config_import_rows ENABLE ROW LEVEL SECURITY;
        CREATE POLICY config_import_rows_tenant_isolation ON docintel.config_import_rows
        USING (tenant_id = docintel.current_tenant_id())
        WITH CHECK (tenant_id = docintel.current_tenant_id());
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS docintel.config_import_rows")
    op.execute("DROP TABLE IF EXISTS docintel.config_imports")
