"""rules/runner.py — Normalization + Validation runner for the Processing Worker.

Implements DI_LLD_v2.2 §Processing Worker steps 11 and 12:

  Step 11 — normalize fields:
    For each extracted fact, run the ordered profile_field_normalizers in sequence.
    Each normalizer's output is fed as input to the next.
    Final normalized_value is stored on the extracted_fact row.

  Step 12 — run deterministic validation rules:
    For each extracted fact, run the ordered profile_field_validators.
    Persist one validation_results row per rule per fact.
    Return the list of results to the caller (confidence scoring uses it separately).

Caller: workers/job_runner.py (Step 10a).

This module does NOT commit transactions — the caller manages the session lifecycle.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.rules.normalizers import NormalizerResult, get_normalizer
from verigence.di.rules.schema_v2_validators import get_schema_v2_validator
from verigence.di.rules.validators import ValidatorRuleResult, get_validator

logger = structlog.get_logger(__name__)


# ── Data transfer objects ─────────────────────────────────────────────────────

@dataclass
class ExtractedFieldInput:
    """Represents one extracted fact as passed in by the job runner."""
    extracted_fact_id: uuid.UUID
    profile_field_id: uuid.UUID
    canonical_field_id: uuid.UUID
    raw_value_text: str | None
    found_status: str            # FOUND | NOT_FOUND | AMBIGUOUS | ERROR


@dataclass
class NormalizedFieldOutput:
    """Result of running normalization for one extracted fact."""
    extracted_fact_id: uuid.UUID
    canonical_field_id: uuid.UUID
    normalized_value: Any        # JSON-serialisable; None if not normalizable
    normalization_ok: bool
    normalization_message: str | None = None


@dataclass
class FieldValidationOutput:
    """Result of running validation rules for one extracted fact."""
    extracted_fact_id: uuid.UUID
    canonical_field_id: uuid.UUID
    results: list[ValidatorRuleResult] = field(default_factory=list)

    @property
    def has_error_fail(self) -> bool:
        """True when at least one ERROR-severity FAIL exists."""
        return any(
            r.result == "FAIL" and r.severity == "ERROR"
            for r in self.results
        )


@dataclass
class RunnerOutput:
    normalized: list[NormalizedFieldOutput] = field(default_factory=list)
    validated: list[FieldValidationOutput] = field(default_factory=list)


# ── Public entry points ───────────────────────────────────────────────────────

async def normalize_and_validate(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    processing_run_id: uuid.UUID,
    profile_id: uuid.UUID,
    extracted_fields: list[ExtractedFieldInput],
) -> RunnerOutput:
    """Run normalization (step 11) then validation (step 12) for all extracted fields.

    Persists:
    - Updated ``normalized_value`` on each ``extracted_facts`` row.
    - One ``validation_results`` row per rule per field.

    Returns RunnerOutput for the caller to use in confidence scoring.
    Does NOT commit — caller owns the transaction.
    """
    if not extracted_fields:
        return RunnerOutput()

    # ── Load normalization rule configs for this profile ──────────────────────
    norm_configs = await _load_normalizer_configs(session, profile_id)
    # ── Load validation rule configs for this profile ─────────────────────────
    val_configs = await _load_validator_configs(session, profile_id)

    output = RunnerOutput()
    now = datetime.now(UTC)

    for ef in extracted_fields:
        fid = ef.profile_field_id

        # ── Step 11: normalize ────────────────────────────────────────────────
        norm_result = _run_normalizers(
            raw=ef.raw_value_text,
            normalizer_configs=norm_configs.get(fid, []),
        )
        output.normalized.append(NormalizedFieldOutput(
            extracted_fact_id=ef.extracted_fact_id,
            canonical_field_id=ef.canonical_field_id,
            normalized_value=norm_result.normalized_value,
            normalization_ok=norm_result.ok,
            normalization_message=norm_result.message,
        ))

        # Persist normalized_value back onto the extracted_fact row
        await session.execute(
            text("""
                UPDATE docintel.extracted_facts
                SET normalized_value = CAST(:nv AS jsonb)
                WHERE tenant_id = :tid
                  AND extracted_fact_id = :fact_id
            """),
            {
                "tid": tenant_id,
                "fact_id": ef.extracted_fact_id,
                "nv": json.dumps(norm_result.normalized_value),
            },
        )

        # ── Step 12: validate ─────────────────────────────────────────────────
        field_val_output = FieldValidationOutput(
            extracted_fact_id=ef.extracted_fact_id,
            canonical_field_id=ef.canonical_field_id,
        )
        for vcfg in val_configs.get(fid, []):
            rule_key: str = vcfg["rule_key"]
            impl_key: str = vcfg["implementation_key"]
            params: dict[str, Any] = vcfg.get("parameters") or {}
            severity: str = vcfg.get("severity", "ERROR")

            val_fn = get_validator(impl_key) or get_schema_v2_validator(impl_key)
            if val_fn is None:
                vr = ValidatorRuleResult(
                    rule_key=rule_key,
                    result="ERROR",
                    severity="ERROR",
                    message=f"Validation implementation {impl_key!r} not registered",
                )
            else:
                # Override severity from profile config
                params_with_severity = {**params, "severity": severity}
                try:
                    vr = val_fn(norm_result.normalized_value, ef.raw_value_text, params_with_severity)
                    vr.rule_key = rule_key   # always use the catalog rule_key, not impl_key
                except Exception as exc:
                    vr = ValidatorRuleResult(
                        rule_key=rule_key,
                        result="ERROR",
                        severity="ERROR",
                        message=f"Validation rule execution error: {exc}",
                    )

            field_val_output.results.append(vr)

            # Persist validation_result row
            await session.execute(
                text("""
                    INSERT INTO docintel.validation_results
                        (tenant_id, validation_result_id, processing_run_id, document_id,
                         canonical_field_id, rule_key, result, severity, message, details,
                         created_at_utc)
                    VALUES
                        (:tid, :vrid, :run_id, :doc_id,
                         :canonical_field_id, :rule_key, :result, :severity,
                         :message, CAST(:details AS jsonb), :now)
                """),
                {
                    "tid": tenant_id,
                    "vrid": uuid.uuid4(),
                    "run_id": processing_run_id,
                    "doc_id": document_id,
                    "canonical_field_id": ef.canonical_field_id,
                    "rule_key": rule_key,
                    "result": vr.result,
                    "severity": vr.severity,
                    "message": vr.message,
                    "details": json.dumps(vr.details) if vr.details else "null",
                    "now": now,
                },
            )

        output.validated.append(field_val_output)
        log = logger.bind(
            tenant_id=tenant_id,
            document_id=str(document_id),
            extracted_fact_id=str(ef.extracted_fact_id),
        )
        log.debug(
            "field_normalized_and_validated",
            norm_ok=norm_result.ok,
            val_results=[r.result for r in field_val_output.results],
        )

    return output


# ── Private helpers ───────────────────────────────────────────────────────────

async def _load_normalizer_configs(
    session: AsyncSession,
    profile_id: uuid.UUID,
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Load ordered normalizer configs per profile_field_id for this profile."""
    rows = (
        await session.execute(
            text("""
                SELECT
                    pfn.profile_field_id,
                    pfn.sequence_no,
                    pfn.rule_key,
                    pfn.parameters,
                    nrc.implementation_key
                FROM docintel.profile_field_normalizers pfn
                JOIN docintel.normalization_rule_catalog nrc
                  ON nrc.rule_key = pfn.rule_key AND nrc.status = 'ACTIVE'
                JOIN docintel.extraction_profile_fields epf
                  ON epf.profile_field_id = pfn.profile_field_id
                WHERE epf.profile_id = :pid
                  AND epf.enabled = true
                ORDER BY pfn.profile_field_id, pfn.sequence_no
            """),
            {"pid": profile_id},
        )
    ).mappings().all()

    result: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in rows:
        fid = uuid.UUID(str(row["profile_field_id"]))
        result.setdefault(fid, []).append({
            "rule_key": row["rule_key"],
            "implementation_key": row["implementation_key"],
            "parameters": row["parameters"] or {},
        })
    return result


