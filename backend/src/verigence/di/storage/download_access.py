"""Short-lived direct download access for private object storage.

Large document bytes should not be proxied through the DI application service for
interactive review. DI still performs authorization and document/context checks,
then issues a time-limited S3-compatible presigned GET URL so the browser can read
the private R2 object directly.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Protocol, cast

import boto3

from verigence.di.settings import get_settings

DEFAULT_DOWNLOAD_URL_TTL_SECONDS = 600


class _PresignClient(Protocol):
    def generate_presigned_url(
        self,
        client_method: str,
        *,
        Params: dict[str, str],
        ExpiresIn: int,
    ) -> str: ...


@lru_cache(maxsize=1)
def _presign_client() -> _PresignClient:
    settings = get_settings()
    return cast(
        _PresignClient,
        boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint,
            aws_access_key_id=settings.storage_access_key_id,
            aws_secret_access_key=settings.storage_secret_access_key,
            region_name=settings.storage_region,
        ),
    )


def create_presigned_download_url(
    logical_key: str,
    *,
    expires_seconds: int = DEFAULT_DOWNLOAD_URL_TTL_SECONDS,
) -> str:
    """Create a private GET capability without downloading the object through DI."""
    if not logical_key.strip():
        raise ValueError("logical_key is required")
    if expires_seconds < 1 or expires_seconds > 3600:
        raise ValueError("expires_seconds must be between 1 and 3600")

    settings = get_settings()
    url = _presign_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.storage_bucket, "Key": logical_key},
        ExpiresIn=expires_seconds,
    )
    if not url:
        raise RuntimeError("Object storage did not return a presigned download URL")
    return url
