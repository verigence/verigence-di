"""tests/test_intake_quality.py — Unit tests for quality-validator wiring in intake.

Verifies that intake_document:
- Returns NOT_FIT (not FIT) when quality rules reject the upload.
- Returns FIT and creates a processing job when all rules pass.
- Does NOT create a processing job for NOT_FIT documents.

All tests are marked no_docker. Storage and DB are replaced by mocks.
"""
from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

pytestmark = pytest.mark.no_docker

from verigence.di.application.intake import intake_document
from verigence.di.domain.enums import UploadStatus
from fastapi import UploadFile


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_upload(data: bytes, filename: str = "test.pdf", mime: str = "application/pdf") -> UploadFile:
    """Create an in-memory UploadFile."""
    return UploadFile(
        filename=filename,
        file=io.BytesIO(data),
        headers=MagicMock(get=MagicMock(return_value=mime)),
    )


def _minimal_pdf() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\n"
        b"startxref\n190\n%%EOF\n"
    )


def _make_mappings_row(**kwargs) -> MagicMock:  # type: ignore[no-untyped-def]
    """Return a mock that behaves like a SQLAlchemy mapping row (supports [] and .get())."""
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: kwargs[k])
    row.get = MagicMock(side_effect=lambda k, default=None: kwargs.get(k, default))
    return row


def _make_session_mock() -> AsyncMock:
    """Minimal async session: retention policy + storage key + artifact INSERT.

    Uses proper mapping mocks so RetentionDisposition(row["disposition"]) works.
    """
    session = AsyncMock()

    _retention_policy_id = uuid.uuid4()

    # 1. get_active_retention_policy — returns a mappings().one_or_none()
    retention_row = _make_mappings_row(
        retention_policy_id=_retention_policy_id,
        retention_days=365,
        disposition="PURGE_CONTENT",
    )
    retention_mappings = MagicMock()
    retention_mappings.one_or_none.return_value = retention_row
    retention_result = MagicMock()
    retention_result.mappings.return_value = retention_mappings

    # 2. INSERT documents (create_document_receiving) — plain result
    insert_doc_result = MagicMock()

    # 3. SELECT tenant_storage_key — returns a plain row (accessed as row[0])
    storage_key_row = MagicMock()
    storage_key_row.__getitem__ = MagicMock(return_value=str(uuid.uuid4()))
    storage_key_result = MagicMock()
    storage_key_result.one_or_none.return_value = storage_key_row

    # 4. INSERT document_artifacts — plain result
    insert_artifact_result = MagicMock()

    # 5+ UPDATE document / INSERT job / validate_upload internals (unlimited generics)
    generic = MagicMock()

    session.execute = AsyncMock(side_effect=[
        retention_result,       # get_active_retention_policy
        insert_doc_result,      # INSERT documents
        storage_key_result,     # SELECT tenant_storage_key
        insert_artifact_result, # INSERT document_artifacts
    ] + [generic] * 30)

    session.commit = AsyncMock()
    return session


def _make_storage_mock() -> MagicMock:
    storage = MagicMock()
    storage_meta = MagicMock()
    storage_meta.storage_id = uuid.uuid4()
    storage.put_stream = AsyncMock(return_value=storage_meta)
    return storage


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_intake_calls_validate_upload() -> None:
    """validate_upload must be called during intake_document."""
    from verigence.di.quality.validator import ValidatorResult

    session = _make_session_mock()
    storage = _make_storage_mock()
    upload = _make_upload(_minimal_pdf())

    fit_result = ValidatorResult(upload_status=UploadStatus.FIT, detected_mime="application/pdf")

    with patch(
        "verigence.di.application.intake.validate_upload",
        new=AsyncMock(return_value=fit_result),
    ) as mock_validate:
        await intake_document(
            session=session,
            storage=storage,
            tenant_id="tenant-1",
            subject_id=uuid.uuid4(),
            source_channel=__import__(
                "verigence.di.domain.enums", fromlist=["SourceChannel"]
            ).SourceChannel.WEB,
            uploaded_by_actor_id="actor-1",
            uploaded_by_actor_type="USER",
            correlation_id="corr-001",
            upload=upload,
        )

    mock_validate.assert_called_once()
    kwargs = mock_validate.call_args.kwargs
    assert kwargs["tenant_id"] == "tenant-1"
    assert len(kwargs["data"]) > 0


