"""UC02 human authorization against Security state.

This module is intentionally separate from the Baseline-2.2 Tenant JWT verifier.
UC02 control-plane mutations receive the original Security-issued human JWT,
validate it as identity/session evidence, and ask Security for the current
administrative classification. No embedded role/permission/Tenant claim is
accepted as live authority for those operations.

Approved read-only Project Master catalogue/template/version requests use the
same locally verified human JWT but do not perform a live SuperAdmin round-trip.
Mutations remain SuperAdmin-only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import structlog
from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from verigence.di.auth.jwks import get_jwks_cache
from verigence.di.errors import ErrorCode, http_exception
from verigence.di.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_ISSUER = "verigence-security"
_AUDIENCE = "verigence-platform"
_REQUIRED_HUMAN_CLAIMS = frozenset({"iss", "sub", "aud", "iat", "exp", "jti", "actor_type"})
_FORBIDDEN_AUTHORITY_CLAIMS = frozenset(
    {"tenant_id", "permissions", "roles", "device_id", "location_id", "act"}
)
_LIGHTWEIGHT_MASTER_READS = (
    re.compile(r"^/v1/tenants/[^/]+/project-masters/?$"),
    re.compile(r"^/v1/tenants/[^/]+/project-masters/[^/]+/template/?$"),
    re.compile(r"^/v1/tenants/[^/]+/project-masters/[^/]+/versions/?$"),
)


@dataclass(frozen=True)
class HumanPrincipal:
    user_id: str


@dataclass(frozen=True)
class SecurityAdminScope:
    role_key: str
    scope_type: str
    scope_id: str | None


@dataclass(frozen=True)
class SecurityAdminContext:
    user_id: str
    is_super_admin: bool
    admin_scopes: tuple[SecurityAdminScope, ...]


@dataclass(frozen=True)
class HumanAdminRequest:
    user_id: str
    bearer_token: str
    admin_context: SecurityAdminContext


class SecurityAdminError(RuntimeError):
    """Security could not provide trustworthy live human administrator context."""


security_human_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="SecurityHumanAccessToken",
    bearerFormat="JWT",
    description="Security-issued human access JWT for UC02 administration.",
)


def verify_security_human_token(token: str) -> HumanPrincipal | None:
    """Validate the current minimal Security human JWT contract.

    The human token establishes identity/session only. UC02 deliberately rejects
    embedded Tenant, role, permission, device/location, or delegation claims as
    control-plane authority.
    """

    if not token or token.startswith("mock."):
        return None
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not isinstance(kid, str) or not kid:
            return None
        key = get_jwks_cache().get_key(kid)
        if key is None:
            logger.warning("uc02_human_jwks_key_not_found", kid=kid)
            return None
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=_AUDIENCE,
            issuer=_ISSUER,
        )
    except (JWTError, ValueError, TypeError):
        logger.warning("uc02_human_jwt_verification_failed")
        return None

    if not _REQUIRED_HUMAN_CLAIMS.issubset(claims):
        return None
    if claims.get("actor_type") != "USER":
        return None
    if _FORBIDDEN_AUTHORITY_CLAIMS.intersection(claims):
        return None

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        return None
    try:
        user_id = str(UUID(subject))
    except ValueError:
        return None
    return HumanPrincipal(user_id=user_id)


def security_base_url_from_jwks_url(jwks_url: str) -> str:
    """Derive the Security origin from its configured JWKS URL."""

    parsed = urlsplit(jwks_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SecurityAdminError("Security JWKS URL is not a usable HTTP origin")
    return f"{parsed.scheme}://{parsed.netloc}"


class SecurityAdminClient:
    """Call Security admin-context with the exact initiating human bearer token."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Security base URL is required")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def get_admin_context(self, *, human_bearer_token: str) -> SecurityAdminContext:
        if not human_bearer_token:
            raise ValueError("human_bearer_token is required")
        try:
            response = self._client.get(
                "/security/v1/platform/admin-context",
                headers={"Authorization": f"Bearer {human_bearer_token}"},
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "security_admin_call_failed",
                reason="endpoint_unavailable",
                path="/security/v1/platform/admin-context",
            )
            raise SecurityAdminError("Security administrative endpoint is unavailable") from exc

        if response.status_code < 200 or response.status_code >= 300:
            logger.warning(
                "security_admin_call_failed",
                http_status=response.status_code,
                path="/security/v1/platform/admin-context",
            )
            raise SecurityAdminError("Security administrative request was denied")
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise SecurityAdminError("Security administrative response is not valid JSON") from exc
        return _parse_admin_context(payload)


