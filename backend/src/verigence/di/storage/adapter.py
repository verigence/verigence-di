"""storage/adapter.py — Provider-neutral StorageAdapter interface + R2/MinIO implementation.

The domain and application layers only import StorageAdapter (the abstract base).
The concrete implementation (S3StorageAdapter) is wired in via dependency injection
from settings. No cloud provider SDK leaks into domain or API code.

Logical key shape (DI_DECISIONS.md D5):
  {tenant_slug}/subjects/{subject_slug}-{subject_id_short}/
    documents/{form_folder}/{doc_id_short}_{sanitised_filename}

  form_folder = govt_id | printable | handwritten | additional

Example:
  acme-bank/subjects/john-smith-a3f2b1c0/documents/govt_id/d74194e2_passport.pdf
"""
from __future__ import annotations

import abc
import io
import re
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import IO, Any, cast
from uuid import UUID

# ── R2 path helpers (D5) ──────────────────────────────────────────────────────

_FORM_TYPE_FOLDER: dict[str, str] = {
    "GOVT_ID":     "govt_id",
    "PRINTABLE":   "printable",
    "HANDWRITTEN": "handwritten",
    "ADDITIONAL":  "additional",
}

# MIME type → file extension mapping.
# Includes images, PDF, and all common Office / document formats.
_MIME_EXT: dict[str, str] = {
    # Images
    "image/jpeg":                                                          "jpg",
    "image/png":                                                           "png",
    "image/tiff":                                                          "tif",
    "image/webp":                                                          "webp",
    "image/gif":                                                           "gif",
    "image/bmp":                                                           "bmp",
    # PDF
    "application/pdf":                                                     "pdf",
    # Microsoft Office (modern)
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":   "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":         "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    # Microsoft Office (legacy)
    "application/msword":                                                  "doc",
    "application/vnd.ms-excel":                                            "xls",
    "application/vnd.ms-powerpoint":                                       "ppt",
    # OpenDocument
    "application/vnd.oasis.opendocument.text":                             "odt",
    "application/vnd.oasis.opendocument.spreadsheet":                      "ods",
    "application/vnd.oasis.opendocument.presentation":                     "odp",
    # Text / CSV
    "text/plain":                                                          "txt",
    "text/csv":                                                            "csv",
    # Archives (for multi-page scans)
    "application/zip":                                                     "zip",
}


