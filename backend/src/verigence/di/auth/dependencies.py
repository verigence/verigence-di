"""auth/dependencies.py — FastAPI dependency functions (Baseline 2.2).

v2.2 changes:
- Endpoint authorization now checks permissions[] (authoritative), not role names.
- `require_permission(*perms)` factory replaces the old `require_role()`.
- `require_role()` is kept as an alias for backward compat.
- `require_tenant_actor` still validates path tenantId == JWT tenant_id.
- Device-ID check placeholder added (full enforcement in Step 6b).
"""
from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.auth.verifier import verify_token

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=True)
_system_bearer = HTTPBearer(auto_error=True)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "UNAUTHORIZED", "title": detail, "status": 401, "retryable": False},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "FORBIDDEN", "title": detail, "status": 403, "retryable": False},
    )


# ── Core dependency ───────────────────────────────────────────────────────────

async def require_actor(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> ActorPrincipal:
    """Verify the Bearer JWT and return the resolved ActorPrincipal."""
    principal = verify_token(creds.credentials)
    if principal is None:
        raise _unauthorized("Invalid or expired token")
    return principal


# ── Tenant-scoped dependency ──────────────────────────────────────────────────

class _RequireTenantActor:
    """Validates actor.tenant_id == path tenantId."""

    async def __call__(
        self,
        tenantId: str,
        actor: ActorPrincipal = Depends(require_actor),
    ) -> ActorPrincipal:
        if actor.tenant_id != tenantId:
            raise _forbidden("Token tenant does not match path tenant")
        return actor


require_tenant_actor = _RequireTenantActor()


# ── System-bearer dependency ──────────────────────────────────────────────────

async def require_system_actor(
    creds: HTTPAuthorizationCredentials = Depends(_system_bearer),
) -> ActorPrincipal:
    """Require a SYSTEM actor with di.platform.whatsapp.admin permission."""
    principal = verify_token(creds.credentials, system=True)
    if principal is None:
        raise _unauthorized("Invalid or expired system token")
    if not principal.can(Permission.PLATFORM_WHATSAPP_ADMIN):
        raise _forbidden("di.platform.whatsapp.admin permission required")
    return principal


# ── Permission-based dependency factory (v2.2) ────────────────────────────────

def require_permission(*perms: Permission):  # type: ignore[no-untyped-def]
    """Return a FastAPI dependency that enforces ALL listed permissions.

    Does NOT enforce tenantId path match — use require_tenant_permission() for
    routes that carry a {tenantId} path parameter.

    Usage::

        @router.post("/subjects")
        async def create(actor = Depends(require_permission(Permission.SUBJECT_CREATE))):
            ...
    """
    async def _check(actor: ActorPrincipal = Depends(require_actor)) -> ActorPrincipal:
        missing = [p.value for p in perms if not actor.can(p)]
        if missing:
            raise _forbidden(f"Missing permission(s): {', '.join(missing)}")
        return actor
    return _check


def require_tenant_permission(*perms: Permission):  # type: ignore[no-untyped-def]
    """Return a FastAPI dependency that validates tenantId path match AND permissions.

    Combines require_tenant_actor (tenant_id path check) with permission enforcement.

    Usage::

        @router.post("/v1/tenants/{tenantId}/subjects")
        async def create(
            actor = Depends(require_tenant_permission(Permission.SUBJECT_CREATE)),
        ):
            ...
    """
    async def _check(
        actor: ActorPrincipal = Depends(require_tenant_actor),
    ) -> ActorPrincipal:
        missing = [p.value for p in perms if not actor.can(p)]
        if missing:
            raise _forbidden(f"Missing permission(s): {', '.join(missing)}")
        return actor
    return _check


# ── require_role kept for backward compatibility ──────────────────────────────

def require_role(*roles: str):  # type: ignore[no-untyped-def]
    """Backward-compat shim: delegates to has_role() check.

    Prefer require_permission() for new route handlers.
    """
    async def _check(
        actor: ActorPrincipal = Depends(require_tenant_actor),
    ) -> ActorPrincipal:
        if not actor.has_role(*roles):
            raise _forbidden(f"Required role(s): {', '.join(roles)}")
        return actor
    return _check
