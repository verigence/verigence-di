"""delete_document must clear documents.current_processing_run_id before it
deletes the processing runs the pointer references (fk_documents_current_
processing_run), or the delete fails and Audit Core retries on every pass."""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from verigence.di.repositories.documents import delete_document

pytestmark = pytest.mark.no_docker


class _Rows:
    def all(self) -> list[tuple[str]]:
        return [("artifact-key-1",)]


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement, params=None):  # type: ignore[no-untyped-def]
        self.statements.append((" ".join(str(statement).split()), dict(params or {})))
        return _Rows()


class _Storage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


@pytest.mark.asyncio
async def test_current_processing_run_pointer_is_cleared_before_the_runs_are_deleted() -> None:
    session, storage = _RecordingSession(), _Storage()
    document_id, subject_id = uuid.uuid4(), uuid.uuid4()
    await delete_document(
        session,  # type: ignore[arg-type]
        tenant_id="tenant-a", document_id=document_id, subject_id=subject_id, storage=storage,  # type: ignore[arg-type]
    )
    sql = [statement for statement, _ in session.statements]
    clear = next(i for i, s in enumerate(sql) if s.startswith("UPDATE docintel.documents SET current_processing_run_id=NULL"))
    delete_runs = next(i for i, s in enumerate(sql) if s.startswith("DELETE FROM docintel.processing_runs"))
    delete_document_row = next(i for i, s in enumerate(sql) if s.startswith("DELETE FROM docintel.documents"))
    assert clear < delete_runs < delete_document_row
    # scoped to this one document of this tenant and subject
    assert session.statements[clear][1] == {"tid": "tenant-a", "doc_id": document_id, "sid": subject_id}
    assert "document_id=:doc_id" in sql[clear] and "subject_id=:sid" in sql[clear]
    assert storage.deleted == ["artifact-key-1"]
