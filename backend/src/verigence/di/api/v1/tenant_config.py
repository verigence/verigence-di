"""api/v1/tenant_config.py — Tenant Configuration + Quality Policy routes.

OAS operations (8):
  GET /v1/tenants/{tenantId}/settings                → getTenantSettings     (tenant_config:read)
  PUT /v1/tenants/{tenantId}/settings                → putTenantSettings     (tenant_config:write)
  GET /v1/tenants/{tenantId}/retention-policies      → listRetentionPolicies (tenant_config:read)
  POST /v1/tenants/{tenantId}/retention-policies     → createRetentionPolicy (tenant_config:write)
  PUT /v1/tenants/{tenantId}/retention-policies/{id} → updateRetentionPolicy (tenant_config:write)
  GET /v1/tenants/{tenantId}/quality-policy          → getQualityPolicy      (tenant_config:read)
  PUT /v1/tenants/{tenantId}/quality-policy          → putQualityPolicy      (tenant_config:write)
  GET /v1/tenants/{tenantId}/quality-rules           → listQualityRules      (tenant_config:read)
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.errors import ErrorCode, problem
from verigence.di.repositories.database import tenant_session

router = APIRouter(prefix="/v1", tags=["Tenant Configuration"])


# ── Tenant Settings ───────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/settings")
async def get_tenant_settings(
    tenant_id: str,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.TENANT_CONFIG_READ)),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT tenant_id, tenant_storage_key, timezone_name,
                           eod_retry_local_time, eod_retry_enabled,
                           classification_acceptance_score, subject_matching_min_confidence,
                           upload_timeout_minutes, max_upload_bytes, allowed_mime_types,
                           whatsapp_subject_reference_prefix, verification_threshold,
                           status, created_at_utc, updated_at_utc
                    FROM docintel.tenant_settings WHERE tenant_id = :tid
                """),
                {"tid": tenant_id},
            )
        ).mappings().one_or_none()
    if row is None:
        raise problem(404, "Tenant not found", ErrorCode.TENANT_NOT_FOUND)
    return _fmt_settings(row)


