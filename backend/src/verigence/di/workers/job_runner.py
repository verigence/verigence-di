"""workers/job_runner.py — Processing Worker job execution (all 17 LLD steps).

Implements DI_LLD_v2.2 §Processing Worker, one full processing run per claimed job:

  Step 1  — claim job (done by processor.py before calling us)
  Step 2  — create immutable Processing Run
  Step 3  — set Document PROCESSING
  Step 4  — form classification candidate set (DI_CLASSIFICATION_v2.2)
  Step 5  — persist candidate snapshot on Processing Run
  Step 6  — zero candidates → NON_RETRYABLE CLASSIFICATION_NO_CANDIDATES
  Step 7  — call DocumentAIAdapter.classify()
  Step 8  — accept single winner above acceptance_score; else NON_RETRYABLE CLASSIFICATION_AMBIGUOUS
  Step 9  — use profileId from candidate snapshot (do not re-resolve)
  Step 10 — call DocumentAIAdapter.extract()
  Step 11 — normalize fields (rules.runner)
  Step 12 — run deterministic validation rules (rules.runner)
  Step 13 — persist immutable extracted_facts + MACHINE document_field_values
  Step 14 — calculate Document confidence score
  Step 15 — persist verification_threshold_applied=90.00
  Step 16 — derive Human Verification Status
  Step 17 — set PROCESSED + CONFIRMED

Schema V2 adds provider-facing ``extraction_key`` support and role-safe handling
without replacing this pipeline.  The canonical field remains the stored business
vocabulary; the extraction key is only the provider contract key.  Deterministic
normalization/validation failures force human review rather than being silently
ignored.

All DB mutations go through the session passed in. Caller (processor.py) owns the
session lifecycle and calls commit / rollback / fail_job on error.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.document_ai.adapter import (
    ClassificationCandidate,
    DocumentAIAdapter,
    ExtractionField,
    FieldResult,
)
from verigence.di.domain.enums import FoundStatus, HumanVerificationStatus
from verigence.di.domain.scoring import ScoredField, calculate_confidence_score
from verigence.di.repositories.search_index import upsert_search_index
from verigence.di.rules.runner import ExtractedFieldInput, normalize_and_validate

logger = structlog.get_logger(__name__)

PIPELINE_VERSION = "2.2.0-schema-v2"


# ── Domain exceptions ─────────────────────────────────────────────────────────

class ProcessingError(Exception):
    """Base class for all processing failures."""
    def __init__(self, code: str, detail: str, retryable: bool) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class RetryableError(ProcessingError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail, retryable=True)


class NonRetryableError(ProcessingError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail, retryable=False)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class JobRunResult:
    success: bool
    processing_run_id: uuid.UUID
    confidence_score: Decimal | None = None
    human_verification_status: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    retryable: bool = False


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_processing_job(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    processing_job_id: uuid.UUID,
    job_type: str,
    correlation_id: str,
    ai_adapter: DocumentAIAdapter,
) -> JobRunResult:
    """Execute all 17 LLD processing steps for one claimed job.

    Returns JobRunResult. Does NOT commit or rollback — caller owns that.
    On ProcessingError, returns a failure result so caller can handle cleanup.
    """
    log = logger.bind(
        tenant_id=tenant_id,
        document_id=str(document_id),
        processing_job_id=str(processing_job_id),
        correlation_id=correlation_id,
    )
    _job_start = time.monotonic()

    # ── Step 2: Create immutable Processing Run ───────────────────────────────
    processing_run_id = uuid.uuid4()
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.processing_runs
                (tenant_id, processing_run_id, processing_job_id, document_id,
                 correlation_id, run_type, run_status, pipeline_version,
                 started_at_utc, created_at_utc)
            VALUES
                (:tid, :run_id, :job_id, :doc_id,
                 :corr, :run_type, 'RUNNING', :pipeline_version,
                 :now, :now)
        """),
        {
            "tid": tenant_id,
            "run_id": processing_run_id,
            "job_id": processing_job_id,
            "doc_id": document_id,
            "corr": correlation_id,
            "run_type": job_type,
            "pipeline_version": PIPELINE_VERSION,
            "now": now,
        },
    )
    log = log.bind(processing_run_id=str(processing_run_id))
    log.info("processing_run_started")

    try:
        result = await _execute_steps(
            session=session,
            tenant_id=tenant_id,
            document_id=document_id,
            processing_job_id=processing_job_id,
            processing_run_id=processing_run_id,
            job_type=job_type,
            correlation_id=correlation_id,
            ai_adapter=ai_adapter,
            log=log,
            started_at=now,
            job_start=_job_start,
        )
    except ProcessingError as exc:
        # Mark the Processing Run as FAILED
        await _fail_processing_run(
            session=session,
            tenant_id=tenant_id,
            processing_run_id=processing_run_id,
            error_class="RETRYABLE" if exc.retryable else "NON_RETRYABLE",
            error_code=exc.code,
            error_detail=exc.detail,
        )
        log.warning("processing_run_failed",
                    retryable=exc.retryable,
                    error_code=exc.code,
                    error_detail=exc.detail)
        return JobRunResult(
            success=False,
            processing_run_id=processing_run_id,
            error_code=exc.code,
            error_detail=exc.detail,
            retryable=exc.retryable,
        )
    except Exception as exc:
        # Unexpected error — treat as retryable
        err_detail = f"Unexpected worker error: {exc}"
        await _fail_processing_run(
            session=session,
            tenant_id=tenant_id,
            processing_run_id=processing_run_id,
            error_class="RETRYABLE",
            error_code="WORKER_INTERNAL_ERROR",
            error_detail=err_detail,
        )
        log.exception("processing_run_unexpected_error")
        return JobRunResult(
            success=False,
            processing_run_id=processing_run_id,
            error_code="WORKER_INTERNAL_ERROR",
            error_detail=err_detail,
            retryable=True,
        )

    return result


