from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from verigence.di.repositories.audit_links import mark_audit_link_attempt


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
        "error": None,
    }
