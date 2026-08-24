"""AI-assisted DI Configuration Authoring API.

Additive administration surface. It does not alter runtime document upload,
processing, /fields, or /analyse contracts.

Trust boundary:
- Gemini proposes JSON only.
- DI validates and stores the proposal.
- Admin test is non-persistent preview extraction.
- Admin approval materialises a DRAFT Document Type/Profile configuration.
- A separate publish permission is required to make the profile active.
"""
from __future__ import annotations

import io
import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import text

from verigence.di.api.v1.schemas import ApiResponse
from verigence.di.auth.dependencies import require_tenant_permission
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.document_ai.schema_authoring import (
    generate_schema_proposal,
    test_schema_proposal,
    validate_schema_proposal,
)
from verigence.di.errors import ErrorCode, problem
from verigence.di.repositories.database import tenant_session
from verigence.di.storage.adapter import StorageAdapter, get_storage_adapter

router = APIRouter(prefix="/v1", tags=["Configuration Authoring"])
logger = structlog.get_logger(__name__)

_MAX_SAMPLE_BYTES = 30 * 1024 * 1024


def _safe_filename(value: str | None) -> str:
    name = (value or "sample.bin").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")[:120]
    return name or "sample.bin"


def _sample_key(tenant_id: str, proposal_id: uuid.UUID, filename: str) -> str:
    tenant_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", tenant_id).strip("-")[:80] or "tenant"
    return f"{tenant_slug}/configuration-proposals/{proposal_id}/{_safe_filename(filename)}"


