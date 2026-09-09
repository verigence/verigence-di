from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from verigence.di.api.v1.tenant_housekeeping import (
    SelectedDocumentPurgeCommand,
    purge_selected_document_data,
)
from verigence.di.domain.enums import RetentionDisposition, SubjectType
from verigence.di.repositories.audit_storage_contexts import ensure_audit_storage_context
from verigence.di.repositories.documents import create_document_receiving
from verigence.di.repositories.subjects import create_subject
from verigence.di.repositories.tenants import provision_retention_policy, provision_tenant


@pytest.mark.asyncio
async def test_selected_document_housekeeping_rejects_wrong_tenant_confirmation() -> None:
    tenant_id = "tenant-a"
    command = SelectedDocumentPurgeCommand(
        confirmTenantId="tenant-b",
        confirmation="PURGE_SELECTED_DOCUMENTS",
        documentIds=[uuid.uuid4()],
    )

    with pytest.raises(HTTPException) as caught:
        await purge_selected_document_data(
            tenant_id,
            command,
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_selected_document_housekeeping_purges_capture_v2_state(db_session) -> None:  # type: ignore[no-untyped-def]
    # Regression test: a Document with a UC03 Document Capture V2 upload row
    # (migration 0021) used to make this purge fail with a foreign key
    # violation on document_capture_v2_uploads_tenant_id_document_id_fkey --
    # neither document_capture_v2_uploads nor its sibling
    # document_capture_v2_classification_jobs were in the housekeeping
    # deletion order, despite both FK-referencing documents(tenant_id,
    # document_id). Reproduces production: a Super Admin purging Journey
    # data through Audit Core's housekeeping, which calls this endpoint.
    tenant_id = f"housekeeping-v2-{uuid.uuid4().hex[:10]}"
    await provision_tenant(db_session, tenant_id)
    retention_policy_id = await provision_retention_policy(db_session, tenant_id)
    subject = await create_subject(
        db_session,
        tenant_id=tenant_id,
        subject_type=SubjectType.PERSON,
        display_name="Test Subject",
        created_by_actor_id="test-actor",
    )
    document = await create_document_receiving(
        db_session,
        tenant_id=tenant_id,
        subject_id=subject["subject_id"],
        uploaded_by_actor_id="test-actor",
        uploaded_by_actor_type="USER",
        correlation_id=str(uuid.uuid4()),
        retention_policy_id=retention_policy_id,
        retention_days=365,
        retention_disposition=RetentionDisposition.PURGE_CONTENT,
    )
    document_id = document["document_id"]
    storage_context = await ensure_audit_storage_context(
        db_session,
        tenant_id=tenant_id,
        external_context_ref=f"ctx-{uuid.uuid4()}",
        dealer_id=uuid.uuid4(),
        dealer_outlet_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        subject_id=subject["subject_id"],
        service_principal_id="test-service",
        project_slug="proj",
        dealer_slug="dlr",
        dealer_outlet_slug="out",
        customer_slug="cust",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO docintel.document_capture_v2_uploads (
                tenant_id, document_id, audit_storage_context_id,
                external_context_ref, phase, client_upload_id,
                logical_object_key, original_filename, declared_mime_type,
                candidate_document_type_keys, requirement_refs_by_document_type_key,
                state, created_at_utc, updated_at_utc
            ) VALUES (
                :tenant_id, :document_id, :storage_context_id,
                :external_context_ref, 'BOOKING', :client_upload_id,
                :logical_key, :filename, 'application/pdf',
                CAST(:candidate_keys AS jsonb), CAST('{}' AS jsonb),
                'RECEIVING', now(), now()
            )
            """
        ),
        {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "storage_context_id": storage_context["storage_context_id"],
            "external_context_ref": storage_context["external_context_ref"],
            "client_upload_id": f"upload-{uuid.uuid4()}",
            "logical_key": f"{tenant_id}/{document_id}",
            "filename": "booking_form.pdf",
            "candidate_keys": '["booking_form"]',
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO docintel.document_capture_v2_classification_jobs
                (tenant_id, document_id)
            VALUES (:tenant_id, :document_id)
            """
        ),
        {"tenant_id": tenant_id, "document_id": document_id},
    )
    await db_session.flush()

    result = await purge_selected_document_data(
        tenant_id,
        SelectedDocumentPurgeCommand(
            confirmTenantId=tenant_id,
            confirmation="PURGE_SELECTED_DOCUMENTS",
            documentIds=[document_id],
        ),
        None,  # type: ignore[arg-type]
        db_session,
    )

    assert result.data is not None
    assert result.data.purgeStatus == "REMOVED"
    assert result.data.deletedDocuments == 1

    remaining_uploads = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM docintel.document_capture_v2_uploads "
                "WHERE tenant_id=:tid AND document_id=:doc_id"
            ),
            {"tid": tenant_id, "doc_id": document_id},
        )
    ).scalar_one()
    remaining_jobs = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM docintel.document_capture_v2_classification_jobs "
                "WHERE tenant_id=:tid AND document_id=:doc_id"
            ),
            {"tid": tenant_id, "doc_id": document_id},
        )
    ).scalar_one()
    remaining_documents = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM docintel.documents "
                "WHERE tenant_id=:tid AND document_id=:doc_id"
            ),
            {"tid": tenant_id, "doc_id": document_id},
        )
    ).scalar_one()
    assert remaining_uploads == 0
    assert remaining_jobs == 0
    assert remaining_documents == 0
