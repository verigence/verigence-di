"""audit/chain.py — SHA-256 hash-chained append-only audit log.

Implements the Tenant audit chain serialisation described in
DI_LLD_v2.1.md §3 (Audit Writer) and DI_ARCHITECTURE_v2.1.md §15.

Key invariants:
- Chain-head row is locked with SELECT … FOR UPDATE before every append.
- The previous event's hash becomes the new event's previous_event_hash.
- Audit event rows are immutable (enforced by DB trigger reject_update_delete).
- Pre-Tenant WhatsApp quarantine uses the singleton system audit chain.
- Sensitive document contents are never included in audit payloads.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _canonical_payload(event_type: str, entity_type: str, entity_id: str,
                       actor_type: str, actor_id: str, tenant_id: str | None,
                       correlation_id: str | None, before_state: dict | None,
                       after_state: dict | None, metadata: dict | None,
                       occurred_at: datetime, previous_hash: str | None) -> str:
    """Produce a deterministic canonical JSON string for hashing."""
    payload = {
        "tenant_id": tenant_id,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "correlation_id": correlation_id,
        "occurred_at": occurred_at.isoformat(),
        "previous_event_hash": previous_hash,
        "before_state": before_state,
        "after_state": after_state,
        "metadata": metadata,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


async def append_tenant_audit_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_type: str,
    actor_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    correlation_id: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Append one event to the Tenant audit chain. Returns event_hash.

    Serialises concurrent appends by locking the chain-head row FOR UPDATE.
    Must be called within an open transaction that also holds RLS tenant context.
    """
    # 1. Lock chain head for this Tenant
    head_row = await session.execute(
        text(
            "SELECT last_event_hash FROM docintel.audit_chain_heads "
            "WHERE tenant_id = :tid FOR UPDATE"
        ),
        {"tid": tenant_id},
    )
    head = head_row.fetchone()
    if head is None:
        # First event for this Tenant — insert a head row
        await session.execute(
            text(
                "INSERT INTO docintel.audit_chain_heads (tenant_id, last_event_hash, last_event_at_utc) "
                "VALUES (:tid, NULL, NULL) ON CONFLICT DO NOTHING"
            ),
            {"tid": tenant_id},
        )
        previous_hash = None
    else:
        previous_hash = head[0]

    occurred_at = datetime.now(UTC)
    event_id = uuid.uuid4()

    canonical = _canonical_payload(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        before_state=before_state,
        after_state=after_state,
        metadata=metadata,
        occurred_at=occurred_at,
        previous_hash=previous_hash,
    )
    event_hash = _sha256(canonical)

    # 2. Insert immutable audit event
    await session.execute(
        text("""
            INSERT INTO docintel.audit_events (
                tenant_id, audit_event_id, actor_type, actor_id,
                event_type, entity_type, entity_id,
                occurred_at_utc, correlation_id,
                before_state, after_state, metadata,
                previous_event_hash, event_hash
            ) VALUES (
                :tenant_id, :audit_event_id, :actor_type, :actor_id,
                :event_type, :entity_type, :entity_id,
                :occurred_at, :correlation_id,
                :before_state, :after_state, :metadata,
                :previous_event_hash, :event_hash
            )
        """),
        {
            "tenant_id": tenant_id,
            "audit_event_id": str(event_id),
            "actor_type": actor_type,
            "actor_id": actor_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "occurred_at": occurred_at,
            "correlation_id": correlation_id,
            "before_state": json.dumps(before_state) if before_state else None,
            "after_state": json.dumps(after_state) if after_state else None,
            "metadata": json.dumps(metadata) if metadata else None,
            "previous_event_hash": previous_hash,
            "event_hash": event_hash,
        },
    )

    # 3. Advance chain head
    await session.execute(
        text(
            "UPDATE docintel.audit_chain_heads "
            "SET last_event_hash = :h, last_event_at_utc = :t "
            "WHERE tenant_id = :tid"
        ),
        {"h": event_hash, "t": occurred_at, "tid": tenant_id},
    )

    return event_hash
