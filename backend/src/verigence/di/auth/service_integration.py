"""Security-issued ServiceIntegration authentication for DI machine endpoints.

UC02 machine integration is platform-global: the service JWT is audience-bound to
DI and does not require a Tenant claim. Tenant scope comes from the trusted route
and DI's own RLS/domain checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

from verigence.di.auth.jwks import JWKSUnavailableError, get_jwks_cache
from verigence.di.errors import ErrorCode, http_exception

logger = structlog.get_logger(__name__)

_ISSUER = "verigence-security"
_AUDIENCE = "di"

service_bearer = HTTPBearer(auto_error=False, scheme_name="SecurityServiceIntegration")


@dataclass(frozen=True)
class ServiceIntegrationPrincipal:
    service_id: str


def _reject(reason: str) -> None:
    logger.warning("service_integration_token_rejected", reason=reason)


def verify_security_service_token(token: str) -> ServiceIntegrationPrincipal | None:
    """Return the ServiceIntegration principal, or None for an invalid token.

    Raises ``JWKSUnavailableError`` when Security signing keys cannot be fetched.
    """
    if not token or token.startswith("mock."):
        _reject("mock_or_empty_token")
        return None
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            _reject("missing_kid")
            return None
        key = get_jwks_cache().get_key(kid)
        if key is None:
            _reject("unknown_signing_key")
            return None
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
    except (JWTError, ValueError, TypeError):
        _reject("invalid_token")
        return None

    if claims.get("actor_type") != "SERVICE_INTEGRATION":
        _reject("wrong_actor_type")
        return None
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        _reject("missing_sub")
        return None
    return ServiceIntegrationPrincipal(service_id=subject.strip())


async def require_service_integration(
    credentials: HTTPAuthorizationCredentials | None = Depends(service_bearer),
) -> ServiceIntegrationPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise http_exception(ErrorCode.UNAUTHORIZED, detail="ServiceIntegration token is required.")
    try:
        principal = verify_security_service_token(credentials.credentials.strip())
    except JWKSUnavailableError as exc:
        raise http_exception(
            ErrorCode.SECURITY_INTEGRATION_FAILED,
            detail="Token signing keys are temporarily unavailable. Retry shortly.",
        ) from exc
    if principal is None:
        raise http_exception(ErrorCode.UNAUTHORIZED, detail="ServiceIntegration token is invalid.")
    return principal
