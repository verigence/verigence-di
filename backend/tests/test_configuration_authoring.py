from __future__ import annotations

import pytest

from verigence.di.document_ai.schema_authoring import validate_schema_proposal


def _proposal() -> dict:
    return {
        "documentTypeKey": "no_dues_certificate",
        "displayName": "No Dues Certificate",
        "description": "Dealer settlement certificate",
        "physicalFormType": "PRINTABLE",
        "fields": [
            {
                "fieldKey": "customer_name",
                "displayName": "Customer Name",
                "dataType": "STRING",
                "required": False,
                "evidenceLabels": ["Customer Name"],
                "aliases": ["Customer Name"],
                "extractionInstruction": "Extract the customer name exactly as printed.",
                "scoreIncluded": False,
                "scoreWeight": 0,
                "derived": False,
            }
        ],
        "warnings": [],
    }


def test_authoring_validator_hardens_extraction_instruction() -> None:
    result = validate_schema_proposal(_proposal())

    field = result["fields"][0]
    assert field["fieldKey"] == "customer_name"
    assert field["derived"] is False
    assert "Never infer, calculate, reconstruct, or guess" in field["extractionInstruction"]
    assert result["authoringPolicy"]["manualApprovalRequired"] is True
    assert result["authoringPolicy"]["directDatabaseWriteByModel"] is False


def test_authoring_validator_rejects_derived_field() -> None:
    payload = _proposal()
    payload["fields"][0]["derived"] = True

    with pytest.raises(ValueError, match="derived/calculated"):
        validate_schema_proposal(payload)


def test_authoring_validator_rejects_field_without_visible_evidence_anchor() -> None:
    payload = _proposal()
    payload["fields"][0]["evidenceLabels"] = []

    with pytest.raises(ValueError, match="no evidenceLabels"):
        validate_schema_proposal(payload)


def test_authoring_validator_rejects_duplicate_field_keys() -> None:
    payload = _proposal()
    payload["fields"].append(dict(payload["fields"][0]))

    with pytest.raises(ValueError, match="Duplicate fieldKey"):
        validate_schema_proposal(payload)


def test_authoring_validator_rejects_invalid_document_key() -> None:
    payload = _proposal()
    payload["documentTypeKey"] = "No Dues Certificate"

    with pytest.raises(ValueError, match="lower snake_case"):
        validate_schema_proposal(payload)
