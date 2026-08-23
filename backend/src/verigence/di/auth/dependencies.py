"""auth/dependencies.py — FastAPI dependency functions (Baseline 2.2).

v2.2 changes:
- Endpoint authorization checks permissions[] (authoritative), not role names.
- `require_permission(*perms)` factory replaces the old `require_role()`.
- `require_role()` is kept as an alias for backward compatibility.
- Tenant authorization validates the route Tenant against JWT tenant_id.
"""
from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.auth.verifier import verify_token
from verigence.di.otel import attach_identity_context

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=True)
_system_bearer = HTTPBearer(auto_error=True)


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


async def require_actor(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> ActorPrincipal:
    """Verify the Bearer JWT and return the resolved ActorPrincipal."""
    principal = verify_token(creds.credentials)
    if principal is None:
        raise _unauthorized("Invalid or expired token")
    attach_identity_context(actor_id=principal.actor_id, tenant_id=principal.tenant_id)
    return principal


class _RequireTenantActor:
    """Validate route Tenant identity against the Security JWT tenant_id.

    The approved DI OpenAPI uses ``tenantId``. A few historical route modules
    still expose ``tenant_id``; accepting both here keeps the authorization
    gate fail-closed while those route spellings are normalized.
    """

    async def __call__(
        self,
        request: Request,
        actor: ActorPrincipal = Depends(require_actor),
    ) -> ActorPrincipal:
        camel = request.path_params.get("tenantId")
        snake = request.path_params.get("tenant_id")
        if camel is not None and snake is not None and camel != snake:
            raise _forbidden("Ambiguous tenant path")
        route_tenant = camel or snake
        if not route_tenant:
            raise _forbidden("Tenant-scoped route is missing tenant path context")
        if actor.tenant_id != str(route_tenant):
            raise _forbidden("Token tenant does not match path tenant")
        return actor


require_tenant_actor = _RequireTenantActor()


async def require_system_actor(
    creds: HTTPAuthorizationCredentials = Depends(_system_bearer),
) -> ActorPrincipal:
    """Require a canonical SYSTEM actor with WhatsApp platform permission."""
    principal = verify_token(creds.credentials, system=True)
    if principal is None:
        raise _unauthorized("Invalid or expired system token")
    attach_identity_context(actor_id=principal.actor_id, tenant_id=principal.tenant_id)
    if not principal.can(Permission.PLATFORM_WHATSAPP_ADMIN):
        raise _forbidden("di.platform.whatsapp.admin permission required")
    return principal


def require_permission(*perms: Permission):  # type: ignore[no-untyped-def]
    """Return a dependency that enforces all listed permissions."""

    async def _check(actor: ActorPrincipal = Depends(require_actor)) -> ActorPrincipal:
        missing = [p.value for p in perms if not actor.can(p)]
        if missing:
            raise _forbidden(f"Missing permission(s): {', '.join(missing)}")
        return actor

    return _check


def require_tenant_permission(*perms: Permission):  # type: ignore[no-untyped-def]
    """Validate Tenant path match and enforce all listed permissions."""

    async def _check(
        actor: ActorPrincipal = Depends(require_tenant_actor),
    ) -> ActorPrincipal:
        missing = [p.value for p in perms if not actor.can(p)]
        if missing:
            raise _forbidden(f"Missing permission(s): {', '.join(missing)}")
        return actor

    return _check


def require_role(*roles: str):  # type: ignore[no-untyped-def]
    """Backward-compatible role check; new code must prefer permissions."""

    async def _check(
        actor: ActorPrincipal = Depends(require_tenant_actor),
    ) -> ActorPrincipal:
        if not actor.has_role(*roles):
            raise _forbidden(f"Required role(s): {', '.join(roles)}")
        return actor

    return _check
