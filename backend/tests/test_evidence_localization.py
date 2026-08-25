from __future__ import annotations

import json

import pytest

from verigence.di.document_ai.adapter import ExtractionField
from verigence.di.document_ai.gemini_adapter import _build_prompt, _parse_response
from verigence.di.document_ai.schemas import get_schema


def test_prompt_requests_page_and_normalized_box_without_guessing() -> None:
    prompt = _build_prompt(
        get_schema("booking_form"),
        [ExtractionField(field_key="customer_name")],
    )

    assert '"pageNo"' in prompt
    assert '"box_2d"' in prompt
    assert "normalized from 0 to 1000" in prompt
    assert "Do not wrap the object in an array" in prompt
    assert "Never infer, approximate, or invent a page number or bounding box" in prompt


def test_parse_response_preserves_valid_page_and_box() -> None:
    raw = json.dumps(
        {
            "customer_name": {
                "value": "RAJESH KUMAR",
                "confidence": "high",
                "pageNo": 2,
                "box_2d": [120, 85, 176, 438],
            }
        }
    )

    result = _parse_response(
        raw,
        get_schema("booking_form"),
        [ExtractionField(field_key="customer_name")],
    )[0]

    assert result.page_no == 2
    assert result.evidence_region == {
        "type": "BOX_2D",
        "coordinateSystem": "NORMALIZED_1000",
        "box": [120, 85, 176, 438],
    }


def test_parse_response_accepts_singleton_array_wrapper_from_gemini() -> None:
    raw = json.dumps(
        [
            {
                "customer_name": {
                    "value": "RAJESH KUMAR",
                    "confidence": "high",
                    "pageNo": 1,
                    "box_2d": [120, 85, 176, 438],
                }
            }
        ]
    )

    result = _parse_response(
        raw,
        get_schema("booking_form"),
        [ExtractionField(field_key="customer_name")],
    )[0]

    assert result.raw_value == "RAJESH KUMAR"
    assert result.page_no == 1
    assert result.evidence_region == {
        "type": "BOX_2D",
        "coordinateSystem": "NORMALIZED_1000",
        "box": [120, 85, 176, 438],
    }


def test_parse_response_rejects_ambiguous_multi_item_array() -> None:
    raw = json.dumps([{"customer_name": {}}, {"customer_name": {}}])

    with pytest.raises(ValueError, match="single-item array"):
        _parse_response(
            raw,
            get_schema("booking_form"),
            [ExtractionField(field_key="customer_name")],
        )


def test_parse_response_drops_invalid_location_without_dropping_value() -> None:
    raw = json.dumps(
        {
            "customer_name": {
                "value": "RAJESH KUMAR",
                "confidence": "high",
                "pageNo": 0,
                "box_2d": [120, 85, 1101, 438],
            }
        }
    )

    result = _parse_response(
        raw,
        get_schema("booking_form"),
        [ExtractionField(field_key="customer_name")],
    )[0]

    assert result.raw_value == "RAJESH KUMAR"
    assert result.page_no is None
    assert result.evidence_region is None


def test_parse_response_never_accepts_inverted_or_zero_area_box() -> None:
    for box in ([300, 100, 200, 400], [200, 100, 200, 400], [200, 400, 300, 200]):
        raw = json.dumps(
            {
                "customer_name": {
                    "value": "RAJESH KUMAR",
                    "confidence": "medium",
                    "pageNo": 1,
                    "box_2d": box,
                }
            }
        )
        result = _parse_response(
            raw,
            get_schema("booking_form"),
            [ExtractionField(field_key="customer_name")],
        )[0]
        assert result.raw_value == "RAJESH KUMAR"
        assert result.page_no == 1
        assert result.evidence_region is None
