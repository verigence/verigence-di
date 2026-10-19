"""The Capture V2 "Read again" endpoint must not open a second transaction.

Found live 2026-10-19: every POST .../capture-documents/{id}:reprocess failed
with SQLAlchemy ``InvalidRequestError: A transaction is already begun on this
Session``. ``tenant_session()`` sets the RLS context and provisions the tenant
before it yields, so the session is already inside its (autobegun) transaction;
the endpoint then called ``session.begin()`` on top of it. Audit Core retried
each request five times and dead-lettered it (35 PAGE_REREAD items that day),
so no page was ever read again.

``tenant_session()`` commits on a clean exit and rolls back on an error, so the
endpoint needs no transaction block of its own. These tests drive the real
endpoint function with a real ``AsyncSession`` whose transaction has already
begun -- exactly the state ``tenant_session()`` hands over -- without needing a
database: SQLAlchemy opens the connection lazily and never reaches it here.
"""
from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from verigence.di.api.v2 import capture_documents

pytestmark = pytest.mark.no_docker

_TENANT = "afa9e32b-e62f-4cbc-be2b-7ab7ad5ef572"
_CONTEXT = "audit-ctx"


def _session_already_in_transaction() -> AsyncSession:
    engine = create_async_engine("postgresql+asyncpg://unused:unused@localhost/unused")
    session = AsyncSession(engine)
    # What set_tenant_context()/provision_tenant() leave behind: the first
    # statement autobegins the session's transaction.
    session.sync_session._autobegin_t()
    return session


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"calls": 0, "session": None}

    async def fake_status_rows(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [{"document_id": "x"}]

    @contextlib.asynccontextmanager
    async def fake_tenant_session(_tenant_id: str) -> AsyncIterator[AsyncSession]:
        session = _session_already_in_transaction()
        state["session"] = session
        yield session

    async def fake_request_manual_reread(session: AsyncSession, **_kwargs: Any) -> dict[str, Any]:
        state["calls"] += 1
        assert session is state["session"]
        return {"outcome": "queued", "processingJobId": str(uuid.uuid4())}

    monkeypatch.setattr(capture_documents, "_status_rows", fake_status_rows)
    monkeypatch.setattr(capture_documents, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(capture_documents, "request_manual_reread", fake_request_manual_reread)
    return state


async def test_reprocess_queues_a_reading_inside_tenant_sessions_own_transaction(
    patched: dict[str, Any],
) -> None:
    document_id = uuid.uuid4()
    response = await capture_documents.reprocess_capture_document(
        tenantId=_TENANT,
        externalContextRef=_CONTEXT,
        documentId=document_id,
        principal=SimpleNamespace(service_id="audit-core"),  # type: ignore[arg-type]
    )
    assert patched["calls"] == 1
    assert response.outcome == "queued"
    assert response.documentId == document_id
    assert response.processingJobId is not None


async def test_reprocess_still_reports_a_missing_document_as_not_found(
    patched: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def not_found(session: AsyncSession, **_kwargs: Any) -> dict[str, Any]:
        return {"outcome": "not_found"}

    monkeypatch.setattr(capture_documents, "request_manual_reread", not_found)
    with pytest.raises(HTTPException) as raised:
        await capture_documents.reprocess_capture_document(
            tenantId=_TENANT,
            externalContextRef=_CONTEXT,
            documentId=uuid.uuid4(),
            principal=SimpleNamespace(service_id="audit-core"),  # type: ignore[arg-type]
        )
    assert raised.value.status_code == 404
