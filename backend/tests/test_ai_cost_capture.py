"""What the AI provider calls cost (product owner 2026-11-16: "capture the cost").

Every answered call is priced at list price when it is made and kept: on the read's
invocation, on the classification job, failed answers included. GET
/v1/platform/ai-usage gives Audit Core's System Health page the calls, tokens and
cost per day, Project, kind of call and document type."""
from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from verigence.di.api.v1 import platform_health as ph
from verigence.di.document_ai import gemini_cost as gc

MODEL = "gemini-3-flash-preview"


def _usage(prompt: int, response: int, *, thoughts: int = 0, total: int | None = None, cached: int = 0,
           tier: str = gc.STANDARD_TIER) -> gc.GeminiUsage:
    return gc.GeminiUsage(
        prompt_tokens=prompt, response_tokens=response, thoughts_tokens=thoughts, cached_tokens=cached,
        total_tokens=prompt + response + thoughts if total is None else total, service_tier=tier)


def test_a_call_costs_its_tokens_at_the_list_price_of_its_tier():
    # 1,000,000 in at $0.50 + 100,000 out at $3.00
    assert gc.cost_usd(MODEL, gc.STANDARD_TIER, prompt_tokens=1_000_000, response_tokens=100_000) == pytest.approx(0.80)
    # Flex is half price
    assert gc.cost_usd(MODEL, gc.FLEX_TIER, prompt_tokens=1_000_000, response_tokens=100_000) == pytest.approx(0.40)


def test_thinking_is_billed_as_output_even_when_only_the_total_shows_it():
    # reported thinking
    assert gc.billed_output(1000, 200, 50, 1250) == 250
    # the provider's total is larger than prompt + answer + reported thinking: the rest is output too
    assert gc.billed_output(1000, 200, 0, 1300) == 300
    assert gc.cost_usd(MODEL, gc.STANDARD_TIER, prompt_tokens=1000, response_tokens=200, total_tokens=1300) == pytest.approx(
        (1000 * 0.50 + 300 * 3.00) / 1_000_000)


def test_cached_input_is_a_tenth_of_the_input_price():
    full = gc.cost_usd(MODEL, gc.STANDARD_TIER, prompt_tokens=1_000_000, response_tokens=0)
    cached = gc.cost_usd(MODEL, gc.STANDARD_TIER, prompt_tokens=1_000_000, response_tokens=0, cached_tokens=1_000_000)
    assert (full, cached) == (pytest.approx(0.50), pytest.approx(0.05))


def test_a_model_with_no_price_has_no_cost_rather_than_a_guess():
    assert gc.price_per_mtok("some-future-model", gc.STANDARD_TIER) is None
    assert gc.cost_usd("some-future-model", gc.STANDARD_TIER, prompt_tokens=10, response_tokens=10) is None
    calls = [gc.call_metrics(MODEL, _usage(100, 10)), gc.call_metrics("some-future-model", _usage(100, 10))]
    assert gc.summarise_calls(calls)["cost_usd"] is None  # never a part sum shown as the cost


def test_calls_are_collected_only_while_a_job_holds_the_sink_open():
    assert gc.note_call(MODEL, _usage(100, 10))["cost_usd"] is not None  # no sink: priced, kept nowhere
    calls: list[dict] = []
    token = gc.AI_USAGE_SINK.set(calls)
    try:
        gc.note_call(MODEL, _usage(2000, 300, tier=gc.FLEX_TIER))
        gc.note_call(MODEL, _usage(2000, 310))  # the retry goes to the standard tier
    finally:
        gc.AI_USAGE_SINK.reset(token)
    gc.note_call(MODEL, _usage(1, 1))
    total = gc.summarise_calls(calls)
    assert (total["provider_calls"], total["billed_prompt_tokens"], total["response_tokens"]) == (2, 4000, 610)
    assert total["service_tier"] == gc.STANDARD_TIER
    assert total["cost_usd"] == pytest.approx(
        (2000 * 0.25 + 300 * 1.50 + 2000 * 0.50 + 310 * 3.00) / 1_000_000)
    assert gc.summarise_calls([]) == {}


def test_the_window_is_whole_days_in_the_readers_time_zone():
    ist = ZoneInfo("Asia/Kolkata")
    # 16 Nov 2026 22:30 IST
    now = datetime(2026, 11, 16, 17, 0, tzinfo=UTC)
    first_day, since = ph.usage_window(30, ist, now)
    assert first_day == date(2026, 10, 18)
    assert since == datetime(2026, 10, 17, 18, 30, tzinfo=UTC)
    assert ph.usage_window(1, ist, now)[0] == date(2026, 11, 16)


