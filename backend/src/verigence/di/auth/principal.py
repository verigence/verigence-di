"""auth/principal.py — Actor identity resolved from a verified Security JWT.

Security JWT canonical claims consumed by DI:
  sub                → actor_id  (Verigence user UUID)
  tenant_id          → tenant_id
  actor_type         → actor_type (USER | SYSTEM | SERVICE_INTEGRATION) — issued by Security
  roles[]            → roles  (informational)
  permissions[]      → permissions (authoritative for authz checks)
  device_id          → device_id (USER actors)
  access_session_id  → access_session_id
  location_id        → location_id
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from verigence.di.auth.permissions import Permission
from verigence.di.domain.enums import ActorType


@dataclass(frozen=True)
class ActorPrincipal:
    """Resolved, validated identity for the calling actor.

    All fields are sourced directly from the verified Security JWT claims.
    No inference — actor_type is issued by Security, not derived by DI.
    """
    actor_id: str
    tenant_id: str
    actor_type: ActorType = ActorType.USER
    roles: frozenset[str] = field(default_factory=frozenset, compare=False, hash=False)
    permissions: frozenset[str] = field(default_factory=frozenset, compare=False, hash=False)
    device_id: str | None = field(default=None, compare=False, hash=False)
    access_session_id: str | None = field(default=None, compare=False, hash=False)
    location_id: str | None = field(default=None, compare=False, hash=False)
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
        return self.actor_type == ActorType.SERVICE_INTEGRATION

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
