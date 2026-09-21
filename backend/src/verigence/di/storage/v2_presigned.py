"""Direct-to-R2 upload presigning for Document Capture V2.

Kept outside StorageAdapter so the existing adapter contract is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aioboto3

from verigence.di.settings import get_settings


@dataclass(frozen=True)
class V2PresignedPut:
    url: str
    required_headers: dict[str, str]
    expires_seconds: int


def _client_kwargs() -> dict[str, str]:
    settings = get_settings()
    return {
        "endpoint_url": settings.storage_endpoint,
        "aws_access_key_id": settings.storage_access_key_id,
        "aws_secret_access_key": settings.storage_secret_access_key,
        "region_name": settings.storage_region,
    }


def open_v2_s3_client() -> Any:
    """One S3 client for a whole batch of presign calls.

    Presigning a PUT URL is pure local signing (no network round trip), but
    aioboto3's own session/client setup and teardown is not free -- calling
    ``presign_v2_put`` once per file with no shared client, sequentially in a
    multi-file upload request, made batch size the dominant cost of that
    request instead of the number of files being negligible. Callers that
    presign more than one file in the same request should open one client
    with this and pass it to every ``presign_v2_put`` call.
    """
    return aioboto3.Session().client("s3", **_client_kwargs())


async def presign_v2_put(
    *,
    logical_key: str,
    content_type: str | None,
    expires_seconds: int = 300,
    client: Any | None = None,
) -> V2PresignedPut:
    params: dict[str, str] = {
        "Bucket": get_settings().storage_bucket,
        "Key": logical_key,
    }
    headers: dict[str, str] = {}
    if content_type:
        params["ContentType"] = content_type
        headers["Content-Type"] = content_type

    if client is not None:
        url = await client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )
        return V2PresignedPut(url=str(url), required_headers=headers, expires_seconds=expires_seconds)

    session = aioboto3.Session()
    async with session.client("s3", **_client_kwargs()) as s3:
        url = await s3.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )
    return V2PresignedPut(
        url=str(url),
        required_headers=headers,
        expires_seconds=expires_seconds,
    )
