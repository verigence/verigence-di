"""tests/jwt_helper.py — mint real RS256-signed JWTs for integration tests.

Reads the private key from the TEST_JWT_PRIVATE_KEY environment variable
(base64-encoded PKCS8 PEM). The matching public key is committed to the repo
as backend/tests/fixtures/test_jwks.json.

Usage:
    token = mint_jwt(tenant_id="t1", actor_id="a1", roles=["TENANT_ADMIN"])
    headers = {"Authorization": f"Bearer {token}"}
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any

from jose import jwt  # type: ignore[import]

_ISSUER   = "verigence-security"
_AUDIENCE = "verigence-platform"
_KID      = "verigence-di-test-key-1"
_ALG      = "RS256"


def _load_private_key() -> str:
    """Return the RSA private key PEM string from TEST_JWT_PRIVATE_KEY env var."""
    b64 = os.environ.get("TEST_JWT_PRIVATE_KEY", "")
    if not b64:
        raise RuntimeError(
            "TEST_JWT_PRIVATE_KEY env var is not set. "
            "Store the base64-encoded private PEM as this env var."
        )
    return base64.b64decode(b64).decode()


def mint_jwt(
    tenant_id: str,
    actor_id: str,
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    exp_seconds: int = 300,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Mint a signed RS256 JWT identical to what the Security module issues.

    Args:
        tenant_id:    Tenant UUID (used as path parameter in most endpoints)
        actor_id:     Actor UUID (becomes ``sub`` claim)
        roles:        Role name list, e.g. ``["TENANT_ADMIN"]``
        permissions:  Explicit permission list; derived from roles if omitted
        exp_seconds:  Token lifetime in seconds (default 300)
        extra_claims: Additional claims merged into the payload
    Returns:
        Signed JWT string
    """
    from verigence.di.auth.permissions import ROLE_PERMISSIONS  # avoid circular at module load

    if roles is None:
        roles = []
    if permissions is None:
        perms: set[str] = set()
        for role in roles:
            bundle = ROLE_PERMISSIONS.get(role.upper(), frozenset())
            perms.update(p.value for p in bundle)
        permissions = sorted(perms)

    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": actor_id,
        "iat": now,
        "exp": now + exp_seconds,
        "jti": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "actor_type": "USER",
        "roles": roles,
        "permissions": permissions,
    }
    if extra_claims:
        payload.update(extra_claims)

    headers = {"kid": _KID}
    private_key = _load_private_key()
    return jwt.encode(payload, private_key, algorithm=_ALG, headers=headers)


def mint_expired_jwt(tenant_id: str, actor_id: str, roles: list[str] | None = None) -> str:
    """Mint a JWT that is already expired (exp = now - 60s)."""
    return mint_jwt(tenant_id, actor_id, roles=roles, exp_seconds=-60)


def mint_jwt_wrong_audience(tenant_id: str, actor_id: str) -> str:
    """Mint a JWT with an incorrect audience claim."""
    return mint_jwt(
        tenant_id, actor_id, roles=["TENANT_ADMIN"],
        extra_claims={"aud": "wrong-service"},
    )


def mint_jwt_wrong_issuer(tenant_id: str, actor_id: str) -> str:
    """Mint a JWT with an incorrect issuer claim."""
    return mint_jwt(
        tenant_id, actor_id, roles=["TENANT_ADMIN"],
        extra_claims={"iss": "wrong-issuer"},
    )
