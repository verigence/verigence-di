"""Scenario model and JSON loader for the live DI + Rules E2E harness."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DocumentSpec:
    name: str
    document_type_key: str
    path: Path
    expected_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleExpectations:
    enabled: bool = True
    expected_summary: str | None = None
    expected_results: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    name: str
    subject_display_name: str
    subject_type: str
    documents: tuple[DocumentSpec, ...]
    rules: RuleExpectations | None
    numeric_tolerance: float = 0.01
    require_confirmed: bool = True


def _require_non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def load_scenario(path: str | Path) -> Scenario:
    """Load and validate a JSON E2E scenario.

    Document paths are resolved relative to the scenario JSON file, which makes
    committed scenarios portable across developer machines and CI runners.
    """
    scenario_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Scenario file does not exist: {scenario_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Scenario is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Scenario root must be a JSON object")

    name = _require_non_empty_string(raw.get("name"), "name")
    subject = raw.get("subject")
    if not isinstance(subject, dict):
        raise ValueError("subject must be an object")
    subject_display_name = _require_non_empty_string(
        subject.get("displayName"), "subject.displayName"
    )
    subject_type = _require_non_empty_string(
        subject.get("subjectType", "PERSON"), "subject.subjectType"
    ).upper()

    raw_documents = raw.get("documents")
    if not isinstance(raw_documents, list) or not raw_documents:
        raise ValueError("documents must contain at least one document")

    documents: list[DocumentSpec] = []
    names: set[str] = set()
    for index, item in enumerate(raw_documents):
        label = f"documents[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        document_name = _require_non_empty_string(item.get("name"), f"{label}.name")
        if document_name in names:
            raise ValueError(f"Duplicate document name: {document_name}")
        names.add(document_name)
        document_type_key = _require_non_empty_string(
            item.get("documentTypeKey"), f"{label}.documentTypeKey"
        )
        raw_path = _require_non_empty_string(item.get("path"), f"{label}.path")
        document_path = (scenario_path.parent / raw_path).resolve()
        expected_fields = item.get("expectFields", {})
        if not isinstance(expected_fields, dict):
            raise ValueError(f"{label}.expectFields must be an object")
        documents.append(
            DocumentSpec(
                name=document_name,
                document_type_key=document_type_key,
                path=document_path,
                expected_fields=dict(expected_fields),
            )
        )

    rules: RuleExpectations | None = None
    raw_rules = raw.get("rules")
    if raw_rules is not None:
        if not isinstance(raw_rules, dict):
            raise ValueError("rules must be an object")
        raw_expected_results = raw_rules.get("expect", {})
        if not isinstance(raw_expected_results, dict):
            raise ValueError("rules.expect must be an object")
        expected_results = {
            _require_non_empty_string(key, "rules.expect key"): _require_non_empty_string(
                value, f"rules.expect.{key}"
            ).upper()
            for key, value in raw_expected_results.items()
        }
        expected_summary_raw = raw_rules.get("expectedSummary")
        expected_summary = (
            _require_non_empty_string(expected_summary_raw, "rules.expectedSummary").upper()
            if expected_summary_raw is not None
            else None
        )
        rules = RuleExpectations(
            enabled=bool(raw_rules.get("enabled", True)),
            expected_summary=expected_summary,
            expected_results=expected_results,
        )

    numeric_tolerance_raw = raw.get("numericTolerance", 0.01)
    try:
        numeric_tolerance = float(numeric_tolerance_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("numericTolerance must be numeric") from exc
    if numeric_tolerance < 0:
        raise ValueError("numericTolerance cannot be negative")

    return Scenario(
        name=name,
        subject_display_name=subject_display_name,
        subject_type=subject_type,
        documents=tuple(documents),
        rules=rules,
        numeric_tolerance=numeric_tolerance,
        require_confirmed=bool(raw.get("requireConfirmed", True)),
    )