async def _canonical_catalogue(tenant_id: str) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT DISTINCT field_key
                    FROM docintel.canonical_fields
                    WHERE status='ACTIVE'
                      AND (owner_tenant_id=:tid OR owner_tenant_id IS NULL)
                    ORDER BY field_key
                """),
                {"tid": tenant_id},
            )
        ).scalars().all()
    return [str(item) for item in rows]


def _fmt_row(row: Any, *, include_payload: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "proposalId": str(row["proposal_id"]),
        "status": row["status"],
        "sampleFilename": row["sample_filename"],
        "sampleMimeType": row["sample_mime_type"],
        "sampleSizeBytes": row["sample_size_bytes"],
        "documentTypeKey": row["proposed_document_type_key"],
        "displayName": row["proposed_display_name"],
        "physicalFormType": row["physical_form_type"],
        "generatedByModel": row.get("generated_by_model"),
        "promptTokens": row.get("prompt_tokens", 0),
        "responseTokens": row.get("response_tokens", 0),
        "createdByActorId": row["created_by_actor_id"],
        "approvedByActorId": row.get("approved_by_actor_id"),
        "publishedByActorId": row.get("published_by_actor_id"),
        "materializedDocumentTypeId": str(row["materialized_document_type_id"]) if row.get("materialized_document_type_id") else None,
        "materializedProfileId": str(row["materialized_profile_id"]) if row.get("materialized_profile_id") else None,
        "createdAt": row["created_at_utc"].isoformat() if row.get("created_at_utc") else None,
        "updatedAt": row["updated_at_utc"].isoformat() if row.get("updated_at_utc") else None,
        "approvedAt": row["approved_at_utc"].isoformat() if row.get("approved_at_utc") else None,
        "publishedAt": row["published_at_utc"].isoformat() if row.get("published_at_utc") else None,
    }
    if include_payload:
        result["proposal"] = row["proposal_payload"]
        result["latestTestResult"] = row.get("latest_test_result")
    return result


async def _load_proposal(tenant_id: str, proposal_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("""
                    SELECT * FROM docintel.configuration_proposals
                    WHERE tenant_id=:tid AND proposal_id=:pid
                """),
                {"tid": tenant_id, "pid": proposal_id},
            )
        ).mappings().one_or_none()
    if row is None:
        raise problem(404, "Configuration proposal not found", ErrorCode.DOCUMENT_TYPE_NOT_FOUND)
    return row


@router.post(
    "/tenants/{tenant_id}/configuration-proposals",
    status_code=201,
    summary="Generate Configuration Proposal from Sample",
    description=(
        "Upload a representative sample document. DI stores the sample and calls the configured "
        "Gemini provider to propose a tenant extraction schema. The model cannot write or publish "
        "configuration. Required permission: di.extraction_config.write."
    ),
    operation_id="createConfigurationProposal",
)
async def create_configuration_proposal(
    tenant_id: str,
    file: UploadFile = File(...),
    display_name: str | None = Form(default=None, alias="displayName"),
    description: str | None = Form(default=None),
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.EXTRACTION_CONFIG_WRITE)),
    storage: StorageAdapter = Depends(get_storage_adapter),
) -> dict[str, Any]:
    raw = await file.read(_MAX_SAMPLE_BYTES + 1)
    if not raw:
        raise problem(422, "Sample document is empty", ErrorCode.FILE_EMPTY)
    if len(raw) > _MAX_SAMPLE_BYTES:
        raise problem(413, "Sample document exceeds 30 MiB", ErrorCode.FILE_TOO_LARGE)

    proposal_id = uuid.uuid4()
    filename = _safe_filename(file.filename)
    mime_type = (file.content_type or "application/octet-stream").strip()
    logical_key = _sample_key(tenant_id, proposal_id, filename)
    try:
        await storage.put_stream(
            logical_key,
            io.BytesIO(raw),
            content_type=mime_type,
            metadata={"purpose": "configuration-authoring", "proposal-id": str(proposal_id)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("configuration_proposal_sample_storage_failed", tenant_id=tenant_id, proposal_id=str(proposal_id))
        raise problem(503, f"Unable to store authoring sample: {type(exc).__name__}", ErrorCode.STORAGE_WRITE_FAILED) from exc

    try:
        generated = await generate_schema_proposal(
            artifact_bytes=raw,
            mime_type=mime_type,
            requested_display_name=display_name,
            description=description,
            canonical_field_keys=await _canonical_catalogue(tenant_id),
        )
    except ValueError as exc:
        raise problem(422, str(exc), ErrorCode.VALIDATION_ERROR) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("configuration_proposal_generation_failed", tenant_id=tenant_id, proposal_id=str(proposal_id))
        raise problem(500, f"Gemini schema proposal failed: {type(exc).__name__}: {exc}", ErrorCode.INTERNAL_ERROR) from exc

    now = datetime.now(UTC)
    proposal = generated.proposal
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("""
                INSERT INTO docintel.configuration_proposals (
                    tenant_id, proposal_id, status, sample_storage_key, sample_filename,
                    sample_mime_type, sample_size_bytes, proposed_document_type_key,
                    proposed_display_name, physical_form_type, proposal_payload,
                    generated_by_model, prompt_tokens, response_tokens, created_by_actor_id,
                    created_at_utc, updated_at_utc
                ) VALUES (
                    :tid, :pid, 'PROPOSED', :storage_key, :filename,
                    :mime, :size, :doc_key, :display_name, :form_type,
                    CAST(:payload AS jsonb), :model, :prompt_tokens, :response_tokens,
                    :actor_id, :now, :now
                )
            """),
            {
                "tid": tenant_id,
                "pid": proposal_id,
                "storage_key": logical_key,
                "filename": filename,
                "mime": mime_type,
                "size": len(raw),
                "doc_key": proposal["documentTypeKey"],
                "display_name": proposal["displayName"],
                "form_type": proposal["physicalFormType"],
                "payload": json.dumps(proposal),
                "model": generated.model,
                "prompt_tokens": generated.prompt_tokens,
                "response_tokens": generated.response_tokens,
                "actor_id": actor.actor_id,
                "now": now,
            },
        )
        await session.commit()

    row = await _load_proposal(tenant_id, proposal_id)
    logger.info(
        "configuration_proposal_created",
        tenant_id=tenant_id,
        proposal_id=str(proposal_id),
        actor_id=actor.actor_id,
        document_type_key=proposal["documentTypeKey"],
        model=generated.model,
    )
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_row(row)).model_dump()


@router.get(
    "/tenants/{tenant_id}/configuration-proposals",
    summary="List Configuration Proposals",
    operation_id="listConfigurationProposals",
)
async def list_configuration_proposals(
    tenant_id: str,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.EXTRACTION_CONFIG_READ)),
) -> dict[str, Any]:
    del actor
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("""
                    SELECT * FROM docintel.configuration_proposals
                    WHERE tenant_id=:tid
                    ORDER BY created_at_utc DESC
                    LIMIT 100
                """),
                {"tid": tenant_id},
            )
        ).mappings().all()
    return ApiResponse(errorCode="000", errorMessage="Success", data=[_fmt_row(row, include_payload=False) for row in rows]).model_dump()


@router.get(
    "/tenants/{tenant_id}/configuration-proposals/{proposal_id}",
    summary="Get Configuration Proposal",
    operation_id="getConfigurationProposal",
)
async def get_configuration_proposal(
    tenant_id: str,
    proposal_id: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.EXTRACTION_CONFIG_READ)),
) -> dict[str, Any]:
    del actor
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_row(await _load_proposal(tenant_id, proposal_id))).model_dump()


@router.put(
    "/tenants/{tenant_id}/configuration-proposals/{proposal_id}",
    summary="Update Configuration Proposal",
    description="Admin edits an untrusted proposal. Editing after a test clears the old test result and requires re-test.",
    operation_id="updateConfigurationProposal",
)
async def update_configuration_proposal(
    tenant_id: str,
    proposal_id: uuid.UUID,
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.EXTRACTION_CONFIG_WRITE)),
) -> dict[str, Any]:
    row = await _load_proposal(tenant_id, proposal_id)
    if row["status"] not in {"PROPOSED", "DRAFT", "TESTED"}:
        raise problem(409, f"Proposal in {row['status']} state cannot be edited", ErrorCode.CONFLICT)
    try:
        proposal = validate_schema_proposal(body.get("proposal", body))
    except ValueError as exc:
        raise problem(422, str(exc), ErrorCode.VALIDATION_ERROR) from exc

    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("""
                UPDATE docintel.configuration_proposals
                SET status='DRAFT', proposal_payload=CAST(:payload AS jsonb),
                    proposed_document_type_key=:doc_key,
                    proposed_display_name=:display_name,
                    physical_form_type=:form_type,
                    latest_test_result=NULL,
                    updated_at_utc=:now
                WHERE tenant_id=:tid AND proposal_id=:pid
            """),
            {
                "payload": json.dumps(proposal),
                "doc_key": proposal["documentTypeKey"],
                "display_name": proposal["displayName"],
                "form_type": proposal["physicalFormType"],
                "now": now,
                "tid": tenant_id,
                "pid": proposal_id,
            },
        )
        await session.commit()
    logger.info("configuration_proposal_updated", tenant_id=tenant_id, proposal_id=str(proposal_id), actor_id=actor.actor_id)
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_row(await _load_proposal(tenant_id, proposal_id))).model_dump()


@router.post(
    "/tenants/{tenant_id}/configuration-proposals/{proposal_id}/test",
    summary="Test Configuration Proposal",
    description="Run Gemini extraction against the stored sample without creating runtime Document/Field evidence.",
    operation_id="testConfigurationProposal",
)
async def test_configuration_proposal_endpoint(
    tenant_id: str,
    proposal_id: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.EXTRACTION_CONFIG_WRITE)),
    storage: StorageAdapter = Depends(get_storage_adapter),
) -> dict[str, Any]:
    row = await _load_proposal(tenant_id, proposal_id)
    if row["status"] not in {"PROPOSED", "DRAFT", "TESTED"}:
        raise problem(409, f"Proposal in {row['status']} state cannot be tested", ErrorCode.CONFLICT)
    chunks: list[bytes] = []
    try:
        stream = cast(AsyncIterator[bytes], storage.get_stream(row["sample_storage_key"]))
        async for chunk in stream:
            chunks.append(chunk)
    except Exception as exc:  # noqa: BLE001
        raise problem(503, f"Unable to read authoring sample: {type(exc).__name__}", ErrorCode.STORAGE_READ_FAILED) from exc
    sample = b"".join(chunks)
    try:
        test_result = await test_schema_proposal(
            artifact_bytes=sample,
            mime_type=row["sample_mime_type"],
            proposal=row["proposal_payload"],
        )
    except ValueError as exc:
        raise problem(422, str(exc), ErrorCode.VALIDATION_ERROR) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("configuration_proposal_test_failed", tenant_id=tenant_id, proposal_id=str(proposal_id))
        raise problem(500, f"Test extraction failed: {type(exc).__name__}: {exc}", ErrorCode.INTERNAL_ERROR) from exc

    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("""
                UPDATE docintel.configuration_proposals
                SET status='TESTED', latest_test_result=CAST(:result AS jsonb), updated_at_utc=:now
                WHERE tenant_id=:tid AND proposal_id=:pid
            """),
            {"result": json.dumps(test_result, default=str), "now": now, "tid": tenant_id, "pid": proposal_id},
        )
        await session.commit()
    logger.info("configuration_proposal_tested", tenant_id=tenant_id, proposal_id=str(proposal_id), actor_id=actor.actor_id)
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_row(await _load_proposal(tenant_id, proposal_id))).model_dump()


async def _resolve_or_create_document_type(session: Any, tenant_id: str, actor_id: str, proposal: dict[str, Any], now: datetime) -> uuid.UUID:
    del actor_id
    key = proposal["documentTypeKey"]
    row = (
        await session.execute(
            text("""
                SELECT document_type_id, owner_tenant_id, status
                FROM docintel.document_types
                WHERE document_type_key=:key
                  AND (owner_tenant_id=:tid OR owner_tenant_id IS NULL)
                ORDER BY CASE WHEN owner_tenant_id=:tid THEN 0 ELSE 1 END
                LIMIT 1
            """),
            {"key": key, "tid": tenant_id},
        )
    ).one_or_none()
    if row is not None:
        if row[2] == "RETIRED":
            raise problem(409, f"Document Type {key} is RETIRED", ErrorCode.INVALID_DOCUMENT_TYPE_STATE)
        return cast(uuid.UUID, row[0])

    document_type_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO docintel.document_types (
                document_type_id, owner_tenant_id, document_type_key, display_name,
                description, category, status, created_at_utc, updated_at_utc
            ) VALUES (:id, :tid, :key, :name, :description, :category, 'DRAFT', :now, :now)
        """),
        {
            "id": document_type_id,
            "tid": tenant_id,
            "key": key,
            "name": proposal["displayName"],
            "description": proposal.get("description"),
            "category": proposal["physicalFormType"],
            "now": now,
        },
    )
    return document_type_id


