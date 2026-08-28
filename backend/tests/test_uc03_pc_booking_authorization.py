from __future__ import annotations

import time

import httpx
import pytest

from verigence.di.auth import human_authorization
from verigence.di.auth.human_authorization import SecurityLiveAuthorizationClient

pytestmark = pytest.mark.no_docker


class _JWKSCache:
    def get_key(self, kid: str) -> str | None:
        return "test-key" if kid == "kid-1" else None


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


def test_global_human_token_accepts_device_and_session_identity_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims: dict[str, object] = {
        "iss": "verigence-security",
        "aud": "verigence-platform",
        "sub": "pc-1",
        "actor_type": "USER",
        "device_id": "device-1",
        "session_id": "session-1",
    }
    monkeypatch.setattr(human_authorization, "get_jwks_cache", lambda: _JWKSCache())
    monkeypatch.setattr(
        human_authorization.jwt,
        "get_unverified_header",
        lambda token: {"kid": "kid-1"},
    )
    monkeypatch.setattr(human_authorization.jwt, "decode", lambda *args, **kwargs: claims)

    identity = human_authorization.verify_global_human_token("signed-human-token")

    assert identity is not None
    assert identity.user_id == "pc-1"


def test_global_human_token_still_rejects_tenant_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims: dict[str, object] = {
        "iss": "verigence-security",
        "aud": "verigence-platform",
        "sub": "pc-1",
        "actor_type": "USER",
        "device_id": "device-1",
        "session_id": "session-1",
        "tenant_id": "tenant-1",
    }
    monkeypatch.setattr(human_authorization, "get_jwks_cache", lambda: _JWKSCache())
    monkeypatch.setattr(
        human_authorization.jwt,
        "get_unverified_header",
        lambda token: {"kid": "kid-1"},
    )
    monkeypatch.setattr(human_authorization.jwt, "decode", lambda *args, **kwargs: claims)

    assert human_authorization.verify_global_human_token("signed-human-token") is None


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
