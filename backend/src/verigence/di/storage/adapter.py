"""storage/adapter.py — Provider-neutral StorageAdapter interface + R2/MinIO implementation.

The domain and application layers only import StorageAdapter (the abstract base).
The concrete implementation (R2StorageAdapter) is wired in via dependency injection
from settings. No cloud provider SDK leaks into domain or API code.

Logical key shapes (from DI_LLD_v2.1.md §3):
  ORIGINAL: tenants/{tenant_storage_key}/documents/{document_id}/original/{artifact_id}
  DERIVED:  tenants/{tenant_storage_key}/documents/{document_id}/derived/{artifact_id}
"""
from __future__ import annotations

import abc
import io
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import IO, Any
from uuid import UUID


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
    async def get_stream(self, logical_key: str) -> AsyncIterator[bytes]:
        """Stream bytes from object storage."""

    @abc.abstractmethod
    async def exists(self, logical_key: str) -> bool:
        """Return True if the object exists."""

    @abc.abstractmethod
    async def get_metadata(self, logical_key: str) -> StorageMetadata:
        """Return metadata without downloading the object."""

    @abc.abstractmethod
    async def delete(self, logical_key: str) -> None:
        """Delete object — only callable under retention authorization."""

    # ── Key construction helpers ──────────────────────────────────────────────
    @staticmethod
    def original_key(
        tenant_storage_key: UUID,
        document_id: UUID,
        artifact_id: UUID,
    ) -> str:
        return (
            f"tenants/{tenant_storage_key}/documents/{document_id}"
            f"/original/{artifact_id}"
        )

    @staticmethod
    def derived_key(
        tenant_storage_key: UUID,
        document_id: UUID,
        artifact_id: UUID,
    ) -> str:
        return (
            f"tenants/{tenant_storage_key}/documents/{document_id}"
            f"/derived/{artifact_id}"
        )


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

    def _client_kwargs(self) -> dict:  # type: ignore[type-arg]
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

        import aioboto3  # type: ignore[import]

        # Normalise: accept both sync IO (BytesIO) and async iterators
        if hasattr(stream, "read"):
            # Sync IO object — wrap in BytesIO if not already, then read
            buffer: io.BytesIO = stream if isinstance(stream, io.BytesIO) else io.BytesIO(stream.read())  # type: ignore[assignment]
        else:
            buffer = io.BytesIO()
            async for chunk in stream:  # type: ignore[union-attr]
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

    async def exists(self, logical_key: str) -> bool:
        import aioboto3
        from botocore.exceptions import ClientError  # type: ignore[import]

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
