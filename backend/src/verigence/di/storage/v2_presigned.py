"""Direct-to-R2 upload presigning for Document Capture V2.

Kept outside StorageAdapter so the existing adapter contract is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

import aioboto3

from verigence.di.settings import get_settings


@dataclass(frozen=True)
class V2PresignedPut:
    url: str
    required_headers: dict[str, str]
    expires_seconds: int


async def presign_v2_put(
    *,
    logical_key: str,
    content_type: str | None,
    expires_seconds: int = 300,
) -> V2PresignedPut:
    settings = get_settings()
    client_kwargs = {
        "endpoint_url": settings.storage_endpoint,
        "aws_access_key_id": settings.storage_access_key_id,
        "aws_secret_access_key": settings.storage_secret_access_key,
        "region_name": settings.storage_region,
    }
    params: dict[str, str] = {
        "Bucket": settings.storage_bucket,
        "Key": logical_key,
    }
    headers: dict[str, str] = {}
    if content_type:
        params["ContentType"] = content_type
        headers["Content-Type"] = content_type

    session = aioboto3.Session()
    async with session.client("s3", **client_kwargs) as client:
        url = await client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )
    return V2PresignedPut(
        url=str(url),
        required_headers=headers,
        expires_seconds=expires_seconds,
    )