async def _load_validator_configs(
    session: AsyncSession,
    profile_id: uuid.UUID,
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Load ordered validator configs per profile_field_id for this profile."""
    rows = (
        await session.execute(
            text("""
                SELECT
                    pfv.profile_field_id,
                    pfv.sequence_no,
                    pfv.rule_key,
                    pfv.parameters,
                    pfv.severity,
                    vrc.implementation_key
                FROM docintel.profile_field_validators pfv
                JOIN docintel.validation_rule_catalog vrc
                  ON vrc.rule_key = pfv.rule_key AND vrc.status = 'ACTIVE'
                JOIN docintel.extraction_profile_fields epf
                  ON epf.profile_field_id = pfv.profile_field_id
                WHERE epf.profile_id = :pid
                  AND epf.enabled = true
                ORDER BY pfv.profile_field_id, pfv.sequence_no
            """),
            {"pid": profile_id},
        )
    ).mappings().all()

    result: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in rows:
        fid = uuid.UUID(str(row["profile_field_id"]))
        result.setdefault(fid, []).append({
            "rule_key": row["rule_key"],
            "implementation_key": row["implementation_key"],
            "parameters": row["parameters"] or {},
            "severity": row["severity"],
        })
    return result


def _run_normalizers(
    raw: str | None,
    normalizer_configs: list[dict[str, Any]],
) -> NormalizerResult:
    """Run ordered normalizers in a pipeline.

    Each normalizer's normalized value is serialized deterministically when it
    must become the text input of a subsequent normalizer.  The final return
    value, however, remains the *typed* output produced by the last normalizer.
    This is important for Schema V2 repeating arrays/objects: JSONB must receive
    an array/object, not a string representation of one.

    If no normalizers are configured, preserve the existing behaviour and return
    raw_value_text unchanged.  If any normalizer returns ok=False, the pipeline
    stops and returns that result.
    """
    if not normalizer_configs:
        return NormalizerResult(ok=True, normalized_value=raw)

    current_value: str | None = raw
    final_result = NormalizerResult(ok=True, normalized_value=raw)

    for cfg in normalizer_configs:
        impl_key: str = cfg["implementation_key"]
        params: dict[str, Any] = cfg.get("parameters") or {}

        norm_fn = get_normalizer(impl_key)
        if norm_fn is None:
            return NormalizerResult(
                ok=False,
                normalized_value=None,
                message=f"Normalizer {impl_key!r} not registered",
            )

        try:
            result = norm_fn(current_value, params)
        except Exception as exc:
            return NormalizerResult(
                ok=False,
                normalized_value=None,
                message=f"Normalizer {impl_key!r} raised: {exc}",
            )

        if not result.ok:
            return result

        final_result = result
        value = result.normalized_value
        if value is None:
            current_value = None
        elif isinstance(value, str):
            current_value = value
        elif isinstance(value, (dict, list, bool, int, float)):
            current_value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            current_value = str(value)

    return final_result
