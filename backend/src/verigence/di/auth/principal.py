"""auth/principal.py — Actor identity resolved from a verified JWT (Baseline 2.2).

v2.2 changes (DI_SECURITY_RBAC_v2.2.md):
- JWT canonical claims: tenant_id, actor_id, actor_type, roles[], permissions[]
- Authorization checks permissions[] (authoritative), not role-name strings.
- device_id required for actor_type=USER (enforced in dependency layer).
- Old helpers (is_admin, is_operator etc.) are kept as convenience shims
  but internally delegate to the permissions set.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from verigence.di.auth.permissions import Permission
from verigence.di.domain.enums import ActorType


@dataclass(frozen=True)
class ActorPrincipal:
    """Resolved, validated identity for the calling actor.

    Fields sourced from verified JWT canonical claims (v2.2):
        sub / actor_id  → actor_id
        tenant_id       → tenant_id
        actor_type      → actor_type (USER | SERVICE | SYSTEM)
        roles[]         → roles  (role bundle names — informational)
        permissions[]   → permissions (authoritative for authz checks)
        device_id       → device_id (required for USER actors)
    """
    actor_id: str
    tenant_id: str
    actor_type: ActorType = ActorType.USER
    roles: frozenset[str] = field(default_factory=frozenset, compare=False, hash=False)
    permissions: frozenset[str] = field(default_factory=frozenset, compare=False, hash=False)
    device_id: str | None = field(default=None, compare=False, hash=False)
    raw_claims: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    # ── Permission checks (v2.2 — use these in route handlers) ───────────────

    def can(self, permission: Permission) -> bool:
        """Return True if this actor has the given permission."""
        return permission.value in self.permissions

    def require(self, permission: Permission) -> None:
        """Raise ValueError if the actor lacks the permission.

        Route handlers should use the `require_permission` FastAPI dependency
        rather than calling this directly.
        """
        if not self.can(permission):
            raise ValueError(f"Missing permission: {permission.value}")

    # ── Convenience shims (backward compat + readability) ─────────────────────

    @property
    def is_system(self) -> bool:
        return self.actor_type == ActorType.SYSTEM

    @property
    def is_service(self) -> bool:
        return self.actor_type == ActorType.SERVICE

    # Legacy role-name helpers — kept so existing router code still compiles.
    # New route handlers MUST use .can(Permission.XXX) instead.

    @property
    def is_admin(self) -> bool:
        return "TENANT_ADMIN" in self.roles

    @property
    def is_operator(self) -> bool:
        return bool({"TENANT_ADMIN", "DOCUMENT_OPERATOR"} & self.roles)

    @property
    def is_uploader(self) -> bool:
        return self.can(Permission.DOCUMENT_UPLOAD)

    @property
    def is_verifier(self) -> bool:
        return self.can(Permission.VERIFICATION_WRITE)

    def has_role(self, *roles: str) -> bool:
        """Return True if the actor has at least one of the given role names."""
        return bool(set(roles) & self.roles)
