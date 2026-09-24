from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from verigence.di.repositories.audit_links import mark_audit_link_attempt

# Pure mock-based tests (fake session, no real I/O) -- doesn't need the
# docker-backed DB fixture other tests in this suite rely on.
pytestmark = pytest.mark.no_docker


class _FakeSession:
    def __init__(self) -> None:
        self.statement = None
        self.params: dict[str, Any] | None = None

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        self.statement = statement
        self.params = params


@pytest.mark.asyncio
async def test_mark_audit_link_attempt_uses_database_timestamps_not_shared_bind() -> None:
    session = _FakeSession()
    document_id = uuid4()

    await mark_audit_link_attempt(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        document_id=document_id,
        acknowledged=True,
    )

    sql = str(session.statement)
    assert ":now" not in sql
    assert "audit_link_last_attempt_at_utc  = now()" in sql
    assert "CASE WHEN :ack THEN now() ELSE NULL END" in sql
    assert "updated_at_utc                  = now()" in sql
    assert session.params == {
        "tenant_id": "tenant-1",
        "document_id": document_id,
        "ack": True,
        "retryable": True,
        "error": None,
    }


@pytest.mark.asyncio
async def test_mark_audit_link_attempt_defaults_a_failed_retryable_attempt_to_pending() -> None:
    """A failure that CAN eventually succeed (e.g. a 5xx/429) must stay
    'PENDING' so claim_pending_audit_link keeps reclaiming it, same as
    before this function grew a retryable parameter."""
    session = _FakeSession()
    document_id = uuid4()

    await mark_audit_link_attempt(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        document_id=document_id,
        acknowledged=False,
        error_summary="AUDIT_CORE_INTEGRATION_FAILED: 503",
        retryable=True,
    )

    sql = str(session.statement)
    assert "WHEN :retryable THEN 'PENDING' ELSE 'FAILED'" in sql
    assert session.params["retryable"] is True


@pytest.mark.asyncio
async def test_mark_audit_link_attempt_marks_a_non_retryable_failure_as_terminally_failed() -> None:
    """Found live (2026-09-24): a non-retryable failure (e.g. VAC-NF-006, a
    stale requirement_ref that can never become valid again) used to be
    written back as 'PENDING' regardless of retryable, so
    claim_pending_audit_link kept reclaiming and retrying the exact same
    permanently-broken link forever (observed at 900+ attempts, ~15 hours,
    for a handful of documents). It must now go to the terminal 'FAILED'
    status instead, which claim_pending_audit_link's own
    audit_link_status='PENDING' filter naturally never reclaims again."""
    session = _FakeSession()
    document_id = uuid4()

    await mark_audit_link_attempt(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-1",
        document_id=document_id,
        acknowledged=False,
        error_summary="AUDIT_CORE_INTEGRATION_FAILED: VAC-NF-006",
        retryable=False,
    )

    assert session.params == {
        "tenant_id": "tenant-1",
        "document_id": document_id,
        "ack": False,
        "retryable": False,
        "error": "AUDIT_CORE_INTEGRATION_FAILED: VAC-NF-006",
    }
