"""Schema V2 role-safe field lineage API for Audit Core integration.

This endpoint is additive: the long-standing /documents/{id}/fields contract is
left unchanged while Audit Core adopts the richer provenance payload.  A later
contract version can converge them once all consumers are proven compatible.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text

from verigence.di.api.v1.schemas import ApiResponse
from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.errors import ErrorCode, problem
from verigence.di.repositories.database import tenant_session

router = APIRouter(prefix="/v1/tenants/{tenantId}", tags=["Subject Documents"])


@router.get(
    "/subjects/{subjectId}/documents/{documentId}/fields/lineage",
    operation_id="getSubjectDocumentFieldLineage",
    summary="Get Document Field Lineage",
    description=(
        "Return current field values with their immutable DI extraction lineage and "
        "effective fact role. This is an additive Schema V2 integration contract."
    ),
)
async def get_subject_document_field_lineage(
    tenantId: str,
    subjectId: uuid.UUID,
    documentId: uuid.UUID,
    actor: Annotated[
        ActorPrincipal,
        Depends(require_tenant_permission(Permission.DOCUMENT_FIELDS_READ)),
    ],
) -> ApiResponse[dict]:  # type: ignore[type-arg]
    async with tenant_session(actor.tenant_id) as session:
        doc_row = (
            await session.execute(
                text("""
                    SELECT confirmation_status
                    FROM docintel.documents
                    WHERE tenant_id=:tenant_id
                      AND document_id=:document_id
                      AND subject_id=:subject_id
                """),
                {
                    "tenant_id": actor.tenant_id,
                    "document_id": documentId,
                    "subject_id": subjectId,
                },
            )
        ).one_or_none()
        if doc_row is None:
            raise problem(404, "Document not found", ErrorCode.DOCUMENT_NOT_FOUND)
        if doc_row[0] != "CONFIRMED":
            return ApiResponse(
                errorCode="E008",
                errorMessage="Document is not yet confirmed — fields not available",
                data=None,
            )

        rows = (
            await session.execute(
                text("""
                    SELECT
                        dfv.canonical_field_id,
                        cf.field_key,
                        dfv.current_value,
                        dfv.value_source,
                        dfv.confidence_score,
                        dfv.version_no,
                        dfv.accepted_at_utc,
                        dfv.fact_role,
                        ef.extracted_fact_id,
                        ef.processing_run_id,
                        ef.invocation_id,
                        ef.page_no,
                        ef.evidence_region,
                        epf.extraction_key,
                        pr.extraction_profile_id,
                        pr.pipeline_version,
                        ep.version_no AS extraction_profile_version
                    FROM docintel.document_field_values dfv
                    JOIN docintel.canonical_fields cf
                      ON cf.canonical_field_id=dfv.canonical_field_id
                    LEFT JOIN docintel.extracted_facts ef
                      ON ef.tenant_id=dfv.tenant_id
                     AND ef.extracted_fact_id=dfv.source_extracted_fact_id
                    LEFT JOIN docintel.extraction_profile_fields epf
                      ON epf.profile_field_id=ef.profile_field_id
                    LEFT JOIN docintel.processing_runs pr
                      ON pr.tenant_id=ef.tenant_id
                     AND pr.processing_run_id=ef.processing_run_id
                    LEFT JOIN docintel.extraction_profiles ep
                      ON ep.profile_id=pr.extraction_profile_id
                    WHERE dfv.tenant_id=:tenant_id
                      AND dfv.document_id=:document_id
                      AND dfv.is_current=true
                    ORDER BY cf.field_key, dfv.fact_role, dfv.document_field_value_id
                """),
                {"tenant_id": actor.tenant_id, "document_id": documentId},
            )
        ).mappings().all()

    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data={
            "documentId": str(documentId),
            "fields": [
                {
                    "canonicalFieldId": str(row["canonical_field_id"]),
                    "fieldKey": row["field_key"],
                    "currentValue": row["current_value"],
                    "valueSource": row["value_source"],
                    "confidenceScore": (
                        float(row["confidence_score"])
                        if row["confidence_score"] is not None
                        else None
                    ),
                    "versionNo": row["version_no"],
                    "acceptedAt": (
                        row["accepted_at_utc"].isoformat()
                        if row["accepted_at_utc"] is not None
                        else None
                    ),
                    "factRole": row["fact_role"],
                    "extractionKey": row["extraction_key"],
                    "extractedFactId": (
                        str(row["extracted_fact_id"])
                        if row["extracted_fact_id"] is not None
                        else None
                    ),
                    "processingRunId": (
                        str(row["processing_run_id"])
                        if row["processing_run_id"] is not None
                        else None
                    ),
                    "extractionProfileId": (
                        str(row["extraction_profile_id"])
                        if row["extraction_profile_id"] is not None
                        else None
                    ),
                    "extractionProfileVersion": row["extraction_profile_version"],
                    "invocationId": (
                        str(row["invocation_id"])
                        if row["invocation_id"] is not None
                        else None
                    ),
                    "pipelineVersion": row["pipeline_version"],
                    "pageNo": row["page_no"],
                    "evidenceRegion": row["evidence_region"],
                }
                for row in rows
            ],
        },
    )
