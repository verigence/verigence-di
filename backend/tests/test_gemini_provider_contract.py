from __future__ import annotations

import pytest

from verigence.di.document_ai import gemini_adapter


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _Client:
    response: _Response
    captured: dict

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def post(self, url: str, **kwargs: object) -> _Response:
        type(self).captured = {"url": url, **kwargs}
        return type(self).response


@pytest.mark.asyncio
async def test_gemini_uses_documented_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    _Client.response = _Response(
        200,
        {
            "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
            "usageMetadata": {},
        },
    )
    monkeypatch.setattr(gemini_adapter.httpx, "AsyncClient", _Client)

    await gemini_adapter._call_gemini_instrumented(
        "AQ.test-auth-key", b"pdf", "application/pdf", "prompt"
    )

    assert _Client.captured["headers"] == {"x-goog-api-key": "AQ.test-auth-key"}
    assert "params" not in _Client.captured


@pytest.mark.asyncio
async def test_gemini_401_is_not_treated_as_empty_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Client.response = _Response(401, text="UNAUTHENTICATED")
    monkeypatch.setattr(gemini_adapter.httpx, "AsyncClient", _Client)

    with pytest.raises(gemini_adapter.GeminiApiError) as caught:
        await gemini_adapter._call_gemini_instrumented(
            "AQ.test-auth-key", b"pdf", "application/pdf", "prompt"
        )

    assert caught.value.status_code == 401
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_adapter_propagates_provider_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(**kwargs: object) -> tuple[str, int, int, int]:
        del kwargs
        raise gemini_adapter.GeminiApiError(401, "UNAUTHENTICATED")

    monkeypatch.setattr(gemini_adapter, "_call_gemini_instrumented", fail)
    adapter = gemini_adapter.GeminiDocumentAIAdapter("AQ.test-auth-key")

    with pytest.raises(gemini_adapter.GeminiApiError):
        await adapter.extract(
            b"pdf",
            "application/pdf",
            [],
            document_type_key="pan_card",
        )