def _slugify(value: str, max_len: int) -> str:
    """Convert an arbitrary string to a lowercase URL-safe slug."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:max_len] or "unknown"


def _sanitise_filename(
    filename: str | None,
    fallback_stem: str,
    mime_type: str | None,
) -> str:
    """Return a safe, extension-bearing filename for use in R2 keys.

    Rules (D5):
    - Strip directory separators
    - Spaces → underscores
    - Only alphanumeric, dot, underscore, hyphen allowed
    - Max 80 chars total
    - If filename is absent or empty, fall back to '{fallback_stem}.{ext_from_mime}'
    """
    if filename:
        name = filename.replace("\\", "/").split("/")[-1]  # strip directory
        name = name.replace(" ", "_")
        name = re.sub(r"[^A-Za-z0-9._\-]", "", name)
        name = name[:80]
        if name:
            return name

    ext = _MIME_EXT.get(mime_type or "", "bin")
    return f"{fallback_stem}.{ext}"


def build_original_key(
    *,
    tenant_id: str,
    subject_id: UUID,
    subject_display_name: str | None,
    document_id: UUID,
    physical_form_type: str,
    original_filename: str | None,
    detected_mime_type: str | None = None,
) -> str:
    """Build the R2 object key for an ORIGINAL document artifact.

    Format (DI_DECISIONS.md D5):
      {tenant_slug}/subjects/{subject_slug}-{subject_id_short}/
        documents/{form_folder}/{doc_id_short}_{sanitised_filename}
    """
    tenant_slug      = _slugify(tenant_id, 40)
    subject_slug     = _slugify(subject_display_name or "unknown", 30)
    subject_id_short = str(subject_id).replace("-", "")[:8]
    doc_id_short     = str(document_id).replace("-", "")[:8]
    form_folder      = _FORM_TYPE_FOLDER.get(physical_form_type, "additional")

    safe_filename = _sanitise_filename(
        original_filename,
        fallback_stem=f"{doc_id_short}_{form_folder}",
        mime_type=detected_mime_type,
    )

    # Always prefix with doc_id_short so filename is unique and DB-correlatable
    if not safe_filename.startswith(doc_id_short):
        safe_filename = f"{doc_id_short}_{safe_filename}"

    return (
        f"{tenant_slug}"
        f"/subjects/{subject_slug}-{subject_id_short}"
        f"/documents/{form_folder}"
        f"/{safe_filename}"
    )


@dataclass(frozen=True)
class StorageMetadata:
    storage_id: UUID
    logical_key: str
    content_type: str | None
    size_bytes: int | None


class StorageAdapter(abc.ABC):
    """Abstract provider-neutral storage interface."""

    @abc.abstractmethod
    async def put_stream(
        self,
        logical_key: str,
        stream: IO[bytes] | AsyncIterator[bytes],
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StorageMetadata:
        """Write a stream to object storage and return metadata."""

    @abc.abstractmethod
    def get_stream(self, logical_key: str) -> AsyncIterator[bytes]:
        """Stream bytes from object storage."""

    @abc.abstractmethod
    async def get_presigned_url(self, logical_key: str, expires_seconds: int) -> str:
        """Return a temporary direct GET URL without exposing storage credentials."""

    @abc.abstractmethod
    async def exists(self, logical_key: str) -> bool:
        """Return True if the object exists."""

    @abc.abstractmethod
    async def get_metadata(self, logical_key: str) -> StorageMetadata:
        """Return metadata without downloading the object."""

    @abc.abstractmethod
    async def delete(self, logical_key: str) -> None:
        """Delete object — only callable under retention authorization."""


# ── R2 / MinIO S3-compatible implementation ───────────────────────────────────
class S3StorageAdapter(StorageAdapter):
    """S3-compatible implementation for Cloudflare R2 and local MinIO.

    Uses aioboto3 for async streaming. The same code runs against:
    - Local Docker MinIO  (endpoint_url = http://localhost:9000)
    - Cloudflare R2       (endpoint_url = https://<account>.r2.cloudflarestorage.com)
    """

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        region: str = "auto",
    ) -> None:
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._bucket = bucket
        self._region = region

    def _client_kwargs(self) -> dict[str, str]:
        return {
            "endpoint_url": self._endpoint_url,
            "aws_access_key_id": self._access_key_id,
            "aws_secret_access_key": self._secret_access_key,
            "region_name": self._region,
        }

    async def put_stream(
        self,
        logical_key: str,
        stream: IO[bytes] | AsyncIterator[bytes],
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StorageMetadata:
        import uuid

        import aioboto3

        # Normalise: accept both sync IO and async iterators without leaking the
        # provider's upload-body type into the application interface.
        if hasattr(stream, "read"):
            sync_stream = cast("IO[bytes]", stream)
            buffer = sync_stream if isinstance(sync_stream, io.BytesIO) else io.BytesIO(sync_stream.read())
        else:
            async_stream = cast("AsyncIterator[bytes]", stream)
            buffer = io.BytesIO()
            async for chunk in async_stream:
                buffer.write(chunk)
        size = buffer.tell()
        buffer.seek(0)

        extra: dict[str, Any] = {}
        if content_type:
            extra["ContentType"] = content_type
        if metadata:
            extra["Metadata"] = metadata

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            await s3.put_object(
                Bucket=self._bucket,
                Key=logical_key,
                Body=buffer,
                **extra,
            )

        storage_id = uuid.uuid4()
        return StorageMetadata(
            storage_id=storage_id,
            logical_key=logical_key,
            content_type=content_type,
            size_bytes=size,
        )

    async def get_stream(self, logical_key: str) -> AsyncIterator[bytes]:
        import aioboto3

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            response = await s3.get_object(Bucket=self._bucket, Key=logical_key)
            async for chunk in response["Body"].iter_chunks(chunk_size=65536):
                yield chunk

    async def get_presigned_url(self, logical_key: str, expires_seconds: int) -> str:
        import aioboto3

        # Presigning is local cryptographic work. The URL lets the browser/mobile
        # fetch the large object directly from R2/MinIO instead of proxying bytes
        # through the DI Railway service.
        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": logical_key},
                ExpiresIn=expires_seconds,
            )
        return str(url)

    async def exists(self, logical_key: str) -> bool:
        import aioboto3
        from botocore.exceptions import ClientError

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=logical_key)
                return True
            except ClientError as e:
                if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                    return False
                raise

    async def get_metadata(self, logical_key: str) -> StorageMetadata:
        import uuid

        import aioboto3

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            head = await s3.head_object(Bucket=self._bucket, Key=logical_key)

        return StorageMetadata(
            storage_id=uuid.uuid4(),
            logical_key=logical_key,
            content_type=head.get("ContentType"),
            size_bytes=head.get("ContentLength"),
        )

    async def delete(self, logical_key: str) -> None:
        import aioboto3

        session = aioboto3.Session()
        async with session.client("s3", **self._client_kwargs()) as s3:
            await s3.delete_object(Bucket=self._bucket, Key=logical_key)


def get_storage_adapter() -> StorageAdapter:
    """FastAPI dependency — returns configured adapter from settings.

    Routes the adapter selection based on DI_STORAGE_PROVIDER env var:
    - minio: local Docker MinIO (development, local testing)
    - r2: Cloudflare R2 (production)

    Both are S3-compatible and use the same S3StorageAdapter implementation.
    """
    from verigence.di.settings import get_settings

    s = get_settings()

    # Both MinIO and R2 are S3-compatible
    # Provider enum exists for future extensibility or logging/metrics
    return S3StorageAdapter(
        endpoint_url=s.storage_endpoint,
        access_key_id=s.storage_access_key_id,
        secret_access_key=s.storage_secret_access_key,
        bucket=s.storage_bucket,
        region=s.storage_region,
    )
