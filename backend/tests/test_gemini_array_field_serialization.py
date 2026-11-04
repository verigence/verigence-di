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


def test_a_bare_array_value_is_kept_not_dropped() -> None:
    """Live 2026-11-05: an NDC's rows came back as a bare array for line_items
    (not {"value": [...]}) and were stored as not found on every read."""
    rows = [{"particulars_raw": "Vehicle cost", "debit_amount": 2950000},
            {"particulars_raw": "FINANCE D/O 8537", "credit_amount": 2563740}]
    raw_text = json.dumps({"line_items": rows, "total_cost": {"value": 3241050, "confidence": "high"}})

    results = _parse_response(
        raw_text, _schema_stub(), [ExtractionField(field_key="line_items"), ExtractionField(field_key="total_cost")]
    )

    by_key = {r.field_key: r for r in results}
    assert by_key["line_items"].found_status == FoundStatus.FOUND
    assert by_key["line_items"].normalized_value == rows and json.loads(by_key["line_items"].raw_value) == rows
    assert by_key["total_cost"].normalized_value == 3241050


def test_a_bare_scalar_is_kept_and_a_bare_boolean_or_null_is_not() -> None:
    raw_text = json.dumps({"invoice_number": "INV27C001593", "flag": True, "missing": None})
    results = _parse_response(
        raw_text, _schema_stub(),
        [ExtractionField(field_key="invoice_number"), ExtractionField(field_key="flag"),
         ExtractionField(field_key="missing")],
    )
    by_key = {r.field_key: r for r in results}
    assert by_key["invoice_number"].found_status == FoundStatus.FOUND
    assert by_key["invoice_number"].normalized_value == "INV27C001593"
    assert by_key["flag"].found_status == FoundStatus.NOT_FOUND
    assert by_key["missing"].found_status == FoundStatus.NOT_FOUND

