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
    # Two objects citing the same page are not one-per-page: still refused.
    raw = json.dumps([
        {"customer_name": {"value": "SECRET ONE", "confidence": "high", "pageNo": 1}},
        {"customer_name": {"value": "SECRET TWO", "confidence": "high", "pageNo": 1}, "extra": 1},
    ])
    with capture_logs() as logs, pytest.raises(GeminiResponseInvalidError):
        _parse_response(raw, get_schema("booking_form"), _FIELDS)
    shape = next(e for e in logs if e["event"] == "gemini_multi_item_answer_shape")
    assert shape["items"] == 2
    assert [i["pages"] for i in shape["shape"]] == [[1], [1]]
    assert shape["shape"][1]["otherKeys"] == 1
    assert "SECRET" not in json.dumps(shape)


_INVOICE_FIELDS = [
    ExtractionField(field_key=k)
    for k in ("invoice_number", "grand_total_amount", "line_items", "buyer_name")
]


def _f(value, page):
    return {"value": value, "confidence": "high", "pageNo": page}


def test_two_page_invoice_answered_per_page_is_merged() -> None:
    """The live shape (2026-10-21): a two-page accessory invoice came back as
    two objects, one per page. Identity from the first page, the total from
    the last, line items joined in page order."""
    raw = json.dumps([
        {"invoice_number": _f("C1R27F000000053", 1), "grand_total_amount": _f("3000.00", 1),
         "buyer_name": _f("A KUMAR", 1), "line_items": _f([{"d": "mat"}], 1)},
        {"invoice_number": _f("C1R27F000000053", 2), "grand_total_amount": _f("4746.00", 2),
         "line_items": _f([{"d": "guard"}], 2)},
    ])
    with capture_logs() as logs:
        result = {r.field_key: r for r in _parse_response(raw, get_schema("accessory_invoice_dms"), _INVOICE_FIELDS)}
    assert result["invoice_number"].raw_value == "C1R27F000000053"
    assert result["grand_total_amount"].raw_value == "4746.00"
    assert result["buyer_name"].raw_value == "A KUMAR"
    assert json.loads(result["line_items"].raw_value) == [{"d": "mat"}, {"d": "guard"}]
    assert any(e["event"] == "gemini_per_page_answer_merged" for e in logs)


def test_items_out_of_page_order_or_without_pages_are_still_refused() -> None:
    out_of_order = json.dumps([
        {"invoice_number": _f("X", 2)},
        {"invoice_number": _f("X", 1)},
    ])
    no_pages = json.dumps([
        {"invoice_number": {"value": "X", "confidence": "high"}},
        {"invoice_number": {"value": "X", "confidence": "high"}},
    ])
    for raw in (out_of_order, no_pages):
        with pytest.raises(GeminiResponseInvalidError):
            _parse_response(raw, get_schema("accessory_invoice_dms"), _INVOICE_FIELDS)
