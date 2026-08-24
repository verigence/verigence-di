"""Pure tests for the live DI + Rules E2E harness configuration/assertions."""
from __future__ import annotations

import json

import pytest
from e2e.di_rules.models import RuleExpectations, load_scenario
from e2e.di_rules.runner import (
    validate_expected_fields,
    validate_rule_findings,
    values_match,
)

pytestmark = pytest.mark.no_docker


def test_values_match_normalises_ocr_friendly_text_and_numbers() -> None:
    assert values_match("  Abhishek   Khuntia ", "abhishek khuntia")
    assert values_match("₹1,250.00", 1250)
    assert values_match("100.009", 100, numeric_tolerance=0.01)
    assert not values_match("100.02", 100, numeric_tolerance=0.01)


def test_validate_expected_fields_reports_missing_and_mismatch() -> None:
    fields = [
        {"fieldKey": "pan_number", "currentValue": "DJFPK8448P"},
        {"fieldKey": "amount", "currentValue": "1,250.00"},
    ]
    assert validate_expected_fields(
        fields,
        {"pan_number": "djfpk8448p", "amount": 1250},
        numeric_tolerance=0.01,
    ) == []

    errors = validate_expected_fields(
        fields,
        {"pan_number": "WRONG", "date_of_birth": "1990-02-13"},
        numeric_tolerance=0.01,
    )
    assert len(errors) == 2
    assert "pan_number" in errors[0]
    assert "date_of_birth" in errors[1]


def test_validate_rule_findings_checks_summary_and_named_rules() -> None:
    analysis = {
        "summary": "RECONCILED",
        "findings": [
            {"ruleKey": "R1_AMOUNT_MATCH", "result": "PASS"},
            {"ruleKey": "R7_DUPLICATE_DETECTION", "result": "PASS"},
        ],
    }
    expected = RuleExpectations(
        expected_summary="RECONCILED",
        expected_results={
            "R1_AMOUNT_MATCH": "PASS",
            "R7_DUPLICATE_DETECTION": "PASS",
        },
    )
    assert validate_rule_findings(analysis, expected) == []

    errors = validate_rule_findings(
        analysis,
        RuleExpectations(
            expected_summary="DISCREPANCY",
            expected_results={"R1_AMOUNT_MATCH": "FAIL", "R2_UTR_SUFFIX_MATCH": "PASS"},
        ),
    )
    assert len(errors) == 3


def test_load_scenario_resolves_document_paths_relative_to_manifest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    manifest_dir = tmp_path / "scenario"
    manifest_dir.mkdir()
    manifest = manifest_dir / "case.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "reconcile-payment",
                "subject": {"displayName": "Test Customer", "subjectType": "PERSON"},
                "documents": [
                    {
                        "name": "receipt",
                        "documentTypeKey": "dealer_receipt",
                        "path": "../docs/receipt.pdf",
                        "expectFields": {"amount": 1000},
                    }
                ],
                "rules": {
                    "expectedSummary": "RECONCILED",
                    "expect": {"R1_AMOUNT_MATCH": "PASS"},
                },
            }
        ),
        encoding="utf-8",
    )

    scenario = load_scenario(manifest)

    assert scenario.name == "reconcile-payment"
    assert scenario.documents[0].path == (docs_dir / "receipt.pdf").resolve()
    assert scenario.documents[0].expected_fields == {"amount": 1000}
    assert scenario.rules is not None
    assert scenario.rules.expected_results == {"R1_AMOUNT_MATCH": "PASS"}


def test_load_scenario_rejects_duplicate_document_names(tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "duplicate.json"
    manifest.write_text(
        json.dumps(
            {
                "name": "bad",
                "subject": {"displayName": "Test"},
                "documents": [
                    {"name": "same", "documentTypeKey": "pan_card", "path": "a.jpg"},
                    {"name": "same", "documentTypeKey": "pan_card", "path": "b.jpg"},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate document name"):
        load_scenario(manifest)
