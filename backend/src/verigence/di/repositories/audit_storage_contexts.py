"""UC02 trusted Audit Core storage context repository."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_audit_storage_context(
    session: AsyncSession,
    *,
    tenant_id: str,
    external_context_ref: str,
    subject_id: uuid.UUID,
    dealer_id: uuid.UUID,
    outlet_id: uuid.UUID,
    customer_id: uuid.UUID,
    actor_id: str,
    project_display_name: str | None = None,
    dealer_display_name: str | None = None,
    outlet_display_name: str | None = None,
    customer_display_name: str | None = None,
) -> tuple[dict[str, object], bool]:
    """Create one immutable Audit storage context or return the identical context.

    D28 makes ``external_context_ref`` the idempotent identity. Immutable business
    IDs and frozen display metadata are never rewritten after creation.
    """
    existing = await get_audit_storage_context_by_ref(
        session,
        tenant_id=tenant_id,
        external_context_ref=external_context_ref,
    )
    if existing is not None:
        immutable = {
            "subject_id": subject_id,
            "dealer_id": dealer_id,
            "outlet_id": outlet_id,
            "customer_id": customer_id,
        }
        if any(existing[key] != value for key, value in immutable.items()):
            raise ValueError("Audit storage context reference conflicts with immutable IDs")
        return existing, False

    now = datetime.now(UTC)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO docintel.audit_storage_contexts (
                    tenant_id, external_context_ref, subject_id,
                    dealer_id, outlet_id, customer_id,
                    project_display_name, dealer_display_name,
                    outlet_display_name, customer_display_name,
                    status, created_by_actor_id, created_at_utc, updated_at_utc
                ) VALUES (
                    :tenant_id, :external_context_ref, :subject_id,
                    :dealer_id, :outlet_id, :customer_id,
                    :project_name, :dealer_name, :outlet_name, :customer_name,
                    'ACTIVE', :actor_id, :now, :now
                )
                RETURNING context_id, tenant_id, external_context_ref, subject_id,
                          dealer_id, outlet_id, customer_id,
                          project_display_name, dealer_display_name,
                          outlet_display_name, customer_display_name,
                          status, created_at_utc, updated_at_utc
                """
            ),
            {
                "tenant_id": tenant_id,
                "external_context_ref": external_context_ref,
                "subject_id": subject_id,
                "dealer_id": dealer_id,
                "outlet_id": outlet_id,
                "customer_id": customer_id,
                "project_name": project_display_name,
                "dealer_name": dealer_display_name,
                "outlet_name": outlet_display_name,
                "customer_name": customer_display_name,
                "actor_id": actor_id,
                "now": now,
            },
        )
    ).mappings().one()
    return dict(row), True


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
                SELECT context_id, tenant_id, external_context_ref, subject_id,
                       dealer_id, outlet_id, customer_id,
                       project_display_name, dealer_display_name,
                       outlet_display_name, customer_display_name,
                       status, created_at_utc, updated_at_utc
                FROM docintel.audit_storage_contexts
                WHERE tenant_id=:tenant_id AND context_id=:context_id
                """
            ),
            {"tenant_id": tenant_id, "context_id": context_id},
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


async def get_audit_storage_context_by_ref(
    session: AsyncSession,
    *,
    tenant_id: str,
    external_context_ref: str,
) -> dict[str, object] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT context_id, tenant_id, external_context_ref, subject_id,
                       dealer_id, outlet_id, customer_id,
                       project_display_name, dealer_display_name,
                       outlet_display_name, customer_display_name,
                       status, created_at_utc, updated_at_utc
                FROM docintel.audit_storage_contexts
                WHERE tenant_id=:tenant_id
                  AND external_context_ref=:external_context_ref
                  AND status='ACTIVE'
                """
            ),
            {
                "tenant_id": tenant_id,
                "external_context_ref": external_context_ref,
            },
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None
