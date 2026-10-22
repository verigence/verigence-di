"""tests/test_no_night_processing.py

Product owner, 2026-10-22: nothing is processed at night. The nightly
reprocessing run (17:00 UTC = 22:30 IST) is gone, with the three things it
queued: more tries for every FAILED document, the reading of classified pages
that never got a job, and the one re-read of a page our setup refused
(classification or reading). A document that ended FAILED stays FAILED; Audit
Core raises the PC's "Document to resubmit" task and the PC uploads it again.

These tests keep it gone: the scheduler tick, run over the whole trigger
window against documents the old run would have queued, queues nothing and
reports nothing; the names are gone; the listing never announces a night
attempt. Daytime retries (T0, +10, +20 minutes) are covered elsewhere and are
not touched.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_nightly_once_and_reaper import _classified_unqueued_upload, _failed_document
from tests.test_v2_retry_policy_db import _v2_page_failed_classification, _v2_page_failed_reading
from verigence.di import retry_policy
from verigence.di.integrations.audit_core import AuditCoreLinkClient
from verigence.di.repositories import processing_jobs
from verigence.di.retry_policy import retry_status
from verigence.di.scheduler import beat


class _Recorder:
    """Stands in for the structlog logger: records (level, event)."""

    def __init__(self, events: list[tuple[str, str]] | None = None) -> None:
        self.events: list[tuple[str, str]] = events if events is not None else []

    def bind(self, **_: Any) -> _Recorder:
        return _Recorder(self.events)

    def __getattr__(self, level: str):  # type: ignore[no-untyped-def]
        def record(event: str, **_: Any) -> None:
            self.events.append((level, event))
        return record


class _NoTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> bool:
        return False


class _SharedSession:
    """A session factory that always hands out the test's own session (rolled
    back at the end), so the tick runs against it without committing."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> _SharedSession:
        return self

    async def __aenter__(self) -> _SharedSession:
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    def begin(self) -> _NoTransaction:
        return _NoTransaction()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


async def _snapshot(session: AsyncSession, tenants: list[str]) -> dict[str, list[tuple[Any, ...]]]:
    queries = {
        "processing_jobs": "SELECT tenant_id, document_id, job_type, attempt_no, job_status "
                           "FROM docintel.processing_jobs WHERE tenant_id = ANY(:t) ORDER BY 1, 2, 3, 4",
        "classification_jobs": "SELECT tenant_id, document_id, job_status, attempt_no "
                               "FROM docintel.document_capture_v2_classification_jobs "
                               "WHERE tenant_id = ANY(:t) ORDER BY 1, 2",
        "uploads": "SELECT tenant_id, document_id, state, failure_code "
                   "FROM docintel.document_capture_v2_uploads WHERE tenant_id = ANY(:t) ORDER BY 1, 2",
        "documents": "SELECT tenant_id, document_id, processing_status, confirmation_status, processing_failure_code "
                     "FROM docintel.documents WHERE tenant_id = ANY(:t) ORDER BY 1, 2",
    }
    return {
        name: [tuple(row) for row in (await session.execute(text(sql), {"t": tenants})).all()]
        for name, sql in queries.items()
    }


