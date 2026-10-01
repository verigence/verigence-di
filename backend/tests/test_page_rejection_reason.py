"""A rejected page says why, the image rules read the scan inside a PDF
page, and an oversized image is downscaled before extraction."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from verigence.di.api.v2.capture_documents import V2CaptureDocumentStatus
from verigence.di.document_ai.gemini_adapter import capped_image
from verigence.di.quality.rules import _image_bytes, get_rule

pytestmark = pytest.mark.no_docker


def _image(width: int, height: int, *, noisy: bool, fmt: str = "JPEG") -> bytes:
    import random

    image = Image.new("RGB", (width, height), (128, 128, 128))
    if noisy:
        pixels = image.load()
        rng = random.Random(7)
        for x in range(width):
            for y in range(height):
                v = rng.randrange(0, 256)
                pixels[x, y] = (v, v, v)
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def _scanned_pdf(image_bytes: bytes) -> bytes:
    """A one-page PDF that is one embedded scan image, as a phone app makes."""
    output = io.BytesIO()
    Image.open(io.BytesIO(image_bytes)).save(output, format="PDF")
    return output.getvalue()


def test_status_listing_carries_the_failure_reason() -> None:
    fields = set(V2CaptureDocumentStatus.model_fields)
    assert {"failureCode", "failureDetail", "extractionQueued"} <= fields


def test_a_classified_page_is_queued_with_a_readable_type_and_a_profile() -> None:
    from verigence.di.workers.capture_v2_classifier import extraction_skip_reason

    assert extraction_skip_reason(requires_processing=True, has_published_profile=True) is None
    assert extraction_skip_reason(requires_processing=False, has_published_profile=True) == "TYPE_NOT_READ"
    assert extraction_skip_reason(requires_processing=True, has_published_profile=False) == "NO_PUBLISHED_PROFILE"


def test_image_rules_read_the_scan_inside_a_pdf_page() -> None:
    sharp = _scanned_pdf(_image(600, 400, noisy=True))
    flat = _scanned_pdf(_image(600, 400, noisy=False))
    assert _image_bytes(sharp) != sharp  # the embedded image, not the PDF wrapper

    blur = get_rule("di.quality.image_blur_score")
    assert blur is not None
    assert blur(sharp, "di.quality.image_blur_score", {"min_variance": 100.0}).outcome == "PASS"
    rejected = blur(flat, "di.quality.image_blur_score", {"min_variance": 100.0})
    assert rejected.outcome == "FAIL" and "Blur score" in (rejected.message or "")

    dims = get_rule("di.quality.image_min_dimensions")
    assert dims is not None
    assert dims(sharp, "di.quality.image_min_dimensions", {"min_width": 500, "min_height": 300}).outcome == "PASS"
    assert dims(sharp, "di.quality.image_min_dimensions", {"min_width": 1000, "min_height": 300}).outcome == "FAIL"


def test_a_pdf_without_an_embedded_image_still_skips() -> None:
    from tests.test_quality_rules import _minimal_pdf

    blur = get_rule("di.quality.image_blur_score")
    assert blur is not None
    assert blur(_minimal_pdf(), "di.quality.image_blur_score", {}).outcome == "SKIP"


def test_extraction_downscales_only_an_oversized_image() -> None:
    big = _image(3000, 2000, noisy=False, fmt="PNG")
    payload, mime = capped_image(big, "image/png", 1536)
    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(payload)) as sent:
        assert sent.size == (1536, 1024)

    small = _image(800, 600, noisy=False)
    assert capped_image(small, "image/jpeg", 1536) == (small, "image/jpeg")
    pdf = _scanned_pdf(small)
    assert capped_image(pdf, "application/pdf", 1536) == (pdf, "application/pdf")
    assert capped_image(big, "image/png", 0) == (big, "image/png")
