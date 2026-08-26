"""Durable DI -> Audit Core document-link delivery state."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def audit_link_retry_delay_seconds(attempt_count: int) -> int:
    """Bound retries without allowing a failed Audit callback to starve extraction."""
    if attempt_count <= 0:
        return 0
    if attempt_count == 1:
        return 5
    if attempt_count == 2:
        return 15
    if attempt_count == 3:
        return 30
    return 60


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
                  AND (
                      audit_link_last_attempt_at_utc IS NULL
                      OR audit_link_last_attempt_at_utc <= now() - make_interval(
                          secs => CASE
                              WHEN audit_link_attempt_count <= 0 THEN 0
                              WHEN audit_link_attempt_count = 1 THEN 5
                              WHEN audit_link_attempt_count = 2 THEN 15
                              WHEN audit_link_attempt_count = 3 THEN 30
                              ELSE 60
                          END
                      )
                  )
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
                audit_link_last_attempt_at_utc = CAST(:now AS timestamptz),
                audit_link_status = CASE WHEN CAST(:ack AS boolean) THEN 'ACKNOWLEDGED' ELSE 'PENDING' END,
                audit_link_acknowledged_at_utc = CASE
                    WHEN CAST(:ack AS boolean) THEN CAST(:now AS timestamptz)
                    ELSE NULL
                END,
                audit_link_last_error = CASE
                    WHEN CAST(:ack AS boolean) THEN NULL
                    ELSE CAST(:error AS text)
                END,
                updated_at_utc = CAST(:now AS timestamptz)
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