async def _resolve_or_create_canonical_field(session: Any, tenant_id: str, item: dict[str, Any], now: datetime) -> uuid.UUID:
    row = (
        await session.execute(
            text("""
                SELECT canonical_field_id, data_type
                FROM docintel.canonical_fields
                WHERE field_key=:key AND status='ACTIVE'
                  AND (owner_tenant_id=:tid OR owner_tenant_id IS NULL)
                ORDER BY CASE WHEN owner_tenant_id=:tid THEN 0 ELSE 1 END
                LIMIT 1
            """),
            {"key": item["fieldKey"], "tid": tenant_id},
        )
    ).one_or_none()
    if row is not None:
        if row[1] != item["dataType"]:
            raise problem(
                409,
                f"Canonical field {item['fieldKey']} already exists as {row[1]}, not {item['dataType']}",
                ErrorCode.INVALID_CONFIGURATION,
            )
        return cast(uuid.UUID, row[0])

    canonical_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO docintel.canonical_fields (
                canonical_field_id, owner_tenant_id, field_key, display_name,
                data_type, description, status, created_at_utc, updated_at_utc
            ) VALUES (:id, :tid, :key, :name, :data_type, :description, 'ACTIVE', :now, :now)
        """),
        {
            "id": canonical_id,
            "tid": tenant_id,
            "key": item["fieldKey"],
            "name": item["displayName"],
            "data_type": item["dataType"],
            "description": item.get("description"),
            "now": now,
        },
    )
    return canonical_id


@router.post(
    "/tenants/{tenant_id}/configuration-proposals/{proposal_id}/approve",
    summary="Approve Tested Proposal into Draft Configuration",
    description=(
        "Requires a TESTED proposal. Materialises tenant configuration as DRAFT only: Document Type, "
        "canonical fields, Extraction Profile fields and tenant Document Type mapping. Nothing is published."
    ),
    operation_id="approveConfigurationProposal",
)
async def approve_configuration_proposal(
    tenant_id: str,
    proposal_id: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.EXTRACTION_CONFIG_WRITE)),
) -> dict[str, Any]:
    row = await _load_proposal(tenant_id, proposal_id)
    if row["status"] != "TESTED" or row.get("latest_test_result") is None:
        raise problem(409, "Proposal must be TESTED after its latest edit before approval", ErrorCode.CONFLICT)
    try:
        proposal = validate_schema_proposal(row["proposal_payload"])
    except ValueError as exc:
        raise problem(422, str(exc), ErrorCode.VALIDATION_ERROR) from exc

    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        document_type_id = await _resolve_or_create_document_type(session, tenant_id, actor.actor_id, proposal, now)

        # Approval must not alter current runtime availability. A newly created DRAFT
        # Document Type remains inactive; an already ACTIVE type stays active while
        # the new tenant-scoped profile is reviewed as DRAFT.
        await session.execute(
            text("""
                UPDATE docintel.tenant_document_types tdt
                SET is_active=false, updated_at_utc=:now
                FROM docintel.document_types dt
                WHERE tdt.document_type_id=dt.document_type_id
                  AND tdt.tenant_id=:tid
                  AND dt.document_type_key=:key
                  AND tdt.document_type_id<>:dtid
                  AND dt.status<>'ACTIVE'
            """),
            {"now": now, "tid": tenant_id, "key": proposal["documentTypeKey"], "dtid": document_type_id},
        )
        await session.execute(
            text("""
                INSERT INTO docintel.tenant_document_types (
                    tenant_id, document_type_id, physical_form_type, requires_processing,
                    is_active, display_order, created_at_utc, updated_at_utc
                ) VALUES (
                    :tid, :dtid, :form_type, true,
                    EXISTS (
                        SELECT 1 FROM docintel.document_types
                        WHERE document_type_id=:dtid AND status='ACTIVE'
                    ),
                    100, :now, :now
                )
                ON CONFLICT (tenant_id, document_type_id) DO UPDATE
                SET physical_form_type=EXCLUDED.physical_form_type,
                    requires_processing=true,
                    is_active=EXCLUDED.is_active,
                    updated_at_utc=EXCLUDED.updated_at_utc
            """),
            {"tid": tenant_id, "dtid": document_type_id, "form_type": proposal["physicalFormType"], "now": now},
        )

        version_no = (
            await session.execute(
                text("""
                    SELECT COALESCE(MAX(version_no),0)+1
                    FROM docintel.extraction_profiles
                    WHERE document_type_id=:dtid AND scope_tenant_id=:tid
                """),
                {"dtid": document_type_id, "tid": tenant_id},
            )
        ).scalar_one()
        profile_id = uuid.uuid4()
        await session.execute(
            text("""
                INSERT INTO docintel.extraction_profiles (
                    profile_id, document_type_id, scope_tenant_id, version_no,
                    profile_name, status, classification_hint, created_by_actor_id,
                    created_at_utc, updated_at_utc
                ) VALUES (
                    :pid, :dtid, :tid, :version_no, :profile_name, 'DRAFT', :hint,
                    :actor_id, :now, :now
                )
            """),
            {
                "pid": profile_id,
                "dtid": document_type_id,
                "tid": tenant_id,
                "version_no": version_no,
                "profile_name": f"{proposal['displayName']} Extraction v{version_no}",
                "hint": proposal["documentTypeKey"],
                "actor_id": actor.actor_id,
                "now": now,
            },
        )

        for sequence, item in enumerate(proposal["fields"], start=1):
            canonical_id = await _resolve_or_create_canonical_field(session, tenant_id, item, now)
            aliases = list(dict.fromkeys(item["evidenceLabels"] + item["aliases"]))
            await session.execute(
                text("""
                    INSERT INTO docintel.extraction_profile_fields (
                        profile_field_id, profile_id, canonical_field_id, enabled, expected,
                        extraction_instruction, aliases, score_included, score_weight,
                        use_for_subject_matching, subject_identifier_type,
                        manual_correction_allowed, display_sequence, created_at_utc, updated_at_utc
                    ) VALUES (
                        gen_random_uuid(), :pid, :cfid, true, :expected, :instruction,
                        CAST(:aliases AS jsonb), :score_included, :score_weight,
                        false, NULL, true, :sequence, :now, :now
                    )
                """),
                {
                    "pid": profile_id,
                    "cfid": canonical_id,
                    "expected": item["required"],
                    "instruction": item["extractionInstruction"],
                    "aliases": json.dumps(aliases),
                    "score_included": item["scoreIncluded"],
                    "score_weight": item["scoreWeight"],
                    "sequence": sequence * 10,
                    "now": now,
                },
            )

        await session.execute(
            text("""
                UPDATE docintel.configuration_proposals
                SET status='APPROVED', approved_by_actor_id=:actor_id, approved_at_utc=:now,
                    materialized_document_type_id=:dtid, materialized_profile_id=:pid,
                    updated_at_utc=:now
                WHERE tenant_id=:tid AND proposal_id=:proposal_id
            """),
            {
                "actor_id": actor.actor_id,
                "now": now,
                "dtid": document_type_id,
                "pid": profile_id,
                "tid": tenant_id,
                "proposal_id": proposal_id,
            },
        )
        await session.commit()

    logger.info(
        "configuration_proposal_approved",
        tenant_id=tenant_id,
        proposal_id=str(proposal_id),
        actor_id=actor.actor_id,
        profile_id=str(profile_id),
    )
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_row(await _load_proposal(tenant_id, proposal_id))).model_dump()


@router.post(
    "/tenants/{tenant_id}/configuration-proposals/{proposal_id}/publish",
    summary="Publish Approved Configuration Proposal",
    description="Separate publish permission. Atomically retires the prior tenant-scoped published profile for the same type.",
    operation_id="publishConfigurationProposal",
)
async def publish_configuration_proposal(
    tenant_id: str,
    proposal_id: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.EXTRACTION_CONFIG_PUBLISH)),
) -> dict[str, Any]:
    row = await _load_proposal(tenant_id, proposal_id)
    if row["status"] != "APPROVED" or not row.get("materialized_profile_id") or not row.get("materialized_document_type_id"):
        raise problem(409, "Proposal must be APPROVED before publish", ErrorCode.CONFLICT)
    profile_id = row["materialized_profile_id"]
    document_type_id = row["materialized_document_type_id"]
    now = datetime.now(UTC)

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM docintel.extraction_profiles WHERE profile_id=:pid AND scope_tenant_id=:tid"),
                {"pid": profile_id, "tid": tenant_id},
            )
        ).scalar_one_or_none()
        if status != "DRAFT":
            raise problem(409, "Materialized Extraction Profile is no longer DRAFT", ErrorCode.INVALID_PROFILE_STATE)
        await session.execute(
            text("""
                UPDATE docintel.extraction_profiles
                SET status='RETIRED', updated_at_utc=:now
                WHERE document_type_id=:dtid AND scope_tenant_id=:tid
                  AND status='PUBLISHED'
            """),
            {"now": now, "dtid": document_type_id, "tid": tenant_id},
        )
        await session.execute(
            text("UPDATE docintel.document_types SET status='ACTIVE', updated_at_utc=:now WHERE document_type_id=:dtid AND status='DRAFT'"),
            {"now": now, "dtid": document_type_id},
        )
        await session.execute(
            text("""
                UPDATE docintel.tenant_document_types
                SET is_active=true, requires_processing=true, updated_at_utc=:now
                WHERE tenant_id=:tid AND document_type_id=:dtid
            """),
            {"now": now, "tid": tenant_id, "dtid": document_type_id},
        )
        await session.execute(
            text("""
                UPDATE docintel.extraction_profiles
                SET status='PUBLISHED', published_by_actor_id=:actor_id,
                    published_at_utc=:now, updated_at_utc=:now
                WHERE profile_id=:pid
            """),
            {"actor_id": actor.actor_id, "now": now, "pid": profile_id},
        )
        await session.execute(
            text("""
                UPDATE docintel.configuration_proposals
                SET status='PUBLISHED', published_by_actor_id=:actor_id,
                    published_at_utc=:now, updated_at_utc=:now
                WHERE tenant_id=:tid AND proposal_id=:proposal_id
            """),
            {"actor_id": actor.actor_id, "now": now, "tid": tenant_id, "proposal_id": proposal_id},
        )
        await session.commit()

    logger.info("configuration_proposal_published", tenant_id=tenant_id, proposal_id=str(proposal_id), actor_id=actor.actor_id)
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_row(await _load_proposal(tenant_id, proposal_id))).model_dump()


@router.post(
    "/tenants/{tenant_id}/configuration-proposals/{proposal_id}/retire",
    summary="Retire Published Configuration Proposal",
    operation_id="retireConfigurationProposal",
)
async def retire_configuration_proposal(
    tenant_id: str,
    proposal_id: uuid.UUID,
    actor: ActorPrincipal = Depends(require_tenant_permission(Permission.EXTRACTION_CONFIG_PUBLISH)),
) -> dict[str, Any]:
    row = await _load_proposal(tenant_id, proposal_id)
    if row["status"] != "PUBLISHED" or not row.get("materialized_profile_id"):
        raise problem(409, "Only a currently PUBLISHED proposal may be retired", ErrorCode.CONFLICT)
    profile_id = row["materialized_profile_id"]
    document_type_id = row["materialized_document_type_id"]
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        profile_status = (
            await session.execute(text("SELECT status FROM docintel.extraction_profiles WHERE profile_id=:pid"), {"pid": profile_id})
        ).scalar_one_or_none()
        if profile_status != "PUBLISHED":
            raise problem(409, "The proposal profile is no longer the published profile", ErrorCode.CONFLICT)
        await session.execute(
            text("UPDATE docintel.extraction_profiles SET status='RETIRED', updated_at_utc=:now WHERE profile_id=:pid"),
            {"now": now, "pid": profile_id},
        )
        await session.execute(
            text("UPDATE docintel.tenant_document_types SET is_active=false, updated_at_utc=:now WHERE tenant_id=:tid AND document_type_id=:dtid"),
            {"now": now, "tid": tenant_id, "dtid": document_type_id},
        )
        await session.execute(
            text("UPDATE docintel.configuration_proposals SET status='RETIRED', updated_at_utc=:now WHERE tenant_id=:tid AND proposal_id=:proposal_id"),
            {"now": now, "tid": tenant_id, "proposal_id": proposal_id},
        )
        await session.commit()
    logger.info("configuration_proposal_retired", tenant_id=tenant_id, proposal_id=str(proposal_id), actor_id=actor.actor_id)
    return ApiResponse(errorCode="000", errorMessage="Success", data=_fmt_row(await _load_proposal(tenant_id, proposal_id))).model_dump()
