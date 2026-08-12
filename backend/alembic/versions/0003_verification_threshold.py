"""0003_verification_threshold

Add nullable verification_threshold column to docintel.tenant_settings.
NULL means "use system-wide default" (DI_VERIFICATION_THRESHOLD env var, default 90.00).
Per-tenant value overrides the system-wide default when set.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column(
            "verification_threshold",
            sa.Numeric(precision=5, scale=2),
            nullable=True,
            comment="Per-tenant verification threshold override. NULL = use system default.",
        ),
        schema="docintel",
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "verification_threshold", schema="docintel")
