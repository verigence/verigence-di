"""Persist Audit Core requirement refs for Document Capture V2.

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-06

V2 accepts unknown documents and learns the document type only during classification.
Audit Core, however, owns the exact Journey requirement UUID required by the existing
DI -> Audit Core evidence callback.  Store the type-to-requirement map at upload-init
so the classifier can bind the accepted type before extraction is queued.
"""
from __future__ import annotations

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE docintel.document_capture_v2_uploads
        ADD COLUMN requirement_refs_by_document_type_key jsonb NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute(
        """
        ALTER TABLE docintel.document_capture_v2_uploads
        ADD CONSTRAINT ck_document_capture_v2_requirement_ref_map_object
        CHECK (jsonb_typeof(requirement_refs_by_document_type_key) = 'object')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE docintel.document_capture_v2_uploads
        DROP CONSTRAINT IF EXISTS ck_document_capture_v2_requirement_ref_map_object
        """
    )
    op.execute(
        """
        ALTER TABLE docintel.document_capture_v2_uploads
        DROP COLUMN IF EXISTS requirement_refs_by_document_type_key
        """
    )
