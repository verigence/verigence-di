"""DI -> Audit Core asynchronous Booking document linkage client."""
from __future__ import annotations

import base64
import json
import os
import time
from functools import lru_cache

import httpx

_SERVICE_TOKEN_FALLBACK_TTL_SECONDS = 60.0
_SERVICE_TOKEN_EXPIRY_SAFETY_SECONDS = 300.0


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


class AuditCoreLinkClient:
    def __init__(self) -> None:
        security_base = os.environ.get("DI_SECURITY_BASE_URL", "").strip().rstrip("/")
        client_id = os.environ.get("DI_SECURITY_CLIENT_ID", "").strip()
        client_secret = os.environ.get("DI_SECURITY_CLIENT_SECRET", "")
        audit_core_base = os.environ.get("DI_AUDIT_CORE_BASE_URL", "").strip().rstrip("/")
        if not security_base or not client_id or not client_secret or not audit_core_base:
            raise RuntimeError("DI Audit Core linkage integration is not configured")
        self._security = httpx.AsyncClient(
            base_url=security_base,
            auth=(client_id, client_secret),
            timeout=5.0,
        )
        self._audit = httpx.AsyncClient(base_url=audit_core_base, timeout=5.0)
        self._token: str | None = None
        self._reuse_until = 0.0

    async def _service_token(self) -> str:
        now = time.monotonic()
        if self._token and now < self._reuse_until:
            return self._token
        response = await self._security.post(
            "/security/v1/service/token",
            data={"audience": "audit"},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Security audit service-token request failed with HTTP {response.status_code}"
            )
        payload = response.json()
        token = payload.get("accessToken") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise RuntimeError("Security audit service-token response is invalid")
        self._token = token
        self._reuse_until = time.monotonic() + _service_token_reuse_seconds(token)
        return token

    async def link_booking_document(
        self,
        *,
        requirement_ref: str,
        document_id: str,
    ) -> None:
        token = await self._service_token()
        response = await self._audit.post(
            "/v1/internal/di/booking-document-links",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "requirementRef": requirement_ref,
                "documentId": document_id,
            },
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(
                f"Audit Core link callback failed with HTTP {response.status_code}"
            )


@lru_cache
def get_audit_core_link_client() -> AuditCoreLinkClient:
    return AuditCoreLinkClient()
