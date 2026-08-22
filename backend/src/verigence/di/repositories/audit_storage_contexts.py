"""UC02 trusted Audit Core storage context repository."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AuditStorageContextConflict(ValueError):
    """An immutable external context reference was reused with conflicting IDs."""


async def ensure_audit_storage_context(
    session: AsyncSession,
    *,
    tenant_id: str,
    external_context_ref: str,
    dealer_id: uuid.UUID,
    dealer_outlet_id: uuid.UUID,
    customer_id: uuid.UUID,
    subject_id: uuid.UUID,
    service_principal_id: str,
    project_slug: str,
    dealer_slug: str,
    dealer_outlet_slug: str,
    customer_slug: str,
) -> dict[str, object]:
    """Create or return the immutable context identified by external_context_ref."""
    existing = await get_audit_storage_context_by_ref(
        session,
        tenant_id=tenant_id,
        external_context_ref=external_context_ref,
    )
    if existing is not None:
        immutable_values = {
            "subject_id": subject_id,
            "dealer_id": dealer_id,
            "dealer_outlet_id": dealer_outlet_id,
            "customer_id": customer_id,
        }
        if any(existing[key] != value for key, value in immutable_values.items()):
            raise AuditStorageContextConflict(
                "externalContextRef already identifies a different Audit business context"
            )
        return existing

    now = datetime.now(UTC)
    row = (
        await session.execute(
            text(
                """
                INSERT INTO docintel.audit_storage_contexts (
                    tenant_id, external_context_ref, subject_id,
                    dealer_id, dealer_outlet_id, customer_id,
                    project_slug, dealer_slug, dealer_outlet_slug, customer_slug,
                    created_by_service_principal, created_at_utc
                ) VALUES (
                    :tenant_id, :external_context_ref, :subject_id,
                    :dealer_id, :dealer_outlet_id, :customer_id,
                    :project_slug, :dealer_slug, :dealer_outlet_slug, :customer_slug,
                    :service_principal_id, :now
                )
                RETURNING storage_context_id, tenant_id, external_context_ref,
                          subject_id, dealer_id, dealer_outlet_id, customer_id,
                          project_slug, dealer_slug, dealer_outlet_slug, customer_slug,
                          created_by_service_principal, created_at_utc
                """
            ),
            {
                "tenant_id": tenant_id,
                "external_context_ref": external_context_ref,
                "subject_id": subject_id,
                "dealer_id": dealer_id,
                "dealer_outlet_id": dealer_outlet_id,
                "customer_id": customer_id,
                "project_slug": project_slug,
                "dealer_slug": dealer_slug,
                "dealer_outlet_slug": dealer_outlet_slug,
                "customer_slug": customer_slug,
                "service_principal_id": service_principal_id,
                "now": now,
            },
        )
    ).mappings().one()
    return dict(row)


async def get_audit_storage_context(
    session: AsyncSession,
    *,
    tenant_id: str,
    storage_context_id: uuid.UUID,
) -> dict[str, object] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT storage_context_id, tenant_id, external_context_ref,
                       subject_id, dealer_id, dealer_outlet_id, customer_id,
                       project_slug, dealer_slug, dealer_outlet_slug, customer_slug,
                       created_by_service_principal, created_at_utc
                FROM docintel.audit_storage_contexts
                WHERE tenant_id=:tenant_id
                  AND storage_context_id=:storage_context_id
                """
            ),
            {"tenant_id": tenant_id, "storage_context_id": storage_context_id},
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
                SELECT storage_context_id, tenant_id, external_context_ref,
                       subject_id, dealer_id, dealer_outlet_id, customer_id,
                       project_slug, dealer_slug, dealer_outlet_slug, customer_slug,
                       created_by_service_principal, created_at_utc
                FROM docintel.audit_storage_contexts
                WHERE tenant_id=:tenant_id
                  AND external_context_ref=:external_context_ref
                """
            ),
            {"tenant_id": tenant_id, "external_context_ref": external_context_ref},
        )
    ).mappings().one_or_none()
    return dict(row) if row is not None else None
