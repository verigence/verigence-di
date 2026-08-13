"""repositories/tenants.py — Tenant provisioning.

Every tenant must have a row in docintel.tenant_settings before any
other table can reference that tenant_id (FK constraint).

provision_tenant() is an upsert — safe to call on every request.
It does nothing if the row already exists (ON CONFLICT DO NOTHING).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Sensible system defaults for auto-provisioned tenants
_DEFAULT_CLASSIFICATION_SCORE = 70.00
_DEFAULT_SUBJECT_MATCHING_CONFIDENCE = 80.00
_DEFAULT_UPLOAD_TIMEOUT_MINUTES = 30
_DEFAULT_MAX_UPLOAD_BYTES = 31_457_280   # 30 MB
_DEFAULT_ALLOWED_MIME_TYPES = '["application/pdf","image/jpeg","image/png","image/tiff"]'
_DEFAULT_QUALITY_POLICY = '[]'


async def provision_tenant(session: AsyncSession, tenant_id: str) -> None:
    """Ensure a tenant_settings row exists for tenant_id.

    Uses ON CONFLICT DO NOTHING so it is safe to call on every request
    without performance impact after the first call.
    """
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.tenant_settings (
                tenant_id,
                tenant_storage_key,
                timezone_name,
                eod_retry_local_time,
                eod_retry_enabled,
                classification_acceptance_score,
                subject_matching_min_confidence,
                upload_timeout_minutes,
                max_upload_bytes,
                allowed_mime_types,
                quality_policy,
                whatsapp_subject_reference_prefix,
                status,
                created_at_utc,
                updated_at_utc
            ) VALUES (
                :tenant_id,
                :storage_key,
                'UTC',
                '23:00:00',
                true,
                :classification_score,
                :matching_confidence,
                :upload_timeout,
                :max_bytes,
                CAST(:mime_types AS jsonb),
                CAST(:quality_policy AS jsonb),
                '',
                'ACTIVE',
                :now,
                :now
            )
            ON CONFLICT (tenant_id) DO NOTHING
        """),
        {
            "tenant_id": tenant_id,
            "storage_key": uuid.uuid4(),
            "classification_score": _DEFAULT_CLASSIFICATION_SCORE,
            "matching_confidence": _DEFAULT_SUBJECT_MATCHING_CONFIDENCE,
            "upload_timeout": _DEFAULT_UPLOAD_TIMEOUT_MINUTES,
            "max_bytes": _DEFAULT_MAX_UPLOAD_BYTES,
            "mime_types": _DEFAULT_ALLOWED_MIME_TYPES,
            "quality_policy": _DEFAULT_QUALITY_POLICY,
            "now": now,
        },
    )


async def provision_retention_policy(
    session: AsyncSession,
    tenant_id: str,
) -> uuid.UUID:
    """Ensure a default retention policy exists for tenant_id and link it.

    Creates a default 7-year retention policy and sets it as the active
    policy on tenant_settings. Safe to call multiple times.
    Returns the retention_policy_id.
    """
    now = datetime.now(UTC)
    policy_id = uuid.uuid4()

    # Insert default retention policy (ON CONFLICT DO NOTHING)
    await session.execute(
        text("""
            INSERT INTO docintel.retention_policies
                (tenant_id, retention_policy_id, policy_key, display_name,
                 retention_days, disposition, status, created_at_utc, updated_at_utc)
            VALUES
                (:tenant_id, :policy_id, 'default', 'Default 1-Year Retention',
                 365, 'DELETE', 'ACTIVE', :now, :now)
            ON CONFLICT (tenant_id, retention_policy_id) DO NOTHING
        """),
        {"tenant_id": tenant_id, "policy_id": policy_id, "now": now},
    )

    # Get the actual active policy_id (may already exist from a previous call)
    row = (await session.execute(
        text("""
            SELECT rp.retention_policy_id
            FROM docintel.retention_policies rp
            WHERE rp.tenant_id = :tenant_id AND rp.status = 'ACTIVE'
            LIMIT 1
        """),
        {"tenant_id": tenant_id},
    )).one_or_none()

    actual_id = row[0] if row else policy_id

    # Link to tenant_settings if not already linked
    await session.execute(
        text("""
            UPDATE docintel.tenant_settings
            SET active_retention_policy_id = :policy_id,
                updated_at_utc = :now
            WHERE tenant_id = :tenant_id
              AND active_retention_policy_id IS NULL
        """),
        {"tenant_id": tenant_id, "policy_id": actual_id, "now": now},
    )

    return actual_id


async def provision_actor(
    session: AsyncSession,
    tenant_id: str,
    actor_id: str,
) -> None:
    """Ensure an actor row exists for (tenant_id, actor_id).

    Called automatically before any write that references created_by_actor_id.
    Safe to call multiple times (ON CONFLICT DO NOTHING).
    """
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.actors
                (tenant_id, actor_id, actor_type, display_name,
                 status, created_at_utc, updated_at_utc)
            VALUES
                (:tenant_id, :actor_id, 'USER', :display_name,
                 'ACTIVE', :now, :now)
            ON CONFLICT (tenant_id, actor_id) DO NOTHING
        """),
        {
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "display_name": actor_id,
            "now": now,
        },
    )
