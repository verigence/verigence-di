"""0004 — relax tenant_settings constraints for auto-provisioning

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-16

Changes:
- quality_policy: remove array-must-be-non-empty check (empty = no rules = accept all)
- whatsapp_subject_reference_prefix: allow empty string (not all tenants use WhatsApp)
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE docintel.tenant_settings
            DROP CONSTRAINT IF EXISTS tenant_settings_quality_policy_check
    """)
    op.execute("""
        ALTER TABLE docintel.tenant_settings
            ADD CONSTRAINT tenant_settings_quality_policy_check
            CHECK (jsonb_typeof(quality_policy) = 'array')
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE docintel.tenant_settings
            DROP CONSTRAINT IF EXISTS tenant_settings_quality_policy_check
    """)
    op.execute("""
        ALTER TABLE docintel.tenant_settings
            ADD CONSTRAINT tenant_settings_quality_policy_check
            CHECK (jsonb_typeof(quality_policy) = 'array' AND jsonb_array_length(quality_policy) > 0)
    """)
