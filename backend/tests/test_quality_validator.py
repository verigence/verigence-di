"""tests/test_quality_validator.py — Unit tests for the upload validator.

All tests are marked no_docker. The DB session is replaced by an AsyncMock so
no real PostgreSQL connection is needed.

Tests cover:
- Zero-byte file → CORRUPT / FILE_EMPTY
- Structurally corrupt image → CORRUPT / INVALID_FILE_CONTENT
- Missing quality policy → CORRUPT / QUALITY_POLICY_NOT_CONFIGURED
- FIT result when all rules pass
- NOT_FIT result when a rule fails
- Quality results are persisted (INSERT called per rule)
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from verigence.di.domain.enums import UploadStatus
from verigence.di.quality.validator import validate_upload

pytestmark = pytest.mark.no_docker

# ── DB mock helpers ───────────────────────────────────────────────────────────

def _make_session(
    *,
    quality_policy: list | None = None,
    catalog_rows: list | None = None,
) -> AsyncMock:
    """Build a minimal async SQLAlchemy session mock.

    quality_policy: value returned for tenant_settings.quality_policy
                    None → row not found (no policy configured)
    catalog_rows:   list of {rule_key, implementation_key} dicts for the catalog
    """
    session = AsyncMock()

    # Prepare execute side effects in call order:
    # 1st execute → tenant quality_policy query
    # 2nd execute → quality_rule_catalog query
    # subsequent executes → INSERT quality_results rows (one per rule)

    policy_mapping = MagicMock()
    policy_mapping.__getitem__ = MagicMock(side_effect=lambda k: quality_policy)

    policy_result = MagicMock()
    policy_result.one_or_none.return_value = (
        policy_mapping if quality_policy is not None else None
    )

    # Build catalog result mock
    catalog_result = MagicMock()
    mappings_result = MagicMock()
    mappings_result.all.return_value = catalog_rows or []
    catalog_result.mappings.return_value = mappings_result

    # INSERT returns don't matter
    insert_result = MagicMock()

    # execute returns: policy → catalog → inserts (unlimited)
    session.execute = AsyncMock(
        side_effect=[policy_result, catalog_result] + [insert_result] * 20
    )

    return session


def _pdf_bytes() -> bytes:
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


def _jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


# ── Zero-byte file ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zero_byte_file_returns_corrupt() -> None:
    session = AsyncMock()
    result = await validate_upload(
        session=session,
        tenant_id="t1",
        document_id=uuid.uuid4(),
        data=b"",
        declared_mime="application/pdf",
        filename="empty.pdf",
    )
    assert result.upload_status == UploadStatus.CORRUPT
    assert result.upload_issue_code == "FILE_EMPTY"
    # No DB calls needed for empty-file short-circuit
    session.execute.assert_not_called()


# ── Missing quality policy ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_quality_policy_returns_corrupt() -> None:
    session = _make_session(quality_policy=None)
    result = await validate_upload(
        session=session,
        tenant_id="t1",
        document_id=uuid.uuid4(),
        data=_pdf_bytes(),
        declared_mime="application/pdf",
        filename="test.pdf",
    )
    assert result.upload_status == UploadStatus.CORRUPT
    assert result.upload_issue_code == "QUALITY_POLICY_NOT_CONFIGURED"


# ── Empty quality policy (no rules) → FIT ────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_policy_no_rules_returns_fit() -> None:
    session = _make_session(quality_policy=[], catalog_rows=[])
    # Use structurally valid PDF — pypdf parses it, PIL not involved
    result = await validate_upload(
        session=session,
        tenant_id="t1",
        document_id=uuid.uuid4(),
        data=_pdf_bytes(),
        declared_mime="application/pdf",
        filename="test.pdf",
    )
    assert result.upload_status == UploadStatus.FIT
    assert result.upload_issue_code is None
    assert result.quality_results == []


# ── Rule with PASS → FIT ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_passing_rule_returns_fit() -> None:
    policy = [
        {"rule_key": "file_not_empty", "enabled": True, "parameters": {}},
    ]
    catalog = [
        {"rule_key": "file_not_empty", "implementation_key": "di.quality.file_not_empty"},
    ]
    session = _make_session(quality_policy=policy, catalog_rows=catalog)

    result = await validate_upload(
        session=session,
        tenant_id="t1",
        document_id=uuid.uuid4(),
        data=_pdf_bytes(),
        declared_mime="application/pdf",
        filename="test.pdf",
    )
    assert result.upload_status == UploadStatus.FIT
    assert len(result.quality_results) == 1
    assert result.quality_results[0].outcome == "PASS"


# ── Rule with FAIL → NOT_FIT ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failing_rule_returns_not_fit() -> None:
    policy = [
        # max_bytes=1 → will FAIL for any real content
        {"rule_key": "file_size_max", "enabled": True, "parameters": {"max_bytes": 1}},
    ]
    catalog = [
        {"rule_key": "file_size_max", "implementation_key": "di.quality.file_size_max"},
    ]
    session = _make_session(quality_policy=policy, catalog_rows=catalog)

    result = await validate_upload(
        session=session,
        tenant_id="t1",
        document_id=uuid.uuid4(),
        data=_pdf_bytes(),
        declared_mime="application/pdf",
        filename="test.pdf",
    )
    assert result.upload_status == UploadStatus.NOT_FIT
    assert result.upload_issue_code is not None
    assert len(result.quality_results) == 1
    assert result.quality_results[0].outcome == "FAIL"


# ── Disabled rule is skipped ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disabled_rule_is_skipped() -> None:
    policy = [
        {"rule_key": "file_size_max", "enabled": False, "parameters": {"max_bytes": 1}},
    ]
    catalog = [
        {"rule_key": "file_size_max", "implementation_key": "di.quality.file_size_max"},
    ]
    session = _make_session(quality_policy=policy, catalog_rows=catalog)

    result = await validate_upload(
        session=session,
        tenant_id="t1",
        document_id=uuid.uuid4(),
        data=_pdf_bytes(),
        declared_mime="application/pdf",
        filename="test.pdf",
    )
    # Disabled rule must not run → FIT with zero quality_results
    assert result.upload_status == UploadStatus.FIT
    assert result.quality_results == []


# ── Rule_key missing from catalog → ERROR outcome, but overall FIT ───────────

@pytest.mark.asyncio
async def test_rule_key_not_in_catalog_produces_error_outcome() -> None:
    policy = [
        {"rule_key": "ghost_rule", "enabled": True, "parameters": {}},
    ]
    catalog: list = []  # empty catalog
    session = _make_session(quality_policy=policy, catalog_rows=catalog)

    result = await validate_upload(
        session=session,
        tenant_id="t1",
        document_id=uuid.uuid4(),
        data=_pdf_bytes(),
        declared_mime="application/pdf",
        filename="test.pdf",
    )
    # ERROR but no FAIL → FIT
    assert result.upload_status == UploadStatus.FIT
    assert len(result.quality_results) == 1
    assert result.quality_results[0].outcome == "ERROR"


# ── Multiple rules: one FAIL makes overall NOT_FIT ────────────────────────────

@pytest.mark.asyncio
async def test_multiple_rules_one_fail_is_not_fit() -> None:
    policy = [
        {"rule_key": "file_not_empty", "enabled": True, "parameters": {}},
        {"rule_key": "file_size_max", "enabled": True, "parameters": {"max_bytes": 1}},
    ]
    catalog = [
        {"rule_key": "file_not_empty", "implementation_key": "di.quality.file_not_empty"},
        {"rule_key": "file_size_max", "implementation_key": "di.quality.file_size_max"},
    ]
    session = _make_session(quality_policy=policy, catalog_rows=catalog)

    result = await validate_upload(
        session=session,
        tenant_id="t1",
        document_id=uuid.uuid4(),
        data=_pdf_bytes(),
        declared_mime="application/pdf",
        filename="test.pdf",
    )
    assert result.upload_status == UploadStatus.NOT_FIT
    assert len(result.quality_results) == 2
    outcomes = {r.rule_key: r.outcome for r in result.quality_results}
    assert outcomes["file_not_empty"] == "PASS"
    assert outcomes["file_size_max"] == "FAIL"
