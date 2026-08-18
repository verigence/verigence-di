"""0006 — make source_channel nullable on documents

Decision D10 (DI_DECISIONS.md): source_channel is no longer supplied by the
caller at upload time. The front-end application is responsible for maintaining
channel context. The DI module sets it to NULL for REST API uploads and
WHATSAPP for WhatsApp intake (Phase 2).

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE docintel.documents
        ALTER COLUMN source_channel DROP NOT NULL
    """)


def downgrade() -> None:
    # Restore NOT NULL — fill any NULLs with 'API' first so the constraint applies cleanly
    op.execute("""
        UPDATE docintel.documents
        SET source_channel = 'API'
        WHERE source_channel IS NULL
    """)
    op.execute("""
        ALTER TABLE docintel.documents
        ALTER COLUMN source_channel SET NOT NULL
    """)