def _extraction(**over):
    row = {"day": date(2026, 11, 16), "tenant_id": "t1", "document_type_key": "booking_form", "model": MODEL,
           "tier": "STANDARD", "calls": 10, "failed_calls": 1, "calls_without_usage": 0, "prompt_tokens": 40_000,
           "output_tokens": 15_000, "recorded_cost_usd": 0, "unpriced_prompt_tokens": 0, "unpriced_output_tokens": 0}
    return {**row, **over}


def test_a_read_that_kept_its_cost_is_reported_as_recorded():
    row = ph.extraction_usage_row(_extraction(recorded_cost_usd=0.065))
    assert (row["capability"], row["documentTypeKey"], row["calls"], row["failedCalls"]) == ("EXTRACTION", "booking_form", 10, 1)
    assert (row["costUsd"], row["costFromTokensUsd"]) == (pytest.approx(0.065), 0.0)


def test_a_read_from_before_costs_were_kept_is_priced_from_its_tokens():
    row = ph.extraction_usage_row(_extraction(unpriced_prompt_tokens=40_000, unpriced_output_tokens=15_000))
    assert row["costFromTokensUsd"] == pytest.approx((40_000 * 0.50 + 15_000 * 3.00) / 1_000_000)
    assert row["costUsd"] == row["costFromTokensUsd"]
    flex = ph.extraction_usage_row(_extraction(tier="FLEX", unpriced_prompt_tokens=40_000, unpriced_output_tokens=15_000))
    assert flex["costUsd"] == pytest.approx(row["costUsd"] / 2)
    unknown = ph.extraction_usage_row(_extraction(model="unknown", unpriced_prompt_tokens=1, unpriced_output_tokens=1))
    assert unknown["costUsd"] is None
    # Input the provider served from its cache was billed at a tenth of the price.
    cached = ph.extraction_usage_row(_extraction(
        unpriced_prompt_tokens=40_000, unpriced_output_tokens=15_000, unpriced_cached_tokens=10_000))
    assert cached["costUsd"] == pytest.approx((30_000 * 0.50 + 10_000 * 0.05 + 15_000 * 3.00) / 1_000_000)


def _classification(**over):
    row = {"day": date(2026, 11, 17), "tenant_id": "t1", "model": MODEL, "tier": "STANDARD", "has_usage": True,
           "before_recording": False, "jobs": 20, "failed_jobs": 0, "calls": 21, "prompt_tokens": 44_000,
           "output_tokens": 900, "recorded_cost_usd": 0.0247, "jobs_without_price": 0}
    return {**row, **over}


def test_classification_jobs_report_their_calls_and_cost():
    row = ph.classification_usage_row(_classification())
    assert (row["capability"], row["calls"], row["callsWithoutUsage"], row["costUsd"]) == (
        "CLASSIFICATION", 21, 0, pytest.approx(0.0247))


def test_a_job_that_made_no_call_costs_nothing_and_one_never_recorded_is_not_costed():
    trusted = ph.classification_usage_row(_classification(
        has_usage=False, model="unknown", tier="unknown", calls=0, prompt_tokens=0, output_tokens=0,
        recorded_cost_usd=0, jobs=5))
    assert (trusted["calls"], trusted["callsWithoutUsage"], trusted["costUsd"]) == (0, 0, 0.0)
    old = ph.classification_usage_row(_classification(
        has_usage=False, before_recording=True, model="unknown", tier="unknown", calls=0, prompt_tokens=0,
        output_tokens=0, recorded_cost_usd=0, jobs=300))
    assert (old["calls"], old["callsWithoutUsage"], old["costUsd"]) == (300, 300, None)
    unpriced = ph.classification_usage_row(_classification(jobs_without_price=2))
    assert unpriced["costUsd"] is None


# --- against the migrated database -------------------------------------------------

import json  # noqa: E402
import uuid  # noqa: E402
from datetime import timedelta  # noqa: E402

from sqlalchemy import text  # noqa: E402

from verigence.di.workers import capture_v2_classifier as cw  # noqa: E402


async def _job(session, tenant: str, *, created: datetime, status: str = "COMPLETED") -> uuid.UUID:
    job_id = uuid.uuid4()
    await session.execute(text("""
        INSERT INTO docintel.document_capture_v2_classification_jobs
            (tenant_id, classification_job_id, document_id, job_status, created_at_utc, updated_at_utc)
        VALUES (:t, :j, :d, :s, :c, :c)
    """), {"t": tenant, "j": job_id, "d": uuid.uuid4(), "s": status, "c": created})
    return job_id


