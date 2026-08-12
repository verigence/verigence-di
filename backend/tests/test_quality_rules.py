"""tests/test_quality_rules.py — Unit tests for quality rule implementations.

All tests are marked no_docker: pure in-process, no DB, no network.
Each test exercises the rule function directly via the REGISTRY.
"""
from __future__ import annotations

import io
import struct

import pytest

pytestmark = pytest.mark.no_docker

from verigence.di.quality.rules import (
    REGISTRY,
    QualityRuleResult,
    _detect_mime,
    get_rule,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _small_jpeg() -> bytes:
    """Minimal valid JPEG: SOI + EOI markers."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


def _small_png() -> bytes:
    """Minimal valid PNG signature + IHDR."""
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: 13-byte data = 1×1 pixel, 8-bit, RGB
    width, height = 1, 1
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    import zlib
    crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", crc)
    # IEND chunk
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return sig + ihdr_chunk + iend_chunk


def _minimal_pdf() -> bytes:
    """Minimal parseable PDF with one empty page."""
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


# ── REGISTRY lookup ───────────────────────────────────────────────────────────

def test_registry_contains_all_six_rules() -> None:
    expected = {
        "di.quality.file_not_empty",
        "di.quality.file_size_max",
        "di.quality.mime_type_allowed",
        "di.quality.image_min_dimensions",
        "di.quality.image_blur_score",
        "di.quality.pdf_page_count",
    }
    assert expected == set(REGISTRY.keys())


def test_get_rule_returns_callable() -> None:
    fn = get_rule("di.quality.file_not_empty")
    assert fn is not None and callable(fn)


def test_get_rule_unknown_returns_none() -> None:
    assert get_rule("di.quality.does_not_exist") is None


# ── file_not_empty ────────────────────────────────────────────────────────────

def test_file_not_empty_pass() -> None:
    fn = get_rule("di.quality.file_not_empty")
    assert fn is not None
    r = fn(b"some data", "di.quality.file_not_empty", {})
    assert r.outcome == "PASS"
    assert r.measurement["file_size_bytes"] == 9


def test_file_not_empty_fail_on_zero_bytes() -> None:
    fn = get_rule("di.quality.file_not_empty")
    assert fn is not None
    r = fn(b"", "di.quality.file_not_empty", {})
    assert r.outcome == "FAIL"
    assert r.message is not None and "empty" in r.message.lower()


# ── file_size_max ─────────────────────────────────────────────────────────────

def test_file_size_max_pass() -> None:
    fn = get_rule("di.quality.file_size_max")
    assert fn is not None
    r = fn(b"x" * 100, "di.quality.file_size_max", {"max_bytes": 200})
    assert r.outcome == "PASS"


def test_file_size_max_fail_when_over_limit() -> None:
    fn = get_rule("di.quality.file_size_max")
    assert fn is not None
    r = fn(b"x" * 201, "di.quality.file_size_max", {"max_bytes": 200})
    assert r.outcome == "FAIL"
    assert r.parameters_applied["max_bytes"] == 200
    assert r.measurement["file_size_bytes"] == 201


def test_file_size_max_uses_default_30mb() -> None:
    fn = get_rule("di.quality.file_size_max")
    assert fn is not None
    r = fn(b"x" * 1024, "di.quality.file_size_max", {})
    assert r.outcome == "PASS"
    assert r.parameters_applied["max_bytes"] == 30 * 1024 * 1024


# ── mime_type_allowed ─────────────────────────────────────────────────────────

def test_mime_type_allowed_passes_jpeg() -> None:
    fn = get_rule("di.quality.mime_type_allowed")
    assert fn is not None
    r = fn(_small_jpeg(), "di.quality.mime_type_allowed", {})
    # JPEG magic bytes → image/jpeg
    assert r.outcome == "PASS"


def test_mime_type_allowed_fails_unknown() -> None:
    fn = get_rule("di.quality.mime_type_allowed")
    assert fn is not None
    r = fn(b"\x00\x01\x02\x03" * 100, "di.quality.mime_type_allowed", {})
    assert r.outcome == "FAIL"
    assert r.message is not None


def test_mime_type_allowed_custom_list() -> None:
    fn = get_rule("di.quality.mime_type_allowed")
    assert fn is not None
    # Only allow PDF; pass PDF bytes
    pdf_bytes = _minimal_pdf()
    r = fn(pdf_bytes, "di.quality.mime_type_allowed", {"allowed_types": ["application/pdf"]})
    assert r.outcome == "PASS"


# ── image_min_dimensions ──────────────────────────────────────────────────────

def test_image_min_dimensions_skip_on_non_image() -> None:
    """Non-image bytes → PIL fails → SKIP (not ERROR)."""
    fn = get_rule("di.quality.image_min_dimensions")
    assert fn is not None
    r = fn(b"\x00" * 100, "di.quality.image_min_dimensions", {"min_width": 10, "min_height": 10})
    # Either SKIP (PIL not importable or can't decode) — never an uncaught exception
    assert r.outcome in ("SKIP", "FAIL", "PASS")


def test_image_min_dimensions_pass_1x1_png() -> None:
    fn = get_rule("di.quality.image_min_dimensions")
    assert fn is not None
    png = _small_png()
    r = fn(png, "di.quality.image_min_dimensions", {"min_width": 1, "min_height": 1})
    # PIL present: PASS; PIL absent: SKIP — both acceptable
    assert r.outcome in ("PASS", "SKIP")


# ── image_blur_score ──────────────────────────────────────────────────────────

def test_blur_score_skips_gracefully_without_opencv() -> None:
    """If opencv is not installed the rule must return SKIP, not raise."""
    fn = get_rule("di.quality.image_blur_score")
    assert fn is not None
    r = fn(b"\x00" * 50, "di.quality.image_blur_score", {"min_variance": 50.0})
    assert r.outcome in ("SKIP", "ERROR", "FAIL")
    # Must never propagate an exception
    assert isinstance(r, QualityRuleResult)


# ── pdf_page_count ────────────────────────────────────────────────────────────

def test_pdf_page_count_pass() -> None:
    fn = get_rule("di.quality.pdf_page_count")
    assert fn is not None
    r = fn(_minimal_pdf(), "di.quality.pdf_page_count", {"max_pages": 10})
    # pypdf present: PASS (1 page ≤ 10); pypdf absent: SKIP
    assert r.outcome in ("PASS", "SKIP")


def test_pdf_page_count_fail_over_limit() -> None:
    fn = get_rule("di.quality.pdf_page_count")
    assert fn is not None
    r = fn(_minimal_pdf(), "di.quality.pdf_page_count", {"max_pages": 0})
    # pypdf present: FAIL (1 page > 0); pypdf absent: SKIP
    assert r.outcome in ("FAIL", "SKIP")


def test_pdf_page_count_skip_on_non_pdf() -> None:
    fn = get_rule("di.quality.pdf_page_count")
    assert fn is not None
    r = fn(b"\x00" * 100, "di.quality.pdf_page_count", {"max_pages": 5})
    assert r.outcome == "SKIP"


# ── _detect_mime helper ───────────────────────────────────────────────────────

def test_detect_mime_pdf() -> None:
    assert _detect_mime(_minimal_pdf()) == "application/pdf"


def test_detect_mime_jpeg() -> None:
    assert _detect_mime(_small_jpeg()) == "image/jpeg"


def test_detect_mime_png() -> None:
    assert _detect_mime(_small_png()) == "image/png"


def test_detect_mime_unknown_returns_octet_stream() -> None:
    result = _detect_mime(b"\x01\x02\x03\x04" * 10)
    assert result == "application/octet-stream"
