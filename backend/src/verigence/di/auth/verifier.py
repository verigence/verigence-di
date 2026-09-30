"""auth/verifier.py — JWT verification against Security module JWKS.

Security module JWT canonical claims:
  iss                 : verigence-security
  aud                 : verigence-platform
  sub                 : Verigence user/principal UUID
  tenant_id           : Tenant UUID for Tenant-scoped actors
  actor_type          : USER | SYSTEM | SERVICE_INTEGRATION
  roles[]             : Tenant-scoped role names (informational)
  permissions[]       : Effective permissions (authoritative)
  device_id           : Registered device UUID (USER actors)
  access_session_id   : Security access session UUID
  location_id         : Matched location UUID

Mock token protocol (local + dev only — not available in production):
  "mock.<tenant_id>.<actor_id>.<ROLE_NAME>[.<ROLE_NAME>...]"
  Permissions are resolved from the default role bundles.
  Mock tokens are rejected when DI_ENV=production.
"""
from __future__ import annotations

from typing import Any

import structlog
from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWTClaimsError

from verigence.di.auth.jwks import JWKSUnavailableError, get_jwks_cache
from verigence.di.auth.permissions import ROLE_PERMISSIONS
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.domain.enums import ActorType
from verigence.di.runtime_errors import safe_exception_context

logger = structlog.get_logger(__name__)

# ── Security JWT contract constants ───────────────────────────────────────────
_ISSUER = "verigence-security"
_AUDIENCE = "verigence-platform"

_CLAIM_TENANT_ID = "tenant_id"
_CLAIM_ACTOR_TYPE = "actor_type"
_CLAIM_ROLES = "roles"
_CLAIM_PERMISSIONS = "permissions"
_CLAIM_DEVICE_ID = "device_id"
_CLAIM_ACCESS_SESSION_ID = "access_session_id"
_CLAIM_LOCATION_ID = "location_id"

# Mock defaults
_MOCK_TENANT = "mock-tenant-id"
_MOCK_ACTOR = "mock-actor-id"
_MOCK_ROLE = "TENANT_ADMIN"


def _permissions_for_roles(roles: list[str]) -> frozenset[str]:
    """Resolve permissions from role bundle names (mock mode only)."""
    perms: set[str] = set()
    for role in roles:
        bundle = ROLE_PERMISSIONS.get(role.upper(), frozenset())
        perms.update(p.value for p in bundle)
    return frozenset(perms)


def _reject(reason: str, **fields: Any) -> None:
    """Log why a token was refused. Never log the token or its claims payload."""
    logger.warning("jwt_rejected", reason=reason, **fields)


def verify_token(token: str, *, system: bool = False) -> ActorPrincipal | None:
    """Verify *token* and return an ActorPrincipal, or None if it is not valid.

    Raises ``JWKSUnavailableError`` when the Security JWKS cannot be reached, so
    callers answer 503 for a dependency outage instead of 401.
    """
    try:
        return _verify(token, system=system)
    except JWKSUnavailableError:
        raise
    except Exception as exc:
        _reject("verification_error", system=system, **safe_exception_context(exc))
        return None


def _verify(token: str, *, system: bool) -> ActorPrincipal | None:
    from verigence.di.settings import get_settings

    settings = get_settings()

    # ── Mock token — local and dev only, never production ─────────────────────
    if token.startswith("mock."):
        if settings.is_production:
            _reject("mock_token_in_production")
            return None
        # "mock.<tenant>.<actor>.<ROLE1>[.<ROLE2>...]"
        parts = token.split(".", maxsplit=3)
        tenant = parts[1] if len(parts) > 1 else _MOCK_TENANT
        actor = parts[2] if len(parts) > 2 else _MOCK_ACTOR
        raw_roles_str = parts[3] if len(parts) > 3 else _MOCK_ROLE
        roles = [
            r.strip().upper()
            for r in raw_roles_str.replace(",", ".").split(".")
            if r.strip()
        ]
        if not roles:
            roles = [_MOCK_ROLE]
        perms = _permissions_for_roles(roles)
        if system:
            return ActorPrincipal(
                actor_id=actor,
                tenant_id=tenant,
                actor_type=ActorType.SYSTEM,
                roles=frozenset(roles),
                permissions=perms,
                raw_claims={},
            )
        return ActorPrincipal(
            actor_id=actor,
            tenant_id=tenant,
            actor_type=ActorType.USER,
            roles=frozenset(roles),
            permissions=perms,
            raw_claims={},
        )

    # ── Real Security JWKS verification ───────────────────────────────────────
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        _reject("malformed_token")
        return None

    kid = unverified_header.get("kid", "")
    cache = get_jwks_cache()
    key = cache.get_key(kid)
    if key is None:
        _reject("unknown_signing_key", kid=str(kid)[:64])
        return None

    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=_AUDIENCE,
            issuer=_ISSUER,
        )
    except ExpiredSignatureError:
        _reject("token_expired")
        return None
    except JWTClaimsError:
        _reject("invalid_claims")
        return None
    except JWTError:
        _reject("invalid_signature")
        return None

    # ── Extract canonical claims ───────────────────────────────────────────────
    actor_id: str = claims.get("sub", "")
    tenant_id: str = claims.get(_CLAIM_TENANT_ID, "")
    raw_actor_type = claims.get(_CLAIM_ACTOR_TYPE)
    raw_roles: list[str] = claims.get(_CLAIM_ROLES, [])
    raw_perms: list[str] = claims.get(_CLAIM_PERMISSIONS, [])
    device_id: str | None = claims.get(_CLAIM_DEVICE_ID)
    access_session_id: str | None = claims.get(_CLAIM_ACCESS_SESSION_ID)
    location_id: str | None = claims.get(_CLAIM_LOCATION_ID)

    if not actor_id:
        _reject("missing_sub")
        return None

    if not isinstance(raw_actor_type, str) or not raw_actor_type:
        _reject("missing_actor_type", actor_id=actor_id)
        return None

    try:
        actor_type = ActorType(raw_actor_type)
    except ValueError:
        _reject("unknown_actor_type", actor_id=actor_id, actor_type=raw_actor_type[:64])
        return None

    # Dedicated system endpoints require a canonical SYSTEM actor. Security may
    # issue SYSTEM identities with a Tenant scope, so tenant_id is allowed here.
    if system:
        if actor_type is not ActorType.SYSTEM:
            _reject(
                "system_endpoint_wrong_actor_type",
                actor_id=actor_id,
                actor_type=actor_type.value,
            )
            return None
    else:
        # Normal DI business/Admin operations are Tenant-scoped for all canonical
        # actor types (USER, SYSTEM and SERVICE_INTEGRATION).
        if not tenant_id:
            _reject("missing_tenant_id", actor_id=actor_id)
            return None

    return ActorPrincipal(
        actor_id=actor_id,
        tenant_id=tenant_id,
        actor_type=actor_type,
        roles=frozenset(r for r in raw_roles if isinstance(r, str)),
        permissions=frozenset(p for p in raw_perms if isinstance(p, str)),
        device_id=device_id,
        access_session_id=access_session_id,
        location_id=location_id,
        raw_claims=claims,
    )
