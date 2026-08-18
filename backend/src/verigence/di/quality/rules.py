"""quality/rules.py — Approved deterministic quality rule implementations.

Each rule is a callable registered in the REGISTRY dict keyed by
implementation_key (matches quality_rule_catalog.implementation_key).

Rules MUST be deterministic — no AI, no network calls.
Rules MUST NOT raise; they return a QualityRuleResult.

Architecture contract (DI_CONFIGURATION_MODEL_v2.0.md §8):
- rule_key  : stable DB key used in quality_policy and quality_rule_catalog
- outcome   : PASS | FAIL | SKIP | ERROR
- Parameters come from Tenant quality_policy (validated at Tenant activation).
- Measurements are stored verbatim in document_quality_results.measurement.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class QualityRuleResult:
    rule_key: str
    outcome: str                          # PASS | FAIL | SKIP | ERROR
    parameters_applied: dict[str, Any]
    measurement: dict[str, Any]
    message: str | None = None


# ── Type alias ────────────────────────────────────────────────────────────────
RuleFn = Callable[[bytes, str, dict[str, Any]], QualityRuleResult]


# ── Rule implementations ──────────────────────────────────────────────────────

def _rule_file_not_empty(
    data: bytes,
    rule_key: str,
    params: dict[str, Any],
) -> QualityRuleResult:
    """Reject zero-byte uploads."""
    size = len(data)
    outcome = "PASS" if size > 0 else "FAIL"
    return QualityRuleResult(
        rule_key=rule_key,
        outcome=outcome,
        parameters_applied=params,
        measurement={"file_size_bytes": size},
        message=None if outcome == "PASS" else "File is empty (0 bytes)",
    )


def _rule_file_size_max(
    data: bytes,
    rule_key: str,
    params: dict[str, Any],
) -> QualityRuleResult:
    """Reject files exceeding max_bytes parameter."""
    max_bytes: int = int(params.get("max_bytes", 30 * 1024 * 1024))
    size = len(data)
    outcome = "PASS" if size <= max_bytes else "FAIL"
    return QualityRuleResult(
        rule_key=rule_key,
        outcome=outcome,
        parameters_applied={"max_bytes": max_bytes},
        measurement={"file_size_bytes": size},
        message=None if outcome == "PASS" else f"File {size} bytes exceeds limit {max_bytes} bytes",
    )


def _rule_mime_type_allowed(
    data: bytes,
    rule_key: str,
    params: dict[str, Any],
) -> QualityRuleResult:
    """Check detected MIME type is in allowed_types list."""
    allowed: list[str] = params.get("allowed_types", [
        "image/jpeg", "image/png", "image/webp", "image/tiff", "application/pdf",
    ])
    detected = _detect_mime(data)
    outcome = "PASS" if detected in allowed else "FAIL"
    return QualityRuleResult(
        rule_key=rule_key,
        outcome=outcome,
        parameters_applied={"allowed_types": allowed},
        measurement={"detected_mime": detected},
        message=None if outcome == "PASS" else f"MIME type {detected!r} is not allowed",
    )


def _rule_image_min_dimensions(
    data: bytes,
    rule_key: str,
    params: dict[str, Any],
) -> QualityRuleResult:
    """Reject images below min_width × min_height pixels."""
    min_width: int  = int(params.get("min_width",  200))
    min_height: int = int(params.get("min_height", 200))
    applied = {"min_width": min_width, "min_height": min_height}

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        outcome = "PASS" if w >= min_width and h >= min_height else "FAIL"
        msg = None if outcome == "PASS" else f"Image {w}×{h} below minimum {min_width}×{min_height}"
        return QualityRuleResult(
            rule_key=rule_key,
            outcome=outcome,
            parameters_applied=applied,
            measurement={"width": w, "height": h},
            message=msg,
        )
    except Exception as exc:
        return QualityRuleResult(
            rule_key=rule_key,
            outcome="SKIP",
            parameters_applied=applied,
            measurement={"error": str(exc)},
            message="Could not decode image for dimension check",
        )


def _rule_image_blur_score(
    data: bytes,
    rule_key: str,
    params: dict[str, Any],
) -> QualityRuleResult:
    """Estimate image sharpness using Laplacian variance. Fail if below threshold.

    A low Laplacian variance indicates a blurry image.
    Typical threshold for acceptable document scans: 50–200 (configurable).
    """
    min_variance: float = float(params.get("min_variance", 100.0))
    applied = {"min_variance": min_variance}

    try:
        import cv2
        import numpy as np

        img_array = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return QualityRuleResult(
                rule_key=rule_key, outcome="SKIP",
                parameters_applied=applied,
                measurement={"error": "cv2 could not decode image"},
                message="Could not decode image for blur check",
            )
        variance = float(cv2.Laplacian(img, cv2.CV_64F).var())
        outcome = "PASS" if variance >= min_variance else "FAIL"
        msg = None if outcome == "PASS" else f"Blur score {variance:.1f} below threshold {min_variance}"
        return QualityRuleResult(
            rule_key=rule_key,
            outcome=outcome,
            parameters_applied=applied,
            measurement={"laplacian_variance": round(variance, 2)},
            message=msg,
        )
    except ImportError:
        return QualityRuleResult(
            rule_key=rule_key, outcome="SKIP",
            parameters_applied=applied,
            measurement={"error": "opencv-python-headless not available"},
            message="Blur check skipped — OpenCV not available",
        )
    except Exception as exc:
        return QualityRuleResult(
            rule_key=rule_key, outcome="ERROR",
            parameters_applied=applied,
            measurement={"error": str(exc)},
            message=f"Blur check error: {exc}",
        )


def _rule_pdf_page_count(
    data: bytes,
    rule_key: str,
    params: dict[str, Any],
) -> QualityRuleResult:
    """Reject PDFs with more than max_pages pages."""
    max_pages: int = int(params.get("max_pages", 50))
    applied = {"max_pages": max_pages}

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data), strict=False)
        page_count = len(reader.pages)
        outcome = "PASS" if page_count <= max_pages else "FAIL"
        msg = None if outcome == "PASS" else f"PDF has {page_count} pages, max is {max_pages}"
        return QualityRuleResult(
            rule_key=rule_key,
            outcome=outcome,
            parameters_applied=applied,
            measurement={"page_count": page_count},
            message=msg,
        )
    except Exception as exc:
        return QualityRuleResult(
            rule_key=rule_key, outcome="SKIP",
            parameters_applied=applied,
            measurement={"error": str(exc)},
            message="Could not parse PDF for page count",
        )


# ── Public registry: implementation_key → function ───────────────────────────
# Keys must match quality_rule_catalog.implementation_key in the DB.

REGISTRY: dict[str, RuleFn] = {
    "di.quality.file_not_empty":        _rule_file_not_empty,
    "di.quality.file_size_max":         _rule_file_size_max,
    "di.quality.mime_type_allowed":     _rule_mime_type_allowed,
    "di.quality.image_min_dimensions":  _rule_image_min_dimensions,
    "di.quality.image_blur_score":      _rule_image_blur_score,
    "di.quality.pdf_page_count":        _rule_pdf_page_count,
}


def get_rule(implementation_key: str) -> RuleFn | None:
    """Return the rule function for the given implementation key, or None."""
    return REGISTRY.get(implementation_key)


# ── MIME detection helper (shared with quality rules) ─────────────────────────

def _detect_mime(data: bytes) -> str:
    """Detect MIME type from bytes using python-magic, then header sniff."""
    try:
        import magic
        return magic.from_buffer(data[:2048], mime=True)
    except Exception:
        pass
    # Fallback: magic-byte sniffing
    if data[:4] == b"%PDF":
        return "application/pdf"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    return "application/octet-stream"
