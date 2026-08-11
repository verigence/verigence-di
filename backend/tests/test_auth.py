"""tests/test_auth.py — Unit tests for JWT verifier and RBAC helpers.

No Docker, no network — uses the mock token protocol from verifier.py.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_docker

from verigence.di.auth.principal import ActorPrincipal
from verigence.di.auth.verifier import verify_token
from verigence.di.domain.enums import ActorType


# ── verify_token mock-mode tests ─────────────────────────────────────────────

def test_empty_token_returns_none() -> None:
    result = verify_token("")
    assert result is None


def test_mock_admin_token() -> None:
    principal = verify_token("mock.tenant-abc.user-xyz.admin")
    assert principal is not None
    assert principal.tenant_id == "tenant-abc"
    assert principal.actor_id == "user-xyz"
    assert principal.role == "admin"


def test_mock_operator_token() -> None:
    principal = verify_token("mock.t1.u1.operator")
    assert principal is not None
    assert principal.is_operator is True
    assert principal.is_admin is False


def test_mock_uploader_token() -> None:
    principal = verify_token("mock.t1.u1.uploader")
    assert principal is not None
    assert principal.is_uploader is True
    assert principal.is_verifier is False


def test_mock_readonly_token_not_uploader() -> None:
    principal = verify_token("mock.t1.u1.readonly")
    assert principal is not None
    assert principal.is_uploader is False
    assert principal.is_operator is False


def test_non_mock_prefixed_token_falls_through_to_real_jwks_in_mock_mode() -> None:
    # Non mock.-prefixed tokens fall through to real JWKS verification
    # which fails in tests (no real JWKS endpoint) → None is correct.
    principal = verify_token("some.arbitrary.jwt.value")
    assert principal is None  # JWKS verification fails → None expected


# ── ActorPrincipal RBAC helpers ───────────────────────────────────────────────

def test_has_role_exact_match() -> None:
    p = ActorPrincipal(actor_id="a", tenant_id="t", role="verifier")
    assert p.has_role("verifier") is True
    assert p.has_role("admin") is False


def test_admin_is_also_operator_and_uploader_and_verifier() -> None:
    p = ActorPrincipal(actor_id="a", tenant_id="t", role="admin")
    assert p.is_admin is True
    assert p.is_operator is True
    assert p.is_uploader is True
    assert p.is_verifier is True


def test_system_actor() -> None:
    p = ActorPrincipal(
        actor_id="sys", tenant_id="t", role="system",
        actor_type=ActorType.SYSTEM,
    )
    assert p.is_system is True
    assert p.is_admin is False
