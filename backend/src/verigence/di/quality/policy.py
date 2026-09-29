"""quality/policy.py — the scan-quality policy every tenant starts with.

Every UC03 page is a scan or a phone photo, combined into a PDF or uploaded
as an image. These rules run on the page image (the scan inside a PDF page)
before any classification or extraction call, so a page that cannot be read
is rejected at once, named to the person who uploaded it, and never billed.

Thresholds are a starting point, tuned per tenant from
``document_quality_results.measurement`` once real scans have been through:
- blur: Laplacian variance of the full-resolution greyscale page; the rule's
  own default is 100, 80 is a little more lenient so light-text pages such as
  receipts are not rejected before a tenant has calibrated it.
- dimensions: 800x600 rejects thumbnails and previews, not real captures
  (an A4 scan at 100 dpi is 827x1169; phone photos are wider).
- page count: Audit Core sends one page at a time and merges at most a few
  pages of one document; 100 matches its own upload limit.
"""

from __future__ import annotations

from typing import Any

DEFAULT_QUALITY_POLICY: list[dict[str, Any]] = [
    {"rule_key": "di.quality.file_not_empty", "enabled": True, "parameters": {}},
    {
        "rule_key": "di.quality.image_min_dimensions",
        "enabled": True,
        "parameters": {"min_width": 800, "min_height": 600},
    },
    {
        "rule_key": "di.quality.image_blur_score",
        "enabled": True,
        "parameters": {"min_variance": 80.0},
    },
    {"rule_key": "di.quality.pdf_page_count", "enabled": True, "parameters": {"max_pages": 100}},
]

# The platform catalogue: rule_key -> (description, implementation_key, parameter schema).
# A tenant policy may only name a catalogued, ACTIVE rule.
QUALITY_RULE_CATALOG: list[dict[str, Any]] = [
    {
        "rule_key": "di.quality.file_not_empty",
        "implementation_key": "di.quality.file_not_empty",
        "description": "The upload holds at least one byte.",
        "parameter_schema": {"type": "object", "properties": {}},
    },
    {
        "rule_key": "di.quality.file_size_max",
        "implementation_key": "di.quality.file_size_max",
        "description": "The upload is no larger than max_bytes (default 30 MiB).",
        "parameter_schema": {"type": "object", "properties": {"max_bytes": {"type": "integer"}}},
    },
    {
        "rule_key": "di.quality.mime_type_allowed",
        "implementation_key": "di.quality.mime_type_allowed",
        "description": "The detected file type is one of allowed_types (default PDF, JPEG, PNG, WebP, TIFF).",
        "parameter_schema": {
            "type": "object",
            "properties": {"allowed_types": {"type": "array", "items": {"type": "string"}}},
        },
    },
    {
        "rule_key": "di.quality.image_min_dimensions",
        "implementation_key": "di.quality.image_min_dimensions",
        "description": "The page image (or the scan inside a PDF page) is at least min_width x min_height pixels.",
        "parameter_schema": {
            "type": "object",
            "properties": {"min_width": {"type": "integer"}, "min_height": {"type": "integer"}},
        },
    },
    {
        "rule_key": "di.quality.image_blur_score",
        "implementation_key": "di.quality.image_blur_score",
        "description": "The page image (or the scan inside a PDF page) is sharp: Laplacian variance at least min_variance.",
        "parameter_schema": {"type": "object", "properties": {"min_variance": {"type": "number"}}},
    },
    {
        "rule_key": "di.quality.pdf_page_count",
        "implementation_key": "di.quality.pdf_page_count",
        "description": "A PDF has at most max_pages pages.",
        "parameter_schema": {"type": "object", "properties": {"max_pages": {"type": "integer"}}},
    },
]