@router.put("/tenants/{tenant_id}/settings")
async def put_tenant_settings(
    tenant_id: str,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.TENANT_CONFIG_WRITE)),
) -> dict[str, Any]:
    """Upsert tenant settings."""
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        existing = (
            await session.execute(
                text("SELECT tenant_id FROM docintel.tenant_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
        ).one_or_none()

        if existing:
            await session.execute(
                text("""
                    UPDATE docintel.tenant_settings SET
                        timezone_name = COALESCE(:tz, timezone_name),
                        eod_retry_local_time = COALESCE(:eod, eod_retry_local_time),
                        eod_retry_enabled = COALESCE(:eod_en, eod_retry_enabled),
                        classification_acceptance_score = COALESCE(:cas, classification_acceptance_score),
                        subject_matching_min_confidence = COALESCE(:smc, subject_matching_min_confidence),
                        upload_timeout_minutes = COALESCE(:utm, upload_timeout_minutes),
                        max_upload_bytes = COALESCE(:mub, max_upload_bytes),
                        allowed_mime_types = COALESCE(:amt::jsonb, allowed_mime_types),
                        whatsapp_subject_reference_prefix = COALESCE(:wsp, whatsapp_subject_reference_prefix),
                        verification_threshold = COALESCE(:vt, verification_threshold),
                        updated_at_utc = :now
                    WHERE tenant_id = :tid
                """),
                {
                    "tid": tenant_id,
                    "tz": body.get("timezoneName"),
                    "eod": body.get("eodRetryLocalTime"),
                    "eod_en": body.get("eodRetryEnabled"),
                    "cas": body.get("classificationAcceptanceScore"),
                    "smc": body.get("subjectMatchingMinConfidence"),
                    "utm": body.get("uploadTimeoutMinutes"),
                    "mub": body.get("maxUploadBytes"),
                    "amt": json.dumps(body["allowedMimeTypes"]) if "allowedMimeTypes" in body else None,
                    "wsp": body.get("whatsappSubjectReferencePrefix"),
                    "vt": body.get("verificationThreshold"),
                    "now": now,
                },
            )
        else:
            # Initial upsert — create with required fields
            storage_key = uuid.uuid4()
            await session.execute(
                text("""
                    INSERT INTO docintel.tenant_settings
                        (tenant_id, tenant_storage_key, timezone_name,
                         eod_retry_local_time, eod_retry_enabled,
                         classification_acceptance_score, subject_matching_min_confidence,
                         upload_timeout_minutes, max_upload_bytes, allowed_mime_types,
                         quality_policy, whatsapp_subject_reference_prefix,
                         status, created_at_utc, updated_at_utc)
                    VALUES
                        (:tid, :sk, :tz, :eod, :eod_en, :cas, :smc,
                         :utm, :mub, :amt::jsonb,
                         '[]'::jsonb, :wsp,
                         'ACTIVE', :now, :now)
                """),
                {
                    "tid": tenant_id,
                    "sk": storage_key,
                    "tz": body.get("timezoneName", "UTC"),
                    "eod": body.get("eodRetryLocalTime", "18:00:00"),
                    "eod_en": body.get("eodRetryEnabled", True),
                    "cas": body.get("classificationAcceptanceScore", 70.0),
                    "smc": body.get("subjectMatchingMinConfidence", 90.0),
                    "utm": body.get("uploadTimeoutMinutes", 15),
                    "mub": body.get("maxUploadBytes", 31457280),
                    "amt": json.dumps(body.get("allowedMimeTypes",
                                               ["image/jpeg", "image/png", "application/pdf"])),
                    "wsp": body.get("whatsappSubjectReferencePrefix", "REF:"),
                    "now": now,
                },
            )
        await session.commit()
        row = (
            await session.execute(
                text("""
                    SELECT tenant_id, tenant_storage_key, timezone_name,
                           eod_retry_local_time, eod_retry_enabled,
                           classification_acceptance_score, subject_matching_min_confidence,
                           upload_timeout_minutes, max_upload_bytes, allowed_mime_types,
                           whatsapp_subject_reference_prefix, verification_threshold,
                           status, created_at_utc, updated_at_utc
                    FROM docintel.tenant_settings WHERE tenant_id = :tid
                """),
                {"tid": tenant_id},
            )
        ).mappings().one()
    return _fmt_settings(row)


# ── Retention Policies ────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/retention-policies")
async def list_retention_policies(
    tenant_id: str,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.TENANT_CONFIG_READ)),
) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT retention_policy_id, policy_name, retention_days,
                           disposition, active, created_at_utc, updated_at_utc
                    FROM docintel.retention_policies
                    WHERE tenant_id = :tid
                    ORDER BY created_at_utc DESC
                """),
                {"tid": tenant_id},
            )
        ).mappings().all()
    return [_fmt_retention_policy(r) for r in rows]


@router.post("/tenants/{tenant_id}/retention-policies", status_code=201)
async def create_retention_policy(
    tenant_id: str,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.TENANT_CONFIG_WRITE)),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    policy_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("""
                INSERT INTO docintel.retention_policies
                    (tenant_id, retention_policy_id, policy_name, retention_days,
                     disposition, active, created_at_utc, updated_at_utc)
                VALUES (:tid, :pid, :name, :days, :disp, :active, :now, :now)
            """),
            {
                "tid": tenant_id, "pid": policy_id,
                "name": body.get("policyName", "Default"),
                "days": body.get("retentionDays", 365),
                "disp": body.get("disposition", "KEEP_CONTENT"),
                "active": body.get("active", True),
                "now": now,
            },
        )
        await session.commit()
        row = (
            await session.execute(
                text("""
                    SELECT retention_policy_id, policy_name, retention_days,
                           disposition, active, created_at_utc, updated_at_utc
                    FROM docintel.retention_policies WHERE retention_policy_id = :pid
                """),
                {"pid": policy_id},
            )
        ).mappings().one()
    return _fmt_retention_policy(row)


@router.put("/tenants/{tenant_id}/retention-policies/{retention_policy_id}")
async def update_retention_policy(
    tenant_id: str,
    retention_policy_id: uuid.UUID,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.TENANT_CONFIG_WRITE)),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        existing = (
            await session.execute(
                text("""
                    SELECT 1 FROM docintel.retention_policies
                    WHERE tenant_id = :tid AND retention_policy_id = :pid
                """),
                {"tid": tenant_id, "pid": retention_policy_id},
            )
        ).one_or_none()
        if not existing:
            raise problem(404, "Retention Policy not found", ErrorCode.RETENTION_POLICY_NOT_FOUND)

        await session.execute(
            text("""
                UPDATE docintel.retention_policies
                SET policy_name = COALESCE(:name, policy_name),
                    retention_days = COALESCE(:days, retention_days),
                    disposition = COALESCE(:disp, disposition),
                    active = COALESCE(:active, active),
                    updated_at_utc = :now
                WHERE tenant_id = :tid AND retention_policy_id = :pid
            """),
            {
                "tid": tenant_id, "pid": retention_policy_id,
                "name": body.get("policyName"),
                "days": body.get("retentionDays"),
                "disp": body.get("disposition"),
                "active": body.get("active"),
                "now": now,
            },
        )
        await session.commit()
        row = (
            await session.execute(
                text("""
                    SELECT retention_policy_id, policy_name, retention_days,
                           disposition, active, created_at_utc, updated_at_utc
                    FROM docintel.retention_policies WHERE retention_policy_id = :pid
                """),
                {"pid": retention_policy_id},
            )
        ).mappings().one()
    return _fmt_retention_policy(row)


# ── Quality Policy ────────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/quality-policy")
async def get_quality_policy(
    tenant_id: str,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.TENANT_CONFIG_READ)),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT quality_policy FROM docintel.tenant_settings
                    WHERE tenant_id = :tid
                """),
                {"tid": tenant_id},
            )
        ).one_or_none()
    if row is None:
        raise problem(404, "Tenant not found", ErrorCode.TENANT_NOT_FOUND)
    return {"tenantId": tenant_id, "qualityPolicy": row[0] or []}