# ── the run itself ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_scheduler_queues_nothing_at_the_old_nightly_time(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    tenants: list[str] = []

    def tenant(kind: str) -> str:
        tenants.append(f"nonight-{kind}-{suffix}")
        return tenants[-1]

    # What the old run queued, one of each: a Capture V2 reading our setup
    # refused (its one night re-read), an AI-failed reading (never had one),
    # a classification our setup refused, a classified page never queued for
    # reading, a legacy document that failed technically and one that waits
    # for its retry.
    await _v2_page_failed_reading(db_session, tenant("setup-read"), "DOCUMENT_AI_NOT_CONFIGURED")
    await _v2_page_failed_reading(db_session, tenant("ai-read"), "DOCUMENT_AI_UNAVAILABLE")
    await _v2_page_failed_classification(db_session, tenant("setup-cls"), "DOCUMENT_AI_NOT_CONFIGURED", attempt_no=1)
    await _v2_page_failed_classification(db_session, tenant("ai-cls"), "DOCUMENT_AI_UNAVAILABLE")
    await _classified_unqueued_upload(db_session, tenant("unqueued"))
    await _failed_document(db_session, tenant("legacy"), failure_code="WORKER_INTERNAL_ERROR",
                           initial_correlation="corr-legacy")
    pending = tenant("legacy-pending")
    pending_document = await _failed_document(db_session, pending, failure_code="WORKER_INTERNAL_ERROR",
                                              initial_correlation="corr-pending")
    await db_session.execute(
        text("UPDATE docintel.documents SET processing_status='RETRY_PENDING', confirmation_status='PENDING' "
             "WHERE tenant_id=:t AND document_id=:d"),
        {"t": pending, "d": pending_document},
    )
    before = await _snapshot(db_session, tenants)
    assert before["processing_jobs"] and before["documents"]  # the fixtures are really there

    reported: list[Any] = []
    import verigence.di.integrations.audit_core as audit_core_link

    monkeypatch.setattr(audit_core_link, "get_audit_core_link_client", lambda: reported.append("client"))
    recorder = _Recorder()
    monkeypatch.setattr(beat, "logger", recorder)

    async def no_tenants(_session: Any) -> list[dict[str, Any]]:
        return []  # the EOD retry (legacy documents only) is another job, not under test

    monkeypatch.setattr(beat, "_load_enabled_tenants", no_tenants)
    factory = _SharedSession(db_session)
    # The whole of the old trigger window: 17:00 UTC +/- 90 seconds, every tick.
    for hour, minute, second in [(16, 58, 31), (16, 59, 30), (17, 0, 0), (17, 0, 45), (17, 1, 30), (17, 1, 31)]:
        await beat._run_scheduler_tick_in_context(
            factory, datetime(2026, 10, 22, hour, minute, second, tzinfo=UTC),
        )

    assert await _snapshot(db_session, tenants) == before
    assert reported == [], "nothing is reported to Audit Core: there is no run"
    assert [event for _, event in recorder.events if "night" in event] == []
    assert [event for level, event in recorder.events if level in ("warning", "error")] == [], recorder.events
    night_jobs = (await db_session.execute(
        text("SELECT COUNT(*) FROM docintel.processing_jobs WHERE tenant_id = ANY(:t) AND job_type='NIGHTLY_REPROCESS'"),
        {"t": tenants},
    )).scalar_one()
    assert night_jobs == 0
    claimed = (await db_session.execute(
        text("SELECT COUNT(*) FROM docintel.scheduler_runs WHERE run_name LIKE 'NIGHTLY_REPROCESS%' "
             "AND run_date = DATE '2026-10-22'"),
    )).scalar_one()
    assert claimed == 0


# ── nothing of it is left to call ─────────────────────────────────────────────

@pytest.mark.no_docker
def test_no_nightly_name_is_left_in_the_scheduler_the_job_queue_or_the_retry_policy() -> None:
    for module in (beat, processing_jobs, retry_policy):
        left = [name for name in dir(module) if "night" in name.lower()]
        assert left == [], (module.__name__, left)
    assert not hasattr(AuditCoreLinkClient, "report_nightly_reprocessing_run")
    assert not hasattr(retry_policy, "NIGHT_ELIGIBLE_FAILURE_CODES")


@pytest.mark.no_docker
def test_the_scheduler_tick_has_no_time_of_day_trigger_but_the_eod_retry() -> None:
    import inspect

    source = inspect.getsource(beat._run_scheduler_tick_in_context)
    assert "NIGHTLY" not in source.upper()
    assert "_is_eod_window" in source  # the daytime EOD retry of legacy documents is a different job


# ── the listing never announces a night attempt ───────────────────────────────

_CODES = [None, "DOCUMENT_AI_NOT_CONFIGURED", "DOCUMENT_AI_UNAVAILABLE", "DOCUMENT_AI_RATE_LIMITED",
          "STORAGE_READ_ERROR", "DI_QUALITY_IMAGE_BLUR_SCORE", "CLASSIFICATION_FAILED"]


@pytest.mark.no_docker
@pytest.mark.parametrize("code", _CODES)
@pytest.mark.parametrize("upload_status", ["FIT", "NOT_FIT", "VALIDATING", None])
@pytest.mark.parametrize(
    "state_fields",
    [
        {"state": "FAILED"},
        {"state": "STORED", "classification_job_status": "PENDING", "classification_attempt_no": 2},
        {"state": "STORED", "classification_job_status": "PENDING", "classification_attempt_no": 4},
        {"state": "CLASSIFIED", "processing_status": "FAILED", "processing_attempts": 1},
        {"state": "CLASSIFIED", "processing_status": "FAILED", "processing_attempts": 3},
        {"state": "CLASSIFIED", "processing_status": "RETRY_PENDING", "processing_attempts": 1,
         "processing_next_due_at_utc": datetime(2026, 10, 22, 17, 0, tzinfo=UTC)},
    ],
)
def test_the_listing_never_says_a_night_attempt_is_coming_or_under_way(
    state_fields: dict[str, Any], upload_status: str | None, code: str | None,
) -> None:
    row = {
        **state_fields, "upload_status": upload_status, "failure_code": code,
        "processing_failure_code": code, "classification_error_code": code,
        # Columns the listing query used to carry; a stale one must change nothing.
        "processing_next_job_type": "NIGHTLY_REPROCESS", "night_reprocess_used": False,
    }
    status = retry_status(row)
    assert status["inNightAttempt"] is False
    assert status["retryTonight"] is False
