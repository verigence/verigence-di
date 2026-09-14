"""tests/test_nightly_reprocessing_jobs.py

Unit coverage for repositories/processing_jobs.py::insert_nightly_reprocessing_jobs
-- the per-tick query+insert logic scheduler/beat.py calls once nightly. Mock-based
(no Docker), matching test_processing_jobs_retry_invariant.py's established pattern
for this module's other job-insertion functions; the constraint changes that make
these inserts actually succeed against real Postgres are covered separately by
test_processing_runs_run_type_constraint.py-style Docker tests.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from verigence.di.repositories.processing_jobs import (
    NIGHTLY_REPROCESS_MAX_ATTEMPTS,
    insert_nightly_reprocessing_jobs,
)

pytestmark = pytest.mark.no_docker


def _eligible_rows_result(rows: list[dict]) -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


@pytest.mark.asyncio
async def test_a_never_before_reprocessed_document_is_queued_at_first_nightly_attempt() -> None:
    session = AsyncMock()
    tenant_id, document_id = "tenant-test", uuid.uuid4()
    select_result = _eligible_rows_result(
        [{"tenant_id": tenant_id, "document_id": document_id, "last_attempt_no": 2,
          "original_correlation_id": "corr-initial"}]
    )
    insert_result = MagicMock()
    session.execute = AsyncMock(side_effect=[select_result, insert_result])

    queued = await insert_nightly_reprocessing_jobs(session)

    assert queued == 1
    assert session.execute.call_count == 2
    insert_sql, insert_params = session.execute.call_args_list[1][0]
    assert "NIGHTLY_REPROCESS" in str(insert_sql)
    assert "ON CONFLICT (tenant_id, document_id, job_type, attempt_no) DO NOTHING" in str(insert_sql)
    # 1=INITIAL, 2=EOD_RETRY/V2_FAST_RETRY, so a document with no prior
    # NIGHTLY_REPROCESS row (last_attempt_no defaults to 2) gets attempt_no=3.
    assert insert_params["attempt_no"] == 3
    assert insert_params["tenant_id"] == tenant_id
    assert insert_params["doc_id"] == document_id


@pytest.mark.asyncio
async def test_a_document_already_at_the_max_attempt_count_is_left_alone() -> None:
    session = AsyncMock()
    last_attempt_no = 3 + NIGHTLY_REPROCESS_MAX_ATTEMPTS - 1 - 1  # one below the ceiling
    select_result = _eligible_rows_result(
        [{"tenant_id": "tenant-test", "document_id": uuid.uuid4(),
          "last_attempt_no": last_attempt_no + 1, "original_correlation_id": "corr-initial"}]
    )
    session.execute = AsyncMock(return_value=select_result)

    queued = await insert_nightly_reprocessing_jobs(session)

    # next_attempt_no would exceed the ceiling -- no insert, no second execute call.
    assert queued == 0
    assert session.execute.call_count == 1


@pytest.mark.asyncio
async def test_one_rows_insert_failure_does_not_abort_the_rest_of_the_batch() -> None:
    session = AsyncMock()
    rows = [
        {"tenant_id": "tenant-test", "document_id": uuid.uuid4(), "last_attempt_no": 2,
         "original_correlation_id": "corr-a"},
        {"tenant_id": "tenant-test", "document_id": uuid.uuid4(), "last_attempt_no": 2,
         "original_correlation_id": "corr-b"},
    ]
    select_result = _eligible_rows_result(rows)
    session.execute = AsyncMock(
        side_effect=[select_result, RuntimeError("db blip"), MagicMock()]
    )

    queued = await insert_nightly_reprocessing_jobs(session)

    # Matches _insert_eod_retry_jobs' own established handling -- log and
    # move on rather than let one bad row abort the whole nightly pass.
    assert queued == 1
    assert session.execute.call_count == 3
