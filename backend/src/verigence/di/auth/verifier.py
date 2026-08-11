"""auth/verifier.py — JWT verification against Clerk JWKS.

Responsible for:
1. Decoding the JWT header to extract `kid`.
2. Looking up the public key from the JWKS cache.
3. Verifying signature, expiry, and required claims.
4. Returning an ActorPrincipal on success or None on any failure.

This module never raises — it returns None on all failures so the
dependency layer can return a clean 401 to the client.
"""
from __future__ import annotations

import logging
from typing import Any

from jose import JWTError, jwt  # type: ignore[import]

from verigence.di.auth.jwks import get_jwks_cache
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.domain.enums import ActorType

logger = logging.getLogger(__name__)

# Claim names coming from the Clerk session template
_CLAIM_TENANT = "org_id"       # Clerk organization ID = Verigence Tenant
_CLAIM_ROLE = "org_role"       # Role within the org
_CLAIM_ACTOR_TYPE = "actor_type"  # USER | SYSTEM | SERVICE (optional, default USER)

_MOCK_SUBJECT = "mock-actor-id"
_MOCK_TENANT = "mock-tenant-id"
_MOCK_ROLE = "admin"


def verify_token(token: str) -> ActorPrincipal | None:
    """Verify *token* and return an ActorPrincipal, or None on failure."""
    try:
        return _verify(token)
    except Exception as exc:
        logger.debug("jwt_verification_error", extra={"error": str(exc)})
        return None


def _verify(token: str) -> ActorPrincipal | None:
    # ── Mock mode (local dev / CI) ────────────────────────────────────────
    from verigence.di.settings import get_settings
    settings = get_settings()

    if settings.docai_mock:
        # In mock mode accept any non-empty token and return a synthetic admin.
        # Real token validation is still available; we just don't require it.
        if not token:
            return None
        if token.startswith("mock."):
            # Allow test suites to pass specific synthetic principals:
            # "mock.{tenant_id}.{actor_id}.{role}"
            parts = token.split(".", maxsplit=4)
            tenant = parts[1] if len(parts) > 1 else _MOCK_TENANT
            actor = parts[2] if len(parts) > 2 else _MOCK_SUBJECT
            role = parts[3] if len(parts) > 3 else _MOCK_ROLE
            return ActorPrincipal(
                actor_id=actor,
                tenant_id=tenant,
                role=role,
                actor_type=ActorType.USER,
                raw_claims={},
            )
        # Fall through to real verification if a real-looking token is supplied

    # ── Real JWKS verification ────────────────────────────────────────────
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

    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            options={"verify_aud": False},  # Clerk tokens don't always carry aud
        )
    except JWTError as exc:
        logger.debug("jwt_decode_failed", extra={"error": str(exc)})
        return None

    actor_id: str = claims.get("sub", "")
    tenant_id: str = claims.get(_CLAIM_TENANT, "")
    role: str = claims.get(_CLAIM_ROLE, "readonly")
    raw_actor_type: str = claims.get(_CLAIM_ACTOR_TYPE, "USER")

    if not actor_id or not tenant_id:
        logger.warning(
            "jwt_missing_required_claims",
            extra={"has_sub": bool(actor_id), "has_org_id": bool(tenant_id)},
        )
        return None

    try:
        actor_type = ActorType(raw_actor_type)
    except ValueError:
        actor_type = ActorType.USER

    return ActorPrincipal(
        actor_id=actor_id,
        tenant_id=tenant_id,
        role=role,
        actor_type=actor_type,
        raw_claims=claims,
    )
