from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from verigence.di.api.v1.tenant_housekeeping import (
    SelectedDocumentPurgeCommand,
    purge_selected_document_data,
)


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
