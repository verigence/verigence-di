"""repositories/search_index.py — document_search_index upsert.

D14: After Step 17 (CONFIRMED), the Processing Worker calls upsert_search_index()
to write a denormalised, queryable snapshot of extracted field values.
One row per document, INSERT … ON CONFLICT (tenant_id, document_id) UPDATE.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_search_index(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    subject_id: uuid.UUID | None,
    document_type_key: str,
    indexed_fields: dict[str, Any],
    schema_version: str,
) -> None:
    """Upsert one row into docintel.document_search_index (D14).

    Args:
        session: The active async SQLAlchemy session (caller commits).
        tenant_id: Owning tenant.
        document_id: Document UUID.
        subject_id: Subject UUID — nullable (WhatsApp unassigned docs have none).
        document_type_key: Accepted document type key from classification.
        indexed_fields: Flat key→value map of all extracted canonical field values.
                        Values may be str, int, float, bool, or None.
        schema_version: Pipeline or schema version tag (e.g. "2.2.0").
    """
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.document_search_index
                (tenant_id, document_id, subject_id, document_type_key,
                 indexed_fields, schema_version, created_at_utc, updated_at_utc)
            VALUES
                (:tid, :doc_id, :subject_id, :doc_type_key,
                 CAST(:indexed_fields AS jsonb), :schema_version, :now, :now)
            ON CONFLICT (tenant_id, document_id)
            DO UPDATE SET
                subject_id        = EXCLUDED.subject_id,
                document_type_key = EXCLUDED.document_type_key,
                indexed_fields    = EXCLUDED.indexed_fields,
                schema_version    = EXCLUDED.schema_version,
                updated_at_utc    = EXCLUDED.updated_at_utc
        """),
        {
            "tid": tenant_id,
            "doc_id": document_id,
            "subject_id": subject_id,
            "doc_type_key": document_type_key,
            "indexed_fields": json.dumps(indexed_fields),
            "schema_version": schema_version,
            "now": now,
        },
    )
