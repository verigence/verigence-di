"""DI -> Audit Core asynchronous Booking document linkage client."""
from __future__ import annotations

import base64
import json
import os
import time
from functools import lru_cache

import httpx

from verigence.di.runtime_errors import correlation_id_or_new

_SERVICE_TOKEN_FALLBACK_TTL_SECONDS = 60.0
_SERVICE_TOKEN_EXPIRY_SAFETY_SECONDS = 300.0
_CORRELATION_HEADER = "X-Correlation-ID"


def _service_token_reuse_seconds(token: str) -> float:
    parts = token.split(".")
    if len(parts) != 3:
        return _SERVICE_TOKEN_FALLBACK_TTL_SECONDS
    try:
        segment = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment).decode("utf-8"))
    except (ValueError, TypeError):
        return _SERVICE_TOKEN_FALLBACK_TTL_SECONDS
    exp = payload.get("exp") if isinstance(payload, dict) else None
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return _SERVICE_TOKEN_FALLBACK_TTL_SECONDS
    return max(0.0, float(exp) - time.time() - _SERVICE_TOKEN_EXPIRY_SAFETY_SECONDS)


class AuditCoreLinkError(RuntimeError):
    """Safe integration failure consumed by the background worker.

    The exception text is the stable technical code only.  Downstream response
    bodies, credentials and document/request values are never attached.
    """

    def __init__(self, *, technical_code: str, status_code: int | None, retryable: bool) -> None:
        self.technical_code = technical_code
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(technical_code)


def _retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code in {408, 500, 502, 503, 504}


class AuditCoreLinkClient:
    def __init__(self) -> None:
        security_base = os.environ.get("DI_SECURITY_BASE_URL", "").strip().rstrip("/")
        client_id = os.environ.get("DI_SECURITY_CLIENT_ID", "").strip()
        client_secret = os.environ.get("DI_SECURITY_CLIENT_SECRET", "")
        audit_core_base = os.environ.get("DI_AUDIT_CORE_BASE_URL", "").strip().rstrip("/")
        if not security_base or not client_id or not client_secret or not audit_core_base:
            raise AuditCoreLinkError(
                technical_code="AUDIT_CORE_INTEGRATION_FAILED",
                status_code=None,
                retryable=False,
            )
        self._security = httpx.AsyncClient(
            base_url=security_base,
            auth=(client_id, client_secret),
            timeout=5.0,
        )
        self._audit = httpx.AsyncClient(base_url=audit_core_base, timeout=5.0)
        self._token: str | None = None
        self._reuse_until = 0.0

    async def _service_token(self, *, correlation_id: str) -> str:
        now = time.monotonic()
        if self._token and now < self._reuse_until:
            return self._token
        try:
            response = await self._security.post(
                "/security/v1/service/token",
                data={"audience": "audit"},
                headers={_CORRELATION_HEADER: correlation_id},
            )
        except httpx.HTTPError as exc:
            raise AuditCoreLinkError(
                technical_code="SECURITY_INTEGRATION_FAILED",
                status_code=None,
                retryable=True,
            ) from exc
        if response.status_code != 200:
            raise AuditCoreLinkError(
                technical_code="SECURITY_INTEGRATION_FAILED",
                status_code=response.status_code,
                retryable=_retryable_status(response.status_code),
            )
        payload = response.json()
        token = payload.get("accessToken") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise AuditCoreLinkError(
                technical_code="SECURITY_INTEGRATION_FAILED",
                status_code=response.status_code,
                retryable=False,
            )
        self._token = token
        self._reuse_until = time.monotonic() + _service_token_reuse_seconds(token)
        return token

    async def link_booking_document(
        self,
        *,
        requirement_ref: str,
        document_id: str,
        correlation_id: str | None = None,
    ) -> None:
        safe_correlation_id = correlation_id_or_new(correlation_id)
        token = await self._service_token(correlation_id=safe_correlation_id)
        try:
            response = await self._audit.post(
                "/v1/internal/di/booking-document-links",
                headers={
                    "Authorization": f"Bearer {token}",
                    _CORRELATION_HEADER: safe_correlation_id,
                },
                json={
                    "requirementRef": requirement_ref,
                    "documentId": document_id,
                },
            )
        except httpx.HTTPError as exc:
            raise AuditCoreLinkError(
                technical_code="AUDIT_CORE_INTEGRATION_FAILED",
                status_code=None,
                retryable=True,
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise AuditCoreLinkError(
                technical_code="AUDIT_CORE_INTEGRATION_FAILED",
                status_code=response.status_code,
                retryable=_retryable_status(response.status_code),
            )


@lru_cache
def get_audit_core_link_client() -> AuditCoreLinkClient:
    return AuditCoreLinkClient()
