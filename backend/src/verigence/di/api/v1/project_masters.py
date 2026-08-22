"""UC02 Project Master facade for DI-owned configuration.

DI remains authoritative for Document Types, Extraction Profiles and Requirement
Profiles. Audit Core/Web may surface this facade, but the initiating human
Security JWT is preserved and live SuperAdmin attestation remains mandatory.

Excel flow:
  template -> upload/stage -> validate/preview -> explicit confirm -> DRAFT
  -> separate publish/activate

No WEF is introduced here. These DI domains do not have an approved effective-
date concept; callers must not synthesize one.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Header, UploadFile
from fastapi.responses import Response
from sqlalchemy import text

from verigence.di.api.v1.schemas import ApiResponse
from verigence.di.application.config_imports import (
    DOCUMENT_TYPES,
    EXTRACTION_PROFILES,
    REQUIREMENT_PROFILES,
    ConfigImportConflict,
    ConfigImportError,
    build_template,
    cancel_config_import,
    confirm_config_import,
    error_report_csv,
    get_config_import,
    list_config_import_rows,
    normalize_master_key,
    stage_config_import,
)
from verigence.di.auth.human_admin import HumanAdminRequest, require_uc02_super_admin
from verigence.di.errors import ErrorCode, http_exception
from verigence.di.repositories.database import tenant_session
from verigence.di.repositories.tenants import provision_actor

router = APIRouter(
    prefix="/v1/tenants/{tenantId}/project-masters",
    tags=["UC02 Project Masters"],
)

_MASTER_CATALOG: dict[str, dict[str, Any]] = {
    DOCUMENT_TYPES: {
        "masterKey": DOCUMENT_TYPES,
        "displayName": "Document Types",
        "ownerModule": "DI",
        "administrationModes": ["FORM", "EXCEL"],
        "requiresWEF": False,
        "publishLifecycle": "DRAFT_TO_ACTIVE",
    },
    EXTRACTION_PROFILES: {
        "masterKey": EXTRACTION_PROFILES,
        "displayName": "Extraction Profiles",
        "ownerModule": "DI",
        "administrationModes": ["FORM", "EXCEL"],
        "requiresWEF": False,
        "publishLifecycle": "DRAFT_TO_PUBLISHED",
    },
    REQUIREMENT_PROFILES: {
        "masterKey": REQUIREMENT_PROFILES,
        "displayName": "Requirement Profiles",
        "ownerModule": "DI",
        "administrationModes": ["FORM", "EXCEL"],
        "requiresWEF": False,
        "publishLifecycle": "DRAFT_TO_PUBLISHED",
    },
}


def _master_key_or_422(master_key: str) -> str:
    try:
        return normalize_master_key(master_key)
    except ConfigImportError as exc:
        raise http_exception(ErrorCode.VALIDATION_ERROR, detail=str(exc)) from exc


def _import_error(exc: ConfigImportError) -> Exception:
    if isinstance(exc, ConfigImportConflict):
        return http_exception(ErrorCode.CONFLICT, detail=str(exc))
    message = str(exc)
    if "not found" in message.lower():
        return http_exception(ErrorCode.DOCUMENT_NOT_FOUND, detail=message)
    return http_exception(ErrorCode.VALIDATION_ERROR, detail=message)


def _import_payload(header: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "importId": header["import_id"],
        "tenantId": header["tenant_id"],
        "masterKey": header["master_key"],
        "fileName": header["file_name"],
        "fileHashSha256": header["file_hash_sha256"],
        "templateVersion": header["template_version"],
        "status": header["status"],
        "rowsParsed": header["rows_parsed"],
        "validRows": header["valid_rows"],
        "warningRows": header["warning_rows"],
        "errorRows": header["error_rows"],
        "resultReference": header.get("result_reference"),
        "createdByUserId": header["created_by_user_id"],
        "createdAtUtc": header["created_at_utc"],
        "confirmedByUserId": header.get("confirmed_by_user_id"),
        "confirmedAtUtc": header.get("confirmed_at_utc"),
    }
    if rows is not None:
        payload["rows"] = [
            {
                "rowNumber": row["row_number"],
                "parsedData": row["parsed_data"],
                "validationStatus": row["validation_status"],
                "validationMessages": row["validation_messages"],
            }
            for row in rows
        ]
    return payload


@router.get("")
async def list_project_masters(
    tenantId: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
) -> ApiResponse[list[dict[str, Any]]]:
    del tenantId, admin
    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=list(_MASTER_CATALOG.values()),
    )


@router.get("/{masterKey}/template")
async def download_project_master_template(
    tenantId: str,
    masterKey: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
) -> Response:
    del tenantId, admin
    key = _master_key_or_422(masterKey)
    content = build_template(key)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{key.lower()}-template.xlsx"',
            "X-DI-Master-Key": key,
            "X-DI-Requires-WEF": "false",
        },
    )


@router.post("/{masterKey}/imports", status_code=201)
async def upload_project_master_import(
    tenantId: str,
    masterKey: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    file: UploadFile = File(...),
) -> ApiResponse[dict[str, Any]]:
    key = _master_key_or_422(masterKey)
    content = await file.read()
    async with tenant_session(tenantId) as session:
        try:
            header = await stage_config_import(
                session,
                tenant_id=tenantId,
                master_key=key,
                idempotency_key=idempotency_key,
                file_name=file.filename or "upload.xlsx",
                content=content,
                created_by_user_id=admin.user_id,
            )
            rows = await list_config_import_rows(
                session, tenant_id=tenantId, import_id=header["import_id"]
            )
        except ConfigImportError as exc:
            raise _import_error(exc) from exc
    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=_import_payload(header, rows),
    )


@router.get("/{masterKey}/imports/{importId}")
async def get_project_master_import(
    tenantId: str,
    masterKey: str,
    importId: uuid.UUID,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
) -> ApiResponse[dict[str, Any]]:
    del admin
    key = _master_key_or_422(masterKey)
    async with tenant_session(tenantId) as session:
        try:
            header = await get_config_import(session, tenant_id=tenantId, import_id=importId)
            if header["master_key"] != key:
                raise ConfigImportError("Configuration import not found for this master")
            rows = await list_config_import_rows(session, tenant_id=tenantId, import_id=importId)
        except ConfigImportError as exc:
            raise _import_error(exc) from exc
    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data=_import_payload(header, rows),
    )


@router.get("/{masterKey}/imports/{importId}/error-report")
async def download_project_master_error_report(
    tenantId: str,
    masterKey: str,
    importId: uuid.UUID,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
) -> Response:
    del admin
    key = _master_key_or_422(masterKey)
    async with tenant_session(tenantId) as session:
        try:
            header = await get_config_import(session, tenant_id=tenantId, import_id=importId)
            if header["master_key"] != key:
                raise ConfigImportError("Configuration import not found for this master")
            rows = await list_config_import_rows(session, tenant_id=tenantId, import_id=importId)
        except ConfigImportError as exc:
            raise _import_error(exc) from exc
    return Response(
        content=error_report_csv(rows),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{key.lower()}-{importId}-validation.csv"'
        },
    )


@router.post("/{masterKey}/imports/{importId}/confirm")
async def confirm_project_master_import(
    tenantId: str,
    masterKey: str,
    importId: uuid.UUID,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
) -> ApiResponse[dict[str, Any]]:
    key = _master_key_or_422(masterKey)
    async with tenant_session(tenantId) as session:
        try:
            header = await get_config_import(session, tenant_id=tenantId, import_id=importId)
            if header["master_key"] != key:
                raise ConfigImportError("Configuration import not found for this master")
            header = await confirm_config_import(
                session,
                tenant_id=tenantId,
                import_id=importId,
                confirmed_by_user_id=admin.user_id,
            )
            rows = await list_config_import_rows(session, tenant_id=tenantId, import_id=importId)
        except ConfigImportError as exc:
            raise _import_error(exc) from exc
    return ApiResponse(
        errorCode="000",
        errorMessage="Import confirmed; DRAFT configuration created",
        data=_import_payload(header, rows),
    )


@router.post("/{masterKey}/imports/{importId}/cancel")
async def cancel_project_master_import(
    tenantId: str,
    masterKey: str,
    importId: uuid.UUID,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
) -> ApiResponse[dict[str, Any]]:
    del admin
    key = _master_key_or_422(masterKey)
    async with tenant_session(tenantId) as session:
        try:
            header = await get_config_import(session, tenant_id=tenantId, import_id=importId)
            if header["master_key"] != key:
                raise ConfigImportError("Configuration import not found for this master")
            await cancel_config_import(session, tenant_id=tenantId, import_id=importId)
            header = await get_config_import(session, tenant_id=tenantId, import_id=importId)
        except ConfigImportError as exc:
            raise _import_error(exc) from exc
    return ApiResponse(
        errorCode="000",
        errorMessage="Import cancelled",
        data=_import_payload(header),
    )


async def _list_versions(session: Any, *, tenant_id: str, master_key: str) -> list[dict[str, Any]]:
    if master_key == DOCUMENT_TYPES:
        rows = (
            await session.execute(
                text("""
                    SELECT dt.document_type_id AS version_id,
                           dt.document_type_key AS business_key,
                           dt.display_name,
                           dt.status,
                           NULL::integer AS version_no,
                           dt.created_at_utc,
                           dt.updated_at_utc,
                           tdt.physical_form_type,
                           tdt.requires_processing,
                           tdt.display_order,
                           tdt.is_active
                    FROM docintel.document_types dt
                    LEFT JOIN docintel.tenant_document_types tdt
                      ON tdt.tenant_id=:tenant_id
                     AND tdt.document_type_id=dt.document_type_id
                    WHERE dt.owner_tenant_id=:tenant_id
                    ORDER BY dt.document_type_key, dt.updated_at_utc DESC
                """),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
    elif master_key == EXTRACTION_PROFILES:
        rows = (
            await session.execute(
                text("""
                    SELECT ep.profile_id AS version_id,
                           dt.document_type_key AS business_key,
                           ep.profile_name AS display_name,
                           ep.status,
                           ep.version_no,
                           ep.created_at_utc,
                           ep.updated_at_utc,
                           ep.published_at_utc
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.document_types dt
                      ON dt.document_type_id=ep.document_type_id
                    WHERE ep.scope_tenant_id=:tenant_id
                    ORDER BY dt.document_type_key, ep.version_no DESC
                """),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
    else:
        rows = (
            await session.execute(
                text("""
                    SELECT rp.requirement_profile_id AS version_id,
                           rp.profile_key AS business_key,
                           rp.profile_key AS display_name,
                           rp.status,
                           rp.version_no,
                           rp.created_at_utc,
                           rp.updated_at_utc,
                           rp.published_at_utc
                    FROM docintel.document_requirement_profiles rp
                    WHERE rp.tenant_id=:tenant_id
                    ORDER BY rp.profile_key, rp.version_no DESC
                """),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
    return [
        {
            "versionId": row["version_id"],
            "businessKey": row["business_key"],
            "displayName": row["display_name"],
            "status": row["status"],
            "versionNo": row.get("version_no"),
            "createdAtUtc": row["created_at_utc"],
            "updatedAtUtc": row["updated_at_utc"],
            **(
                {
                    "publishedAtUtc": row.get("published_at_utc"),
                }
                if master_key != DOCUMENT_TYPES
                else {
                    "physicalFormType": row.get("physical_form_type"),
                    "requiresProcessing": row.get("requires_processing"),
                    "displayOrder": row.get("display_order"),
                    "activeForTenant": bool(row.get("is_active")),
                }
            ),
        }
        for row in rows
    ]


@router.get("/{masterKey}/versions")
async def list_project_master_versions(
    tenantId: str,
    masterKey: str,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
) -> ApiResponse[dict[str, Any]]:
    del admin
    key = _master_key_or_422(masterKey)
    async with tenant_session(tenantId) as session:
        versions = await _list_versions(session, tenant_id=tenantId, master_key=key)
    return ApiResponse(
        errorCode="000",
        errorMessage="Success",
        data={"masterKey": key, "versions": versions},
    )


async def _publish_version(
    session: Any,
    *,
    tenant_id: str,
    master_key: str,
    version_id: uuid.UUID,
    actor_id: str,
) -> None:
    await provision_actor(session, tenant_id, actor_id)
    if master_key == DOCUMENT_TYPES:
        row = (
            await session.execute(
                text("""
                    SELECT dt.status,
                           COALESCE(tdt.physical_form_type, dt.category, 'ADDITIONAL') AS physical_form_type,
                           COALESCE(tdt.requires_processing, true) AS requires_processing,
                           COALESCE(tdt.display_order, 100) AS display_order
                    FROM docintel.document_types dt
                    LEFT JOIN docintel.tenant_document_types tdt
                      ON tdt.tenant_id=:tenant_id
                     AND tdt.document_type_id=dt.document_type_id
                    WHERE dt.owner_tenant_id=:tenant_id
                      AND dt.document_type_id=:version_id
                """),
                {"tenant_id": tenant_id, "version_id": version_id},
            )
        ).mappings().one_or_none()
        if row is None:
            raise ConfigImportError("Document Type version not found")
        if row["status"] == "ACTIVE":
            return
        if row["status"] != "DRAFT":
            raise ConfigImportConflict("Only a DRAFT Document Type may be activated")
        await session.execute(
            text("""
                UPDATE docintel.document_types
                SET status='ACTIVE', updated_at_utc=now()
                WHERE owner_tenant_id=:tenant_id AND document_type_id=:version_id
            """),
            {"tenant_id": tenant_id, "version_id": version_id},
        )
        await session.execute(
            text("""
                INSERT INTO docintel.tenant_document_types (
                    tenant_id, document_type_id, physical_form_type,
                    requires_processing, is_active, display_order,
                    created_at_utc, updated_at_utc
                ) VALUES (
                    :tenant_id, :version_id, :physical_form_type,
                    :requires_processing, true, :display_order, now(), now()
                )
                ON CONFLICT (tenant_id, document_type_id) DO UPDATE
                SET physical_form_type=EXCLUDED.physical_form_type,
                    requires_processing=EXCLUDED.requires_processing,
                    is_active=true,
                    display_order=EXCLUDED.display_order,
                    updated_at_utc=now()
            """),
            {
                "tenant_id": tenant_id,
                "version_id": version_id,
                "physical_form_type": row["physical_form_type"],
                "requires_processing": row["requires_processing"],
                "display_order": row["display_order"],
            },
        )
        return

    if master_key == EXTRACTION_PROFILES:
        row = (
            await session.execute(
                text("""
                    SELECT ep.status, ep.document_type_id
                    FROM docintel.extraction_profiles ep
                    WHERE ep.scope_tenant_id=:tenant_id AND ep.profile_id=:version_id
                """),
                {"tenant_id": tenant_id, "version_id": version_id},
            )
        ).mappings().one_or_none()
        if row is None:
            raise ConfigImportError("Extraction Profile version not found")
        if row["status"] == "PUBLISHED":
            return
        if row["status"] != "DRAFT":
            raise ConfigImportConflict("Only a DRAFT Extraction Profile may be published")
        scored = bool(
            (
                await session.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1 FROM docintel.extraction_profile_fields
                            WHERE profile_id=:version_id AND enabled=true
                              AND expected=true AND score_included=true AND score_weight > 0
                        )
                    """),
                    {"version_id": version_id},
                )
            ).scalar_one()
        )
        if not scored:
            raise ConfigImportConflict(
                "Extraction Profile must contain an enabled expected scored field with weight > 0"
            )
        await session.execute(
            text("""
                UPDATE docintel.extraction_profiles
                SET status='RETIRED', updated_at_utc=now()
                WHERE document_type_id=:document_type_id
                  AND scope_tenant_id=:tenant_id
                  AND status='PUBLISHED'
            """),
            {"document_type_id": row["document_type_id"], "tenant_id": tenant_id},
        )
        await session.execute(
            text("""
                UPDATE docintel.extraction_profiles
                SET status='PUBLISHED', published_by_actor_id=:actor_id,
                    published_at_utc=now(), updated_at_utc=now()
                WHERE scope_tenant_id=:tenant_id AND profile_id=:version_id
            """),
            {"tenant_id": tenant_id, "version_id": version_id, "actor_id": actor_id},
        )
        return

    row = (
        await session.execute(
            text("""
                SELECT status, profile_key
                FROM docintel.document_requirement_profiles
                WHERE tenant_id=:tenant_id AND requirement_profile_id=:version_id
            """),
            {"tenant_id": tenant_id, "version_id": version_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise ConfigImportError("Requirement Profile version not found")
    if row["status"] == "PUBLISHED":
        return
    if row["status"] != "DRAFT":
        raise ConfigImportConflict("Only a DRAFT Requirement Profile may be published")
    await session.execute(
        text("""
            UPDATE docintel.document_requirement_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE tenant_id=:tenant_id AND profile_key=:profile_key
              AND status='PUBLISHED'
        """),
        {"tenant_id": tenant_id, "profile_key": row["profile_key"]},
    )
    await session.execute(
        text("""
            UPDATE docintel.document_requirement_profiles
            SET status='PUBLISHED', published_by_actor_id=:actor_id,
                published_at_utc=now(), updated_at_utc=now()
            WHERE tenant_id=:tenant_id AND requirement_profile_id=:version_id
        """),
        {"tenant_id": tenant_id, "version_id": version_id, "actor_id": actor_id},
    )


@router.post("/{masterKey}/versions/{versionId}/publish")
async def publish_project_master_version(
    tenantId: str,
    masterKey: str,
    versionId: uuid.UUID,
    admin: Annotated[HumanAdminRequest, Depends(require_uc02_super_admin)],
) -> ApiResponse[dict[str, Any]]:
    key = _master_key_or_422(masterKey)
    async with tenant_session(tenantId) as session:
        try:
            await _publish_version(
                session,
                tenant_id=tenantId,
                master_key=key,
                version_id=versionId,
                actor_id=admin.user_id,
            )
            await session.commit()
            versions = await _list_versions(session, tenant_id=tenantId, master_key=key)
        except ConfigImportError as exc:
            raise _import_error(exc) from exc
    published = next((item for item in versions if item["versionId"] == versionId), None)
    return ApiResponse(
        errorCode="000",
        errorMessage="Published",
        data={"masterKey": key, "version": published},
    )
