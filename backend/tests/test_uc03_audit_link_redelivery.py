from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from verigence.di.repositories.processing_jobs import complete_job

pytestmark = pytest.mark.no_docker


@pytest.mark.asyncio
async def test_successful_extraction_requeues_audit_link_delivery() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())

    await complete_job(
        session,
        tenant_id="tenant-test",
        processing_job_id=uuid.uuid4(),
        success=True,
    )

    assert session.execute.call_count == 2
    callback_sql = str(session.execute.call_args_list[1][0][0])
    assert "audit_link_status = 'PENDING'" in callback_sql
    assert "audit_link_last_attempt_at_utc = NULL" in callback_sql
    assert "audit_requirement_ref IS NOT NULL" in callback_sql


@pytest.mark.asyncio
async def test_failed_extraction_does_not_requeue_audit_link_delivery() -> None:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())

    await complete_job(
        session,
        tenant_id="tenant-test",
        processing_job_id=uuid.uuid4(),
        success=False,
        error_code="EXTRACTION_FAILED",
    )

    assert session.execute.call_count == 1
    completion_sql = str(session.execute.call_args_list[0][0][0])
    assert "audit_link_status" not in completion_sql
