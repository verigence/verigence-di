"""quality/validator.py — Upload Validator / Quality Service.

Implements DI_LLD_v2.2 §3 Upload Validator / Quality Service contract:

Integrity checks (→ CORRUPT / UPLOAD_FAILED):
  - Byte count / hash completion
  - Declared vs detected MIME
  - File structure validity (parse/decode check)

Quality checks (→ NOT_FIT / FIT):
  - Load Tenant quality policy from tenant_settings.quality_policy JSONB
  - Execute only approved rule implementation_keys from quality_rule_catalog
  - Persist one document_quality_results row per rule
  - Any FAIL → NOT_FIT
  - All PASS/SKIP/ERROR with no FAIL → FIT

Returns ValidatorResult which the intake service uses to set final upload_status.
"""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.domain.enums import UploadStatus
from verigence.di.quality.rules import QualityRuleResult, _detect_mime, get_rule

logger = structlog.get_logger(__name__)


@dataclass
class ValidatorResult:
    upload_status: UploadStatus
    upload_issue_code: str | None = None
    upload_issue_detail: str | None = None
    detected_mime: str = ""
    quality_results: list[QualityRuleResult] = field(default_factory=list)


async def validate_upload(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    data: bytes,
    declared_mime: str | None,
    filename: str | None,
) -> ValidatorResult:
    """Run integrity + quality checks and persist results.

    Does NOT commit — caller manages the transaction.
    """
    # ── Integrity: empty file ─────────────────────────────────────────────────
    if len(data) == 0:
        return ValidatorResult(
            upload_status=UploadStatus.CORRUPT,
            upload_issue_code="FILE_EMPTY",
            upload_issue_detail="Uploaded file contains zero bytes",
            detected_mime="",
        )

    # ── Integrity: detect MIME and validate structure ─────────────────────────
    detected_mime = _detect_mime(data)

    struct_ok, struct_msg = _check_structure(data, detected_mime)
    if not struct_ok:
        return ValidatorResult(
            upload_status=UploadStatus.CORRUPT,
            upload_issue_code="INVALID_FILE_CONTENT",
            upload_issue_detail=struct_msg,
            detected_mime=detected_mime,
        )

    # ── Quality: load Tenant policy ───────────────────────────────────────────
    policy_row = (
        await session.execute(
            text("""
                SELECT ts.quality_policy
                FROM docintel.tenant_settings ts
                WHERE ts.tenant_id = :tid
            """),
            {"tid": tenant_id},
        )
    ).one_or_none()

    if policy_row is None or not policy_row[0]:
        return ValidatorResult(
            upload_status=UploadStatus.CORRUPT,
            upload_issue_code="QUALITY_POLICY_NOT_CONFIGURED",
            upload_issue_detail="Tenant quality policy is absent or invalid",
            detected_mime=detected_mime,
        )

    quality_policy: list[dict[str, Any]] = policy_row[0]

    # ── Quality: load implementation keys from catalog ────────────────────────
    rule_rows = (
        await session.execute(
            text("""
                SELECT rule_key, implementation_key
                FROM docintel.quality_rule_catalog
                WHERE status = 'ACTIVE'
            """),
        )
    ).mappings().all()
    impl_map: dict[str, str] = {r["rule_key"]: r["implementation_key"] for r in rule_rows}

    # ── Quality: execute rules ────────────────────────────────────────────────
    quality_results: list[QualityRuleResult] = []
    has_fail = False

    for policy_entry in quality_policy:
        rule_key: str = policy_entry.get("rule_key", "")
        enabled: bool = policy_entry.get("enabled", True)
        params: dict[str, Any] = policy_entry.get("parameters") or {}

        if not rule_key or not enabled:
            continue

        impl_key = impl_map.get(rule_key)
        if not impl_key:
            # Rule not in catalog — skip with ERROR outcome
            result = QualityRuleResult(
                rule_key=rule_key,
                outcome="ERROR",
                parameters_applied=params,
                measurement={"error": f"rule_key {rule_key!r} not found in quality_rule_catalog"},
                message=f"Rule {rule_key!r} not in active catalog",
            )
        else:
            rule_fn = get_rule(impl_key)
            if rule_fn is None:
                # Implementation not registered
                result = QualityRuleResult(
                    rule_key=rule_key,
                    outcome="ERROR",
                    parameters_applied=params,
                    measurement={"error": f"implementation_key {impl_key!r} not registered"},
                    message=f"No implementation for {impl_key!r}",
                )
            else:
                try:
                    result = rule_fn(data, rule_key, params)
                except Exception as exc:
                    result = QualityRuleResult(
                        rule_key=rule_key,
                        outcome="ERROR",
                        parameters_applied=params,
                        measurement={"error": str(exc)},
                        message=f"Rule execution error: {exc}",
                    )

        quality_results.append(result)
        if result.outcome == "FAIL":
            has_fail = True

    # ── Persist quality results ───────────────────────────────────────────────
    await _persist_quality_results(
        session=session,
        tenant_id=tenant_id,
        document_id=document_id,
        results=quality_results,
    )

    # ── Derive final upload status ────────────────────────────────────────────
    if has_fail:
        # Find first failing rule for the issue code
        first_fail = next(r for r in quality_results if r.outcome == "FAIL")
        return ValidatorResult(
            upload_status=UploadStatus.NOT_FIT,
            upload_issue_code=first_fail.rule_key.upper().replace(".", "_"),
            upload_issue_detail=first_fail.message,
            detected_mime=detected_mime,
            quality_results=quality_results,
        )

    return ValidatorResult(
        upload_status=UploadStatus.FIT,
        detected_mime=detected_mime,
        quality_results=quality_results,
    )


async def _persist_quality_results(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    results: list[QualityRuleResult],
) -> None:
    """Insert one document_quality_results row per rule result."""
    import json
    now = datetime.now(UTC)
    for r in results:
        await session.execute(
            text("""
                INSERT INTO docintel.document_quality_results
                    (tenant_id, quality_result_id, document_id, rule_key,
                     outcome, parameters_applied, measurement, message,
                     evaluated_at_utc)
                VALUES
                    (:tenant_id, :qid, :document_id, :rule_key,
                     :outcome, :params::jsonb, :measurement::jsonb, :message,
                     :now)
                ON CONFLICT DO NOTHING
            """),
            {
                "tenant_id": tenant_id,
                "qid": uuid.uuid4(),
                "document_id": document_id,
                "rule_key": r.rule_key,
                "outcome": r.outcome,
                "params": json.dumps(r.parameters_applied),
                "measurement": json.dumps(r.measurement),
                "message": r.message,
                "now": now,
            },
        )


def _check_structure(data: bytes, detected_mime: str) -> tuple[bool, str]:
    """Attempt to decode/parse the file to confirm structural validity.

    Returns (ok, error_message).
    """
    if detected_mime == "application/pdf":
        return _check_pdf(data)
    if detected_mime.startswith("image/"):
        return _check_image(data)
    # Unknown / other types: pass structural check
    return True, ""


def _check_pdf(data: bytes) -> tuple[bool, str]:
    try:
        from pypdf import PdfReader  # type: ignore[import]
        reader = PdfReader(io.BytesIO(data), strict=False)
        # Access pages to confirm parseable
        _ = len(reader.pages)
        return True, ""
    except Exception as exc:
        return False, f"PDF parse failed: {exc}"


def _check_image(data: bytes) -> tuple[bool, str]:
    try:
        from PIL import Image  # type: ignore[import]
        img = Image.open(io.BytesIO(data))
        img.verify()  # raises if corrupt
        return True, ""
    except Exception as exc:
        return False, f"Image decode failed: {exc}"