def _parse_admin_context(payload: Any) -> SecurityAdminContext:
    if not isinstance(payload, dict):
        raise SecurityAdminError("Security admin-context response has invalid shape")
    user_id = payload.get("userId")
    is_super_admin = payload.get("isSuperAdmin")
    raw_scopes = payload.get("adminScopes")
    if (
        not isinstance(user_id, str)
        or not user_id
        or not isinstance(is_super_admin, bool)
        or not isinstance(raw_scopes, list)
    ):
        raise SecurityAdminError("Security admin-context response has invalid shape")

    try:
        canonical_user_id = str(UUID(user_id))
    except ValueError as exc:
        raise SecurityAdminError("Security admin-context USER id is invalid") from exc

    scopes: list[SecurityAdminScope] = []
    for raw_scope in raw_scopes:
        if not isinstance(raw_scope, dict):
            raise SecurityAdminError("Security admin-context scope has invalid shape")
        role_key = raw_scope.get("roleKey")
        scope_type = raw_scope.get("scopeType")
        scope_id = raw_scope.get("scopeId")
        if (
            not isinstance(role_key, str)
            or not role_key
            or not isinstance(scope_type, str)
            or not scope_type
            or (scope_id is not None and not isinstance(scope_id, str))
        ):
            raise SecurityAdminError("Security admin-context scope has invalid shape")
        scopes.append(
            SecurityAdminScope(
                role_key=role_key,
                scope_type=scope_type,
                scope_id=scope_id,
            )
        )
    return SecurityAdminContext(
        user_id=canonical_user_id,
        is_super_admin=is_super_admin,
        admin_scopes=tuple(scopes),
    )


def _is_lightweight_master_read(request: Request) -> bool:
    if request.method.upper() != "GET":
        return False
    return any(pattern.fullmatch(request.url.path) for pattern in _LIGHTWEIGHT_MASTER_READS)


def require_uc02_super_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security_human_bearer),
    settings: Settings = Depends(get_settings),
) -> HumanAdminRequest:
    """Authorize UC02 Project Master requests.

    Read-only catalogue/template/version requests stop after local human JWT
    verification. All other routes retain live Security SuperAdmin attestation.
    """

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise http_exception(ErrorCode.UNAUTHORIZED, detail="Security human access token is required.")
    bearer_token = credentials.credentials.strip()
    principal = verify_security_human_token(bearer_token)
    if principal is None:
        raise http_exception(ErrorCode.UNAUTHORIZED, detail="Security human access token is invalid.")

    if _is_lightweight_master_read(request):
        return HumanAdminRequest(
            user_id=principal.user_id,
            bearer_token=bearer_token,
            admin_context=SecurityAdminContext(
                user_id=principal.user_id,
                is_super_admin=False,
                admin_scopes=(),
            ),
        )

    try:
        base_url = security_base_url_from_jwks_url(settings.security_jwks_url)
        with SecurityAdminClient(base_url=base_url) as security:
            admin_context = security.get_admin_context(human_bearer_token=bearer_token)
    except SecurityAdminError:
        logger.warning("uc02_superadmin_attestation_failed", reason="security_unavailable_or_denied")
        raise http_exception(
            ErrorCode.FORBIDDEN,
            detail="Current SuperAdmin authorization could not be confirmed.",
        ) from None

    if admin_context.user_id != principal.user_id:
        logger.warning("uc02_superadmin_attestation_failed", reason="user_mismatch")
        raise http_exception(ErrorCode.FORBIDDEN, detail="Security administrator identity mismatch.")
    if not admin_context.is_super_admin:
        raise http_exception(ErrorCode.FORBIDDEN, detail="SuperAdmin authority is required.")

    return HumanAdminRequest(
        user_id=principal.user_id,
        bearer_token=bearer_token,
        admin_context=admin_context,
    )
