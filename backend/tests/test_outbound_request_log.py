"""Every outbound API call (the model, Security, Audit Core) is logged once
with its response time; path only, never headers or the query string."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from verigence.di import observability

pytestmark = pytest.mark.no_docker


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str):  # type: ignore[no-untyped-def]
        def record(event: str, **fields: Any) -> None:
            self.events.append((level, event, fields))
        return record


@pytest.mark.asyncio
async def test_outbound_calls_are_logged_once_with_their_response_time(monkeypatch: pytest.MonkeyPatch) -> None:
    observability.install_outbound_request_logging()
    recorder = _Recorder()
    monkeypatch.setattr(observability, "_outbound_logger", recorder)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/boom"):
            raise httpx.ConnectError("down")
        return httpx.Response(429 if "generativelanguage" in request.url.host else 200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await client.post("https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=SECRET",
                          headers={"x-goog-api-key": "SECRET"}, json={})
        await client.get("https://verigence-security-dev.example/v1/me")
        with pytest.raises(httpx.ConnectError):
            await client.get("https://verigence-audit-core-dev.example/boom")

    assert [(level, event, f["dependency"], f["path"], f.get("status_code")) for level, event, f in recorder.events] == [
        ("warning", "outbound_request", "GEMINI", "/v1beta/models/x:generateContent", 429),
        ("info", "outbound_request", "SECURITY", "/v1/me", 200),
        ("warning", "outbound_request_failed", "AUDIT_CORE", "/boom", None),
    ]
    assert all(f["duration_ms"] >= 0 for _, _, f in recorder.events)
    assert "SECRET" not in repr(recorder.events)
