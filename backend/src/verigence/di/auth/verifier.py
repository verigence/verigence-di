"""auth/verifier.py — JWT verification against OIDC JWKS (Baseline 2.2).

v2.2 JWT canonical claims (DI_SECURITY_RBAC_v2.2.md):
  Tenant JWT audience : verigence-document-intelligence
  Required claims     : iss, sub, aud, exp, iat,
                        tenant_id, actor_id, actor_type, roles[], permissions[]
  USER conditional    : device_id

System JWT audience   : verigence-document-intelligence-system
  tenant_id must be ABSENT.

Mock token protocol (DI_DOCAI_MOCK=true, local dev/CI):
  "mock.<tenant_id>.<actor_id>.<ROLE_NAME>[.<ROLE_NAME>...]"
  Permissions are resolved from the default role bundles.
"""
from __future__ import annotations

import logging
from typing import Any

from jose import JWTError, jwt  # type: ignore[import]

from verigence.di.auth.jwks import get_jwks_cache
from verigence.di.auth.permissions import ROLE_PERMISSIONS
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.domain.enums import ActorType

logger = logging.getLogger(__name__)

# ── v2.2 JWT contract constants ───────────────────────────────────────────────
_AUDIENCE_TENANT  = "verigence-document-intelligence"
_AUDIENCE_SYSTEM  = "verigence-document-intelligence-system"

_CLAIM_TENANT_ID  = "tenant_id"
_CLAIM_ACTOR_ID   = "actor_id"
_CLAIM_ACTOR_TYPE = "actor_type"
_CLAIM_ROLES      = "roles"
_CLAIM_PERMISSIONS = "permissions"
_CLAIM_DEVICE_ID  = "device_id"

# Mock defaults
_MOCK_TENANT = "mock-tenant-id"
_MOCK_ACTOR  = "mock-actor-id"
_MOCK_ROLE   = "TENANT_ADMIN"


def _permissions_for_roles(roles: list[str]) -> frozenset[str]:
    """Resolve permissions from role bundle names (mock mode only)."""
    perms: set[str] = set()
    for role in roles:
        bundle = ROLE_PERMISSIONS.get(role.upper(), frozenset())
        perms.update(p.value for p in bundle)
    return frozenset(perms)


def verify_token(token: str, *, system: bool = False) -> ActorPrincipal | None:
    """Verify *token* and return an ActorPrincipal, or None on any failure."""
    try:
        return _verify(token, system=system)
    except Exception as exc:
        logger.debug("jwt_verification_error", extra={"error": str(exc)})
        return None


def _verify(token: str, *, system: bool) -> ActorPrincipal | None:
    from verigence.di.settings import get_settings
    settings = get_settings()

    # ── Mock mode ─────────────────────────────────────────────────────────────
    if settings.docai_mock:
        if not token:
            return None
        if token.startswith("mock."):
            # "mock.<tenant>.<actor>.<ROLE1>[.<ROLE2>...]"
            parts = token.split(".", maxsplit=3)
            tenant  = parts[1] if len(parts) > 1 else _MOCK_TENANT
            actor   = parts[2] if len(parts) > 2 else _MOCK_ACTOR
            # Everything after the third dot is roles (comma-separated for multi-role)
            raw_roles_str = parts[3] if len(parts) > 3 else _MOCK_ROLE
            roles = [r.strip().upper() for r in raw_roles_str.replace(",", ".").split(".") if r.strip()]
            if not roles:
                roles = [_MOCK_ROLE]

            perms = _permissions_for_roles(roles)

            # System mock token
            if system:
                return ActorPrincipal(
                    actor_id=actor,
                    tenant_id="",
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
        # Non-mock-prefix → fall through to real JWKS verification below

    # ── Real JWKS verification ─────────────────────────────────────────────────
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        logger.debug("jwt_bad_header", extra={"error": str(exc)})
        return None

    kid = unverified_header.get("kid", "")
    cache = get_jwks_cache()
    key = cache.get_key(kid)
    if key is None:
        logger.warning("jwks_key_not_found", extra={"kid": kid})
        return None

    expected_audience = _AUDIENCE_SYSTEM if system else _AUDIENCE_TENANT
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=expected_audience,
        )
    except JWTError as exc:
        logger.debug("jwt_decode_failed", extra={"error": str(exc)})
        return None

    # ── Extract canonical claims ───────────────────────────────────────────────
    actor_id: str  = claims.get(_CLAIM_ACTOR_ID, "") or claims.get("sub", "")
    tenant_id: str = claims.get(_CLAIM_TENANT_ID, "")
    raw_actor_type = claims.get(_CLAIM_ACTOR_TYPE, "USER")
    raw_roles: list[str] = claims.get(_CLAIM_ROLES, [])
    raw_perms: list[str] = claims.get(_CLAIM_PERMISSIONS, [])
    device_id: str | None = claims.get(_CLAIM_DEVICE_ID)

    if not actor_id:
        logger.warning("jwt_missing_actor_id")
        return None

    # System tokens must NOT carry tenant_id
    if system and tenant_id:
        logger.warning("jwt_system_token_has_tenant_id", extra={"tenant_id": tenant_id})
        return None

    # Tenant tokens must carry tenant_id
    if not system and not tenant_id:
        logger.warning("jwt_missing_tenant_id", extra={"actor_id": actor_id})
        return None

    try:
        actor_type = ActorType(raw_actor_type)
    except ValueError:
        actor_type = ActorType.USER

    return ActorPrincipal(
        actor_id=actor_id,
        tenant_id=tenant_id,
        actor_type=actor_type,
        roles=frozenset(r for r in raw_roles if isinstance(r, str)),
        permissions=frozenset(p for p in raw_perms if isinstance(p, str)),
        device_id=device_id,
        raw_claims=claims,
    )
