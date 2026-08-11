"""auth/dependencies.py — FastAPI dependency functions for authentication and RBAC.

Usage in route handlers:

    from verigence.di.auth.dependencies import require_actor, require_tenant_actor

    # Any authenticated actor:
    @router.get("/...")
    async def my_route(actor: ActorPrincipal = Depends(require_actor)):
        ...

    # Actor whose JWT tenant_id matches the path {tenantId}:
    @router.get("/v1/tenants/{tenantId}/...")
    async def my_route(
        tenantId: str,
        actor: ActorPrincipal = Depends(require_tenant_actor),
    ):
        ...

    # System-bearer endpoints (WhatsApp webhook, internal ops):
    @router.post("/internal/...")
    async def my_route(actor: ActorPrincipal = Depends(require_system_actor)):
        ...

RBAC enforcement is done inside route handlers via actor.is_admin,
actor.is_operator, etc., or by using the require_role() factory below.
"""
from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from verigence.di.auth.principal import ActorPrincipal
from verigence.di.auth.verifier import verify_token

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=True)
_system_bearer = HTTPBearer(auto_error=True)


# ── Core dependency ───────────────────────────────────────────────────────────

async def require_actor(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> ActorPrincipal:
    """Verify the Bearer JWT and return the resolved ActorPrincipal.

    Raises HTTP 401 on invalid/expired token.
    """
    principal = verify_token(creds.credentials)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"type": "UNAUTHORIZED", "title": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


# ── Tenant-scoped dependency ──────────────────────────────────────────────────

class _RequireTenantActor:
    """Dependency class that validates actor.tenant_id == path tenantId."""

    async def __call__(
        self,
        tenantId: str,
        actor: ActorPrincipal = Depends(require_actor),
    ) -> ActorPrincipal:
        if actor.tenant_id != tenantId:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "type": "FORBIDDEN",
                    "title": "Token tenant does not match path tenant",
                },
            )
        return actor


require_tenant_actor = _RequireTenantActor()


# ── System-bearer dependency ──────────────────────────────────────────────────

async def require_system_actor(
    creds: HTTPAuthorizationCredentials = Depends(_system_bearer),
) -> ActorPrincipal:
    """Require a SYSTEM-role actor (for WhatsApp webhooks / internal ops)."""
    principal = verify_token(creds.credentials)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"type": "UNAUTHORIZED", "title": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not principal.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"type": "FORBIDDEN", "title": "System actor required"},
        )
    return principal


# ── RBAC factory ─────────────────────────────────────────────────────────────

def require_role(*roles: str):  # type: ignore[no-untyped-def]
    """Return a FastAPI dependency that enforces one of the given roles.

    Example::

        @router.post("/...")
        async def create(actor = Depends(require_role("admin", "operator"))):
            ...
    """
    async def _check(actor: ActorPrincipal = Depends(require_actor)) -> ActorPrincipal:
        if not actor.has_role(*roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "type": "FORBIDDEN",
                    "title": f"Required role(s): {', '.join(roles)}",
                },
            )
        return actor
    return _check
