"""api/v1/requirement_profiles.py — Requirement Profile + Subject assignment routes.

OAS operations (6):
  GET  /v1/tenants/{tenantId}/document-requirement-profiles
       → listRequirementProfiles        (requirement_profile:read)
  POST /v1/tenants/{tenantId}/document-requirement-profiles
       → createRequirementProfile       (requirement_profile:write)
  GET  /v1/tenants/{tenantId}/document-requirement-profiles/{profileId}
       → getRequirementProfile          (requirement_profile:read)
  PUT  /v1/tenants/{tenantId}/document-requirement-profiles/{profileId}
       → updateDraftRequirementProfile  (requirement_profile:write)
  POST /v1/tenants/{tenantId}/document-requirement-profiles/{profileId}/publish
       → publishRequirementProfile      (requirement_profile:publish)
  PUT  /v1/tenants/{tenantId}/subjects/{subjectId}/requirement-profile
       → assignRequirementProfile       (requirement_profile:assign)
"""
from __future__ import annotations

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

router = APIRouter(prefix="/v1", tags=["Requirement Configuration"])


# ── GET /v1/tenants/{tenantId}/document-requirement-profiles ─────────────────

@router.get("/tenants/{tenant_id}/document-requirement-profiles")
async def list_requirement_profiles(
    tenant_id: str,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.REQUIREMENT_PROFILE_READ)
    ),
) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT requirement_profile_id, profile_key, version_no,
                           description, status,
                           created_by_actor_id, published_by_actor_id,
                           created_at_utc, published_at_utc, updated_at_utc
                    FROM docintel.document_requirement_profiles
                    WHERE tenant_id = :tid
                    ORDER BY profile_key, version_no DESC
                """),
                {"tid": tenant_id},
            )
        ).mappings().all()
    return [_fmt_profile(r) for r in rows]


# ── POST /v1/tenants/{tenantId}/document-requirement-profiles ─────────────────

@router.post("/tenants/{tenant_id}/document-requirement-profiles", status_code=201)
async def create_requirement_profile(
    tenant_id: str,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.REQUIREMENT_PROFILE_WRITE)
    ),
) -> dict[str, Any]:
    """Create a DRAFT Requirement Profile version."""
    profile_key: str = body.get("profileKey", "")
    description: str | None = body.get("description")
    items: list[dict] = body.get("items") or []
    if not profile_key:
        raise problem(422, "profileKey is required", ErrorCode.VALIDATION_ERROR)

    now = datetime.now(UTC)
    profile_id = uuid.uuid4()

    async with tenant_session(tenant_id) as session:
        # Next version_no for this profile_key
        ver_row = (
            await session.execute(
                text("""
                    SELECT COALESCE(MAX(version_no), 0) + 1
                    FROM docintel.document_requirement_profiles
                    WHERE tenant_id = :tid AND profile_key = :key
                """),
                {"tid": tenant_id, "key": profile_key},
            )
        ).scalar()

        await session.execute(
            text("""
                INSERT INTO docintel.document_requirement_profiles
                    (tenant_id, requirement_profile_id, profile_key, version_no,
                     description, status, created_by_actor_id,
                     created_at_utc, updated_at_utc)
                VALUES (:tid, :pid, :key, :ver, :desc, 'DRAFT', :actor_id, :now, :now)
            """),
            {
                "tid": tenant_id, "pid": profile_id, "key": profile_key,
                "ver": ver_row or 1, "desc": description,
                "actor_id": actor.actor_id, "now": now,
            },
        )

        # Insert items
        for item in items:
            await session.execute(
                text("""
                    INSERT INTO docintel.document_requirement_profile_items
                        (tenant_id, requirement_item_id, requirement_profile_id,
                         document_type_id, requirement_classification,
                         minimum_count, display_sequence, enabled, created_at_utc)
                    VALUES (:tid, :iid, :pid, :dtid, :cls, :min_cnt, :seq, true, :now)
                """),
                {
                    "tid": tenant_id,
                    "iid": uuid.uuid4(),
                    "pid": profile_id,
                    "dtid": item.get("documentTypeId"),
                    "cls": item.get("requirementClassification", "MANDATORY"),
                    "min_cnt": item.get("minimumCount", 1),
                    "seq": item.get("displaySequence", 100),
                    "now": now,
                },
            )
        await session.commit()

        profile_row = (
            await session.execute(
                text("""
                    SELECT requirement_profile_id, profile_key, version_no,
                           description, status, created_by_actor_id, published_by_actor_id,
                           created_at_utc, published_at_utc, updated_at_utc
                    FROM docintel.document_requirement_profiles
                    WHERE tenant_id = :tid AND requirement_profile_id = :pid
                """),
                {"tid": tenant_id, "pid": profile_id},
            )
        ).mappings().one()
    return _fmt_profile(profile_row)


# ── GET /v1/tenants/{tenantId}/document-requirement-profiles/{profileId} ──────

@router.get("/tenants/{tenant_id}/document-requirement-profiles/{profile_id}")
async def get_requirement_profile(
    tenant_id: str,
    profile_id: uuid.UUID,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.REQUIREMENT_PROFILE_READ)
    ),
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT requirement_profile_id, profile_key, version_no,
                           description, status, created_by_actor_id, published_by_actor_id,
                           created_at_utc, published_at_utc, updated_at_utc
                    FROM docintel.document_requirement_profiles
                    WHERE tenant_id = :tid AND requirement_profile_id = :pid
                """),
                {"tid": tenant_id, "pid": profile_id},
            )
        ).mappings().one_or_none()
    if row is None:
        raise problem(404, "Requirement Profile not found",
                      ErrorCode.REQUIREMENT_PROFILE_NOT_FOUND)
    return _fmt_profile(row)


