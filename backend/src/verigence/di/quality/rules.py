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


def _image_bytes(data: bytes) -> bytes:
    """What the image rules measure: the upload itself, or, for a PDF page
    that is a scan (embedded images, no text), the largest embedded image.
    A PDF without one is returned as is, and the rule skips as before."""
    if data[:4] != b"%PDF":
        return data
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data), strict=False)
        images = [image for page in reader.pages[:1] for image in page.images]
        if not images:
            return data
        return max(images, key=lambda image: len(image.data)).data
    except Exception:
        return data


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
        img = Image.open(io.BytesIO(_image_bytes(data)))
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

        img_array = np.frombuffer(_image_bytes(data), dtype=np.uint8)
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


def _rule_image_contrast(
    data: bytes,
    rule_key: str,
    params: dict[str, Any],
) -> QualityRuleResult:
    """Reject a faded page: the writing is grey, not dark, against its paper.

    Added 2026-10-20 (product owner): a faded, low-contrast phone photo of a
    handwritten Gate Pass passed the blur check -- the printed form lines are
    sharp -- and its date was read as 2020 instead of 2026.

    The page is measured at 1200 px on its long side. Writing is found with a
    black-hat transform (pixels at least 30 darker than their local paper),
    so a dark table around the paper or a shadow does not count as ink:

    - ``ink_level``: the 10th percentile grey level of the writing
      (0 black .. 255 white) -- how dark the darkest strokes are;
    - ``stroke_contrast``: the 90th percentile of how much darker the writing
      is than the paper around it.

    The page fails only when both say faded: ``ink_level`` above
    ``max_ink_level`` and ``stroke_contrast`` below ``min_stroke_contrast``.
    A page with no writing at all is skipped (other rules handle it).
    """
    max_ink_level: float = float(params.get("max_ink_level", 90.0))
    min_stroke_contrast: float = float(params.get("min_stroke_contrast", 160.0))
    applied = {"max_ink_level": max_ink_level, "min_stroke_contrast": min_stroke_contrast}

    try:
        import cv2
        import numpy as np

        img = cv2.imdecode(np.frombuffer(_image_bytes(data), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return QualityRuleResult(
                rule_key=rule_key, outcome="SKIP", parameters_applied=applied,
                measurement={"error": "cv2 could not decode image"},
                message="Could not decode image for contrast check",
            )
        height, width = img.shape[:2]
        scale = 1200.0 / max(height, width)
        if scale < 1.0:
            img = cv2.resize(img, (max(1, int(width * scale)), max(1, int(height * scale))),
                             interpolation=cv2.INTER_AREA)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        depth = cv2.morphologyEx(img, cv2.MORPH_BLACKHAT, kernel)
        ink = depth > 30
        ink_fraction = float(ink.mean())
        if ink_fraction < 0.002:
            return QualityRuleResult(
                rule_key=rule_key, outcome="SKIP", parameters_applied=applied,
                measurement={"ink_fraction": round(ink_fraction, 4)},
                message="No writing found for the contrast check",
            )
        ink_level = float(np.percentile(img[ink], 10))
        stroke_contrast = float(np.percentile(depth[ink], 90))
        faded = ink_level > max_ink_level and stroke_contrast < min_stroke_contrast
        return QualityRuleResult(
            rule_key=rule_key,
            outcome="FAIL" if faded else "PASS",
            parameters_applied=applied,
            measurement={
                "ink_level": round(ink_level, 1),
                "stroke_contrast": round(stroke_contrast, 1),
                "ink_fraction": round(ink_fraction, 4),
            },
            message=(
                f"Page too faded: writing is grey (ink level {ink_level:.0f}, "
                f"contrast {stroke_contrast:.0f}); re-scan in good light"
            ) if faded else None,
        )
    except ImportError:
        return QualityRuleResult(
            rule_key=rule_key, outcome="SKIP", parameters_applied=applied,
            measurement={"error": "opencv-python-headless not available"},
            message="Contrast check skipped — OpenCV not available",
        )
    except Exception as exc:
        return QualityRuleResult(
            rule_key=rule_key, outcome="ERROR", parameters_applied=applied,
            measurement={"error": str(exc)},
            message=f"Contrast check error: {exc}",
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
    "di.quality.image_contrast":        _rule_image_contrast,
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
