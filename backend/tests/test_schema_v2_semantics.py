from __future__ import annotations

import re
from pathlib import Path

import pytest

from verigence.di.document_ai.schemas import get_schema

pytestmark = pytest.mark.no_docker

# Keep this suite on the normal PR CI path after legacy migration compatibility repairs.
_MAPPING = Path(__file__).resolve().parents[2] / "docs" / "schema-v2" / "WAVE1_SEMANTIC_MAPPING_v0.1.md"
_PACKAGED_MAPPING = (
    Path(__file__).resolve().parents[1]
    / "schema-v2-assets"
    / "WAVE1_SEMANTIC_MAPPING_v0.1.md"
)


def _rows(section: str) -> list[tuple[str, str, str, str, str]]:
    text = _MAPPING.read_text(encoding="utf-8")
    match = re.search(rf"## {re.escape(section)}\n\n(.*?)(?=\n## |\Z)", text, re.S)
    assert match is not None, section
    result: list[tuple[str, str, str, str, str]] = []
    for line in match.group(1).splitlines():
        if not line.startswith("| `"):
            continue
        columns = [part.strip() for part in line.strip("|").split("|")]
        result.append(
            (
                columns[0].strip("` "),
                columns[1].strip("` "),
                columns[2].strip("` "),
                columns[3].strip("` "),
                columns[4].strip("` "),
            )
        )
    return result


def test_deployed_wave1_mapping_asset_matches_frozen_design() -> None:
    assert _PACKAGED_MAPPING.read_bytes() == _MAPPING.read_bytes()


def test_wave1_frozen_mapping_has_expected_extraction_population() -> None:
    all_rows = (
        _rows("GST_CERTIFICATE")
        + _rows("CORPORATE_ID")
        + _rows("BANK_APPROVAL_LETTER")
        + _rows("VALUATION_REPORT")
    )
    extraction_rows = [row for row in all_rows if row[3] not in {"REFERENCE", "DERIVED"}]

    assert len(extraction_rows) == 113


def test_same_chassis_canonical_is_role_isolated_across_wave1() -> None:
    bank_chassis = next(row for row in _rows("BANK_APPROVAL_LETTER") if row[0] == "chassis_number")
    valuation_chassis = next(row for row in _rows("VALUATION_REPORT") if row[0] == "chassis_number")

    assert bank_chassis[1] == "chassis_number"
    assert valuation_chassis[1] == "chassis_number"
    assert bank_chassis[2] == "SUBJECT_VEHICLE"
    assert valuation_chassis[2] == "EXCHANGE_VEHICLE"
    assert bank_chassis[2] != valuation_chassis[2]


def test_reference_and_derived_categories_are_not_gemini_outputs() -> None:
    bank_keys = {field.key for field in get_schema("bank_approval_letter").fields}
    valuation_keys = {field.key for field in get_schema("valuation_report").fields}

    assert "financier_type" not in bank_keys
    assert "valuation_platform" not in valuation_keys
    assert "financier_name" in bank_keys
    assert "platform_name_as_printed" in valuation_keys


def test_presence_observations_remain_boolean_schema_fields() -> None:
    bank_fields = {field.key: field for field in get_schema("bank_approval_letter").fields}
    valuation_fields = {field.key: field for field in get_schema("valuation_report").fields}

    assert bank_fields["signature_present"].field_type == "boolean"
    assert bank_fields["insurance_funded"].field_type == "boolean"
    assert valuation_fields["approval_signature_present"].field_type == "boolean"
    assert valuation_fields["offer_value_handwritten_or_amended"].field_type == "boolean"
