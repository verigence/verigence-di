from __future__ import annotations

import time

import httpx
import pytest

from verigence.di.auth.human_authorization import SecurityLiveAuthorizationClient

pytestmark = pytest.mark.no_docker


def _client(monkeypatch: pytest.MonkeyPatch, handler) -> SecurityLiveAuthorizationClient:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DI_SECURITY_BASE_URL", "https://security.test")
    monkeypatch.setenv("DI_SECURITY_CLIENT_ID", "di-client")
    monkeypatch.setenv("DI_SECURITY_CLIENT_SECRET", "secret")
    client = SecurityLiveAuthorizationClient()
    client._client = httpx.AsyncClient(  # noqa: SLF001
        base_url="https://security.test",
        transport=httpx.MockTransport(handler),
    )
    client._service_token = "cached-service-token"  # noqa: SLF001
    client._service_token_reuse_until = time.monotonic() + 60  # noqa: SLF001
    return client


@pytest.mark.asyncio
async def test_allow_decision_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/security/v1/authorization/check"
        return httpx.Response(
            200,
            json={
                "userId": "pc-1",
                "tenantId": "tenant-1",
                "permissionKey": "di.document.upload",
                "allowed": True,
                "roleKey": "PROCESS_CONSULTANT",
            },
        )

    client = _client(monkeypatch, handler)
    try:
        first = await client.authorize(
            user_id="pc-1",
            tenant_id="tenant-1",
            permission_key="di.document.upload",
        )
        second = await client.authorize(
            user_id="pc-1",
            tenant_id="tenant-1",
            permission_key="di.document.upload",
        )
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert first == second
    assert first.role_key == "PROCESS_CONSULTANT"
    assert calls == 1


@pytest.mark.asyncio
async def test_deny_decision_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "userId": "pc-1",
                "tenantId": "tenant-1",
                "permissionKey": "di.document.read",
                "allowed": False,
                "reasonCode": "DENIED",
            },
        )

    client = _client(monkeypatch, handler)
    try:
        with pytest.raises(PermissionError):
            await client.authorize(
                user_id="pc-1",
                tenant_id="tenant-1",
                permission_key="di.document.read",
            )
        with pytest.raises(PermissionError):
            await client.authorize(
                user_id="pc-1",
                tenant_id="tenant-1",
                permission_key="di.document.read",
            )
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert calls == 2


@pytest.mark.asyncio
async def test_authorization_error_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"detail": "down"})

    client = _client(monkeypatch, handler)
    try:
        with pytest.raises(RuntimeError, match="HTTP 503"):
            await client.authorize(
                user_id="pc-1",
                tenant_id="tenant-1",
                permission_key="di.document.read",
            )
        with pytest.raises(RuntimeError, match="HTTP 503"):
            await client.authorize(
                user_id="pc-1",
                tenant_id="tenant-1",
                permission_key="di.document.read",
            )
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert calls == 2
