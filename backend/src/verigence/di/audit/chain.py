"""audit/chain.py — Entity-scoped SHA-256 hash-chain audit log (Baseline 2.2).

v2.2 change (DI_AUDIT_MODEL_v2.2.md §2):
  audit_chain_heads PK = (tenant_id, entity_type, entity_id)

Each audited entity has its own chain head row. Concurrent writes to
DIFFERENT entities in the same Tenant proceed without serialising on
one row lock. Concurrent writes to the SAME entity still serialize
(correct — tamper evidence is per-entity).

Entity type examples (DI_AUDIT_MODEL_v2.2.md §2):
  DOCUMENT, SUBJECT, EXTRACTION_PROFILE, REQUIREMENT_PROFILE, TENANT
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _canonical_payload(
    event_type: str,
    entity_type: str,
    entity_id: str,
    actor_type: str,
    actor_id: str,
    tenant_id: str | None,
    correlation_id: str | None,
    before_state: dict | None,
    after_state: dict | None,
    metadata: dict | None,
    occurred_at: datetime,
    previous_hash: str | None,
) -> str:
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
    """Append one event to the entity-scoped Tenant audit chain.

    Returns event_hash.

    Serialises concurrent writes to the same (tenant_id, entity_type, entity_id)
    via SELECT FOR UPDATE. Writes to different entities proceed concurrently.
    Must be called within an open transaction that also holds RLS tenant context.
    """
    # 1. Upsert entity chain head (no-op if row already exists), then lock it
    await session.execute(
        text("""
            INSERT INTO docintel.audit_chain_heads
                (tenant_id, entity_type, entity_id, last_event_hash, updated_at_utc)
            VALUES (:tid, :etype, :eid, NULL, :now)
            ON CONFLICT (tenant_id, entity_type, entity_id) DO NOTHING
        """),
        {
            "tid": tenant_id,
            "etype": entity_type,
            "eid": entity_id,
            "now": datetime.now(UTC),
        },
    )

    head_row = await session.execute(
        text("""
            SELECT last_event_hash
            FROM docintel.audit_chain_heads
            WHERE tenant_id = :tid
              AND entity_type = :etype
              AND entity_id   = :eid
            FOR UPDATE
        """),
        {"tid": tenant_id, "etype": entity_type, "eid": entity_id},
    )
    head = head_row.fetchone()
    previous_hash: str | None = head[0] if head else None

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

    # 2. Insert immutable audit event (with entity columns added in migration 0002)
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

    # 3. Advance entity chain head
    await session.execute(
        text("""
            UPDATE docintel.audit_chain_heads
            SET last_event_hash = :h,
                updated_at_utc  = :t
            WHERE tenant_id  = :tid
              AND entity_type = :etype
              AND entity_id   = :eid
        """),
        {
            "h": event_hash,
            "t": occurred_at,
            "tid": tenant_id,
            "etype": entity_type,
            "eid": entity_id,
        },
    )

    return event_hash
