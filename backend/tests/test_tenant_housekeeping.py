from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from verigence.di.api.v1.tenant_housekeeping import (
    TenantTransactionPurgeCommand,
    _transaction_status,
    purge_tenant_transaction_data,
)
from verigence.di.repositories.database import set_tenant_context
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
    await provision_retention_policy(db_session, tenant_id)
    await provision_tenant_document_types(db_session, tenant_id)
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
