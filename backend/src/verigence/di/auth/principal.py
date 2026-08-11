"""auth/principal.py — Actor identity resolved from a verified JWT.

Carried by every authenticated request and available as a FastAPI dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from verigence.di.domain.enums import ActorType


@dataclass(frozen=True)
class ActorPrincipal:
    """Resolved, validated identity for the calling actor.

    Fields are sourced from JWT claims after JWKS verification.

    Claim conventions (Clerk custom claims via session template):
        sub           → actor_id   (Clerk user/service ID)
        org_id        → tenant_id  (Clerk organization = Verigence Tenant)
        org_role      → role       ("admin", "operator", "uploader", "verifier",
                                    "readonly", "system")
        actor_type    → actor_type (USER | SYSTEM | SERVICE; defaults to USER)
    """
    actor_id: str
    tenant_id: str
    role: str
    actor_type: ActorType = ActorType.USER
    # Raw claims preserved for downstream audit use
    raw_claims: dict = field(default_factory=dict, compare=False, hash=False)  # type: ignore[type-arg]

    # ── RBAC helpers ─────────────────────────────────────────────────────────

    def has_role(self, *roles: str) -> bool:
        """Return True if the actor's role is one of the supplied roles."""
        return self.role in roles

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_operator(self) -> bool:
        return self.role in ("admin", "operator")

    @property
    def is_uploader(self) -> bool:
        return self.role in ("admin", "operator", "uploader")

    @property
    def is_verifier(self) -> bool:
        return self.role in ("admin", "operator", "verifier")

    @property
    def is_system(self) -> bool:
        return self.actor_type == ActorType.SYSTEM
