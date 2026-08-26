"""Super Admin housekeeping for tenant-scoped DI transaction data.

This is intentionally separate from Project purge. Housekeeping removes document
transaction state and stored document objects while preserving Tenant provisioning,
subjects/storage contexts, Document Types, Canonical Fields, Extraction Profiles,
and other DI configuration.
"""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.api.v1.schemas import ApiResponse
from verigence.di.auth.human_admin import HumanAdminRequest, require_uc02_super_admin
from verigence.di.repositories.database import get_db_session, set_tenant_context
from verigence.di.storage.adapter import get_storage_adapter

router = APIRouter(
    prefix="/v1/tenants/{tenantId}/admin/housekeeping",
    tags=["Tenant Housekeeping"],
)

_CONFIRMATION = "PURGE_TRANSACTION_DATA"
_SELECTED_DOCUMENT_CONFIRMATION = "PURGE_SELECTED_DOCUMENTS"


class TenantTransactionDataStatus(BaseModel):
    tenantId: str
    documents: int
    storageObjects: int
    extractedFacts: int
    acceptedFieldValues: int
    processingJobs: int
    processingRuns: int
    processorInvocations: int


class TenantTransactionPurgeCommand(BaseModel):
    confirmTenantId: str
    confirmation: Literal["PURGE_TRANSACTION_DATA"]


class TenantTransactionPurgeData(BaseModel):
    tenantId: str
    purgeStatus: Literal["REMOVED"]
    deletedDocuments: int
    deletedStorageObjects: int
    configurationPreserved: bool = True


class SelectedDocumentPurgeCommand(BaseModel):
    confirmTenantId: str
    confirmation: Literal["PURGE_SELECTED_DOCUMENTS"]
    documentIds: list[UUID] = Field(min_length=1, max_length=5000)


class SelectedDocumentPurgeData(BaseModel):
    tenantId: str
    purgeStatus: Literal["REMOVED"]
    requestedDocuments: int
    deletedDocuments: int
    deletedStorageObjects: int
    configurationPreserved: bool = True