# ── PUT /v1/tenants/{tenantId}/document-requirement-profiles/{profileId} ──────

@router.put("/tenants/{tenant_id}/document-requirement-profiles/{profile_id}")
async def update_draft_requirement_profile(
    tenant_id: str,
    profile_id: uuid.UUID,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.REQUIREMENT_PROFILE_WRITE)
    ),
) -> dict[str, Any]:
    """Replace contents of a DRAFT Requirement Profile version."""
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT status FROM docintel.document_requirement_profiles
                    WHERE tenant_id = :tid AND requirement_profile_id = :pid
                """),
                {"tid": tenant_id, "pid": profile_id},
            )
        ).one_or_none()
        if row is None:
            raise problem(404, "Requirement Profile not found",
                          ErrorCode.REQUIREMENT_PROFILE_NOT_FOUND)
        if row[0] != "DRAFT":
            raise problem(409, "Only DRAFT profiles may be updated",
                          ErrorCode.INVALID_PROFILE_STATE)

        description: str | None = body.get("description")
        await session.execute(
            text("""
                UPDATE docintel.document_requirement_profiles
                SET description = :desc, updated_at_utc = :now
                WHERE tenant_id = :tid AND requirement_profile_id = :pid
            """),
            {"tid": tenant_id, "pid": profile_id, "desc": description, "now": now},
        )
        await session.commit()
        updated = (
            await session.execute(
                text("""
                    SELECT requirement_profile_id, profile_key, version_no,
                           description, status, created_by_actor_id, published_by_actor_id,
                           created_at_utc, published_at_utc, updated_at_utc
                    FROM docintel.document_requirement_profiles
                    WHERE tenant_id = :tid AND requirement_profile_id = :pid
                """),
                {"tid": tenant_id, "pid": profile_id},
            )
        ).mappings().one()
    return _fmt_profile(updated)


# ── POST /v1/tenants/{tenantId}/document-requirement-profiles/{profileId}/publish

@router.post(
    "/tenants/{tenant_id}/document-requirement-profiles/{profile_id}/publish"
)
async def publish_requirement_profile(
    tenant_id: str,
    profile_id: uuid.UUID,
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.REQUIREMENT_PROFILE_PUBLISH)
    ),
) -> dict[str, Any]:
    """Publish DRAFT; atomically retire previous PUBLISHED of the same profileKey."""
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT status, profile_key FROM docintel.document_requirement_profiles
                    WHERE tenant_id = :tid AND requirement_profile_id = :pid
                """),
                {"tid": tenant_id, "pid": profile_id},
            )
        ).one_or_none()
        if row is None:
            raise problem(404, "Requirement Profile not found",
                          ErrorCode.REQUIREMENT_PROFILE_NOT_FOUND)
        if row[0] != "DRAFT":
            raise problem(409, "Only DRAFT profiles may be published",
                          ErrorCode.INVALID_PROFILE_STATE)
        profile_key = row[1]

        # Retire any existing PUBLISHED version of the same key
        await session.execute(
            text("""
                UPDATE docintel.document_requirement_profiles
                SET status = 'RETIRED', updated_at_utc = :now
                WHERE tenant_id = :tid AND profile_key = :key AND status = 'PUBLISHED'
            """),
            {"tid": tenant_id, "key": profile_key, "now": now},
        )
        await session.execute(
            text("""
                UPDATE docintel.document_requirement_profiles
                SET status = 'PUBLISHED',
                    published_by_actor_id = :actor_id,
                    published_at_utc = :now,
                    updated_at_utc = :now
                WHERE tenant_id = :tid AND requirement_profile_id = :pid
            """),
            {"tid": tenant_id, "pid": profile_id,
             "actor_id": actor.actor_id, "now": now},
        )
        await session.commit()
        updated = (
            await session.execute(
                text("""
                    SELECT requirement_profile_id, profile_key, version_no,
                           description, status, created_by_actor_id, published_by_actor_id,
                           created_at_utc, published_at_utc, updated_at_utc
                    FROM docintel.document_requirement_profiles
                    WHERE tenant_id = :tid AND requirement_profile_id = :pid
                """),
                {"tid": tenant_id, "pid": profile_id},
            )
        ).mappings().one()
    return _fmt_profile(updated)


