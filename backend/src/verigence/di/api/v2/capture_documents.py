"""Document Capture V2 machine API used by Audit Core.

The browser never calls this API with document bytes. Audit Core creates upload
intents; the browser PUTs bytes directly to the returned R2/MinIO URL; finalize is
only a latency hint. Status reads can reconcile an already-uploaded object when a
browser finalize call was lost.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from verigence.di.auth.service_integration import (
    ServiceIntegrationPrincipal,
    require_service_integration,
)
from verigence.di.errors import ErrorCode, http_exception
from verigence.di.repositories.audit_storage_contexts import get_audit_storage_context_by_ref
from verigence.di.repositories.database import tenant_session
from verigence.di.repositories.documents import (
    create_document_receiving,
    delete_document,
    get_active_retention_policy,
)
from verigence.di.repositories.tenants import provision_actor
from verigence.di.storage.adapter import get_storage_adapter
from verigence.di.storage.audit_keys import build_audit_original_key
from verigence.di.storage.v2_presigned import presign_v2_put

router = APIRouter(prefix="/v2/tenants/{tenantId}", tags=["Document Capture V2"])


class V2UploadIntentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clientUploadId: str = Field(min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=500)
    contentType: str | None = Field(default=None, max_length=160)


class V2UploadIntentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal["BOOKING", "DELIVERY"]
    candidateDocumentTypeKeys: list[str] = Field(min_length=1, max_length=64)
    files: list[V2UploadIntentItem] = Field(min_length=1, max_length=20)


class V2UploadIntent(BaseModel):
    clientUploadId: str
    documentId: UUID
    uploadUrl: str
    uploadHeaders: dict[str, str]
    expiresAtUtc: datetime


class V2UploadIntentResponse(BaseModel):
    externalContextRef: str
    phase: Literal["BOOKING", "DELIVERY"]
    uploads: list[V2UploadIntent]


class V2CaptureDocumentStatus(BaseModel):
    documentId: UUID
    clientUploadId: str
    state: str
    classifiedDocumentTypeKey: str | None = None
    originalFilename: str
    contentUrl: str | None = None
    processingStatus: str | None = None


class V2CaptureDocumentList(BaseModel):
    externalContextRef: str
    phase: Literal["BOOKING", "DELIVERY"]
    documents: list[V2CaptureDocumentStatus]


def _context_uuid(context: dict[str, object], key: str) -> UUID:
    return UUID(str(context[key]))


def _context_string(context: dict[str, object], key: str) -> str:
    return str(context[key])


async def _queue_if_object_exists(
    *,
    tenant_id: str,
    document_id: UUID,
) -> bool:
    """Reconcile RECEIVING -> STORED + classification job after direct R2 PUT."""
    storage = get_storage_adapter()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT u.logical_object_key, u.declared_mime_type, u.state,
                           d.upload_status
                    FROM docintel.document_capture_v2_uploads u
                    JOIN docintel.documents d
                      ON d.tenant_id=u.tenant_id AND d.document_id=u.document_id
                    WHERE u.tenant_id=:tenant_id AND u.document_id=:document_id
                    FOR UPDATE OF u, d
                    """
                ),
                {"tenant_id": tenant_id, "document_id": document_id},
            )
        ).mappings().one_or_none()
        if row is None:
            raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
        if row["state"] != "RECEIVING":
            return False
        logical_key = str(row["logical_object_key"])
        if not await storage.exists(logical_key):
            return False
        metadata = await storage.get_metadata(logical_key)
        now = datetime.now(UTC)
        await session.execute(
            text(
                """
                INSERT INTO docintel.document_artifacts (
                    tenant_id, artifact_id, document_id, storage_id,
                    logical_object_key, artifact_type, mime_type,
                    file_size_bytes, created_at_utc
                ) VALUES (
                    :tenant_id, :artifact_id, :document_id, :storage_id,
                    :logical_key, 'ORIGINAL', :mime_type,
                    :file_size_bytes, :now
                )
                ON CONFLICT (tenant_id, logical_object_key) DO NOTHING
                """
            ),
            {
                "tenant_id": tenant_id,
                "artifact_id": uuid.uuid4(),
                "document_id": document_id,
                "storage_id": uuid.uuid4(),
                "logical_key": logical_key,
                "mime_type": metadata.content_type or row["declared_mime_type"],
                "file_size_bytes": metadata.size_bytes,
                "now": now,
            },
        )
        await session.execute(
            text(
                """
                UPDATE docintel.documents
                SET file_size_bytes=:file_size_bytes,
                    detected_mime_type=COALESCE(:mime_type, declared_mime_type),
                    upload_status='VALIDATING',
                    updated_at_utc=:now
                WHERE tenant_id=:tenant_id AND document_id=:document_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "file_size_bytes": metadata.size_bytes,
                "mime_type": metadata.content_type,
                "now": now,
            },
        )
        await session.execute(
            text(
                """
                UPDATE docintel.document_capture_v2_uploads
                SET state='STORED', stored_at_utc=:now, updated_at_utc=:now
                WHERE tenant_id=:tenant_id AND document_id=:document_id
                """
            ),
            {"tenant_id": tenant_id, "document_id": document_id, "now": now},
        )
        await session.execute(
            text(
                """
                INSERT INTO docintel.document_capture_v2_classification_jobs (
                    tenant_id, document_id, job_status, due_at_utc,
                    attempt_no, created_at_utc, updated_at_utc
                ) VALUES (
                    :tenant_id, :document_id, 'PENDING', :now, 1, :now, :now
                )
                ON CONFLICT (tenant_id, document_id) DO NOTHING
                """
            ),
            {"tenant_id": tenant_id, "document_id": document_id, "now": now},
        )
        await session.execute(
            text("SELECT pg_notify('di_capture_v2_jobs', :payload)"),
            {"payload": str(document_id)},
        )
        await session.commit()
        return True


@router.post(
    "/audit-storage-contexts/{externalContextRef}/capture-documents:init",
    response_model=V2UploadIntentResponse,
)
async def create_capture_upload_intents(
    tenantId: str,
    externalContextRef: str,
    command: V2UploadIntentCommand,
    principal: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
) -> V2UploadIntentResponse:
    candidate_keys = list(dict.fromkeys(key.strip() for key in command.candidateDocumentTypeKeys if key.strip()))
    if not candidate_keys:
        raise http_exception(ErrorCode.INVALID_REQUEST, detail="Candidate document types are required")

    intents: list[V2UploadIntent] = []
    async with tenant_session(tenantId) as session:
        context = await get_audit_storage_context_by_ref(
            session,
            tenant_id=tenantId,
            external_context_ref=externalContextRef,
        )
        if context is None:
            raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND, detail="Audit storage context not found")
        await provision_actor(session, tenantId, principal.service_id, actor_type="SERVICE")
        retention = await get_active_retention_policy(session, tenant_id=tenantId)
        if retention is None:
            raise http_exception(ErrorCode.INVALID_REQUEST, detail="Tenant has no active retention policy")

        for item in command.files:
            existing = (
                await session.execute(
                    text(
                        """
                        SELECT document_id, logical_object_key
                        FROM docintel.document_capture_v2_uploads
                        WHERE tenant_id=:tenant_id
                          AND external_context_ref=:external_context_ref
                          AND phase=:phase
                          AND client_upload_id=:client_upload_id
                        """
                    ),
                    {
                        "tenant_id": tenantId,
                        "external_context_ref": externalContextRef,
                        "phase": command.phase,
                        "client_upload_id": item.clientUploadId,
                    },
                )
            ).mappings().one_or_none()

            if existing is None:
                doc = await create_document_receiving(
                    session,
                    tenant_id=tenantId,
                    subject_id=_context_uuid(context, "subject_id"),
                    uploaded_by_actor_id=principal.service_id,
                    uploaded_by_actor_type="SERVICE",
                    correlation_id=f"capture-v2:{item.clientUploadId}",
                    retention_policy_id=retention["retention_policy_id"],
                    retention_days=retention["retention_days"],
                    retention_disposition=retention["disposition"],
                    original_filename=item.filename,
                    declared_mime_type=item.contentType,
                    physical_form_type="ADDITIONAL",
                    requires_processing=False,
                )
                document_id = UUID(str(doc["document_id"]))
                logical_key = build_audit_original_key(
                    tenant_id=tenantId,
                    dealer_id=_context_uuid(context, "dealer_id"),
                    dealer_outlet_id=_context_uuid(context, "dealer_outlet_id"),
                    customer_id=_context_uuid(context, "customer_id"),
                    project_slug=_context_string(context, "project_slug"),
                    dealer_slug=_context_string(context, "dealer_slug"),
                    dealer_outlet_slug=_context_string(context, "dealer_outlet_slug"),
                    customer_slug=_context_string(context, "customer_slug"),
                    document_id=document_id,
                    physical_form_type="ADDITIONAL",
                    original_filename=item.filename,
                    detected_mime_type=item.contentType,
                )
                await session.execute(
                    text(
                        """
                        UPDATE docintel.documents
                        SET audit_storage_context_id=:storage_context_id,
                            updated_at_utc=now()
                        WHERE tenant_id=:tenant_id AND document_id=:document_id
                        """
                    ),
                    {
                        "tenant_id": tenantId,
                        "document_id": document_id,
                        "storage_context_id": _context_uuid(context, "storage_context_id"),
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO docintel.document_capture_v2_uploads (
                            tenant_id, document_id, audit_storage_context_id,
                            external_context_ref, phase, client_upload_id,
                            logical_object_key, original_filename, declared_mime_type,
                            candidate_document_type_keys, state,
                            created_at_utc, updated_at_utc
                        ) VALUES (
                            :tenant_id, :document_id, :storage_context_id,
                            :external_context_ref, :phase, :client_upload_id,
                            :logical_key, :filename, :content_type,
                            CAST(:candidate_keys AS jsonb), 'RECEIVING', now(), now()
                        )
                        """
                    ),
                    {
                        "tenant_id": tenantId,
                        "document_id": document_id,
                        "storage_context_id": _context_uuid(context, "storage_context_id"),
                        "external_context_ref": externalContextRef,
                        "phase": command.phase,
                        "client_upload_id": item.clientUploadId,
                        "logical_key": logical_key,
                        "filename": item.filename,
                        "content_type": item.contentType,
                        "candidate_keys": __import__("json").dumps(candidate_keys),
                    },
                )
            else:
                document_id = UUID(str(existing["document_id"]))
                logical_key = str(existing["logical_object_key"])

            signed = await presign_v2_put(
                logical_key=logical_key,
                content_type=item.contentType,
            )
            intents.append(
                V2UploadIntent(
                    clientUploadId=item.clientUploadId,
                    documentId=document_id,
                    uploadUrl=signed.url,
                    uploadHeaders=signed.required_headers,
                    expiresAtUtc=datetime.now(UTC) + timedelta(seconds=signed.expires_seconds),
                )
            )
        await session.commit()

    return V2UploadIntentResponse(
        externalContextRef=externalContextRef,
        phase=command.phase,
        uploads=intents,
    )


