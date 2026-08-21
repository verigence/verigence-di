"""UC02 trusted Audit Core storage context repository."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_audit_storage_context(
    session: AsyncSession,
    *,
    tenant_id: str,
    dealer_id: uuid.UUID,
    outlet_id: uuid.UUID,
    customer_id: uuid.UUID,
    subject_id: uuid.UUID,
    actor_id: str,
    dealer_display_name: str | None = None,
    outlet_display_name: str | None = None,
    customer_display_name: str | None = None,
) -> dict[str, object]:
    """Create/update the trusted context for one Audit Core Customer.

    Immutable IDs are authoritative. Display names are readability metadata only;
    changing them does not change historical object keys already persisted.
    """
    now = datetime.now(UTC)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO docintel.audit_storage_contexts (
                    tenant_id, dealer_id, outlet_id, customer_id, subject_id,
                    dealer_display_name, outlet_display_name, customer_display_name,
                    status, created_by_actor_id, created_at_utc, updated_at_utc
                ) VALUES (
                    :tenant_id, :dealer_id, :outlet_id, :customer_id, :subject_id,
                    :dealer_name, :outlet_name, :customer_name,
                    'ACTIVE', :actor_id, :now, :now
                )
                ON CONFLICT (tenant_id, customer_id) DO UPDATE
                SET dealer_id=EXCLUDED.dealer_id,
                    outlet_id=EXCLUDED.outlet_id,
                    subject_id=EXCLUDED.subject_id,
                    dealer_display_name=EXCLUDED.dealer_display_name,
                    outlet_display_name=EXCLUDED.outlet_display_name,
                    customer_display_name=EXCLUDED.customer_display_name,
                    status='ACTIVE',
                    updated_at_utc=EXCLUDED.updated_at_utc
                RETURNING context_id, tenant_id, dealer_id, outlet_id, customer_id,
                          subject_id, dealer_display_name, outlet_display_name,
                          customer_display_name, status, created_at_utc, updated_at_utc
                """
            ),
            {
                "tenant_id": tenant_id,
                "dealer_id": dealer_id,
                "outlet_id": outlet_id,
                "customer_id": customer_id,
                "subject_id": subject_id,
                "dealer_name": dealer_display_name,
                "outlet_name": outlet_display_name,
                "customer_name": customer_display_name,
                "actor_id": actor_id,
                "now": now,
            },
        )
    ).mappings().one()
    return dict(row)


async def get_audit_storage_context(
    session: AsyncSession,
    *,
    tenant_id: str,
    context_id: uuid.UUID,
) -> dict[str, object] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT context_id, tenant_id, dealer_id, outlet_id, customer_id,
                       subject_id, dealer_display_name, outlet_display_name,
                       customer_display_name, status, created_at_utc, updated_at_utc
                FROM docintel.audit_storage_contexts
                WHERE tenant_id=:tenant_id AND context_id=:context_id
                """
            ),
            {"tenant_id": tenant_id, "context_id": context_id},
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None
