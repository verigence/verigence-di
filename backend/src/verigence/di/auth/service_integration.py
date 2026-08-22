"""Security-issued ServiceIntegration authentication for DI machine endpoints.

UC02 machine integration is platform-global: the service JWT is audience-bound to
DI and does not require a Tenant claim. Tenant scope comes from the trusted route
and DI's own RLS/domain checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from verigence.di.auth.jwks import get_jwks_cache
from verigence.di.errors import ErrorCode, http_exception

_ISSUER = "verigence-security"
_AUDIENCE = "di"

service_bearer = HTTPBearer(auto_error=False, scheme_name="SecurityServiceIntegration")


@dataclass(frozen=True)
class ServiceIntegrationPrincipal:
    service_id: str


def verify_security_service_token(token: str) -> ServiceIntegrationPrincipal | None:
    if not token or token.startswith("mock."):
        return None
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            return None
        key = get_jwks_cache().get_key(kid)
        if key is None:
            return None
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=_AUDIENCE,
            issuer=_ISSUER,
        )
    except (JWTError, ValueError, TypeError):
        return None

    if claims.get("actor_type") != "SERVICE_INTEGRATION":
        return None
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        return None
    return ServiceIntegrationPrincipal(service_id=subject.strip())


async def require_service_integration(
    credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
) -> ServiceIntegrationPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise http_exception(ErrorCode.UNAUTHORIZED, detail="ServiceIntegration token is required.")
    principal = verify_security_service_token(credentials.credentials.strip())
    if principal is None:
        raise http_exception(ErrorCode.UNAUTHORIZED, detail="ServiceIntegration token is invalid.")
    return principal