@router.post(
    "/audit-storage-contexts/{externalContextRef}/capture-documents/{documentId}:finalize",
    response_model=V2CaptureDocumentStatus,
)
async def finalize_capture_document(
    tenantId: str,
    externalContextRef: str,
    documentId: UUID,
    principal: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
) -> V2CaptureDocumentStatus:
    del principal
    await _queue_if_object_exists(tenant_id=tenantId, document_id=documentId)
    rows = await _status_rows(tenantId, externalContextRef, None, documentId)
    if not rows:
        raise http_exception(ErrorCode.DOCUMENT_NOT_FOUND)
    return await _public_status(tenantId, rows[0])


async def _status_rows(
    tenant_id: str,
    external_context_ref: str,
    phase: str | None,
    document_id: UUID | None = None,
) -> Sequence[RowMapping]:
    async with tenant_session(tenant_id) as session:
        clauses = ["u.tenant_id=:tenant_id", "u.external_context_ref=:external_context_ref"]
        params: dict[str, object] = {
            "tenant_id": tenant_id,
            "external_context_ref": external_context_ref,
        }
        if phase is not None:
            clauses.append("u.phase=:phase")
            params["phase"] = phase
        if document_id is not None:
            clauses.append("u.document_id=:document_id")
            params["document_id"] = document_id
        return (
            await session.execute(
                text(
                    f"""
                    SELECT u.document_id, u.client_upload_id, u.state,
                           u.classified_document_type_key, u.original_filename,
                           u.logical_object_key, d.processing_status,
                           d.content_state
                    FROM docintel.document_capture_v2_uploads u
                    JOIN docintel.documents d
                      ON d.tenant_id=u.tenant_id AND d.document_id=u.document_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY u.created_at_utc, u.document_id
                    """
                ),
                params,
            )
        ).mappings().all()


