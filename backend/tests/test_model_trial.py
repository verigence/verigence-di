"""The model trial (product owner 2026-11-21: bring the AI cost down while quality improves; which
model can read PAN, Aadhaar, money receipts, RTO and insurance). These hold the parts of the
trial a wrong answer would hide in: what counts as the same value, the checks that need no
model, which model name is called, and that a read is made with the worker's own request."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from verigence.di.document_ai.adapter import ExtractionField
from verigence.di.trials import model_trial as trial


# ── What counts as the same value ────────────────────────────────────────────
@pytest.mark.parametrize(("left", "right"), [
    ("1,25,000.00/-", "125000"),
    ("Rs. 5000", "5000.0"),
    ("₹ 11,000", "11000"),
    ("abcde 1234 f", "ABCDE1234F"),
    ("OD-01-AB-1234", "od01ab1234"),
    ("Suresh  Kumar", "SURESH KUMAR"),
])
def test_two_ways_of_writing_one_value_compare_equal(left: str, right: str) -> None:
    assert trial.normalise(left) == trial.normalise(right)


@pytest.mark.parametrize(("left", "right"), [("125000", "125001"), ("5000.50", "5000"),
                                             ("ABCDE1234F", "ABCDE1234E"), ("Suresh", "Sures")])
def test_different_values_stay_different(left: str, right: str) -> None:
    assert trial.normalise(left) != trial.normalise(right)


def test_nothing_read_is_empty() -> None:
    assert trial.normalise(None) == "" and trial.normalise("  ") == ""


# ── The checks that need no model ────────────────────────────────────────────
def _with_check_digit(first_eleven: str) -> str:
    """An Aadhaar-shaped number that passes the check, made here so no real number is in the repo."""
    return next(first_eleven + str(d) for d in range(10) if trial.aadhaar_check_ok(first_eleven + str(d)))


def test_pan_shape() -> None:
    assert trial.pan_shape_ok("abcde1234f") is True
    assert trial.pan_shape_ok("ABCDE 1234 F") is True
    assert trial.pan_shape_ok("ABCD01234F") is False      # a digit read where a letter stands
    assert trial.pan_shape_ok("") is None


def test_aadhaar_check_digit() -> None:
    good = _with_check_digit("23412341234")
    assert trial.aadhaar_check_ok(good) is True
    assert trial.aadhaar_check_ok(f"{good[:4]} {good[4:8]} {good[8:]}") is True
    one_digit_misread = good[:5] + str((int(good[5]) + 1) % 10) + good[6:]
    assert trial.aadhaar_check_ok(one_digit_misread) is False
    two_swapped = good[:3] + good[4] + good[3] + good[5:]
    if two_swapped != good:
        assert trial.aadhaar_check_ok(two_swapped) is False
    assert trial.aadhaar_check_ok("1234 5678") is False     # too short to be one
    assert trial.aadhaar_check_ok("XXXX XXXX 1234") is None  # masked: cannot be checked
    assert trial.aadhaar_check_ok(None) is None


def test_checks_apply_by_field_name() -> None:
    good = _with_check_digit("23412341234")
    fields = {"pan_number": {"value": "ABCDE1234F"}, "customer_aadhaar_number": {"value": good},
              "customer_name": {"value": "A"}, "co_applicant_pan_number": {"value": None}}
    assert trial.checks_for(fields) == {"pan_number": True, "customer_aadhaar_number": True}


# ── Which model name is called ───────────────────────────────────────────────
def test_a_model_is_called_by_its_own_name_or_its_shortest_fuller_name() -> None:
    available = ["models/gemini-3-flash-preview", "models/gemini-3.1-flash-lite-preview",
                 "models/gemini-3.1-flash-lite-preview-09-2026", "models/gemini-2.5-flash-lite"]
    assert trial.pick_models(available, ["gemini-3-flash-preview", "gemini-3.1-flash-lite",
                                         "gemini-2.5-flash-lite", "gemini-9-nano"]) == {
        "gemini-3-flash-preview": "gemini-3-flash-preview",
        "gemini-3.1-flash-lite": "gemini-3.1-flash-lite-preview",
        "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
        "gemini-9-nano": None,
    }


def test_request_is_read_and_bounded(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps({"run": "2026-11-22-a", "models": ["m1", " m2 "], "concurrency": 50}))
    request = trial.Request.load(path)
    assert (request.run, request.models, request.concurrency, request.tier) == (
        "2026-11-22-a", ["m1", "m2"], 8, trial.STANDARD)
    path.write_text(json.dumps({"run": "x; drop", "models": ["m1"]}))
    with pytest.raises(ValueError):
        trial.Request.load(path)
    path.write_text(json.dumps({"run": "ok", "models": []}))
    with pytest.raises(ValueError):
        trial.Request.load(path)


# ── One read ─────────────────────────────────────────────────────────────────
_FIELDS = [ExtractionField(field_key="pan_number"), ExtractionField(field_key="pan_holder_name")]


def _answer(fields: dict[str, Any], **usage: int) -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(fields)}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": usage.get("prompt", 1900),
                              "candidatesTokenCount": usage.get("answer", 300)}}


async def _read(handler: Any, **over: Any) -> trial.Read:
    waited: list[float] = []

    async def no_wait(seconds: float) -> None:
        waited.append(seconds)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        read = await trial.read_with_model(
            client, api_key="k", model=over.get("model", "gemini-x"), artifact_bytes=b"\xff\xd8page",
            mime_type="image/jpeg", prompt="read this", document_type_key="pan_card", fields=_FIELDS,
            thinking_level=over.get("thinking", "low"), max_output_tokens=4096,
            tier=over.get("tier", trial.STANDARD), timeout=5.0, sleep=no_wait,
        )
    read.waited = waited  # type: ignore[attr-defined]
    return read


@pytest.mark.asyncio
async def test_a_read_is_the_workers_request_to_the_named_model() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_answer({"pan_number": {"value": "abcde1234f", "confidence": "high"}}))

    read = await _read(handler, model="gemini-3.1-flash-lite-preview")
    assert seen[0].url.path.endswith("/models/gemini-3.1-flash-lite-preview:generateContent")
    body = json.loads(seen[0].content)
    parts = body["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg" and parts[1]["text"] == "read this"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert "service_tier" not in body
    assert read.ok and (read.prompt_tokens, read.response_tokens) == (1900, 300)
    assert read.fields["pan_number"]["norm"] == "ABCDE1234F"
    assert read.fields["pan_holder_name"]["norm"] == ""      # asked for, not found
    assert trial.checks_for(read.fields) == {"pan_number": True}


@pytest.mark.asyncio
async def test_a_model_that_refuses_the_thinking_setting_is_read_without_it() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if "thinkingConfig" in bodies[-1]["generationConfig"]:
            return httpx.Response(400, json={"error": {"message": "Thinking level is not supported for this model."}})
        return httpx.Response(200, json=_answer({"pan_number": {"value": "ABCDE1234F", "confidence": "high"}}))

    read = await _read(handler)
    assert read.ok and read.thinking == "" and len(bodies) == 2


@pytest.mark.asyncio
async def test_a_busy_provider_is_asked_again_later_and_not_for_ever() -> None:
    calls = {"n": 0}

    def twice_busy(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, json={"error": {"message": "quota"}})
        return httpx.Response(200, json=_answer({"pan_number": {"value": "ABCDE1234F", "confidence": "high"}}))

    read = await _read(twice_busy)
    assert read.ok and read.waited == [15.0, 45.0]  # type: ignore[attr-defined]

    def always_busy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    read = await _read(always_busy)
    assert not read.ok and read.error_code == "HTTP_503" and read.error_detail == "overloaded"
    assert read.waited == list(trial.WAITS)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_an_answer_that_cannot_be_used_is_a_failed_read_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})

    read = await _read(handler)
    assert not read.ok and read.error_code == "ANSWER_UNUSABLE" and read.fields == {}


@pytest.mark.asyncio
async def test_flex_is_asked_for_only_when_the_trial_says_so() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_answer({}))

    read = await _read(handler, tier=trial.FLEX)
    assert bodies[0]["service_tier"] == "flex" and read.tier == trial.FLEX


# ── A whole run, against the database ────────────────────────────────────────
_TABLES = [stmt for stmt in (Path(__file__).parent.parent / "trials" / "schema.sql").read_text().split(";")
           if "GRANT" not in stmt and stmt.strip() and not all(
               line.strip().startswith("--") or not line.strip() for line in stmt.splitlines())]


@pytest.mark.asyncio
async def test_a_run_reads_each_document_with_each_model_once_and_makes_a_failed_read_again(
    db_session: Any, db_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    import uuid

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from verigence.di.repositories import database
    from verigence.di.settings import get_settings

    engine = create_async_engine(db_url)
    monkeypatch.setattr(database, "AsyncSessionFactory",
                        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))

    for stmt in _TABLES:
        await db_session.execute(text(stmt))
    run_label = f"test-{uuid.uuid4().hex[:8]}"
    docs = [uuid.uuid4(), uuid.uuid4()]
    for doc in docs:
        await db_session.execute(
            text("INSERT INTO di_trials.sample VALUES (:run, 't1', :doc, 'pan_card', 'RANDOM')"),
            {"run": run_label, "doc": doc})
    await db_session.commit()

    async def page(tenant_id: str, document_id: Any) -> trial.Page:
        return trial.Page("pan_card", _FIELDS, b"\xff\xd8page", "image/jpeg", "read this")

    monkeypatch.setattr(trial, "load_page", page)
    monkeypatch.setattr(get_settings(), "docai_gemini_api_key", "k", raising=False)
    monkeypatch.setattr(trial, "WAITS", ())
    calls: list[str] = []
    lite_fails = {"on": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"models": [
                {"name": "models/gemini-3-flash-preview", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-3.1-flash-lite-preview", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embedding-1", "supportedGenerationMethods": ["embedContent"]},
            ]})
        calls.append(request.url.path.rsplit("/", 1)[-1])
        if "lite" in request.url.path and lite_fails["on"]:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, json=_answer({"pan_number": {"value": "ABCDE1234F", "confidence": "high"}}))

    request = trial.Request(run=run_label, models=["gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-nope"])
    assert await trial.run(request, transport=httpx.MockTransport(handler)) == 0
    assert len(calls) == 4
    rows = (await db_session.execute(text(
        "SELECT model, asked_model, ok, error_code, fields->'pan_number'->>'norm', checks->>'pan_number' "
        "FROM di_trials.result WHERE run = :run ORDER BY model, document_id"), {"run": run_label})).all()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == (
        [("gemini-3-flash-preview", "gemini-3-flash-preview", True, None)] * 2
        + [("gemini-3.1-flash-lite-preview", "gemini-3.1-flash-lite", False, "HTTP_503")] * 2)
    assert rows[0][4] == "ABCDE1234F" and rows[0][5] == "true"
    out = capsys.readouterr().out
    assert "uses=NOT_AVAILABLE" in out and "ABCDE1234F" not in out   # no value read from a page is printed

    # Run again: what was read is not read again; what failed is.
    calls.clear()
    lite_fails["on"] = False
    assert await trial.run(request, transport=httpx.MockTransport(handler)) == 0
    assert calls == ["gemini-3.1-flash-lite-preview:generateContent"] * 2
    oks = (await db_session.execute(text(
        "SELECT count(*) FILTER (WHERE ok), count(*) FROM di_trials.result WHERE run = :run"), {"run": run_label})).one()
    assert tuple(oks) == (4, 4)
    await db_session.execute(text("DELETE FROM di_trials.result WHERE run = :run"), {"run": run_label})
    await db_session.execute(text("DELETE FROM di_trials.sample WHERE run = :run"), {"run": run_label})
    await db_session.commit()
    await engine.dispose()
