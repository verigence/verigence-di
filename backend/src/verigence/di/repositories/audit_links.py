"""Durable DI -> Audit Core document-link delivery state."""
from __future__ import annotations

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
                       audit_link_attempt_count, correlation_id
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
    retryable: bool = True,
) -> None:
    """Record one Audit-link delivery attempt without ambiguous timestamp binds.

    PostgreSQL owns all timestamps here. Using ``now()`` avoids reusing one
    asyncpg bind parameter across both direct timestamptz assignments and a CASE
    expression, which previously caused ``AmbiguousParameterError`` and blocked
    the worker before extraction jobs could be claimed.

    ``error_summary`` must be a safe technical code/detail and never raw exception
    or downstream response text.

    ``retryable`` decides the terminal state of a failed attempt. Found live
    (2026-09-24): a non-retryable failure (e.g. VAC-NF-006, a stale
    requirement_ref that can never become valid again) used to be written
    back as 'PENDING' regardless -- claim_pending_audit_link's own WHERE
    clause only excludes rows that are NOT 'PENDING', so the exact same
    permanently-broken link kept getting reclaimed and retried forever
    (observed at 900+ attempts, ~15 hours, for a handful of documents).
    A non-retryable failure now writes the terminal 'FAILED' status
    instead, which claim_pending_audit_link naturally never reclaims
    again. A retryable failure keeps the existing 'PENDING' behavior.
    """
    status_expr = "CASE WHEN :ack THEN 'ACKNOWLEDGED' WHEN :retryable THEN 'PENDING' ELSE 'FAILED' END"
    await session.execute(
        text(
            f"""
            UPDATE docintel.documents
            SET audit_link_attempt_count        = audit_link_attempt_count + 1,
                audit_link_last_attempt_at_utc  = now(),
                audit_link_status               = {status_expr},
                audit_link_acknowledged_at_utc  = CASE WHEN :ack THEN now() ELSE NULL END,
                audit_link_last_error           = CASE WHEN :ack THEN NULL ELSE :error END,
                updated_at_utc                  = now()
            WHERE tenant_id       = :tenant_id
              AND document_id     = :document_id
              AND audit_link_status = 'PENDING'
            """
        ),
        {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "ack": acknowledged,
            "retryable": retryable,
            "error": (error_summary or "")[:1000] or None,
        },
    )