async def _public_status(tenant_id: str, row: RowMapping) -> V2CaptureDocumentStatus:
    content_url: str | None = None
    if row["state"] in {"STORED", "CLASSIFYING", "CLASSIFIED", "UNKNOWN", "FAILED"} and row["content_state"] != "PURGED":
        try:
            content_url = await get_storage_adapter().get_presigned_url(
                str(row["logical_object_key"]), 30 * 60
            )
        except Exception:
            content_url = None
    return V2CaptureDocumentStatus(
        documentId=row["document_id"],
        clientUploadId=row["client_upload_id"],
        state=row["state"],
        classifiedDocumentTypeKey=row["classified_document_type_key"],
        originalFilename=row["original_filename"],
        contentUrl=content_url,
        processingStatus=row["processing_status"],
    )


@router.get(
    "/audit-storage-contexts/{externalContextRef}/capture-documents",
    response_model=V2CaptureDocumentList,
)
async def list_capture_documents(
    tenantId: str,
    externalContextRef: str,
    phase: Literal["BOOKING", "DELIVERY"],
    principal: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
) -> V2CaptureDocumentList:
    del principal
    rows = await _status_rows(tenantId, externalContextRef, phase)
    # Lost browser finalize must not become a permanently stuck RECEIVING row.
    for row in rows:
        if row["state"] == "RECEIVING":
            await _queue_if_object_exists(tenant_id=tenantId, document_id=row["document_id"])
    rows = await _status_rows(tenantId, externalContextRef, phase)
    return V2CaptureDocumentList(
        externalContextRef=externalContextRef,
        phase=phase,
        documents=[await _public_status(tenantId, row) for row in rows],
    )


