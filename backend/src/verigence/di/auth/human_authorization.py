"""Live Security authorization for direct human DI business requests.

The active Security human token proves global USER identity only. Tenant and
permission decisions remain live Security state, so these direct browser/mobile
routes verify the human token locally and ask Security /authorization/check using
DI's ServiceIntegration identity.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from verigence.di.auth.jwks import get_jwks_cache
from verigence.di.errors import ErrorCode, http_exception

_ISSUER = "verigence-security"
_AUDIENCE = "verigence-platform"
_ALLOW_TTL_SECONDS = 60.0
_SERVICE_TOKEN_FALLBACK_TTL_SECONDS = 60.0
_SERVICE_TOKEN_EXPIRY_SAFETY_SECONDS = 300.0

_human_bearer = HTTPBearer(auto_error=False, scheme_name="SecurityHumanIdentity")


@dataclass(frozen=True)
class HumanIdentity:
    user_id: str


@dataclass(frozen=True)
class HumanTenantAuthorization:
    user_id: str
    tenant_id: str
    permission_key: str
    role_key: str | None


def verify_global_human_token(token: str) -> HumanIdentity | None:
    """Verify the authority-free Security USER token used by Web/Android."""
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

    if claims.get("actor_type") != "USER":
        return None
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        return None

    forbidden = {"tenant_id", "permissions", "roles", "location_id", "act"}
    if forbidden.intersection(claims):
        return None
    return HumanIdentity(user_id=subject.strip())


def _service_token_reuse_seconds(token: str) -> float:
    parts = token.split(".")
    if len(parts) != 3:
        return _SERVICE_TOKEN_FALLBACK_TTL_SECONDS
    try:
        segment = parts[1]
        segment += "=" * (-len(segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment).decode("utf-8"))
    except (ValueError, TypeError):
        return _SERVICE_TOKEN_FALLBACK_TTL_SECONDS
    exp = payload.get("exp") if isinstance(payload, dict) else None
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return _SERVICE_TOKEN_FALLBACK_TTL_SECONDS
    return max(0.0, float(exp) - time.time() - _SERVICE_TOKEN_EXPIRY_SAFETY_SECONDS)


class SecurityLiveAuthorizationClient:
    def __init__(self) -> None:
        self._base_url = os.environ.get("DI_SECURITY_BASE_URL", "").strip().rstrip("/")
        self._client_id = os.environ.get("DI_SECURITY_CLIENT_ID", "").strip()
        self._client_secret = os.environ.get("DI_SECURITY_CLIENT_SECRET", "")
        if not self._base_url or not self._client_id or not self._client_secret:
            raise RuntimeError("DI Security live authorization is not configured")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=5.0)
        self._service_token: str | None = None
        self._service_token_reuse_until = 0.0
        self._service_token_lock = asyncio.Lock()
        self._allow_cache: dict[tuple[str, str, str], tuple[float, HumanTenantAuthorization]] = {}
        self._allow_lock = asyncio.Lock()
        self._decision_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        self._decision_locks_guard = asyncio.Lock()

    async def _security_token(self) -> str:
        now = time.monotonic()
        if self._service_token and now < self._service_token_reuse_until:
            return self._service_token
        async with self._service_token_lock:
            now = time.monotonic()
            if self._service_token and now < self._service_token_reuse_until:
                return self._service_token
            response = await self._client.post(
                "/security/v1/service/token",
                data={"audience": "security"},
                auth=(self._client_id, self._client_secret),
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Security service-token request failed with HTTP {response.status_code}"
                )
            payload = response.json()
            token = payload.get("accessToken") if isinstance(payload, dict) else None
            if not isinstance(token, str) or not token:
                raise RuntimeError("Security service-token response is invalid")
            self._service_token = token
            self._service_token_reuse_until = (
                time.monotonic() + _service_token_reuse_seconds(token)
            )
            return token

    async def _decision_lock(self, key: tuple[str, str, str]) -> asyncio.Lock:
        async with self._decision_locks_guard:
            lock = self._decision_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._decision_locks[key] = lock
            return lock

    async def authorize(
        self,
        *,
        user_id: str,
        tenant_id: str,
        permission_key: str,
    ) -> HumanTenantAuthorization:
        key = (user_id, tenant_id, permission_key)
        now = time.monotonic()
        async with self._allow_lock:
            cached = self._allow_cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
            if cached:
                self._allow_cache.pop(key, None)

        lock = await self._decision_lock(key)
        async with lock:
            now = time.monotonic()
            async with self._allow_lock:
                cached = self._allow_cache.get(key)
                if cached and cached[0] > now:
                    return cached[1]

            service_token = await self._security_token()
            response = await self._client.post(
                "/security/v1/authorization/check",
                headers={"Authorization": f"Bearer {service_token}"},
                json={
                    "userId": user_id,
                    "tenantId": tenant_id,
                    "permissionKey": permission_key,
                },
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Security authorization request failed with HTTP {response.status_code}"
                )
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Security authorization response is invalid")
            if (
                payload.get("userId") != user_id
                or payload.get("tenantId") != tenant_id
                or payload.get("permissionKey") != permission_key
            ):
                raise RuntimeError("Security authorization response does not match request")
            if payload.get("allowed") is not True:
                raise PermissionError(str(payload.get("reasonCode") or "DENIED"))
            role_key = payload.get("roleKey")
            decision = HumanTenantAuthorization(
                user_id=user_id,
                tenant_id=tenant_id,
                permission_key=permission_key,
                role_key=role_key if isinstance(role_key, str) else None,
            )
            async with self._allow_lock:
                self._allow_cache[key] = (
                    time.monotonic() + _ALLOW_TTL_SECONDS,
                    decision,
                )
            return decision


@lru_cache
def get_security_live_authorization_client() -> SecurityLiveAuthorizationClient:
    return SecurityLiveAuthorizationClient()


async def require_global_human_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(_human_bearer),
) -> HumanIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise http_exception(ErrorCode.UNAUTHORIZED, detail="Human Security token is required.")
    identity = verify_global_human_token(credentials.credentials.strip())
    if identity is None:
        raise http_exception(ErrorCode.UNAUTHORIZED, detail="Human Security token is invalid.")
    return identity


def require_live_tenant_permission(permission_key: str):  # type: ignore[no-untyped-def]
    async def _check(
        request: Request,
        human: HumanIdentity = Depends(require_global_human_identity),
    ) -> HumanTenantAuthorization:
        tenant_id = request.path_params.get("tenantId") or request.path_params.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise http_exception(ErrorCode.FORBIDDEN, detail="Tenant route context is required.")
        try:
            return await get_security_live_authorization_client().authorize(
                user_id=human.user_id,
                tenant_id=tenant_id,
                permission_key=permission_key,
            )
        except PermissionError:
            raise http_exception(
                ErrorCode.FORBIDDEN,
                detail=f"Security denied {permission_key} for the selected Project.",
            ) from None
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "DEPENDENCY_UNAVAILABLE",
                    "title": "Security authorization is temporarily unavailable.",
                    "status": 503,
                    "retryable": True,
                    "category": "DEPENDENCY",
                },
            ) from exc

    return _check
