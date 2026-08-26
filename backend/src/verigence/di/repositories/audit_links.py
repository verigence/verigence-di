"""Durable DI -> Audit Core document-link delivery state."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def claim_pending_audit_link(session: AsyncSession) -> dict | None:  # type: ignore[type-arg]
    row = (
        await session.execute(
            text(
                """
                SELECT tenant_id, document_id, audit_requirement_ref,
                       audit_link_attempt_count
                FROM docintel.documents
                WHERE upload_status = 'FIT'
                  AND audit_link_status = 'PENDING'
                  AND audit_requirement_ref IS NOT NULL
                ORDER BY registered_at_utc, document_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
        )
    ).mappings().one_or_none()
    if row is None:
        return None
    return dict(row)


async def mark_audit_link_attempt(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: UUID,
    acknowledged: bool,
    error_summary: str | None = None,
) -> None:
    now = datetime.now(UTC)
    await session.execute(
        text(
            """
            UPDATE docintel.documents
            SET audit_link_attempt_count = audit_link_attempt_count + 1,
                audit_link_last_attempt_at_utc = :now,
                audit_link_status = CASE WHEN :ack THEN 'ACKNOWLEDGED' ELSE 'PENDING' END,
                audit_link_acknowledged_at_utc = CASE WHEN :ack THEN :now ELSE NULL END,
                audit_link_last_error = CASE WHEN :ack THEN NULL ELSE :error END,
                updated_at_utc = :now
            WHERE tenant_id = :tenant_id
              AND document_id = :document_id
              AND audit_link_status = 'PENDING'
            """
        ),
        {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "ack": acknowledged,
            "error": (error_summary or "")[:1000] or None,
            "now": now,
        },
    )
