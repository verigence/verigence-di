from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from uuid import uuid4

import pytest
from fastapi.responses import StreamingResponse

from verigence.di.api.v1.audit_storage_contexts import _document_content_response
from verigence.di.storage.adapter import StorageAdapter


class _FakeStorage:
    def __init__(self) -> None:
        self.requested_keys: list[str] = []

    async def get_stream(self, logical_key: str) -> AsyncIterator[bytes]:
        self.requested_keys.append(logical_key)
        yield b"first-"
        yield b"second"


@pytest.mark.asyncio
async def test_document_content_response_streams_async_generator_without_buffering() -> None:
    storage = _FakeStorage()
    document_id = uuid4()

    response = _document_content_response(
        storage=cast("StorageAdapter", storage),
        logical_key="tenant/audit/booking-form.pdf",
        mime_type="application/pdf",
        content_hash_sha256="abc123",
        document_id=document_id,
    )

    assert isinstance(response, StreamingResponse)
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="booking-form.pdf"'
    assert response.headers["x-content-sha256"] == "abc123"

    payload = b""
    async for chunk in response.body_iterator:
        assert isinstance(chunk, bytes)
        payload += chunk

    assert payload == b"first-second"
    assert storage.requested_keys == ["tenant/audit/booking-form.pdf"]
