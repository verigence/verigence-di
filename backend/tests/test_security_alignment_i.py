"""Increment I — Security/DI authorization alignment regression tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.requests import Request

from verigence.di.auth import verifier
from verigence.di.auth.dependencies import require_tenant_actor
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.domain.enums import ActorType

pytestmark = pytest.mark.no_docker


class _FakeJwksCache:
    def get_key(self, kid: str) -> str | None:
        return "test-key" if kid == "kid-1" else None


def _claims(*, actor_type: str | None, tenant_id: str = "tenant-a") -> dict[str, object]:
    claims: dict[str, object] = {
        "iss": "verigence-security",
        "aud": "verigence-platform",
        "sub": "actor-1",
        "tenant_id": tenant_id,
        "roles": [],
        "permissions": ["di.subject.read"],
    }
    if actor_type is not None:
        claims["actor_type"] = actor_type
    return claims


def _patch_verified_claims(monkeypatch: pytest.MonkeyPatch, claims: dict[str, object]) -> None:
    monkeypatch.setattr(verifier, "get_jwks_cache", lambda: _FakeJwksCache())
    monkeypatch.setattr(verifier.jwt, "get_unverified_header", lambda token: {"kid": "kid-1"})
    monkeypatch.setattr(verifier.jwt, "decode", lambda *args, **kwargs: claims)


def test_actor_catalog_matches_security_contract() -> None:
    assert {member.value for member in ActorType} == {
        "USER",
        "SYSTEM",
        "SERVICE_INTEGRATION",
    }


def test_unknown_actor_type_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_verified_claims(monkeypatch, _claims(actor_type="SOMETHING_UNKNOWN"))
    assert verifier.verify_token("real.jwt.token") is None


def test_missing_actor_type_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_verified_claims(monkeypatch, _claims(actor_type=None))
    assert verifier.verify_token("real.jwt.token") is None


def test_service_integration_is_accepted_as_tenant_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_verified_claims(monkeypatch, _claims(actor_type="SERVICE_INTEGRATION"))
    principal = verifier.verify_token("real.jwt.token")
    assert principal is not None
    assert principal.actor_type is ActorType.SERVICE_INTEGRATION
    assert principal.tenant_id == "tenant-a"


def test_tenant_scoped_system_token_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_verified_claims(monkeypatch, _claims(actor_type="SYSTEM", tenant_id="tenant-a"))
    principal = verifier.verify_token("real.jwt.token", system=True)
    assert principal is not None
    assert principal.actor_type is ActorType.SYSTEM
    assert principal.tenant_id == "tenant-a"


def test_non_system_token_cannot_use_system_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_verified_claims(monkeypatch, _claims(actor_type="USER", tenant_id="tenant-a"))
    assert verifier.verify_token("real.jwt.token", system=True) is None


def _request(path_params: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "path_params": path_params,
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1),
            "scheme": "http",
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("path_params", [{"tenantId": "tenant-a"}, {"tenant_id": "tenant-a"}])
async def test_tenant_gate_supports_current_path_parameter_spellings(
    path_params: dict[str, str],
) -> None:
    actor = ActorPrincipal(actor_id="actor-1", tenant_id="tenant-a")
    resolved = await require_tenant_actor(_request(path_params), actor)
    assert resolved is actor


@pytest.mark.asyncio
async def test_tenant_gate_rejects_cross_tenant_url() -> None:
    actor = ActorPrincipal(actor_id="actor-1", tenant_id="tenant-a")
    with pytest.raises(Exception) as exc_info:
        await require_tenant_actor(_request({"tenantId": "tenant-b"}), actor)
    assert getattr(exc_info.value, "status_code", None) == 403


def test_tenant_route_modules_do_not_use_identity_only_gate() -> None:
    """Every Tenant business route must pair isolation with an explicit permission."""
    api_dir = Path(__file__).parents[1] / "src" / "verigence" / "di" / "api" / "v1"
    offenders: list[str] = []
    for path in sorted(api_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "Depends(require_tenant_actor)" in text:
            offenders.append(path.name)
    assert offenders == [], f"Tenant routes missing explicit permission gates: {offenders}"
