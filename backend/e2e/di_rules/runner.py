"""Execution engine for live document upload -> extraction -> rule verification."""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import DiApiError, DiClient
from .models import RuleExpectations, Scenario

_TERMINAL_PROCESSING_STATUSES = {"PROCESSED", "FAILED"}


@dataclass(frozen=True)
class RuntimeConfig:
    base_url: str
    tenant_id: str
    token: str
    poll_timeout_seconds: float = 240.0
    poll_interval_seconds: float = 4.0
    request_timeout_seconds: float = 60.0
    report_path: Path | None = None


def _normalise_text(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if not isinstance(value, str):
        return None
    clean = re.sub(r"[^0-9.+-]", "", value.replace(",", ""))
    if not clean or clean in {"+", "-", ".", "+.", "-."}:
        return None
    try:
        number = float(clean)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def values_match(actual: object, expected: object, numeric_tolerance: float = 0.01) -> bool:
    """Compare extracted values with practical OCR/Document-AI normalization.

    Numeric values are compared numerically (so "1,250.00" matches 1250), while
    textual values ignore casing and repeated whitespace. Structured values fall
    back to normal Python equality.
    """
    if actual is None or expected is None:
        return actual is expected

    actual_number = _as_number(actual)
    expected_number = _as_number(expected)
    if actual_number is not None and expected_number is not None:
        return abs(actual_number - expected_number) <= numeric_tolerance

    if isinstance(actual, str) or isinstance(expected, str):
        return _normalise_text(actual) == _normalise_text(expected)
    return actual == expected


def validate_expected_fields(
    fields: list[dict[str, Any]],
    expected_fields: dict[str, Any],
    *,
    numeric_tolerance: float,
) -> list[str]:
    by_key = {
        str(field.get("fieldKey")): field
        for field in fields
        if field.get("fieldKey") is not None
    }
    errors: list[str] = []
    for field_key, expected in expected_fields.items():
        field = by_key.get(field_key)
        if field is None:
            errors.append(f"missing extracted field {field_key!r}")
            continue
        actual = field.get("currentValue")
        if not values_match(actual, expected, numeric_tolerance):
            errors.append(
                f"field {field_key!r}: expected {expected!r}, got {actual!r}"
            )
    return errors


def validate_rule_findings(
    analysis: dict[str, Any], expectations: RuleExpectations
) -> list[str]:
    errors: list[str] = []
    actual_summary = str(analysis.get("summary", "")).upper()
    if expectations.expected_summary and actual_summary != expectations.expected_summary:
        errors.append(
            f"rule summary: expected {expectations.expected_summary}, got {actual_summary or '<missing>'}"
        )

    findings = analysis.get("findings", [])
    if not isinstance(findings, list):
        return [*errors, "analysis response did not contain a findings array"]
    actual_by_key = {
        str(finding.get("ruleKey")): str(finding.get("result", "")).upper()
        for finding in findings
        if isinstance(finding, dict) and finding.get("ruleKey")
    }
    for rule_key, expected_result in expectations.expected_results.items():
        actual_result = actual_by_key.get(rule_key)
        if actual_result is None:
            errors.append(f"rule {rule_key}: finding is missing")
        elif actual_result != expected_result:
            errors.append(
                f"rule {rule_key}: expected {expected_result}, got {actual_result}"
            )
    return errors


def _poll_document(
    client: DiClient,
    config: RuntimeConfig,
    subject_id: str,
    document_id: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + config.poll_timeout_seconds
    last_status = ""
    while time.monotonic() < deadline:
        document = client.get_document(config.tenant_id, subject_id, document_id)
        status = str(document.get("processingStatus") or "").upper()
        if status != last_status:
            print(f"      processingStatus -> {status or '<missing>'}")
            last_status = status
        if status in _TERMINAL_PROCESSING_STATUSES:
            return document
        time.sleep(config.poll_interval_seconds)
    raise DiApiError(
        f"document {document_id} did not reach a terminal processing state within "
        f"{config.poll_timeout_seconds:g}s; last status={last_status or '<missing>'}"
    )


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def run_scenario(scenario: Scenario, config: RuntimeConfig) -> dict[str, Any]:
    """Run a complete live scenario and return its machine-readable report."""
    started = datetime.now(UTC)
    report: dict[str, Any] = {
        "scenario": scenario.name,
        "startedAtUtc": started.isoformat(),
        "baseUrl": config.base_url.rstrip("/"),
        "tenantId": config.tenant_id,
        "subject": {
            "displayName": scenario.subject_display_name,
            "subjectType": scenario.subject_type,
        },
        "documents": [],
        "analysis": None,
        "errors": [],
        "passed": False,
    }

    print("=" * 78)
    print(f"Verigence DI + Rule Engine E2E :: {scenario.name}")
    print("=" * 78)
    print(f"API      : {config.base_url.rstrip('/')}")
    print(f"Tenant   : {config.tenant_id}")
    print(f"Subject  : {scenario.subject_display_name}")
    print(f"Documents: {len(scenario.documents)}")

    try:
        with DiClient(
            base_url=config.base_url,
            token=config.token,
            request_timeout=config.request_timeout_seconds,
        ) as client:
            health = client.health()
            print(f"[PASS] health/ready :: environment={health.get('environment', '?')}")

            subject = client.create_subject(
                config.tenant_id,
                display_name=scenario.subject_display_name,
                subject_type=scenario.subject_type,
            )
            subject_id = str(subject["subjectId"])
            report["subject"]["subjectId"] = subject_id
            print(f"[PASS] subject created :: {subject_id}")

            processed_document_ids: list[str] = []
            for index, spec in enumerate(scenario.documents, start=1):
                print("-" * 78)
                print(
                    f"[{index}/{len(scenario.documents)}] {spec.name} :: "
                    f"{spec.document_type_key} :: {spec.path}"
                )
                document_report: dict[str, Any] = {
                    "name": spec.name,
                    "documentTypeKey": spec.document_type_key,
                    "path": str(spec.path),
                    "expectedFields": spec.expected_fields,
                    "fields": [],
                    "errors": [],
                }
                report["documents"].append(document_report)

                upload = client.upload_document(
                    config.tenant_id,
                    subject_id,
                    document_type_key=spec.document_type_key,
                    path=spec.path,
                )
                document_report["upload"] = upload
                document_id = str(upload["documentId"])
                document_report["documentId"] = document_id

                upload_status = str(upload.get("uploadStatus") or "").upper()
                if upload.get("errorCode") != "000" or upload_status != "ACCEPTED":
                    raise DiApiError(
                        f"{spec.name}: upload rejected errorCode={upload.get('errorCode')} "
                        f"status={upload_status} message={upload.get('errorMessage')}"
                    )
                print(f"[PASS] upload accepted :: {document_id}")

                document = _poll_document(client, config, subject_id, document_id)
                document_report["document"] = document
                processing_status = str(document.get("processingStatus") or "").upper()
                if processing_status != "PROCESSED":
                    raise DiApiError(
                        f"{spec.name}: extraction failed; processingStatus={processing_status}"
                    )
                print(
                    f"[PASS] extraction processed :: confidence={document.get('confidenceScore')} "
                    f"confirmation={document.get('confirmationStatus')}"
                )

                confirmation_status = str(document.get("confirmationStatus") or "").upper()
                if scenario.require_confirmed and confirmation_status != "CONFIRMED":
                    raise DiApiError(
                        f"{spec.name}: expected CONFIRMED extraction but got "
                        f"{confirmation_status or '<missing>'}"
                    )

                fields: list[dict[str, Any]] = []
                if confirmation_status == "CONFIRMED":
                    fields = client.get_fields(config.tenant_id, subject_id, document_id)
                    document_report["fields"] = fields
                    print(f"[PASS] extracted fields available :: {len(fields)} field(s)")
                    for field in fields:
                        print(
                            f"       {field.get('fieldKey')}: {field.get('currentValue')!r} "
                            f"(confidence={field.get('confidenceScore')})"
                        )

                field_errors = validate_expected_fields(
                    fields,
                    spec.expected_fields,
                    numeric_tolerance=scenario.numeric_tolerance,
                )
                if field_errors:
                    document_report["errors"].extend(field_errors)
                    raise DiApiError(f"{spec.name}: " + "; ".join(field_errors))
                if spec.expected_fields:
                    print(f"[PASS] expected field assertions :: {len(spec.expected_fields)}")

                processed_document_ids.append(document_id)

            if scenario.rules and scenario.rules.enabled:
                print("-" * 78)
                print(f"Running reconciliation rules for {len(processed_document_ids)} document(s)")
                analysis = client.analyse(config.tenant_id, processed_document_ids)
                report["analysis"] = analysis
                print(f"Rule summary: {analysis.get('summary')}")
                for finding in analysis.get("findings", []):
                    if isinstance(finding, dict):
                        print(
                            f"  {finding.get('ruleKey')}: {finding.get('result')} :: "
                            f"{finding.get('detail')}"
                        )
                rule_errors = validate_rule_findings(analysis, scenario.rules)
                if rule_errors:
                    raise DiApiError("rule verification failed: " + "; ".join(rule_errors))
                print("[PASS] rule expectations verified")

            report["passed"] = True
    except Exception as exc:  # noqa: BLE001 - live harness must persist the failure report
        message = str(exc)
        report["errors"].append(message)
        print(f"[FAIL] {message}")

    report["finishedAtUtc"] = datetime.now(UTC).isoformat()
    report["durationSeconds"] = round(
        (datetime.fromisoformat(report["finishedAtUtc"]) - started).total_seconds(), 3
    )
    if config.report_path is not None:
        _write_report(config.report_path, report)
        print(f"Report   : {config.report_path}")
    print("=" * 78)
    print("RESULT   : PASS" if report["passed"] else "RESULT   : FAIL")
    print("=" * 78)
    return report
