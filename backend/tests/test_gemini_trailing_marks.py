"""A complete answer followed only by closing marks is read; anything else
after it is still refused (2026-10-21: dealer receipts refused day and night
for three trailing characters)."""
from __future__ import annotations

import json

import pytest
from structlog.testing import capture_logs

from verigence.di.document_ai.adapter import ExtractionField
from verigence.di.document_ai.gemini_adapter import GeminiResponseInvalidError, _parse_response
from verigence.di.document_ai.schemas import get_schema

_FIELDS = [ExtractionField(field_key="customer_name")]
_ANSWER = json.dumps({"customer_name": {"value": "RAJESH KUMAR", "confidence": "high", "pageNo": 1}})


@pytest.mark.parametrize("tail", ["```", "\n```", "}", "]", "\n}\n", " ` "])
def test_complete_answer_with_closing_marks_is_read(tail: str) -> None:
    with capture_logs() as logs:
        result = _parse_response(_ANSWER + tail, get_schema("booking_form"), _FIELDS)[0]
    assert result.raw_value == "RAJESH KUMAR"
    assert any(e["event"] == "gemini_trailing_marks_ignored" for e in logs)


@pytest.mark.parametrize("tail", ["x", '{"customer_name": {"value": "OTHER"}}', "```json", ", 1"])
def test_anything_else_after_the_answer_is_still_refused(tail: str) -> None:
    with pytest.raises(GeminiResponseInvalidError):
        _parse_response(_ANSWER + tail, get_schema("booking_form"), _FIELDS)


def test_multi_item_answer_logs_its_shape_without_values() -> None:
    raw = json.dumps([
        {"customer_name": {"value": "SECRET ONE", "confidence": "high", "pageNo": 1}},
        {"customer_name": {"value": "SECRET TWO", "confidence": "high", "pageNo": 2}, "extra": 1},
    ])
    with capture_logs() as logs, pytest.raises(GeminiResponseInvalidError):
        _parse_response(raw, get_schema("booking_form"), _FIELDS)
    shape = next(e for e in logs if e["event"] == "gemini_multi_item_answer_shape")
    assert shape["items"] == 2
    assert [i["pages"] for i in shape["shape"]] == [[1], [2]]
    assert shape["shape"][1]["otherKeys"] == 1
    assert "SECRET" not in json.dumps(shape)