async def _transaction_status(
    session: AsyncSession,
    tenant_id: str,
) -> TenantTransactionDataStatus:
    await set_tenant_context(session, tenant_id)
    row = (
        await session.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM docintel.documents WHERE tenant_id=:tid) AS documents,
                  (SELECT count(*) FROM docintel.document_artifacts
                     WHERE tenant_id=:tid AND logical_object_key IS NOT NULL) AS storage_objects,
                  (SELECT count(*) FROM docintel.extracted_facts WHERE tenant_id=:tid) AS extracted_facts,
                  (SELECT count(*) FROM docintel.document_field_values WHERE tenant_id=:tid) AS field_values,
                  (SELECT count(*) FROM docintel.processing_jobs WHERE tenant_id=:tid) AS processing_jobs,
                  (SELECT count(*) FROM docintel.processing_runs WHERE tenant_id=:tid) AS processing_runs,
                  (SELECT count(*) FROM docintel.processor_invocations WHERE tenant_id=:tid) AS invocations
                """
            ),
            {"tid": tenant_id},
        )
    ).mappings().one()
    return TenantTransactionDataStatus(
        tenantId=tenant_id,
        documents=int(row["documents"]),
        storageObjects=int(row["storage_objects"]),
        extractedFacts=int(row["extracted_facts"]),
        acceptedFieldValues=int(row["field_values"]),
        processingJobs=int(row["processing_jobs"]),
        processingRuns=int(row["processing_runs"]),
        processorInvocations=int(row["invocations"]),
    )


async def _delete_transaction_rows(session: AsyncSession, tenant_id: str) -> None:
    """Delete only document transaction tables for one Tenant in FK-safe order."""
    await set_tenant_context(session, tenant_id)

    # documents.current_processing_run_id forms a deliberate cycle with processing_runs.
    await session.execute(
        text(
            "UPDATE docintel.documents SET current_processing_run_id=NULL "
            "WHERE tenant_id=:tid"
        ),
        {"tid": tenant_id},
    )

    # Child-first order. Keep this list deliberately explicit so future configuration
    # tables cannot be pulled into housekeeping merely because they have tenant_id.
    tables = (
        "backout_jobs",
        "document_field_values",
        "validation_results",
        "document_classifications",
        "extracted_facts",
        "document_quality_results",
        "document_search_index",
        "entity_links",
        "integration_intake_events",
        "document_artifacts",
        "human_verifications",
        "processor_invocations",
        "processing_runs",
        "processing_jobs",
        "documents",
    )
    for table_name in tables:
        await session.execute(
            text(f"DELETE FROM docintel.{table_name} WHERE tenant_id=:tid"),  # noqa: S608
            {"tid": tenant_id},
        )


async def _delete_selected_document_rows(
    session: AsyncSession,
    tenant_id: str,
    document_ids: list[UUID],
) -> None:
    """Delete only the requested Tenant documents and their transaction graph."""
    await set_tenant_context(session, tenant_id)
    params = {"tid": tenant_id, "document_ids": document_ids}
    target = "document_id = ANY(CAST(:document_ids AS uuid[]))"

    # Break references from Documents to selected Documents/Runs before child deletion.
    await session.execute(
        text(
            f"UPDATE docintel.documents SET current_processing_run_id=NULL "
            f"WHERE tenant_id=:tid AND {target}"
        ),
        params,
    )
    await session.execute(
        text(
            """
            UPDATE docintel.documents
            SET duplicate_of_document_id = CASE
                    WHEN duplicate_of_document_id = ANY(CAST(:document_ids AS uuid[])) THEN NULL
                    ELSE duplicate_of_document_id END,
                replaces_document_id = CASE
                    WHEN replaces_document_id = ANY(CAST(:document_ids AS uuid[])) THEN NULL
                    ELSE replaces_document_id END,
                replaced_by_document_id = CASE
                    WHEN replaced_by_document_id = ANY(CAST(:document_ids AS uuid[])) THEN NULL
                    ELSE replaced_by_document_id END
            WHERE tenant_id=:tid
              AND (
                    duplicate_of_document_id = ANY(CAST(:document_ids AS uuid[]))
                 OR replaces_document_id = ANY(CAST(:document_ids AS uuid[]))
                 OR replaced_by_document_id = ANY(CAST(:document_ids AS uuid[]))
              )
            """
        ),
        params,
    )

    direct_tables = (
        "backout_jobs",
        "document_field_values",
        "validation_results",
        "document_classifications",
        "extracted_facts",
        "document_quality_results",
        "document_search_index",
        "entity_links",
        "integration_intake_events",
        "document_artifacts",
        "human_verifications",
    )
    for table_name in direct_tables:
        await session.execute(
            text(
                f"DELETE FROM docintel.{table_name} "  # noqa: S608
                f"WHERE tenant_id=:tid AND {target}"
            ),
            params,
        )

    await session.execute(
        text(
            """
            DELETE FROM docintel.processor_invocations
            WHERE tenant_id=:tid
              AND processing_run_id IN (
                    SELECT processing_run_id FROM docintel.processing_runs
                    WHERE tenant_id=:tid
                      AND document_id = ANY(CAST(:document_ids AS uuid[]))
              )
            """
        ),
        params,
    )
    await session.execute(
        text(
            "DELETE FROM docintel.processing_runs "
            "WHERE tenant_id=:tid AND document_id = ANY(CAST(:document_ids AS uuid[]))"
        ),
        params,
    )
    await session.execute(
        text(
            "DELETE FROM docintel.processing_jobs "
            "WHERE tenant_id=:tid AND document_id = ANY(CAST(:document_ids AS uuid[]))"
        ),
        params,
    )
    await session.execute(
        text(
            "DELETE FROM docintel.documents "
            "WHERE tenant_id=:tid AND document_id = ANY(CAST(:document_ids AS uuid[]))"
        ),
        params,
    )


@router.get("/transaction-data", response_model=ApiResponse[TenantTransactionDataStatus])
async def get_tenant_transaction_data_status(
    tenantId: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[TenantTransactionDataStatus]:
    """Preview tenant transaction volume before a destructive housekeeping purge."""
    del admin
    data = await _transaction_status(session, tenantId)
    return ApiResponse(errorCode="000", errorMessage="Success", data=data)


@router.post(
    "/transaction-data/purge",
    response_model=ApiResponse[TenantTransactionPurgeData],
)
async def purge_tenant_transaction_data(
    tenantId: str,
    command: TenantTransactionPurgeCommand,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[TenantTransactionPurgeData]:
    """Purge one Tenant's DI transaction data while preserving configuration.

    Storage objects are deleted first. Database cleanup is idempotent, so a retry is
    safe if the request is interrupted after object deletion but before DB commit.
    """
    del admin
    if command.confirmTenantId != tenantId:
        raise HTTPException(
            status_code=400,
            detail="Tenant confirmation does not match the Tenant being purged.",
        )
    if command.confirmation != _CONFIRMATION:
        raise HTTPException(status_code=400, detail="Invalid purge confirmation.")

    await set_tenant_context(session, tenantId)
    status_before = await _transaction_status(session, tenantId)
    artifact_keys = [
        str(value)
        for value in (
            await session.execute(
                text(
                    "SELECT logical_object_key FROM docintel.document_artifacts "
                    "WHERE tenant_id=:tid AND logical_object_key IS NOT NULL"
                ),
                {"tid": tenantId},
            )
        ).scalars().all()
    ]

    storage = get_storage_adapter()
    for logical_key in artifact_keys:
        await storage.delete(logical_key)

    await _delete_transaction_rows(session, tenantId)
    status_after = await _transaction_status(session, tenantId)
    if any(
        (
            status_after.documents,
            status_after.storageObjects,
            status_after.extractedFacts,
            status_after.acceptedFieldValues,
            status_after.processingJobs,
            status_after.processingRuns,
            status_after.processorInvocations,
        )
    ):
        raise RuntimeError("DI Tenant transaction housekeeping did not reach zero state")

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=TenantTransactionPurgeData(
            tenantId=tenantId,
            purgeStatus="REMOVED",
            deletedDocuments=status_before.documents,
            deletedStorageObjects=len(artifact_keys),
        ),
    )


@router.post(
    "/document-data/purge",
    response_model=ApiResponse[SelectedDocumentPurgeData],
)
async def purge_selected_document_data(
    tenantId: str,
    command: SelectedDocumentPurgeCommand,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[SelectedDocumentPurgeData]:
    """Purge selected DI documents, used by Audit Core Journey housekeeping."""
    del admin
    if command.confirmTenantId != tenantId:
        raise HTTPException(
            status_code=400,
            detail="Tenant confirmation does not match the Tenant being purged.",
        )
    if command.confirmation != _SELECTED_DOCUMENT_CONFIRMATION:
        raise HTTPException(status_code=400, detail="Invalid purge confirmation.")

    document_ids = list(dict.fromkeys(command.documentIds))
    params = {"tid": tenantId, "document_ids": document_ids}
    await set_tenant_context(session, tenantId)
    existing_document_ids = list(
        (
            await session.execute(
                text(
                    "SELECT document_id FROM docintel.documents "
                    "WHERE tenant_id=:tid "
                    "AND document_id = ANY(CAST(:document_ids AS uuid[]))"
                ),
                params,
            )
        ).scalars().all()
    )
    artifact_keys = [
        str(value)
        for value in (
            await session.execute(
                text(
                    "SELECT logical_object_key FROM docintel.document_artifacts "
                    "WHERE tenant_id=:tid "
                    "AND document_id = ANY(CAST(:document_ids AS uuid[])) "
                    "AND logical_object_key IS NOT NULL"
                ),
                params,
            )
        ).scalars().all()
    ]

    storage = get_storage_adapter()
    for logical_key in artifact_keys:
        await storage.delete(logical_key)

    if existing_document_ids:
        await _delete_selected_document_rows(session, tenantId, existing_document_ids)

    remaining = int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM docintel.documents "
                    "WHERE tenant_id=:tid "
                    "AND document_id = ANY(CAST(:document_ids AS uuid[]))"
                ),
                params,
            )
        ).scalar_one()
    )
    if remaining:
        raise RuntimeError("DI selected-document housekeeping did not reach zero state")

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=SelectedDocumentPurgeData(
            tenantId=tenantId,
            purgeStatus="REMOVED",
            requestedDocuments=len(document_ids),
            deletedDocuments=len(existing_document_ids),
            deletedStorageObjects=len(artifact_keys),
        ),
    )
