"""tests/test_auth.py — Unit tests for JWT verifier and RBAC (Baseline 2.2).

No Docker, no network — uses the mock token protocol from verifier.py.

v2.2 changes tested:
- Mock tokens resolve role names to permissions[] from ROLE_PERMISSIONS bundles.
- ActorPrincipal uses permissions[], not a single role string.
- .can(Permission.XXX) is the authoritative check.
- Legacy .is_admin / .is_uploader etc. delegate to permissions.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_docker

from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.auth.verifier import verify_token
from verigence.di.domain.enums import ActorType


# ── verify_token mock-mode tests ─────────────────────────────────────────────

def test_empty_token_returns_none() -> None:
    result = verify_token("")
    assert result is None


def test_mock_tenant_admin_token() -> None:
    principal = verify_token("mock.tenant-abc.user-xyz.TENANT_ADMIN")
    assert principal is not None
    assert principal.tenant_id == "tenant-abc"
    assert principal.actor_id == "user-xyz"
    assert "TENANT_ADMIN" in principal.roles
    # TENANT_ADMIN should have subject:create
    assert principal.can(Permission.SUBJECT_CREATE)
    assert principal.can(Permission.DOCUMENT_UPLOAD)
    assert principal.can(Permission.VERIFICATION_WRITE)


def test_mock_document_operator_token() -> None:
    principal = verify_token("mock.t1.u1.DOCUMENT_OPERATOR")
    assert principal is not None
    assert principal.can(Permission.DOCUMENT_UPLOAD)
    assert principal.can(Permission.SUBJECT_CREATE)
    # DOCUMENT_OPERATOR does NOT have verification:write
    assert not principal.can(Permission.VERIFICATION_WRITE)


def test_mock_document_verifier_token() -> None:
    principal = verify_token("mock.t1.u1.DOCUMENT_VERIFIER")
    assert principal is not None
    assert principal.can(Permission.VERIFICATION_WRITE)
    assert principal.can(Permission.VERIFICATION_READ)
    # DOCUMENT_VERIFIER does NOT have document:upload
    assert not principal.can(Permission.DOCUMENT_UPLOAD)


def test_mock_operations_viewer_read_only() -> None:
    principal = verify_token("mock.t1.u1.OPERATIONS_VIEWER")
    assert principal is not None
    assert principal.can(Permission.OPERATIONS_READ)
    assert not principal.can(Permission.DOCUMENT_UPLOAD)
    assert not principal.can(Permission.SUBJECT_CREATE)


def test_non_mock_prefixed_token_fails_jwks_in_mock_mode() -> None:
    # Non mock.-prefixed tokens fall through to real JWKS; fails in test env
    principal = verify_token("some.arbitrary.jwt.value")
    assert principal is None


# ── ActorPrincipal permission checks ─────────────────────────────────────────

def test_can_returns_true_for_held_permission() -> None:
    p = ActorPrincipal(
        actor_id="a", tenant_id="t",
        permissions=frozenset({"subject:create", "document:upload"}),
    )
    assert p.can(Permission.SUBJECT_CREATE) is True
    assert p.can(Permission.VERIFICATION_WRITE) is False


def test_has_role_checks_roles_set() -> None:
    p = ActorPrincipal(actor_id="a", tenant_id="t", roles=frozenset({"DOCUMENT_VERIFIER"}))
    assert p.has_role("DOCUMENT_VERIFIER") is True
    assert p.has_role("TENANT_ADMIN") is False


def test_is_system_actor() -> None:
    p = ActorPrincipal(
        actor_id="sys", tenant_id="",
        actor_type=ActorType.SYSTEM,
        permissions=frozenset({"platform:whatsapp:admin"}),
    )
    assert p.is_system is True
    assert p.can(Permission.PLATFORM_WHATSAPP_ADMIN) is True


def test_is_uploader_delegates_to_permission() -> None:
    # With DOCUMENT_OPERATOR role → should have document:upload permission
    p = verify_token("mock.t1.u1.DOCUMENT_OPERATOR")
    assert p is not None
    assert p.is_uploader is True


def test_is_verifier_delegates_to_permission() -> None:
    p = verify_token("mock.t1.u1.DOCUMENT_VERIFIER")
    assert p is not None
    assert p.is_verifier is True
    assert p.is_uploader is False  # VERIFIER does not have upload


def test_tenant_admin_is_also_admin_and_operator() -> None:
    p = verify_token("mock.t1.u1.TENANT_ADMIN")
    assert p is not None
    assert p.is_admin is True
    assert p.is_operator is True