@router.put("/tenants/{tenant_id}/quality-policy")
async def put_quality_policy(
    tenant_id: str,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.TENANT_CONFIG_WRITE)),
) -> dict[str, Any]:
    """Replace the Tenant quality policy array."""
    rules: list[dict] = body.get("qualityPolicy") or []
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("""
                UPDATE docintel.tenant_settings
                SET quality_policy = :qp::jsonb, updated_at_utc = :now
                WHERE tenant_id = :tid
            """),
            {"tid": tenant_id, "qp": json.dumps(rules), "now": now},
        )
        await session.commit()
    return {"tenantId": tenant_id, "qualityPolicy": rules}


@router.get("/tenants/{tenant_id}/quality-rules")
async def list_quality_rules(
    tenant_id: str,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.TENANT_CONFIG_READ)),
) -> list[dict[str, Any]]:
    """List all active quality rules from the platform catalog."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT rule_key, description, implementation_key,
                           parameter_schema, status
                    FROM docintel.quality_rule_catalog
                    WHERE status = 'ACTIVE'
                    ORDER BY rule_key
                """),
            )
        ).mappings().all()
    return [
        {
            "ruleKey": r["rule_key"],
            "description": r["description"],
            "implementationKey": r["implementation_key"],
            "parameterSchema": r["parameter_schema"],
            "status": r["status"],
        }
        for r in rows
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_settings(r: Any) -> dict[str, Any]:
    return {
        "tenantId": r["tenant_id"],
        "tenantStorageKey": str(r["tenant_storage_key"]),
        "timezoneName": r["timezone_name"],
        "eodRetryLocalTime": str(r["eod_retry_local_time"]),
        "eodRetryEnabled": r["eod_retry_enabled"],
        "classificationAcceptanceScore": float(r["classification_acceptance_score"]),
        "subjectMatchingMinConfidence": float(r["subject_matching_min_confidence"]),
        "uploadTimeoutMinutes": r["upload_timeout_minutes"],
        "maxUploadBytes": r["max_upload_bytes"],
        "allowedMimeTypes": r["allowed_mime_types"],
        "whatsappSubjectReferencePrefix": r["whatsapp_subject_reference_prefix"],
        "verificationThreshold": float(r["verification_threshold"]) if r.get("verification_threshold") is not None else None,
        "status": r["status"],
        "createdAt": r["created_at_utc"].isoformat() if r.get("created_at_utc") else None,
        "updatedAt": r["updated_at_utc"].isoformat() if r.get("updated_at_utc") else None,
    }


def _fmt_retention_policy(r: Any) -> dict[str, Any]:
    return {
        "retentionPolicyId": str(r["retention_policy_id"]),
        "policyName": r["policy_name"],
        "retentionDays": r["retention_days"],
        "disposition": r["disposition"],
        "active": r["active"],
        "createdAt": r["created_at_utc"].isoformat() if r.get("created_at_utc") else None,
        "updatedAt": r["updated_at_utc"].isoformat() if r.get("updated_at_utc") else None,
    }
