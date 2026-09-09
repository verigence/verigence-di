from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from verigence.di.api.v1.tenant_housekeeping import (
    TenantTransactionPurgeCommand,
    _transaction_status,
    purge_tenant_transaction_data,
)
from verigence.di.domain.enums import RetentionDisposition, SubjectType
from verigence.di.repositories.audit_storage_contexts import ensure_audit_storage_context
from verigence.di.repositories.database import set_tenant_context
from verigence.di.repositories.documents import create_document_receiving
from verigence.di.repositories.subjects import create_subject
from verigence.di.repositories.tenants import (
    provision_retention_policy,
    provision_tenant,
    provision_tenant_document_types,
)


@pytest.mark.asyncio
async def test_transaction_housekeeping_preserves_tenant_configuration(db_session) -> None:  # type: ignore[no-untyped-def]
    tenant_id = f"housekeeping-{uuid.uuid4().hex[:10]}"
    await set_tenant_context(db_session, tenant_id)
    await provision_tenant(db_session, tenant_id)
    retention_policy_id = await provision_retention_policy(db_session, tenant_id)
    await provision_tenant_document_types(db_session, tenant_id)

    # Regression coverage: a Document with a UC03 Document Capture V2 upload
    # row (migration 0021) used to make a full tenant purge fail with a
    # foreign key violation on document_capture_v2_uploads -- neither it nor
    # document_capture_v2_classification_jobs were in the deletion order.
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

    tenant_settings_before = int(
        (
            await db_session.execute(
                text("SELECT count(*) FROM docintel.tenant_settings WHERE tenant_id=:tid"),
                {"tid": tenant_id},
            )
        ).scalar_one()
    )
    tenant_document_types_before = int(
        (
            await db_session.execute(
                text("SELECT count(*) FROM docintel.tenant_document_types WHERE tenant_id=:tid"),
                {"tid": tenant_id},
            )
        ).scalar_one()
    )

    result = await purge_tenant_transaction_data(
        tenant_id,
        TenantTransactionPurgeCommand(
            confirmTenantId=tenant_id,
            confirmation="PURGE_TRANSACTION_DATA",
        ),
        None,  # type: ignore[arg-type]
        db_session,
    )

    assert result.data is not None
    assert result.data.purgeStatus == "REMOVED"
    assert result.data.configurationPreserved is True

    status = await _transaction_status(db_session, tenant_id)
    assert status.documents == 0
    assert status.storageObjects == 0
    assert status.extractedFacts == 0
    assert status.acceptedFieldValues == 0
    assert status.processingJobs == 0
    assert status.processingRuns == 0
    assert status.processorInvocations == 0

    remaining_uploads = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM docintel.document_capture_v2_uploads WHERE tenant_id=:tid"
            ),
            {"tid": tenant_id},
        )
    ).scalar_one()
    remaining_jobs = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM docintel.document_capture_v2_classification_jobs "
                "WHERE tenant_id=:tid"
            ),
            {"tid": tenant_id},
        )
    ).scalar_one()
    assert remaining_uploads == 0
    assert remaining_jobs == 0

    tenant_settings_after = int(
        (
            await db_session.execute(
                text("SELECT count(*) FROM docintel.tenant_settings WHERE tenant_id=:tid"),
                {"tid": tenant_id},
            )
        ).scalar_one()
    )
    tenant_document_types_after = int(
        (
            await db_session.execute(
                text("SELECT count(*) FROM docintel.tenant_document_types WHERE tenant_id=:tid"),
                {"tid": tenant_id},
            )
        ).scalar_one()
    )

    assert tenant_settings_after == tenant_settings_before == 1
    assert tenant_document_types_after == tenant_document_types_before
    assert tenant_document_types_after > 0