@pytest.mark.asyncio
async def test_intake_fit_result_creates_processing_job() -> None:
    """A FIT validator result must trigger create_initial_job."""
    from verigence.di.quality.validator import ValidatorResult
    from verigence.di.domain.enums import SourceChannel

    session = _make_session_mock()
    storage = _make_storage_mock()
    upload = _make_upload(_minimal_pdf())

    fit_result = ValidatorResult(upload_status=UploadStatus.FIT, detected_mime="application/pdf")

    with (
        patch("verigence.di.application.intake.validate_upload", new=AsyncMock(return_value=fit_result)),
        patch("verigence.di.application.intake.create_initial_job", new=AsyncMock(return_value=uuid.uuid4())) as mock_job,
    ):
        doc = await intake_document(
            session=session,
            storage=storage,
            tenant_id="tenant-1",
            subject_id=uuid.uuid4(),
            source_channel=SourceChannel.WEB,
            uploaded_by_actor_id="actor-1",
            uploaded_by_actor_type="USER",
            correlation_id="corr-001",
            upload=upload,
        )

    assert doc["upload_status"] == UploadStatus.FIT
    mock_job.assert_called_once()


@pytest.mark.asyncio
async def test_intake_not_fit_skips_processing_job() -> None:
    """A NOT_FIT validator result must NOT create a processing job."""
    from verigence.di.quality.validator import ValidatorResult
    from verigence.di.domain.enums import SourceChannel

    session = _make_session_mock()
    storage = _make_storage_mock()
    upload = _make_upload(_minimal_pdf())

    not_fit_result = ValidatorResult(
        upload_status=UploadStatus.NOT_FIT,
        upload_issue_code="FILE_SIZE_TOO_LARGE",
        upload_issue_detail="Exceeds limit",
        detected_mime="application/pdf",
    )

    with (
        patch("verigence.di.application.intake.validate_upload", new=AsyncMock(return_value=not_fit_result)),
        patch("verigence.di.application.intake.create_initial_job", new=AsyncMock()) as mock_job,
    ):
        doc = await intake_document(
            session=session,
            storage=storage,
            tenant_id="tenant-1",
            subject_id=uuid.uuid4(),
            source_channel=SourceChannel.WEB,
            uploaded_by_actor_id="actor-1",
            uploaded_by_actor_type="USER",
            correlation_id="corr-001",
            upload=upload,
        )

    assert doc["upload_status"] == UploadStatus.NOT_FIT
    assert doc["upload_issue_code"] == "FILE_SIZE_TOO_LARGE"
    mock_job.assert_not_called()


@pytest.mark.asyncio
async def test_intake_corrupt_result_skips_processing_job() -> None:
    """A CORRUPT validator result must NOT create a processing job."""
    from verigence.di.quality.validator import ValidatorResult
    from verigence.di.domain.enums import SourceChannel

    session = _make_session_mock()
    storage = _make_storage_mock()
    upload = _make_upload(_minimal_pdf())

    corrupt_result = ValidatorResult(
        upload_status=UploadStatus.CORRUPT,
        upload_issue_code="INVALID_FILE_CONTENT",
        upload_issue_detail="Corrupt PDF",
        detected_mime="application/pdf",
    )

    with (
        patch("verigence.di.application.intake.validate_upload", new=AsyncMock(return_value=corrupt_result)),
        patch("verigence.di.application.intake.create_initial_job", new=AsyncMock()) as mock_job,
    ):
        doc = await intake_document(
            session=session,
            storage=storage,
            tenant_id="tenant-1",
            subject_id=uuid.uuid4(),
            source_channel=SourceChannel.WEB,
            uploaded_by_actor_id="actor-1",
            uploaded_by_actor_type="USER",
            correlation_id="corr-001",
            upload=upload,
        )

    assert doc["upload_status"] == UploadStatus.CORRUPT
    mock_job.assert_not_called()
