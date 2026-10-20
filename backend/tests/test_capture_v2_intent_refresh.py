"""A repeated upload intent whose file never arrived takes the new mapping.

Found live 2026-10-20: Audit Core timed out waiting for capture-documents:init
(the intent was created all the same), and asked again after grouping with
the full requirement mapping (the first request, for a page of a multi-page
upload, left out its read-once types). DI refused every retry as a CONFLICT,
so 21 pages were retried for hours. Nothing has been read under the earlier
mapping while the intent is still RECEIVING, so the new one stands; once the
file is stored, a different mapping is still a conflict.
"""
from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from verigence.di.api.v2 import capture_documents

pytestmark = pytest.mark.no_docker

_TENANT = "afa9e32b-e62f-4cbc-be2b-7ab7ad5ef572"
_DOC = uuid.uuid4()
_REQ_FORM = uuid.uuid4()
_REQ_RECEIPT = uuid.uuid4()


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _Result:
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self._row


class _Session:
    def __init__(self, existing: dict[str, Any]) -> None:
        self.existing = existing
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = str(statement)
        self.statements.append((sql, params or {}))
        if "FROM docintel.document_capture_v2_uploads" in sql and sql.strip().startswith("SELECT"):
            return _Result(self.existing)
        return _Result(None)

    @contextlib.asynccontextmanager
    async def begin_nested(self) -> AsyncIterator[None]:
        yield

    async def commit(self) -> None:
        return None


def _patch(monkeypatch: pytest.MonkeyPatch, session: _Session) -> None:
    @contextlib.asynccontextmanager
    async def fake_tenant_session(_tenant: str) -> AsyncIterator[_Session]:
        yield session

    @contextlib.asynccontextmanager
    async def fake_s3() -> AsyncIterator[object]:
        yield object()

    async def fake_context(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"storage_context_id": uuid.uuid4()}

    async def nothing(*_a: Any, **_k: Any) -> None:
        return None

    async def retention(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"retention_policy_id": uuid.uuid4(), "retention_days": 1, "disposition": "DELETE"}

    async def presign(**_k: Any) -> Any:
        return SimpleNamespace(url="https://example.test/put", required_headers={}, expires_seconds=600)

    monkeypatch.setattr(capture_documents, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(capture_documents, "open_v2_s3_client", fake_s3)
    monkeypatch.setattr(capture_documents, "get_audit_storage_context_by_ref", fake_context)
    monkeypatch.setattr(capture_documents, "provision_actor", nothing)
    monkeypatch.setattr(capture_documents, "get_active_retention_policy", retention)
    monkeypatch.setattr(capture_documents, "presign_v2_put", presign)


def _command() -> capture_documents.V2UploadIntentCommand:
    return capture_documents.V2UploadIntentCommand(
        phase="BOOKING",
        candidateDocumentTypeKeys=["booking_form", "dealer_receipt"],
        requirementRefsByDocumentTypeKey={"booking_form": _REQ_FORM, "dealer_receipt": _REQ_RECEIPT},
        files=[{"clientUploadId": "page-1", "filename": "a-page-001.pdf", "contentType": "application/pdf"}],
    )


async def _init(session: _Session, monkeypatch: pytest.MonkeyPatch) -> Any:
    _patch(monkeypatch, session)
    return await capture_documents.create_capture_upload_intents(
        tenantId=_TENANT, externalContextRef="audit-ctx", command=_command(),
        principal=SimpleNamespace(service_id="audit-core"),
    )


def _existing(state: str) -> dict[str, Any]:
    # First request: the read-once type (booking_form) was left out.
    return {"document_id": _DOC, "logical_object_key": "k", "state": state,
            "requirement_refs_by_document_type_key": {"dealer_receipt": str(_REQ_RECEIPT)}}


@pytest.mark.asyncio
async def test_an_intent_still_receiving_takes_the_new_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session(_existing("RECEIVING"))
    response = await _init(session, monkeypatch)
    assert response.failures == []
    assert [u.documentId for u in response.uploads] == [_DOC]
    updates = [p for sql, p in session.statements if "UPDATE docintel.document_capture_v2_uploads" in sql]
    assert len(updates) == 1
    assert f'"booking_form": "{_REQ_FORM}"' in updates[0]["refs"]


@pytest.mark.asyncio
async def test_a_stored_file_under_another_mapping_is_still_a_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session(_existing("STORED"))
    response = await _init(session, monkeypatch)
    assert response.uploads == []
    assert [f.errorCode for f in response.failures] == ["CONFLICT"]
