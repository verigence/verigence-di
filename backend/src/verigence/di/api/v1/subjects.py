"""api/v1/subjects.py — Subject Registry REST endpoints.

Implements:
  POST   /v1/tenants/{tenantId}/subjects            createSubject
  GET    /v1/tenants/{tenantId}/subjects            listSubjects
  GET    /v1/tenants/{tenantId}/subjects/{subjectId} getSubject

v2.2: authorization uses permissions[] rather than role names.
"""
from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status

from verigence.di.api.v1.schemas import (
    ApiResponse,
    CreateSubjectRequest,
    SubjectListData,
    SubjectResponse,
)
from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.domain.enums import SubjectStatus
from verigence.di.repositories.database import tenant_session
from verigence.di.repositories.subjects import (
    create_subject,
    get_subject,
    list_subjects,
)

router = APIRouter(prefix="/v1/tenants/{tenantId}", tags=["Subjects"])
logger = structlog.get_logger(__name__)


@router.post(
    "/subjects",
    response_model=ApiResponse[SubjectResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create Subject",
    description=(
        "Register a new Subject (e.g. a borrower or dealer) within a Tenant. "
        "Required permission: `di.subject.create`. "
        "Returns D8 envelope with the created Subject record."
    ),
    response_description="Created subject",
    operation_id="createSubject",
)
async def create_subject_endpoint(
    tenantId: str,
    body: CreateSubjectRequest,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_permission(Permission.SUBJECT_CREATE))],
) -> ApiResponse[SubjectResponse]:
    async with tenant_session(actor.tenant_id) as session:
        subject = await create_subject(
            session,
            tenant_id=actor.tenant_id,
            subject_type=body.subjectType,
            display_name=body.displayName,
            created_by_actor_id=actor.actor_id,
        )

    logger.info(
        "subject_created",
        tenant_id=actor.tenant_id,
        actor_id=actor.actor_id,
        subject_id=str(subject["subject_id"]),
    )

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=SubjectResponse(
            tenantId=subject["tenant_id"],
            subjectId=subject["subject_id"],
            subjectType=subject["subject_type"],
            displayName=subject["display_name"],
            status=subject["status"],
            createdAtUtc=subject["created_at_utc"],
            updatedAtUtc=subject["updated_at_utc"],
        ),
    )


@router.get(
    "/subjects",
    response_model=ApiResponse[SubjectListData],
    summary="List Subjects",
    description=(
        "List and search Subjects within a Tenant with optional status filter and free-text query. "
        "Required permission: `di.subject.read`. "
        "Returns D8 envelope with items array and nextCursor for cursor-based pagination."
    ),
    response_description="Paginated subject list",
    operation_id="listSubjects",
)
async def list_subjects_endpoint(
    tenantId: str,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_permission(Permission.SUBJECT_READ))],
    subject_status: Annotated[SubjectStatus | None, Query(alias="status")] = None,
    query: Annotated[str | None, Query(max_length=240)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> ApiResponse[SubjectListData]:
    async with tenant_session(actor.tenant_id) as session:
        subjects = await list_subjects(
            session,
            tenant_id=actor.tenant_id,
            status=subject_status,
            query=query,
            limit=limit,
            cursor=cursor,
        )

    has_next = len(subjects) > limit
    page = subjects[:limit]
    next_cursor = str(page[-1]["subject_id"]) if has_next and page else None

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=SubjectListData(
            items=[
                SubjectResponse(
                    tenantId=s["tenant_id"],
                    subjectId=s["subject_id"],
                    subjectType=s["subject_type"],
                    displayName=s["display_name"],
                    status=s["status"],
                    createdAtUtc=s["created_at_utc"],
                    updatedAtUtc=s["updated_at_utc"],
                )
                for s in page
            ],
            nextCursor=next_cursor,
        ),
    )


@router.get(
    "/subjects/{subjectId}",
    response_model=ApiResponse[SubjectResponse],
    summary="Get Subject",
    description=(
        "Fetch a single Subject by ID within the Tenant boundary. "
        "Required permission: `di.subject.read`. "
        "Returns D8 envelope with the Subject record, or 404 if not found."
    ),
    response_description="Subject record",
    operation_id="getSubject",
)
async def get_subject_endpoint(
    tenantId: str,
    subjectId: uuid.UUID,
    actor: Annotated[ActorPrincipal, Depends(require_tenant_permission(Permission.SUBJECT_READ))],
) -> ApiResponse[SubjectResponse]:
    async with tenant_session(actor.tenant_id) as session:
        subject = await get_subject(
            session, tenant_id=actor.tenant_id, subject_id=subjectId
        )

    if subject is None:
        from verigence.di.errors import ErrorCode, problem  # noqa: PLC0415

        raise problem(404, "Subject not found", ErrorCode.SUBJECT_NOT_FOUND)

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=SubjectResponse(
            tenantId=subject["tenant_id"],
            subjectId=subject["subject_id"],
            subjectType=subject["subject_type"],
            displayName=subject["display_name"],
            status=subject["status"],
            createdAtUtc=subject["created_at_utc"],
            updatedAtUtc=subject["updated_at_utc"],
        ),
    )
