"""Confirmed live (2026-09-24): an RTO Challan's and an Accessory Invoice's
own ``line_items`` extracted correctly, but landed downstream in
journey_document_extracted_fields as an unparseable string -- Python's
``str()`` on a list of dicts produces single-quoted repr text, not JSON, and
that string is what the whole normalization/persistence pipeline treats as
this field's raw value from here on. This module tests _parse_response's
serialization of array/object field values directly, without needing the
Gemini HTTP call or the normalization/persistence layers downstream of it.
"""
from __future__ import annotations

import json

import pytest

from verigence.di.document_ai.adapter import ExtractionField
from verigence.di.document_ai.gemini_adapter import _parse_response
from verigence.di.domain.enums import FoundStatus

pytestmark = pytest.mark.no_docker


def _schema_stub():
    class _Schema:
        pass

    return _Schema()


def test_array_field_value_is_serialized_as_valid_json_not_python_repr() -> None:
    line_items = [
        {"description_raw": "MV Tax(One Time)", "amount": 100252},
        {"description_raw": "Hypothecation Addition", "amount": 1500},
    ]
    raw_text = json.dumps(
        {"line_items": {"value": line_items, "confidence": "high"}}
    )

    results = _parse_response(
        raw_text, _schema_stub(), [ExtractionField(field_key="line_items")]
    )

    assert len(results) == 1
    result = results[0]
    assert result.found_status == FoundStatus.FOUND
    assert result.normalized_value == line_items
    # The critical assertion: raw_value must be round-trippable JSON, not
    # str()'s single-quoted repr (which json.loads cannot parse).
    assert json.loads(result.raw_value) == line_items


def test_object_field_value_is_serialized_as_valid_json() -> None:
    raw_text = json.dumps(
        {"evidence_region_hint": {"value": {"x": 1, "y": 2}, "confidence": "low"}}
    )

    results = _parse_response(
        raw_text, _schema_stub(), [ExtractionField(field_key="evidence_region_hint")]
    )

    assert json.loads(results[0].raw_value) == {"x": 1, "y": 2}


def test_scalar_field_values_are_unaffected() -> None:
    raw_text = json.dumps(
        {
            "invoice_number": {"value": "C1R27B00000604", "confidence": "high"},
            "grand_total_amount": {"value": 61308.0, "confidence": "high"},
        }
    )

    results = _parse_response(
        raw_text,
        _schema_stub(),
        [
            ExtractionField(field_key="invoice_number"),
            ExtractionField(field_key="grand_total_amount"),
        ],
    )

    by_key = {r.field_key: r for r in results}
    assert by_key["invoice_number"].raw_value == "C1R27B00000604"
    assert by_key["grand_total_amount"].raw_value == "61308.0"
