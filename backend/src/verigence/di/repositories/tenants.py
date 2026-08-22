"""repositories/tenants.py — Tenant provisioning."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_DEFAULT_CLASSIFICATION_SCORE = 70.00
_DEFAULT_SUBJECT_MATCHING_CONFIDENCE = 80.00
_DEFAULT_UPLOAD_TIMEOUT_MINUTES = 30
_DEFAULT_MAX_UPLOAD_BYTES = 31_457_280
_DEFAULT_ALLOWED_MIME_TYPES = '["application/pdf","image/jpeg","image/png","image/tiff"]'
_DEFAULT_QUALITY_POLICY = '[]'
_ALLOWED_ACTOR_TYPES = frozenset({"USER", "SYSTEM", "SERVICE"})


async def provision_tenant(session: AsyncSession, tenant_id: str) -> None:
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.tenant_settings (
                tenant_id, tenant_storage_key, timezone_name,
                eod_retry_local_time, eod_retry_enabled,
                classification_acceptance_score, subject_matching_min_confidence,
                upload_timeout_minutes, max_upload_bytes, allowed_mime_types,
                quality_policy, whatsapp_subject_reference_prefix, status,
                created_at_utc, updated_at_utc
            ) VALUES (
                :tenant_id, :storage_key, 'UTC', '23:00:00', true,
                :classification_score, :matching_confidence,
                :upload_timeout, :max_bytes, CAST(:mime_types AS jsonb),
                CAST(:quality_policy AS jsonb), '', 'ACTIVE', :now, :now
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
    now = datetime.now(UTC)
    policy_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO docintel.retention_policies
                (tenant_id, retention_policy_id, policy_key, display_name,
                 retention_days, disposition, status, created_at_utc, updated_at_utc)
            VALUES
                (:tenant_id, :policy_id, 'default', 'Default 1-Year Retention',
                 365, 'PURGE_CONTENT', 'ACTIVE', :now, :now)
            ON CONFLICT (tenant_id, policy_key) DO NOTHING
        """),
        {"tenant_id": tenant_id, "policy_id": policy_id, "now": now},
    )
    row = (
        await session.execute(
            text("""
                SELECT rp.retention_policy_id
                FROM docintel.retention_policies rp
                WHERE rp.tenant_id = :tenant_id AND rp.status = 'ACTIVE'
                LIMIT 1
            """),
            {"tenant_id": tenant_id},
        )
    ).one_or_none()
    actual_id = row[0] if row else policy_id
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


async def provision_tenant_document_types(
    session: AsyncSession,
    tenant_id: str,
) -> None:
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.tenant_document_types
                (tenant_id, document_type_id, physical_form_type,
                 requires_processing, is_active, display_order,
                 created_at_utc, updated_at_utc)
            SELECT
                :tenant_id, dt.document_type_id,
                COALESCE(dt.category, 'ADDITIONAL'), true, true, 100, :now, :now
            FROM docintel.document_types dt
            WHERE dt.owner_tenant_id IS NULL
              AND dt.status = 'ACTIVE'
            ON CONFLICT (tenant_id, document_type_id) DO NOTHING
        """),
        {"tenant_id": tenant_id, "now": now},
    )


async def provision_actor(
    session: AsyncSession,
    tenant_id: str,
    actor_id: str,
    actor_type: str = "USER",
) -> None:
    """Ensure the exact DI actor classification exists.

    Security's external claim `SERVICE_INTEGRATION` maps to DI's existing internal
    actor type `SERVICE`; callers pass the mapped internal value here.
    """
    normalized_type = actor_type.strip().upper()
    if normalized_type not in _ALLOWED_ACTOR_TYPES:
        raise ValueError(f"Unsupported DI actor type: {actor_type}")
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.actors
                (tenant_id, actor_id, actor_type, display_name,
                 status, created_at_utc, updated_at_utc)
            VALUES
                (:tenant_id, :actor_id, :actor_type, :display_name,
                 'ACTIVE', :now, :now)
            ON CONFLICT (tenant_id, actor_id) DO UPDATE
            SET actor_type = EXCLUDED.actor_type,
                status = 'ACTIVE',
                updated_at_utc = EXCLUDED.updated_at_utc
            WHERE docintel.actors.actor_type = EXCLUDED.actor_type
        """),
        {
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "actor_type": normalized_type,
            "display_name": actor_id,
            "now": now,
        },
    )