async def _read(session, tenant: str, *, started: datetime, outcome: str, usage: dict | None) -> None:
    await session.execute(text("""
        INSERT INTO docintel.processor_invocations
            (tenant_id, invocation_id, processing_run_id, correlation_id, capability, adapter_key, outcome,
             usage_metrics, started_at_utc)
        VALUES (:t, :i, :r, 'corr-ai-cost', 'VISION_EXTRACTION', 'gemini_3_flash_preview_v1', :o,
                CAST(:u AS jsonb), :s)
    """), {"t": tenant, "i": uuid.uuid4(), "r": uuid.uuid4(), "o": outcome, "u": json.dumps(usage or {}), "s": started})


async def test_usage_is_added_to_the_job_attempt_by_attempt_and_reported_by_day(db_session):
    session = db_session
    # Parent rows are not the subject here: this session skips foreign keys.
    await session.execute(text("SET LOCAL session_replication_role = replica"))
    tenant = f"ai-cost-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    # A job read before usage was kept, a job retried once (Flex, then standard), a trusted job.
    await _job(session, tenant, created=now - timedelta(days=2))
    retried = await _job(session, tenant, created=now - timedelta(hours=2))
    await _job(session, tenant, created=now - timedelta(hours=1))
    first = gc.summarise_calls([gc.call_metrics(MODEL, _usage(2000, 40, tier=gc.FLEX_TIER))])
    second = gc.summarise_calls([gc.call_metrics(MODEL, _usage(2000, 45))])
    await session.execute(text(cw.RECORD_USAGE_SQL), cw.usage_params(tenant, retried, first))
    await session.execute(text(cw.RECORD_USAGE_SQL), cw.usage_params(tenant, retried, second))
    stored = (await session.execute(text(
        "SELECT usage_metrics FROM docintel.document_capture_v2_classification_jobs "
        "WHERE tenant_id=:t AND classification_job_id=:j"), {"t": tenant, "j": retried})).scalar_one()
    assert (stored["provider_calls"], stored["billed_prompt_tokens"], stored["billed_output_tokens"]) == (2, 4000, 85)
    assert stored["service_tier"] == gc.STANDARD_TIER
    job_cost = (2000 * 0.25 + 40 * 1.50 + 2000 * 0.50 + 45 * 3.00) / 1_000_000
    assert float(stored["cost_usd"]) == pytest.approx(job_cost)

    # A read that kept its cost, one from before (tokens only), a failed one with nothing kept.
    await _read(session, tenant, started=now - timedelta(minutes=30), outcome="SUCCESS", usage={
        "model": MODEL, "document_type_key": "booking_form", "service_tier": "STANDARD",
        "billed_prompt_tokens": 4000, "response_tokens": 1500, "thoughts_tokens": 0, "total_tokens": 5500,
        "cost_usd": 0.0065})
    await _read(session, tenant, started=now - timedelta(minutes=20), outcome="SUCCESS", usage={
        "model": MODEL, "document_type_key": "booking_form",
        "billed_prompt_tokens": 4000, "response_tokens": 1500, "thoughts_tokens": 0, "total_tokens": 5600,
        "cached_tokens": 1000})
    await _read(session, tenant, started=now - timedelta(minutes=10), outcome="FAILED", usage=None)

    usage = await ph.ai_usage(session, 7, "UTC", now)
    mine = [r for r in usage["rows"] if r["tenantId"] == tenant]
    reads = [r for r in mine if r["capability"] == "EXTRACTION"]
    assert sum(r["calls"] for r in reads) == 3
    assert sum(r["failedCalls"] for r in reads) == 1
    assert sum(r["callsWithoutUsage"] for r in reads) == 1
    priced = [r for r in reads if r["documentTypeKey"] == "booking_form"]
    # recorded 0.0065 + the earlier read priced from its tokens (1,600 output: the total shows 100
    # more; 1,000 of its 4,000 input tokens came from the provider's cache)
    from_tokens = (3000 * 0.50 + 1000 * 0.05 + 1600 * 3.00) / 1_000_000
    assert sum(r["costUsd"] for r in priced) == pytest.approx(0.0065 + from_tokens)
    assert sum(r["costFromTokensUsd"] for r in priced) == pytest.approx(from_tokens)

    jobs = [r for r in mine if r["capability"] == "CLASSIFICATION"]
    recorded = [r for r in jobs if r["model"] == MODEL]
    assert [(r["calls"], r["costUsd"]) for r in recorded] == [(2, pytest.approx(job_cost))]
    assert sum(r["callsWithoutUsage"] for r in jobs) == 1          # the job from before usage was kept
    assert [r["costUsd"] for r in jobs if r["callsWithoutUsage"]] == [None]
    assert usage["classificationRecordedSinceUtc"] is not None
    assert {"model": MODEL, "tier": "FLEX", "inputPerMTok": 0.25, "outputPerMTok": 1.5} in usage["prices"]
