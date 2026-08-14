"""tests/test_backout_queue.py — Unit tests for the D24 backout queue.

All tests are marked no_docker — pure logic, mocked DB session.

Coverage:
- insert_backout_job() inserts correct row and returns a UUID
- insert_backout_job() upserts on conflict (same document_id)
- sweep_expired_backout_jobs() deletes expired rows and returns count
- sweep_expired_backout_jobs() does not delete non-expired rows
- _handle_failure() in processor.py calls fail_job + insert_backout_job
  for BOTH retryable and non-retryable failures
- settings backout_ttl_hours default is 12
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.no_docker


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_session() -> AsyncMock:
    """Return a minimal mock AsyncSession."""
    session = AsyncMock()
    # execute() returns an object whose rowcount we can control
    result = MagicMock()
    result.rowcount = 0
    session.execute = AsyncMock(return_value=result)
    return session


# ── insert_backout_job ─────────────────────────────────────────────────────────

class TestInsertBackoutJob:

    @pytest.mark.asyncio
    async def test_returns_uuid(self) -> None:
        from verigence.di.repositories.backout import insert_backout_job

        session = _make_session()
        bjid = await insert_backout_job(
            session,
            tenant_id="t1",
            document_id=uuid.uuid4(),
            processing_job_id=uuid.uuid4(),
            processing_run_id=uuid.uuid4(),
            error_class="RETRYABLE",
            error_code="CLASSIFICATION_PROVIDER_ERROR",
            error_detail="timeout",
            ttl_hours=12,
        )
        assert isinstance(bjid, uuid.UUID)

    @pytest.mark.asyncio
    async def test_execute_called_once(self) -> None:
        from verigence.di.repositories.backout import insert_backout_job

        session = _make_session()
        await insert_backout_job(
            session,
            tenant_id="t1",
            document_id=uuid.uuid4(),
            processing_job_id=uuid.uuid4(),
            processing_run_id=None,
            error_class="NON_RETRYABLE",
            error_code="CLASSIFICATION_NO_CANDIDATES",
            error_detail="no profiles",
            ttl_hours=12,
        )
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_sql_contains_upsert(self) -> None:
        from verigence.di.repositories.backout import insert_backout_job

        session = _make_session()
        await insert_backout_job(
            session,
            tenant_id="t1",
            document_id=uuid.uuid4(),
            processing_job_id=uuid.uuid4(),
            processing_run_id=None,
            error_class="RETRYABLE",
            error_code=None,
            error_detail=None,
            ttl_hours=6,
        )
        call_args = session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "ON CONFLICT" in sql_text
        assert "DO UPDATE" in sql_text

    @pytest.mark.asyncio
    async def test_expires_at_uses_ttl(self) -> None:
        """The expires_at_utc param passed to DB should be ~ttl_hours from now."""
        from verigence.di.repositories.backout import insert_backout_job

        session = _make_session()
        before = datetime.now(UTC)
        await insert_backout_job(
            session,
            tenant_id="t1",
            document_id=uuid.uuid4(),
            processing_job_id=uuid.uuid4(),
            processing_run_id=None,
            error_class="RETRYABLE",
            error_code=None,
            error_detail=None,
            ttl_hours=3,
        )
        after = datetime.now(UTC)

        params = session.execute.call_args[0][1]
        expires_at = params["expires_at"]
        # Should be within [before+3h, after+3h]
        assert before + timedelta(hours=3) <= expires_at <= after + timedelta(hours=3)

    @pytest.mark.asyncio
    async def test_processing_run_id_nullable(self) -> None:
        """processing_run_id=None is passed through (nullable column)."""
        from verigence.di.repositories.backout import insert_backout_job

        session = _make_session()
        await insert_backout_job(
            session,
            tenant_id="t1",
            document_id=uuid.uuid4(),
            processing_job_id=uuid.uuid4(),
            processing_run_id=None,
            error_class="NON_RETRYABLE",
            error_code="WORKER_INTERNAL_ERROR",
            error_detail="crash",
            ttl_hours=12,
        )
        params = session.execute.call_args[0][1]
        assert params["run_id"] is None


# ── sweep_expired_backout_jobs ────────────────────────────────────────────────

class TestSweepExpiredBackoutJobs:

    @pytest.mark.asyncio
    async def test_returns_rowcount(self) -> None:
        from verigence.di.repositories.backout import sweep_expired_backout_jobs

        session = _make_session()
        session.execute.return_value.rowcount = 5
        count = await sweep_expired_backout_jobs(session)
        assert count == 5

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_expired(self) -> None:
        from verigence.di.repositories.backout import sweep_expired_backout_jobs

        session = _make_session()
        session.execute.return_value.rowcount = 0
        count = await sweep_expired_backout_jobs(session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_sql_uses_now_comparison(self) -> None:
        from verigence.di.repositories.backout import sweep_expired_backout_jobs

        session = _make_session()
        await sweep_expired_backout_jobs(session)
        call_args = session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "expires_at_utc" in sql_text
        assert "DELETE" in sql_text


# ── settings.backout_ttl_hours default ───────────────────────────────────────

class TestBackoutTtlHoursSetting:

    def test_default_is_12(self) -> None:
        from verigence.di.settings import Settings

        # Minimal settings object — only required fields
        s = Settings(
            secret_key="a" * 32,
            database_url="postgresql+asyncpg://u:p@localhost/db",
        )
        assert s.backout_ttl_hours == 12

    def test_can_be_overridden_via_env(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("DI_BACKOUT_TTL_HOURS", "6")
        from verigence.di.settings import Settings

        s = Settings(
            secret_key="a" * 32,
            database_url="postgresql+asyncpg://u:p@localhost/db",
        )
        assert s.backout_ttl_hours == 6


# ── _handle_failure integration ───────────────────────────────────────────────

class TestHandleFailure:
    """Verify that _handle_failure always takes the backout path.

    Patches fail_job and insert_backout_job to avoid real DB calls.
    """

    def _make_session_factory(self) -> MagicMock:
        """Return a mock async_sessionmaker that yields a mock session/begin."""
        session_cm = AsyncMock()
        session_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_cm.__aexit__ = AsyncMock(return_value=False)

        begin_cm = AsyncMock()
        begin_cm.__aenter__ = AsyncMock(return_value=None)
        begin_cm.__aexit__ = AsyncMock(return_value=False)

        session_mock = AsyncMock()
        session_mock.begin = MagicMock(return_value=begin_cm)
        session_mock.execute = AsyncMock()

        outer_cm = AsyncMock()
        outer_cm.__aenter__ = AsyncMock(return_value=session_mock)
        outer_cm.__aexit__ = AsyncMock(return_value=False)

        factory = MagicMock(return_value=outer_cm)
        return factory

    @pytest.mark.asyncio
    async def test_retryable_failure_calls_backout(self) -> None:
        from verigence.di.workers.processor import _handle_failure

        factory = self._make_session_factory()
        job_log = MagicMock()
        job_log.warning = MagicMock()

        with (
            patch("verigence.di.workers.processor.fail_job", new_callable=AsyncMock) as mock_fail,
            patch("verigence.di.workers.processor.insert_backout_job", new_callable=AsyncMock) as mock_backout,
        ):
            await _handle_failure(
                session_factory=factory,
                tenant_id="t1",
                job_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                processing_run_id=uuid.uuid4(),
                error_code="CLASSIFICATION_PROVIDER_ERROR",
                error_detail="timeout",
                retryable=True,
                job_log=job_log,
            )

        mock_fail.assert_called_once()
        mock_backout.assert_called_once()
        # Confirm error_class was RETRYABLE
        call_kwargs = mock_backout.call_args.kwargs
        assert call_kwargs["error_class"] == "RETRYABLE"

    @pytest.mark.asyncio
    async def test_non_retryable_failure_calls_backout(self) -> None:
        from verigence.di.workers.processor import _handle_failure

        factory = self._make_session_factory()
        job_log = MagicMock()
        job_log.warning = MagicMock()

        with (
            patch("verigence.di.workers.processor.fail_job", new_callable=AsyncMock) as mock_fail,
            patch("verigence.di.workers.processor.insert_backout_job", new_callable=AsyncMock) as mock_backout,
        ):
            await _handle_failure(
                session_factory=factory,
                tenant_id="t1",
                job_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                processing_run_id=None,
                error_code="CLASSIFICATION_NO_CANDIDATES",
                error_detail="no profiles",
                retryable=False,
                job_log=job_log,
            )

        mock_fail.assert_called_once()
        mock_backout.assert_called_once()
        call_kwargs = mock_backout.call_args.kwargs
        assert call_kwargs["error_class"] == "NON_RETRYABLE"

    @pytest.mark.asyncio
    async def test_logs_job_failed_backout(self) -> None:
        from verigence.di.workers.processor import _handle_failure

        factory = self._make_session_factory()
        job_log = MagicMock()
        job_log.warning = MagicMock()

        with (
            patch("verigence.di.workers.processor.fail_job", new_callable=AsyncMock),
            patch("verigence.di.workers.processor.insert_backout_job", new_callable=AsyncMock),
        ):
            await _handle_failure(
                session_factory=factory,
                tenant_id="t1",
                job_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                processing_run_id=None,
                error_code="EXTRACTION_PROVIDER_ERROR",
                error_detail="gemini 429",
                retryable=True,
                job_log=job_log,
            )

        job_log.warning.assert_called_once()
        call_args = job_log.warning.call_args
        assert call_args[0][0] == "job_failed_backout"