# ── PUT /v1/tenants/{tenantId}/subjects/{subjectId}/requirement-profile ───────

@router.put("/tenants/{tenant_id}/subjects/{subject_id}/requirement-profile")
async def assign_requirement_profile(
    tenant_id: str,
    subject_id: uuid.UUID,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(
        require_tenant_permission(Permission.REQUIREMENT_PROFILE_ASSIGN)
    ),
) -> dict[str, Any]:
    """Assign one PUBLISHED Requirement Profile version to a Subject."""
    profile_id_str: str | None = body.get("requirementProfileId")
    if not profile_id_str:
        raise problem(422, "requirementProfileId is required", ErrorCode.VALIDATION_ERROR)
    req_profile_id = uuid.UUID(profile_id_str)
    now = datetime.now(UTC)

    async with tenant_session(tenant_id) as session:
        # Verify profile is PUBLISHED
        prof_row = (
            await session.execute(
                text("""
                    SELECT status FROM docintel.document_requirement_profiles
                    WHERE tenant_id = :tid AND requirement_profile_id = :pid
                """),
                {"tid": tenant_id, "pid": req_profile_id},
            )
        ).one_or_none()
        if prof_row is None or prof_row[0] != "PUBLISHED":
            raise problem(404, "Published Requirement Profile not found",
                          ErrorCode.REQUIREMENT_PROFILE_NOT_FOUND)

        # Deactivate current assignment
        await session.execute(
            text("""
                UPDATE docintel.subject_requirement_profile_assignments
                SET status = 'SUPERSEDED', updated_at_utc = :now
                WHERE tenant_id = :tid AND subject_id = :sid AND status = 'ACTIVE'
            """),
            {"tid": tenant_id, "sid": subject_id, "now": now},
        )
        assignment_id = uuid.uuid4()
        await session.execute(
            text("""
                INSERT INTO docintel.subject_requirement_profile_assignments
                    (tenant_id, assignment_id, subject_id, requirement_profile_id,
                     assigned_by_actor_id, status, created_at_utc, updated_at_utc)
                VALUES (:tid, :aid, :sid, :pid, :actor_id, 'ACTIVE', :now, :now)
            """),
            {
                "tid": tenant_id, "aid": assignment_id,
                "sid": subject_id, "pid": req_profile_id,
                "actor_id": actor.actor_id, "now": now,
            },
        )
        await session.commit()

    return {
        "assignmentId": str(assignment_id),
        "subjectId": str(subject_id),
        "requirementProfileId": str(req_profile_id),
        "assignedByActorId": actor.actor_id,
        "status": "ACTIVE",
        "assignedAt": now.isoformat(),
    }


def _fmt_profile(r: Any) -> dict[str, Any]:
    return {
        "requirementProfileId": str(r["requirement_profile_id"]),
        "profileKey": r["profile_key"],
        "versionNo": r["version_no"],
        "description": r.get("description"),
        "status": r["status"],
        "createdByActorId": r["created_by_actor_id"],
        "publishedByActorId": r.get("published_by_actor_id"),
        "createdAt": r["created_at_utc"].isoformat() if r.get("created_at_utc") else None,
        "publishedAt": r["published_at_utc"].isoformat() if r.get("published_at_utc") else None,
        "updatedAt": r["updated_at_utc"].isoformat() if r.get("updated_at_utc") else None,
    }