@router.delete(
    "/audit-storage-contexts/{externalContextRef}/capture-documents/{documentId}",
    status_code=204,
)
async def hard_delete_capture_document(
    tenantId: str,
    externalContextRef: str,
    documentId: UUID,
    principal: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
) -> None:
    del principal
    storage = get_storage_adapter()
    async with tenant_session(tenantId) as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT u.document_id, d.subject_id
                    FROM docintel.document_capture_v2_uploads u
                    JOIN docintel.documents d
                      ON d.tenant_id=u.tenant_id AND d.document_id=u.document_id
                    WHERE u.tenant_id=:tenant_id
                      AND u.external_context_ref=:external_context_ref
                      AND u.document_id=:document_id
                    FOR UPDATE OF u, d
                    """
                ),
                {
                    "tenant_id": tenantId,
                    "external_context_ref": externalContextRef,
                    "document_id": documentId,
                },
            )
        ).mappings().one_or_none()
        if row is None:
            return
        await session.execute(
            text(
                "DELETE FROM docintel.document_capture_v2_classification_jobs "
                "WHERE tenant_id=:tenant_id AND document_id=:document_id"
            ),
            {"tenant_id": tenantId, "document_id": documentId},
        )
        await session.execute(
            text(
                "DELETE FROM docintel.document_capture_v2_uploads "
                "WHERE tenant_id=:tenant_id AND document_id=:document_id"
            ),
            {"tenant_id": tenantId, "document_id": documentId},
        )
        await delete_document(
            session,
            tenant_id=tenantId,
            document_id=documentId,
            subject_id=UUID(str(row["subject_id"])),
            storage=storage,
        )
        await session.commit()