# ── Step execution ────────────────────────────────────────────────────────────

async def _execute_steps(
    *,
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
    processing_job_id: uuid.UUID,
    processing_run_id: uuid.UUID,
    job_type: str,
    correlation_id: str,
    ai_adapter: DocumentAIAdapter,
    log: Any,
    started_at: datetime,
    job_start: float,
) -> JobRunResult:
    """All 17 processing steps — raises ProcessingError on failure."""
    now = started_at

    # ── Step 3: Set Document PROCESSING ──────────────────────────────────────
    await session.execute(
        text("""
            UPDATE docintel.documents
            SET processing_status = 'PROCESSING',
                current_processing_run_id = :run_id,
                updated_at_utc = :now
            WHERE tenant_id = :tid AND document_id = :doc_id
        """),
        {"tid": tenant_id, "doc_id": document_id,
         "run_id": processing_run_id, "now": now},
    )

    # ── Step 4: Form classification candidate set ─────────────────────────────
    tenant_row = await _get_tenant_settings(session, tenant_id)
    acceptance_score = Decimal(str(tenant_row["classification_acceptance_score"]))
    hint_key = await _get_document_hint_key(session, tenant_id, document_id)

    candidates = await _form_candidate_set(session, tenant_id)
    log.info(
        "classification_candidates",
        candidate_count=len(candidates),
        candidate_keys=[c["document_type_key"] for c in candidates],
        hint_key=hint_key,
    )

    # ── Step 5: Persist candidate snapshot ───────────────────────────────────
    # Need requirement context for flags
    subject_id = await _get_document_subject_id(session, tenant_id, document_id)
    req_keys = await _get_requirement_keys(session, tenant_id, subject_id) if subject_id else set()

    candidate_snapshot = _build_candidate_snapshot(candidates, req_keys, hint_key)
    await session.execute(
        text("""
            UPDATE docintel.processing_runs
            SET classification_candidate_set = CAST(:cs AS jsonb)
            WHERE tenant_id = :tid AND processing_run_id = :run_id
        """),
        {
            "tid": tenant_id,
            "run_id": processing_run_id,
            "cs": json.dumps(candidate_snapshot),
        },
    )

    # ── Step 6: Zero candidates check ────────────────────────────────────────
    if not candidates:
        raise NonRetryableError(
            "CLASSIFICATION_NO_CANDIDATES",
            "No ACTIVE Document Types with a PUBLISHED Extraction Profile exist for this Tenant",
        )

    # ── Step 7: Call classifier ───────────────────────────────────────────────
    artifact_bytes, mime_type = await _load_original_artifact(session, tenant_id, document_id)
    candidate_keys = [c["document_type_key"] for c in candidates]

    classify_invocation_id = uuid.uuid4()
    await _insert_invocation(
        session, tenant_id, classify_invocation_id, processing_run_id,
        correlation_id, "CLASSIFICATION", ai_adapter.adapter_key, outcome="STARTED",
    )

    try:
        classify_result = await ai_adapter.classify(
            artifact_bytes=artifact_bytes,
            mime_type=mime_type,
            candidate_type_keys=candidate_keys,
            hint=hint_key,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        await _update_invocation(session, tenant_id, classify_invocation_id,
                                 "FAILED", error_detail=str(exc))
        raise RetryableError("CLASSIFICATION_PROVIDER_ERROR", str(exc)) from exc

    await _update_invocation(
        session, tenant_id, classify_invocation_id, "SUCCESS",
        provider_request_id=classify_result.provider_request_id,
        usage_metrics=classify_result.usage_metrics,
    )

    classifications: list[ClassificationCandidate] = classify_result.results  # type: ignore[assignment]

    # ── Step 8: Accept single winner ─────────────────────────────────────────
    accepted = _accept_classification(classifications, candidates, acceptance_score)
    if accepted is None:
        scores = [(c["document_type_key"], c.get("classification_score")) for c in candidates]
        log.warning(
            "classification_failed",
            reason="AMBIGUOUS",
            candidate_keys=[c["document_type_key"] for c in candidates],
            scores=scores,
        )
        raise NonRetryableError(
            "CLASSIFICATION_AMBIGUOUS",
            f"No single candidate met acceptance score {acceptance_score}; scores: {scores}",
        )

    # Find runner-up for diagnostics
    others = [c for c in classifications if c.document_type_key != accepted["document_type_key"]]
    runner_up = max(others, key=lambda c: float(c.confidence or 0), default=None)
    log.info(
        "classification_result",
        accepted_type_key=accepted["document_type_key"],
        acceptance_score=str(acceptance_score),
        profile_id=str(accepted["profile_id"]),
        runner_up_key=runner_up.document_type_key if runner_up else None,
        runner_up_score=str(runner_up.confidence) if runner_up else None,
    )

    # ── Step 9: Use the profileId from the snapshotted candidate ─────────────
    profile_id = uuid.UUID(str(accepted["profile_id"]))
    document_type_id = uuid.UUID(str(accepted["document_type_id"]))

    # Persist document classification row + update extraction_profile_id on run
    await _persist_classifications(
        session, tenant_id, processing_run_id, document_id,
        classifications, accepted, profile_id,
    )
    await session.execute(
        text("""
            UPDATE docintel.processing_runs
            SET extraction_profile_id = :pid
            WHERE tenant_id = :tid AND processing_run_id = :run_id
        """),
        {"tid": tenant_id, "run_id": processing_run_id, "pid": profile_id},
    )
    # Set document_type_id on the document row
    await session.execute(
        text("""
            UPDATE docintel.documents
            SET document_type_id = :dtid, updated_at_utc = :now
            WHERE tenant_id = :tid AND document_id = :doc_id
        """),
        {"tid": tenant_id, "doc_id": document_id, "dtid": document_type_id, "now": now},
    )

    # ── Step 10: Extract fields ───────────────────────────────────────────────
    profile_fields = await _load_profile_fields(session, profile_id)
    if not profile_fields:
        raise NonRetryableError(
            "EXTRACTION_PROFILE_EMPTY",
            f"Extraction Profile {profile_id} has no enabled fields",
        )

    extract_fields = [
        ExtractionField(
            field_key=_provider_field_key(pf),
            aliases=pf.get("aliases") or [],
            instruction=pf.get("extraction_instruction"),
        )
        for pf in profile_fields
    ]

    # D22: fetch physical_form_type for the accepted document type
    accepted_document_type_key: str = accepted["document_type_key"]
    physical_form_type_for_extract = await _get_physical_form_type(
        session, tenant_id, document_type_id,
    )

    log.info(
        "extraction_request",
        document_type_key=accepted_document_type_key,
        physical_form_type=physical_form_type_for_extract,
        schema_field_count=len(extract_fields),
        file_bytes=len(artifact_bytes),
        file_mime=mime_type,
    )
    _extract_start = time.monotonic()

    extract_invocation_id = uuid.uuid4()
    await _insert_invocation(
        session, tenant_id, extract_invocation_id, processing_run_id,
        correlation_id, "VISION_EXTRACTION", ai_adapter.adapter_key, outcome="STARTED",
    )

    try:
        extract_result = await ai_adapter.extract(
            artifact_bytes=artifact_bytes,
            mime_type=mime_type,
            fields=extract_fields,
            correlation_id=correlation_id,
            physical_form_type=physical_form_type_for_extract,
            document_type_key=accepted_document_type_key,
        )
    except Exception as exc:
        await _update_invocation(session, tenant_id, extract_invocation_id,
                                 "FAILED", error_detail=str(exc))
        raise RetryableError("EXTRACTION_PROVIDER_ERROR", str(exc)) from exc

    await _update_invocation(
        session, tenant_id, extract_invocation_id, "SUCCESS",
        provider_request_id=extract_result.provider_request_id,
        usage_metrics=extract_result.usage_metrics,
    )

    field_results: list[FieldResult] = extract_result.results  # type: ignore[assignment]
    _extract_ms = round((time.monotonic() - _extract_start) * 1000, 1)
    _fields_found = sum(1 for fr in field_results if fr.found_status == FoundStatus.FOUND)
    _fields_null = sum(1 for fr in field_results if fr.found_status != FoundStatus.FOUND)
    _fields_low = sum(1 for fr in field_results
                      if fr.confidence is not None and fr.confidence <= Decimal("40.00"))
    log.info(
        "extraction_result",
        document_type_key=accepted_document_type_key,
        physical_form_type=physical_form_type_for_extract,
        fields_extracted=_fields_found,
        fields_null=_fields_null,
        fields_low_confidence=_fields_low,
        duration_ms=_extract_ms,
    )
    for fr in field_results:
        log.debug(
            "extraction_field_detail",
            document_type_key=accepted_document_type_key,
            field_key=fr.field_key,
            raw_value=fr.raw_value,
            normalized_value=fr.normalized_value,
            found_status=fr.found_status.value,
            confidence=str(fr.confidence) if fr.confidence is not None else None,
        )

    # ── Step 11 + 12: Normalize + Validate ───────────────────────────────────
    # First persist the raw extracted_facts, then normalize them.
    # Result lookup is provider-key based; persistence is canonical-field based.
    field_result_map: dict[str, FieldResult] = {fr.field_key: fr for fr in field_results}

    extracted_inputs: list[ExtractedFieldInput] = []
    fact_id_map: dict[uuid.UUID, uuid.UUID] = {}  # profile_field_id → extracted_fact_id

    for pf in profile_fields:
        provider_key = _provider_field_key(pf)
        fr = field_result_map.get(provider_key)
        profile_field_id = uuid.UUID(str(pf["profile_field_id"]))
        fact_id = uuid.uuid4()
        fact_id_map[profile_field_id] = fact_id

        found_status = fr.found_status.value if fr else FoundStatus.NOT_FOUND.value
        raw_value = fr.raw_value if fr else None
        confidence = float(fr.confidence) if fr and fr.confidence is not None else None

        await session.execute(
            text("""
                INSERT INTO docintel.extracted_facts
                    (tenant_id, extracted_fact_id, processing_run_id, document_id,
                     profile_field_id, canonical_field_id, found_status,
                     raw_value_text, confidence_score, page_no, evidence_region,
                     invocation_id, created_at_utc)
                VALUES
                    (:tid, :fact_id, :run_id, :doc_id,
                     :pf_id, :cf_id, :found_status,
                     :raw_value, :confidence, :page_no, CAST(:evidence_region AS jsonb),
                     :inv_id, :now)
            """),
            {
                "tid": tenant_id,
                "fact_id": fact_id,
                "run_id": processing_run_id,
                "doc_id": document_id,
                "pf_id": profile_field_id,
                "cf_id": pf["canonical_field_id"],
                "found_status": found_status,
                "raw_value": raw_value,
                "confidence": confidence,
                "page_no": fr.page_no if fr else None,
                "evidence_region": json.dumps(fr.evidence_region) if fr and fr.evidence_region else "null",
                "inv_id": extract_invocation_id,
                "now": now,
            },
        )

        extracted_inputs.append(ExtractedFieldInput(
            extracted_fact_id=fact_id,
            profile_field_id=profile_field_id,
            canonical_field_id=uuid.UUID(str(pf["canonical_field_id"])),
            raw_value_text=raw_value,
            found_status=found_status,
        ))

    runner_output = await normalize_and_validate(
        session=session,
        tenant_id=tenant_id,
        document_id=document_id,
        processing_run_id=processing_run_id,
        profile_id=profile_id,
        extracted_fields=extracted_inputs,
    )

    # ── Step 13: Persist MACHINE document_field_values ────────────────────────
    # Build a system actor row if not present (worker writes as system actor)
    system_actor_id = "worker.system"
    await _ensure_system_actor(session, tenant_id, system_actor_id)

    norm_map = {n.extracted_fact_id: n for n in runner_output.normalized}

    for pf in profile_fields:
        provider_key = _provider_field_key(pf)
        profile_field_id = uuid.UUID(str(pf["profile_field_id"]))
        fact_id = fact_id_map[profile_field_id]
        norm = norm_map.get(fact_id)
        fr = field_result_map.get(provider_key)

        norm_value = norm.normalized_value if norm else (fr.normalized_value if fr else None)
        conf_score = float(fr.confidence) if fr and fr.confidence is not None else None

        await session.execute(
            text("""
                INSERT INTO docintel.document_field_values
                    (tenant_id, document_field_value_id, document_id, canonical_field_id,
                     current_value, value_source, source_extracted_fact_id,
                     confidence_score, accepted_by_actor_id, accepted_at_utc,
                     version_no, is_current, created_at_utc)
                VALUES
                    (:tid, :dfv_id, :doc_id, :cf_id,
                     CAST(:cur_val AS jsonb), 'MACHINE', :fact_id,
                     :conf, :actor_id, :now,
                     1, true, :now)
                ON CONFLICT DO NOTHING
            """),
            {
                "tid": tenant_id,
                "dfv_id": uuid.uuid4(),
                "doc_id": document_id,
                "cf_id": pf["canonical_field_id"],
                "cur_val": json.dumps(norm_value),
                "fact_id": fact_id,
                "conf": conf_score,
                "actor_id": system_actor_id,
                "now": now,
            },
        )

    # ── Steps 11+12: Log normalization + validation summaries ────────────────
    _norm_errors = [n for n in runner_output.normalized if not n.normalization_ok]
    _val_failed = [v for v in runner_output.validated if v.has_error_fail]
    log.info(
        "normalization_summary",
        fields_normalized=len(runner_output.normalized),
        normalization_errors=len(_norm_errors),
        failed_fact_ids=[str(n.extracted_fact_id) for n in _norm_errors],
    )
    log.info(
        "validation_summary",
        fields_valid=len(runner_output.validated) - len(_val_failed),
        fields_failed=len(_val_failed),
        failed_fact_ids=[str(v.extracted_fact_id) for v in _val_failed],
    )

    # ── Steps 14–16: Score + verify ───────────────────────────────────────────
    scored_fields = _build_scored_fields(profile_fields, field_result_map)

    # Resolve effective threshold: tenant DB value → system-wide default
    from decimal import Decimal as _Decimal

    from verigence.di.repositories.documents import get_verification_threshold
    from verigence.di.settings import get_settings
    tenant_threshold = await get_verification_threshold(session, tenant_id=tenant_id)
    if tenant_threshold is not None:
        effective_threshold = tenant_threshold
    else:
        effective_threshold = _Decimal(str(get_settings().verification_threshold))

    try:
        conf_result = calculate_confidence_score(scored_fields, threshold=effective_threshold)
    except ValueError as exc:
        raise NonRetryableError("SCORING_DENOMINATOR_ZERO", str(exc)) from exc

    confidence_score = conf_result.confidence_score
    hvs = conf_result.human_verification_status
    deterministic_rules_force_review = bool(_norm_errors or _val_failed)
    if deterministic_rules_force_review:
        hvs = HumanVerificationStatus.MANDATORY

    _required_present = sum(1 for sf in scored_fields if sf.expected and sf.found_status == FoundStatus.FOUND)
    _required_missing = sum(1 for sf in scored_fields if sf.expected and sf.found_status != FoundStatus.FOUND)
    log.info(
        "score_calculated",
        document_type_key=accepted_document_type_key,
        confidence_score=str(confidence_score),
        threshold_applied=str(effective_threshold),
        required_present=_required_present,
        required_missing=_required_missing,
    )
    log.info(
        "hvs_derived",
        document_type_key=accepted_document_type_key,
        confidence_score=str(confidence_score),
        threshold=str(effective_threshold),
        human_verification_status=hvs.value,
        deterministic_rules_force_review=deterministic_rules_force_review,
        normalization_error_count=len(_norm_errors),
        validation_error_count=len(_val_failed),
        reason=(
            "DETERMINISTIC_RULE_FAILURE"
            if deterministic_rules_force_review
            else ("AUTO_REVIEW_OPTIONAL" if hvs == HumanVerificationStatus.OPTIONAL else "NEEDS_REVIEW")
        ),
    )

    # ── Step 17: Set PROCESSED + CONFIRMED ───────────────────────────────────
    await session.execute(
        text("""
            UPDATE docintel.documents
            SET processing_status = 'PROCESSED',
                confirmation_status = 'CONFIRMED',
                confidence_score = :conf,
                verification_threshold_applied = :threshold,
                human_verification_status = :hvs,
                updated_at_utc = :now
            WHERE tenant_id = :tid AND document_id = :doc_id
        """),
        {
            "tid": tenant_id,
            "doc_id": document_id,
            "conf": float(confidence_score),
            "threshold": float(effective_threshold),
            "hvs": hvs.value,
            "now": now,
        },
    )

    # ── Step 17b: Upsert document_search_index (D14) ─────────────────────────
    # Use profile-field identity internally so duplicate canonicals in different
    # roles cannot overwrite each other.  JSON search keys are role-qualified
    # when a profile field has an explicit fact role.
    profile_field_to_norm_value: dict[uuid.UUID, object] = {}
    for pf in profile_fields:
        profile_field_id = uuid.UUID(str(pf["profile_field_id"]))
        fact_id = fact_id_map[profile_field_id]
        norm = norm_map.get(fact_id)
        provider_key = _provider_field_key(pf)
        if norm is not None:
            profile_field_to_norm_value[profile_field_id] = norm.normalized_value
        elif provider_key in field_result_map:
            profile_field_to_norm_value[profile_field_id] = field_result_map[provider_key].normalized_value
        else:
            profile_field_to_norm_value[profile_field_id] = None

    indexed_fields: dict[str, object] = {
        _search_index_key(pf): profile_field_to_norm_value.get(uuid.UUID(str(pf["profile_field_id"])))
        for pf in profile_fields
    }
    await upsert_search_index(
        session=session,
        tenant_id=tenant_id,
        document_id=document_id,
        subject_id=subject_id,
        document_type_key=accepted_document_type_key,
        indexed_fields=indexed_fields,
        schema_version=PIPELINE_VERSION,
    )

    # Mark Processing Run COMPLETED
    await session.execute(
        text("""
            UPDATE docintel.processing_runs
            SET run_status = 'COMPLETED',
                completed_at_utc = :now
            WHERE tenant_id = :tid AND processing_run_id = :run_id
        """),
        {"tid": tenant_id, "run_id": processing_run_id, "now": now},
    )

    _total_ms = round((time.monotonic() - job_start) * 1000, 1)
    indexed_keys = sorted(indexed_fields.keys())
    log.info(
        "pipeline_confirmed",
        document_type_key=accepted_document_type_key,
        processing_run_id=str(processing_run_id),
        confirmation_status="CONFIRMED",
        confidence_score=str(confidence_score),
        human_verification_status=hvs.value,
        indexed_field_keys=indexed_keys,
        total_duration_ms=_total_ms,
    )

    return JobRunResult(
        success=True,
        processing_run_id=processing_run_id,
        confidence_score=confidence_score,
        human_verification_status=hvs.value,
    )


# ── DB helper functions ───────────────────────────────────────────────────────

async def _get_tenant_settings(session: AsyncSession, tenant_id: str) -> dict:
    row = (
        await session.execute(
            text("""
                SELECT classification_acceptance_score
                FROM docintel.tenant_settings
                WHERE tenant_id = :tid
            """),
            {"tid": tenant_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise NonRetryableError(
            "TENANT_NOT_FOUND",
            f"Tenant {tenant_id!r} has no settings row",
        )
    return dict(row)


async def _get_document_hint_key(
    session: AsyncSession, tenant_id: str, document_id: uuid.UUID,
) -> str | None:
    row = (
        await session.execute(
            text("""
                SELECT document_type_hint_key
                FROM docintel.documents
                WHERE tenant_id = :tid AND document_id = :doc_id
            """),
            {"tid": tenant_id, "doc_id": document_id},
        )
    ).one_or_none()
    return row[0] if row else None


async def _get_document_subject_id(
    session: AsyncSession, tenant_id: str, document_id: uuid.UUID,
) -> uuid.UUID | None:
    row = (
        await session.execute(
            text("""
                SELECT subject_id
                FROM docintel.documents
                WHERE tenant_id = :tid AND document_id = :doc_id
            """),
            {"tid": tenant_id, "doc_id": document_id},
        )
    ).one_or_none()
    if row and row[0]:
        return uuid.UUID(str(row[0]))
    return None


async def _get_requirement_keys(
    session: AsyncSession, tenant_id: str, subject_id: uuid.UUID,
) -> set[str]:
    """Get document_type_keys from the Subject's active Requirement Profile."""
    rows = (
        await session.execute(
            text("""
                SELECT dt.document_type_key
                FROM docintel.subject_requirement_assignments srpa
                JOIN docintel.document_requirement_profile_items drpi
                  ON drpi.requirement_profile_id = srpa.requirement_profile_id
                 AND drpi.tenant_id = srpa.tenant_id
                JOIN docintel.document_types dt
                  ON dt.document_type_id = drpi.document_type_id
                WHERE srpa.tenant_id = :tid
                  AND srpa.subject_id = :sid
                  AND srpa.status = 'ACTIVE'
                  AND drpi.enabled = true
            """),
            {"tid": tenant_id, "sid": subject_id},
        )
    ).all()
    return {r[0] for r in rows}


async def _form_candidate_set(
    session: AsyncSession, tenant_id: str,
) -> list[dict]:
    """
    Implements DI_CLASSIFICATION_v2.2.md §2 candidate-set algorithm steps 1-4.

    Returns list of dicts: {document_type_id, document_type_key, profile_id, scope_tenant_id}
    """
    rows = (
        await session.execute(
            text("""
                WITH effective_types AS (
                    -- Step 1+2: visible ACTIVE types; Tenant shadows global on same key
                    SELECT DISTINCT ON (dt.document_type_key)
                        dt.document_type_id,
                        dt.document_type_key,
                        dt.owner_tenant_id
                    FROM docintel.document_types dt
                    WHERE dt.status = 'ACTIVE'
                      AND (dt.owner_tenant_id = :tid OR dt.owner_tenant_id IS NULL)
                    ORDER BY dt.document_type_key,
                             CASE WHEN dt.owner_tenant_id = :tid THEN 0 ELSE 1 END
                ),
                with_profile AS (
                    -- Step 3: resolve PUBLISHED Extraction Profile (Tenant > global)
                    SELECT DISTINCT ON (et.document_type_id)
                        et.document_type_id,
                        et.document_type_key,
                        ep.profile_id,
                        ep.scope_tenant_id
                    FROM effective_types et
                    JOIN docintel.extraction_profiles ep
                      ON ep.document_type_id = et.document_type_id
                     AND ep.status = 'PUBLISHED'
                     AND (ep.scope_tenant_id = :tid OR ep.scope_tenant_id IS NULL)
                    ORDER BY et.document_type_id,
                             CASE WHEN ep.scope_tenant_id = :tid THEN 0 ELSE 1 END
                )
                -- Step 4: only types with a published profile remain
                SELECT document_type_id, document_type_key, profile_id
                FROM with_profile
                ORDER BY document_type_key
            """),
            {"tid": tenant_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def _build_candidate_snapshot(
    candidates: list[dict],
    req_keys: set[str],
    hint_key: str | None,
) -> list[dict]:
    """
    Build the JSON snapshot persisted on processing_runs.classification_candidate_set.
    Order per DI_CLASSIFICATION_v2.2 §2 step 9: hint first, then requirement, then rest.
    """
    snapshot = []
    for c in candidates:
        snapshot.append({
            "documentTypeId": str(c["document_type_id"]),
            "documentTypeKey": c["document_type_key"],
            "profileId": str(c["profile_id"]),
            "isRequirementExpected": c["document_type_key"] in req_keys,
            "isCallerHint": c["document_type_key"] == hint_key,
        })
    # Sort: hint first, then req expected, then alpha
    snapshot.sort(key=lambda e: (
        0 if e["isCallerHint"] else (1 if e["isRequirementExpected"] else 2),
        e["documentTypeKey"],
    ))
    return snapshot


def _accept_classification(
    classifications: list[ClassificationCandidate],
    candidates: list[dict],
    acceptance_score: Decimal,
) -> dict | None:
    """
    DI_CLASSIFICATION_v2.2 §2 step 11:
    Accept exactly one candidate above acceptance_score.
    Returns the matching candidate dict from candidates, or None.
    """
    candidate_key_map = {c["document_type_key"]: c for c in candidates}
    winners = [
        cl for cl in classifications
        if cl.confidence >= acceptance_score
        and cl.document_type_key in candidate_key_map
    ]
    if len(winners) != 1:
        return None
    return candidate_key_map[winners[0].document_type_key]


async def _persist_classifications(
    session: AsyncSession,
    tenant_id: str,
    processing_run_id: uuid.UUID,
    document_id: uuid.UUID,
    classifications: list[ClassificationCandidate],
    accepted: dict,
    profile_id: uuid.UUID,
) -> None:
    now = datetime.now(UTC)
    for cl in classifications:
        is_accepted = cl.document_type_key == accepted["document_type_key"]
        await session.execute(
            text("""
                INSERT INTO docintel.document_classifications
                    (tenant_id, classification_id, processing_run_id, document_id,
                     document_type_id, document_type_key_observed,
                     confidence_score, classification_method, accepted, created_at_utc)
                VALUES
                    (:tid, :cid, :run_id, :doc_id,
                     :dtid, :dtkey,
                     :conf, :method, :accepted, :now)
            """),
            {
                "tid": tenant_id,
                "cid": uuid.uuid4(),
                "run_id": processing_run_id,
                "doc_id": document_id,
                "dtid": accepted["document_type_id"] if is_accepted else None,
                "dtkey": cl.document_type_key,
                "conf": float(cl.confidence),
                "method": cl.method,
                "accepted": is_accepted,
                "now": now,
            },
        )


async def _load_original_artifact(
    session: AsyncSession,
    tenant_id: str,
    document_id: uuid.UUID,
) -> tuple[bytes, str]:
    """Load the ORIGINAL artifact bytes + MIME type from storage."""
    row = (
        await session.execute(
            text("""
                SELECT da.logical_object_key, da.mime_type, da.storage_id
                FROM docintel.document_artifacts da
                WHERE da.tenant_id = :tid
                  AND da.document_id = :doc_id
                  AND da.artifact_type = 'ORIGINAL'
                ORDER BY da.created_at_utc
                LIMIT 1
            """),
            {"tid": tenant_id, "doc_id": document_id},
        )
    ).one_or_none()
    if row is None:
        raise NonRetryableError(
            "ORIGINAL_ARTIFACT_MISSING",
            f"No ORIGINAL artifact found for document {document_id}",
        )
    logical_key, mime_type = row[0], row[1]
    mime_type = mime_type or "application/octet-stream"

    # Load bytes from storage
    from verigence.di.storage.adapter import get_storage_adapter
    storage = get_storage_adapter()
    try:
        data = b"".join([chunk async for chunk in storage.get_stream(logical_key)])
    except Exception as exc:
        raise RetryableError("STORAGE_READ_ERROR", f"Cannot read original artifact: {exc}") from exc

    return data, mime_type


async def _load_profile_fields(
    session: AsyncSession,
    profile_id: uuid.UUID,
) -> list[dict]:
    """Load enabled profile fields with provider extraction keys and fact roles."""
    rows = (
        await session.execute(
            text("""
                SELECT
                    epf.profile_field_id,
                    epf.canonical_field_id,
                    epf.enabled,
                    epf.expected,
                    epf.score_included,
                    epf.score_weight,
                    epf.aliases,
                    epf.extraction_instruction,
                    epf.extraction_key,
                    epf.fact_role_override,
                    cf.field_key AS canonical_field_key
                FROM docintel.extraction_profile_fields epf
                JOIN docintel.canonical_fields cf
                  ON cf.canonical_field_id = epf.canonical_field_id
                WHERE epf.profile_id = :pid
                  AND epf.enabled = true
                ORDER BY epf.display_sequence, cf.field_key, epf.fact_role_override
            """),
            {"pid": profile_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def _provider_field_key(profile_field: dict) -> str:
    """Return the provider-facing key while preserving legacy profiles."""
    extraction_key = profile_field.get("extraction_key")
    if isinstance(extraction_key, str) and extraction_key.strip():
        return extraction_key.strip()
    return str(profile_field["canonical_field_key"])


def _search_index_key(profile_field: dict) -> str:
    """Use role-qualified keys so role-distinct canonicals never overwrite."""
    canonical_key = str(profile_field["canonical_field_key"])
    role = str(profile_field.get("fact_role_override") or "UNSPECIFIED")
    if role == "UNSPECIFIED":
        return canonical_key
    return f"{canonical_key}__{role.lower()}"


async def _get_physical_form_type(
    session: AsyncSession,
    tenant_id: str,
    document_type_id: uuid.UUID,
) -> str:
    """Fetch physical_form_type from tenant_document_types for the accepted type.

    D22: passed to ai_adapter.extract() for schema registry routing.
    Falls back to 'PRINTABLE' if the row is not found.
    """
    row = (
        await session.execute(
            text("""
                SELECT physical_form_type
                FROM docintel.tenant_document_types
                WHERE tenant_id = :tid
                  AND document_type_id = :dtid
            """),
            {"tid": tenant_id, "dtid": document_type_id},
        )
    ).one_or_none()
    return row[0] if row else "PRINTABLE"



def _build_scored_fields(
    profile_fields: list[dict],
    field_result_map: dict[str, FieldResult],
) -> list[ScoredField]:
    scored = []
    for pf in profile_fields:
        if not pf["score_included"]:
            continue
        provider_key = _provider_field_key(pf)
        fr = field_result_map.get(provider_key)
        found = fr.found_status if fr else FoundStatus.NOT_FOUND
        conf = fr.confidence if fr else None
        scored.append(ScoredField(
            field_key=provider_key,
            found_status=found,
            field_confidence=conf,
            score_weight=Decimal(str(pf["score_weight"])),
            expected=pf["expected"],
        ))
    return scored


async def _insert_invocation(
    session: AsyncSession,
    tenant_id: str,
    invocation_id: uuid.UUID,
    processing_run_id: uuid.UUID,
    correlation_id: str,
    capability: str,
    adapter_key: str,
    outcome: str,
) -> None:
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.processor_invocations
                (tenant_id, invocation_id, processing_run_id, correlation_id,
                 capability, adapter_key, outcome, started_at_utc)
            VALUES
                (:tid, :inv_id, :run_id, :corr,
                 :cap, :adapter, :outcome, :now)
        """),
        {
            "tid": tenant_id, "inv_id": invocation_id,
            "run_id": processing_run_id, "corr": correlation_id,
            "cap": capability, "adapter": adapter_key,
            "outcome": outcome, "now": now,
        },
    )


async def _update_invocation(
    session: AsyncSession,
    tenant_id: str,
    invocation_id: uuid.UUID,
    outcome: str,
    provider_request_id: str | None = None,
    usage_metrics: dict | None = None,
    error_detail: str | None = None,
) -> None:
    now = datetime.now(UTC)
    await session.execute(
        text("""
            UPDATE docintel.processor_invocations
            SET outcome = :outcome,
                completed_at_utc = :now,
                provider_request_id = :prid,
                usage_metrics = CAST(:metrics AS jsonb),
                error_detail = :error_detail
            WHERE tenant_id = :tid AND invocation_id = :inv_id
        """),
        {
            "outcome": outcome, "now": now,
            "prid": provider_request_id,
            "metrics": json.dumps(usage_metrics or {}),
            "error_detail": error_detail,
            "tid": tenant_id, "inv_id": invocation_id,
        },
    )


async def _fail_processing_run(
    session: AsyncSession,
    tenant_id: str,
    processing_run_id: uuid.UUID,
    error_class: str,
    error_code: str,
    error_detail: str,
) -> None:
    now = datetime.now(UTC)
    await session.execute(
        text("""
            UPDATE docintel.processing_runs
            SET run_status = 'FAILED',
                error_class = :error_class,
                error_code = :error_code,
                error_detail = :error_detail,
                completed_at_utc = :now
            WHERE tenant_id = :tid AND processing_run_id = :run_id
        """),
        {
            "tid": tenant_id, "run_id": processing_run_id,
            "error_class": error_class,
            "error_code": error_code,
            "error_detail": error_detail,
            "now": now,
        },
    )


async def _ensure_system_actor(
    session: AsyncSession,
    tenant_id: str,
    actor_id: str,
) -> None:
    """Insert a SYSTEM actor row if it does not exist yet (idempotent)."""
    now = datetime.now(UTC)
    await session.execute(
        text("""
            INSERT INTO docintel.actors
                (tenant_id, actor_id, actor_type, display_name, status,
                 created_at_utc, updated_at_utc)
            VALUES
                (:tid, :actor_id, 'SYSTEM', 'Processing Worker', 'ACTIVE', :now, :now)
            ON CONFLICT (tenant_id, actor_id) DO NOTHING
        """),
        {"tid": tenant_id, "actor_id": actor_id, "now": now},
    )
