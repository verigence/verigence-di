"""api/v1/analyse.py — POST /v1/tenants/{tenantId}/analyse endpoint (D15).

Loads extracted indexed_fields for the requested document IDs from
document_search_index, resolves the subject display_name, then runs
the seven deterministic reconciliation rules (D17) and returns a
structured findings report.

Authorization: di.document.read
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from verigence.di.api.v1.schemas import ApiResponse
from verigence.di.application.reconciliation import run_reconciliation
from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.repositories.database import tenant_session

router = APIRouter(prefix="/v1", tags=["Analysis"])
logger = structlog.get_logger(__name__)


# ── Request / Response models ─────────────────────────────────────────────────

class AnalyseRequest(BaseModel):
    document_ids: list[str] = Field(alias="documentIds")

    @field_validator("document_ids")
    @classmethod
    def at_least_one(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("documentIds must contain at least one document ID")
        if len(v) > 50:
            raise ValueError("documentIds must contain at most 50 document IDs")
        return v

    model_config = {"populate_by_name": True}


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/tenants/{tenant_id}/analyse")
async def analyse_documents(
    tenant_id: str,
    body: AnalyseRequest,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.DOCUMENT_READ)),
) -> dict[str, Any]:
    """Run seven reconciliation rules (D17) against a set of document IDs (D15).

    Loads extracted field values from document_search_index and runs all
    applicable rules. Returns a findings list and a summary verdict.

    Summary values:
      RECONCILED         — all applicable rules PASS
      DISCREPANCY        — one or more applicable rules FAIL
      INSUFFICIENT_DATA  — no applicable rule could be evaluated
    """
    async with tenant_session(tenant_id) as session:
        # ── Load indexed_fields rows from document_search_index ───────────────
        if not body.document_ids:
            raise HTTPException(status_code=400, detail="documentIds must not be empty")

        # Build placeholders for the IN clause
        placeholders = ", ".join(f":id_{i}" for i in range(len(body.document_ids)))
        params: dict[str, Any] = {"tid": tenant_id}
        for i, did in enumerate(body.document_ids):
            params[f"id_{i}"] = did

        rows = (
            await session.execute(
                text(f"""
                    SELECT
                        si.document_id,
                        si.subject_id,
                        si.document_type_key,
                        si.indexed_fields
                    FROM docintel.document_search_index si
                    WHERE si.tenant_id = :tid
                      AND si.document_id::text IN ({placeholders})
                """),
                params,
            )
        ).mappings().all()

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="No indexed documents found for the provided document IDs",
            )

        # ── Enforce single subject ────────────────────────────────────────────
        subject_ids = {str(r["subject_id"]) for r in rows if r.get("subject_id")}
        if len(subject_ids) > 1:
            raise HTTPException(
                status_code=422,
                detail="All documents must belong to the same subject for reconciliation.",
            )

        # ── Resolve subject display_name from the first matched subject ───────
        subject_display_name: str | None = None
        if subject_ids:
            first_subject_id = next(iter(subject_ids))
            subj_row = (
                await session.execute(
                    text("""
                        SELECT display_name
                        FROM docintel.subjects
                        WHERE tenant_id = :tid AND subject_id = :sid
                    """),
                    {"tid": tenant_id, "sid": first_subject_id},
                )
            ).mappings().first()
            if subj_row:
                subject_display_name = subj_row.get("display_name")

    # ── Build document list for reconciliation engine ─────────────────────────
    documents = [
        {
            "document_id": str(r["document_id"]),
            "document_type_key": r["document_type_key"] or "",
            "indexed_fields": dict(r["indexed_fields"]) if r["indexed_fields"] else {},
        }
        for r in rows
    ]

    # ── Run reconciliation rules (pure Python — no DB) ────────────────────────
    result = run_reconciliation(
        documents=documents,
        subject_display_name=subject_display_name,
    )

    logger.info(
        "documents_analysed",
        tenant_id=tenant_id,
        actor_id=actor.actor_id,
        document_count=len(body.document_ids),
        summary=result.summary,
    )

    payload = {
        "analysedDocuments": result.analysed_documents,
        "findings": [
            {
                "ruleKey": f.rule_key,
                "result": f.result,
                "detail": f.detail,
            }
            for f in result.findings
        ],
        "summary": result.summary,
    }
    return ApiResponse(errorCode="000", errorMessage="Success", data=payload).model_dump()
