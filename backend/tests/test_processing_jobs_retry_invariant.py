from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from verigence.di.repositories.processing_jobs import (
    V2_FAST_RETRY_DELAY_SECONDS,
    retry_job,
    schedule_v2_fast_retry,
)

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


@pytest.mark.asyncio
async def test_schedule_v2_fast_retry_inserts_a_near_term_second_attempt() -> None:
    # A Capture V2 document's first retryable failure must not wait on the
    # legacy once-daily EOD Retry Scheduler -- confirmed live root cause of
    # documents sitting at "Classified" for hours with no visible failure
    # (processing_status='RETRY_PENDING' renders identically to "still
    # processing" on the capture screen).
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    document_id = uuid.uuid4()
    before = datetime.now(UTC)

    await schedule_v2_fast_retry(
        session,
        tenant_id="tenant-test",
        document_id=document_id,
        correlation_id="corr-1",
    )

    assert session.execute.call_count == 1
    sql, params = session.execute.call_args_list[0][0]
    assert "V2_FAST_RETRY" in str(sql)
    assert "ON CONFLICT (tenant_id, document_id, job_type) DO NOTHING" in str(sql)
    assert params["tenant_id"] == "tenant-test"
    assert params["document_id"] == document_id
    assert params["correlation_id"] == "corr-1"
    # attempt_no=2 matches EOD_RETRY's convention -- the second failure of
    # this fast-retried job should permanently fail, not retry a third time.
    due_in_seconds = (params["due_at"] - before).total_seconds()
    assert 0 < due_in_seconds <= V2_FAST_RETRY_DELAY_SECONDS + 5
