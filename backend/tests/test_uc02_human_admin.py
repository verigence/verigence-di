from __future__ import annotations

from time import time
from uuid import uuid4

import httpx
import pytest

from verigence.di.auth import human_admin

pytestmark = pytest.mark.no_docker


class _JWKSCache:
    def get_key(self, kid: str) -> str | None:
        return "test-key" if kid == "kid-1" else None


def _human_claims() -> dict[str, object]:
    now = int(time())
    return {
        "iss": "verigence-security",
        "aud": "verigence-platform",
        "sub": str(uuid4()),
        "iat": now,
        "exp": now + 300,
        "jti": str(uuid4()),
        "actor_type": "USER",
    }


def _patch_decode(monkeypatch: pytest.MonkeyPatch, claims: dict[str, object]) -> None:
    monkeypatch.setattr(human_admin, "get_jwks_cache", lambda: _JWKSCache())
    monkeypatch.setattr(human_admin.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(human_admin.jwt, "decode", lambda *args, **kwargs: claims)


def test_security_human_token_accepts_minimal_current_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = _human_claims()
    _patch_decode(monkeypatch, claims)

    principal = human_admin.verify_security_human_token("signed-human-token")

    assert principal is not None
    assert principal.user_id == claims["sub"]


@pytest.mark.parametrize(
    "claim_name,claim_value",
    [
        ("tenant_id", "tenant-a"),
        ("permissions", ["di:admin"]),
        ("roles", ["SuperAdmin"]),
        ("device_id", "device-a"),
        ("location_id", "location-a"),
        ("act", {"sub": "delegated"}),
    ],
)
def test_security_human_token_rejects_embedded_authority_claims(
    monkeypatch: pytest.MonkeyPatch,
    claim_name: str,
    claim_value: object,
) -> None:
    claims = _human_claims()
    claims[claim_name] = claim_value
    _patch_decode(monkeypatch, claims)

    assert human_admin.verify_security_human_token("signed-human-token") is None


def test_security_human_token_rejects_service_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = _human_claims()
    claims["actor_type"] = "SERVICE_INTEGRATION"
    _patch_decode(monkeypatch, claims)

    assert human_admin.verify_security_human_token("signed-machine-token") is None


def test_security_human_token_rejects_mock_token() -> None:
    assert human_admin.verify_security_human_token("mock.tenant.actor.SuperAdmin") is None


def test_admin_context_client_forwards_exact_human_bearer() -> None:
    user_id = str(uuid4())
    observed: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers["Authorization"]
        observed["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "userId": user_id,
                "isSuperAdmin": True,
                "adminScopes": [
                    {"roleKey": "SuperAdmin", "scopeType": "PLATFORM", "scopeId": None}
                ],
            },
        )

    with human_admin.SecurityAdminClient(
        base_url="https://security.example.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        context = client.get_admin_context(human_bearer_token="original-human-token")

    assert observed == {
        "authorization": "Bearer original-human-token",
        "path": "/security/v1/platform/admin-context",
    }
    assert context.user_id == user_id
    assert context.is_super_admin is True
    assert context.admin_scopes[0].role_key == "SuperAdmin"


def test_admin_context_client_rejects_invalid_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"userId": str(uuid4()), "isSuperAdmin": "yes"})

    with (
        human_admin.SecurityAdminClient(
            base_url="https://security.example.test",
            transport=httpx.MockTransport(handler),
        ) as client,
        pytest.raises(human_admin.SecurityAdminError),
    ):
        client.get_admin_context(human_bearer_token="original-human-token")


def test_security_base_url_is_derived_from_configured_jwks_origin() -> None:
    assert (
        human_admin.security_base_url_from_jwks_url(
            "https://security.example.test/.well-known/jwks.json"
        )
        == "https://security.example.test"
    )
