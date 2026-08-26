from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from verigence.di.repositories.processing_jobs import retry_job

pytestmark = pytest.mark.no_docker


@pytest.mark.asyncio
async def test_retry_pending_keeps_confirmation_pending() -> None:
    session = AsyncMock()
    result = MagicMock()
    session.execute = AsyncMock(return_value=result)

    await retry_job(
        session,
        tenant_id="tenant-test",
        processing_job_id=uuid.uuid4(),
        error_code="EXTRACTION_PROVIDER_ERROR",
        error_detail="provider unavailable",
    )

    assert session.execute.call_count == 2
    document_update_sql = str(session.execute.call_args_list[1][0][0])
    assert "processing_status = 'RETRY_PENDING'" in document_update_sql
    assert "confirmation_status = 'PENDING'" in document_update_sql
    assert "confirmation_status = 'NOT_CONFIRMED'" not in document_update_sql
