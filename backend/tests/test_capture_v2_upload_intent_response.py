"""V2UploadIntentResponse always carries a failures list (empty by default).

create_capture_upload_intents isolates each file in the batch on its own
SAVEPOINT (see capture_documents.py) instead of one all-or-nothing
transaction, so a problem with one file's DB work no longer fails every
other file in the same batch -- it becomes an entry here instead. This
endpoint has no DB-backed integration coverage in this repo's CI (no
Postgres service is provisioned for it), so this locks in the response
contract at the schema level: existing callers that only read ``uploads``
keep working unchanged, and a caller reading ``failures`` always gets a
list, never a missing field.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from verigence.di.api.v2.capture_documents import (
    V2UploadIntent,
    V2UploadIntentFailure,
    V2UploadIntentResponse,
)

pytestmark = pytest.mark.no_docker


def test_failures_defaults_to_empty_when_every_file_succeeds() -> None:
    response = V2UploadIntentResponse(
        externalContextRef="ctx-1",
        phase="BOOKING",
        uploads=[
            V2UploadIntent(
                clientUploadId="c1",
                documentId=uuid4(),
                uploadUrl="https://example.test/put",
                uploadHeaders={},
                expiresAtUtc="2026-01-01T00:00:00Z",
            )
        ],
    )
    assert response.failures == []


def test_failures_carries_one_entry_per_failed_file_without_touching_successes() -> None:
    response = V2UploadIntentResponse(
        externalContextRef="ctx-1",
        phase="BOOKING",
        uploads=[
            V2UploadIntent(
                clientUploadId="ok-file",
                documentId=uuid4(),
                uploadUrl="https://example.test/put",
                uploadHeaders={},
                expiresAtUtc="2026-01-01T00:00:00Z",
            )
        ],
        failures=[
            V2UploadIntentFailure(
                clientUploadId="bad-file",
                errorCode="CONFLICT",
                detail="The existing V2 upload intent was created with a different Audit Core requirement mapping.",
            )
        ],
    )
    assert [upload.clientUploadId for upload in response.uploads] == ["ok-file"]
    assert [failure.clientUploadId for failure in response.failures] == ["bad-file"]
