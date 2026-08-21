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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from verigence.di.application.intake import intake_document
from verigence.di.domain.enums import UploadStatus

pytestmark = pytest.mark.no_docker

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


def _retention_result() -> MagicMock:
    retention_row = _make_mappings_row(
        retention_policy_id=uuid.uuid4(),
        retention_days=365,
        disposition="PURGE_CONTENT",
    )
    retention_mappings = MagicMock()
    retention_mappings.one_or_none.return_value = retention_row
    result = MagicMock()
    result.mappings.return_value = retention_mappings
    return result


def _subject_name_result() -> MagicMock:
    row = MagicMock()
    row.__getitem__ = MagicMock(return_value="Test Subject")
    result = MagicMock()
    result.one_or_none.return_value = row
    return result


def _make_session_mock() -> AsyncMock:
    """Minimal async session mock for intake without a Document Type hint.

    When no documentTypeKey is supplied there is no Tenant Document Type lookup;
    the Subject display-name lookup immediately follows retention resolution.
    """
    session = AsyncMock()
    generic = MagicMock()
    session.execute = AsyncMock(side_effect=[
        _retention_result(),
        _subject_name_result(),
        MagicMock(),  # INSERT documents
        MagicMock(),  # INSERT document_artifacts
    ] + [generic] * 30)
    session.commit = AsyncMock()
    return session


def _make_session_mock_with_type(
    physical_form_type: str = "GOVT_ID",
    requires_processing: bool = True,
) -> AsyncMock:
    """Session mock where the supplied Document Type resolves for the Tenant."""
    session = AsyncMock()
    tdt_row = MagicMock()
    dt_id = uuid.uuid4()
    tdt_row.__getitem__ = MagicMock(
        side_effect=lambda i: [physical_form_type, requires_processing, dt_id][i]
    )
    tdt_result = MagicMock()
    tdt_result.one_or_none.return_value = tdt_row
    generic = MagicMock()
    session.execute = AsyncMock(side_effect=[
        _retention_result(),
        tdt_result,
        _subject_name_result(),
        MagicMock(),  # INSERT documents
        MagicMock(),  # INSERT document_artifacts
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
    """A FIT document with a known processable type must trigger create_initial_job."""
    from verigence.di.quality.validator import ValidatorResult

    session = _make_session_mock_with_type(physical_form_type="GOVT_ID", requires_processing=True)
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
            uploaded_by_actor_id="actor-1",
            uploaded_by_actor_type="USER",
            correlation_id="corr-001",
            upload=upload,
            document_type_key="passport",
        )

    assert doc["upload_status"] == UploadStatus.FIT
    mock_job.assert_called_once()


@pytest.mark.asyncio
async def test_intake_not_fit_skips_processing_job() -> None:
    """A NOT_FIT validator result must NOT create a processing job."""
    from verigence.di.quality.validator import ValidatorResult

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
            uploaded_by_actor_id="actor-1",
            uploaded_by_actor_type="USER",
            correlation_id="corr-001",
            upload=upload,
        )

    assert doc["upload_status"] == UploadStatus.CORRUPT
    mock_job.assert_not_called()
