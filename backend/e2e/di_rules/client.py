"""HTTP-only client used by the live DI + Rules E2E harness.

The harness deliberately does not connect to the DI database or object storage.
It proves the same public service boundaries used by product callers.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import httpx


class DiApiError(RuntimeError):
    """Raised when the deployed DI API returns an unexpected HTTP/API result."""


class DiClient:
    def __init__(self, *, base_url: str, token: str, request_timeout: float = 60.0) -> None:
        clean_base = base_url.strip().rstrip("/")
        if not clean_base:
            raise ValueError("base_url is required")
        if not token.strip():
            raise ValueError("token is required")
        self._client = httpx.Client(
            base_url=clean_base,
            timeout=request_timeout,
            headers={"Authorization": f"Bearer {token.strip()}"},
        )

    def __enter__(self) -> DiClient:
        self._client.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._client.__exit__(exc_type, exc, tb)

    @property
    def base_url(self) -> str:
        return str(self._client.base_url).rstrip("/")

    @staticmethod
    def _json(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise DiApiError(
                f"{operation} returned non-JSON HTTP {response.status_code}: {response.text[:300]}"
            ) from exc
        if not isinstance(payload, dict):
            raise DiApiError(f"{operation} returned an unexpected JSON payload")
        return payload

    @classmethod
    def _success_data(cls, response: httpx.Response, operation: str) -> Any:
        if response.is_error:
            payload = cls._json(response, operation)
            raise DiApiError(
                f"{operation} failed HTTP {response.status_code}: "
                f"{payload.get('detail') or payload.get('errorMessage') or payload}"
            )
        payload = cls._json(response, operation)
        error_code = payload.get("errorCode")
        if error_code not in (None, "000"):
            raise DiApiError(
                f"{operation} failed errorCode={error_code}: {payload.get('errorMessage')}"
            )
        return payload.get("data", payload)

    def health(self) -> dict[str, Any]:
        response = self._client.get("/health/ready", headers={})
        if response.is_error:
            raise DiApiError(f"health failed HTTP {response.status_code}: {response.text[:300]}")
        return self._json(response, "health")

    def create_subject(self, tenant_id: str, *, display_name: str, subject_type: str) -> dict[str, Any]:
        response = self._client.post(
            f"/v1/tenants/{tenant_id}/subjects",
            json={"displayName": display_name, "subjectType": subject_type},
        )
        data = self._success_data(response, "create subject")
        if not isinstance(data, dict) or not data.get("subjectId"):
            raise DiApiError("create subject succeeded without subjectId")
        return data

    def upload_document(
        self,
        tenant_id: str,
        subject_id: str,
        *,
        document_type_key: str,
        path: Path,
    ) -> dict[str, Any]:
        if not path.is_file():
            raise DiApiError(f"Document file does not exist: {path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as stream:
            response = self._client.post(
                f"/v1/tenants/{tenant_id}/subjects/{subject_id}/documents",
                data={"documentTypeKey": document_type_key},
                files={"file": (path.name, stream, mime_type)},
            )
        if response.is_error:
            payload = self._json(response, f"upload {path.name}")
            raise DiApiError(
                f"upload {path.name} failed HTTP {response.status_code}: "
                f"{payload.get('detail') or payload.get('errorMessage') or payload}"
            )
        payload = self._json(response, f"upload {path.name}")
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("documentId"):
            raise DiApiError(f"upload {path.name} returned no documentId")
        # Upload rejection is represented as HTTP success with a non-000 envelope.
        return {
            **data,
            "errorCode": payload.get("errorCode"),
            "errorMessage": payload.get("errorMessage"),
        }

    def get_document(self, tenant_id: str, subject_id: str, document_id: str) -> dict[str, Any]:
        response = self._client.get(
            f"/v1/tenants/{tenant_id}/subjects/{subject_id}/documents/{document_id}"
        )
        data = self._success_data(response, "get document")
        if not isinstance(data, dict):
            raise DiApiError("get document returned an unexpected data payload")
        return data

    def get_fields(self, tenant_id: str, subject_id: str, document_id: str) -> list[dict[str, Any]]:
        response = self._client.get(
            f"/v1/tenants/{tenant_id}/subjects/{subject_id}/documents/{document_id}/fields"
        )
        data = self._success_data(response, "get extracted fields")
        fields = data.get("fields", []) if isinstance(data, dict) else data
        if not isinstance(fields, list):
            raise DiApiError("get extracted fields returned no fields array")
        return [field for field in fields if isinstance(field, dict)]

    def analyse(self, tenant_id: str, document_ids: list[str]) -> dict[str, Any]:
        response = self._client.post(
            f"/v1/tenants/{tenant_id}/analyse",
            json={"documentIds": document_ids},
        )
        data = self._success_data(response, "analyse documents")
        if not isinstance(data, dict):
            raise DiApiError("analyse documents returned an unexpected data payload")
        return data
