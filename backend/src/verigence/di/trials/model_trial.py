"""A model trial: the same stored documents read again by more than one Gemini model.

Product owner, 21 Nov 2026: "i want to bring AI cost down while making sure quality improves",
and of a cheaper model: "let me know which model can be used for PAN, Aadhar, Money Receipts,
RTO, can we have insurance as well, but insurance formats are quite different".

Which model can read which paper is a question for the papers themselves. This reads a chosen
sample of documents already in Verigence once per model, each exactly as the worker reads it
(the same stored page, the same capped image, the same prompt from the same extraction profile,
the same answer parser), and keeps what each model said. The model in use is one of the arms, so
every comparison is between two reads made the same way on the same day.

It changes nothing a person sees. It reads docintel and the document store, and writes only to
``di_trials.result``. The sample (``di_trials.sample``) is chosen beforehand, by document id, and
the comparing is done afterwards in the database; nothing here prints a value read from a page,
because this repository's workflow logs are public.

For each read it keeps: the fields as parsed (value, a normalised form to compare by, found or
not, confidence), the tokens billed, the seconds taken, and two checks that need no model: a
PAN's shape and an Aadhaar number's check digit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import structlog
from sqlalchemy import text

from verigence.di.document_ai import gemini_adapter
from verigence.di.document_ai.adapter import ExtractionField, FieldResult
from verigence.di.document_ai.gemini_cost import usage_from_response
from verigence.di.document_ai.schemas import get_schema

logger = structlog.get_logger(__name__)

_API = "https://generativelanguage.googleapis.com/v1beta"
STANDARD = "STANDARD"
FLEX = "FLEX"


# ── What is compared ─────────────────────────────────────────────────────────
_AMOUNT = re.compile(r"^(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*)(?:\.([0-9]{1,2}))?\s*(?:/-)?$", re.IGNORECASE)


def normalise(value: object) -> str:
    """The form two reads are compared in: an amount as its number ("1,25,000.00/-" and
    "125000" are the same amount), anything else as its letters and digits in upper case
    (spacing, punctuation and case are not a difference between two reads)."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    amount = _AMOUNT.match(raw)
    if amount:
        whole = amount.group(1).replace(",", "").lstrip("0") or "0"
        paise = (amount.group(2) or "").rstrip("0")
        return f"{whole}.{paise}" if paise else whole
    return re.sub(r"[^A-Z0-9]", "", raw.upper())


_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

# Verhoeff: the check digit every Aadhaar number carries.
_D = ((0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5), (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
      (3, 4, 0, 1, 2, 8, 9, 5, 6, 7), (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
      (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3), (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
      (9, 8, 7, 6, 5, 4, 3, 2, 1, 0))
_P = ((0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4), (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
      (8, 9, 1, 6, 0, 4, 3, 5, 2, 7), (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
      (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8))


def pan_shape_ok(value: object) -> bool | None:
    """Whether a PAN read has a PAN's shape; None when nothing was read."""
    pan = normalise(value)
    return bool(_PAN.match(pan)) if pan else None


def aadhaar_check_ok(value: object) -> bool | None:
    """Whether an Aadhaar number read passes its own check digit. None when nothing was read
    or the number is masked (XXXX XXXX 1234), which cannot be checked."""
    raw = str(value or "")
    if not raw.strip():
        return None
    if re.search(r"[xX*]", raw):
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 12:
        return False
    check = 0
    for position, digit in enumerate(reversed(digits)):
        check = _D[check][_P[position % 8][int(digit)]]
    return check == 0


_CHECKS = {"pan_number": pan_shape_ok, "aadhaar_number": aadhaar_check_ok}


def checks_for(fields: dict[str, dict[str, Any]]) -> dict[str, bool]:
    """The checks that apply to the fields a read produced, by field name."""
    out: dict[str, bool] = {}
    for key, entry in fields.items():
        for needle, check in _CHECKS.items():
            if needle in key.lower():
                verdict = check(entry.get("value"))
                if verdict is not None:
                    out[key] = verdict
    return out


# ── Which models ─────────────────────────────────────────────────────────────
def pick_models(available: list[str], wanted: list[str]) -> dict[str, str | None]:
    """The model name to call for each one asked for: itself when the key can use it, else the
    shortest available name that starts with it ("gemini-3.1-flash-lite" also finds
    "gemini-3.1-flash-lite-preview"), else None."""
    names = sorted({name.removeprefix("models/") for name in available})
    chosen: dict[str, str | None] = {}
    for want in wanted:
        if want in names:
            chosen[want] = want
            continue
        starts = sorted((n for n in names if n.startswith(want)), key=lambda n: (len(n), n))
        chosen[want] = starts[0] if starts else None
    return chosen


async def list_models(client: httpx.AsyncClient, api_key: str) -> list[str]:
    """Every model this key may ask to generate content."""
    names: list[str] = []
    token: str | None = None
    for _ in range(20):
        params: dict[str, str | int] = {"pageSize": 200}
        if token:
            params["pageToken"] = token
        resp = await client.get(f"{_API}/models", headers={"x-goog-api-key": api_key}, params=params)
        resp.raise_for_status()
        body = resp.json()
        for model in body.get("models") or []:
            if "generateContent" in (model.get("supportedGenerationMethods") or []):
                names.append(str(model.get("name") or ""))
        token = body.get("nextPageToken")
        if not token:
            break
    return names


# ── One read ─────────────────────────────────────────────────────────────────
@dataclass
class Read:
    """What one model made of one document."""

    ok: bool
    error_code: str | None = None
    error_detail: str | None = None
    http_status: int = 0
    duration_ms: float = 0.0
    prompt_tokens: int = 0
    response_tokens: int = 0
    thoughts_tokens: int = 0
    cached_tokens: int = 0
    thinking: str = ""
    tier: str = STANDARD
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)


def _as_fields(results: list[FieldResult]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for result in results:
        confidence = result.confidence
        out[result.field_key] = {
            "found": str(getattr(result.found_status, "value", result.found_status)),
            "value": result.raw_value,
            "norm": normalise(result.raw_value),
            "confidence": float(confidence) if isinstance(confidence, Decimal) else None,
            "page": result.page_no,
        }
    return out


def _refuses(detail: str, *names: str) -> bool:
    """Whether a refused request (HTTP 400) names one of these settings as the reason."""
    lowered = detail.lower()
    return any(name.lower() in lowered for name in names)


# A busy or briefly failing provider is asked again, a little later each time: the live system
# shares this key, so the trial steps back instead of pushing.
BUSY = {429, 500, 502, 503, 504}
WAITS = (15.0, 45.0, 90.0)


async def read_with_model(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    artifact_bytes: bytes,
    mime_type: str,
    prompt: str,
    document_type_key: str,
    fields: list[ExtractionField],
    thinking_level: str,
    max_output_tokens: int,
    tier: str,
    timeout: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Read:
    """One document read by one model, with the worker's own request and answer parser.

    A model that refuses the thinking setting, or the Flex tier, is asked once more without it,
    and the read says which it was read with: a trial must not lose a model to a setting only
    the model in use knows."""
    schema = get_schema(document_type_key)
    thinking, asked_tier = thinking_level, tier
    started = time.monotonic()
    read = Read(ok=False, thinking=thinking, tier=asked_tier)
    waits = list(WAITS)
    for _ in range(len(WAITS) + 3):
        read.error_code = read.error_detail = None
        payload = gemini_adapter._build_payload(  # noqa: SLF001 - the worker's own request, on purpose
            artifact_bytes, mime_type, prompt, thinking_level=thinking,
            max_output_tokens=max_output_tokens, media_resolution=schema.media_resolution,
        )
        if asked_tier == FLEX:
            payload["service_tier"] = "flex"
        try:
            resp = await client.post(
                f"{_API}/models/{model}:generateContent", headers={"x-goog-api-key": api_key},
                json=payload, timeout=timeout,
            )
        except httpx.TimeoutException:
            read.error_code = "TIMEOUT"
            break
        except httpx.HTTPError as exc:
            read.error_code = f"TRANSPORT_{type(exc).__name__}"
            break
        read.http_status = resp.status_code
        if resp.status_code == 400:
            detail = resp.text[:600]
            if thinking and _refuses(detail, "thinking"):
                thinking = ""
                continue
            if asked_tier == FLEX and _refuses(detail, "service_tier", "service tier", "flex"):
                asked_tier = STANDARD
                continue
        if resp.status_code in BUSY and waits:
            await sleep(waits.pop(0))
            continue
        if resp.status_code != 200:
            read.error_code = f"HTTP_{resp.status_code}"
            read.error_detail = _provider_message(resp)
            break
        try:
            body = resp.json()
            usage = usage_from_response(body)
            read.prompt_tokens, read.response_tokens = usage.prompt_tokens, usage.response_tokens
            read.thoughts_tokens, read.cached_tokens = usage.thoughts_tokens, usage.cached_tokens
            if usage.blocked:
                read.error_code = "CONTENT_BLOCKED"
                break
            raw = body["candidates"][0]["content"]["parts"][0]["text"]
            read.fields = _as_fields(gemini_adapter._parse_response(raw, schema, fields))  # noqa: SLF001
            read.ok = True
        except Exception as exc:  # noqa: BLE001 - whatever the answer was, it could not be used
            read.error_code = "ANSWER_UNUSABLE"
            read.error_detail = type(exc).__name__
        break
    read.thinking, read.tier = thinking, asked_tier
    read.duration_ms = round((time.monotonic() - started) * 1000, 1)
    return read


def _provider_message(resp: httpx.Response) -> str:
    """The provider's own words for a refusal (about the request, never about the page)."""
    try:
        return str(resp.json()["error"]["message"])[:300]
    except Exception:  # noqa: BLE001
        return resp.text[:300]


# ── The run ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Request:
    run: str
    models: list[str]
    concurrency: int = 4
    tier: str = STANDARD
    limit: int = 0

    @staticmethod
    def load(path: Path) -> Request:
        data = json.loads(path.read_text())
        run = str(data["run"]).strip()
        models = [str(m).strip() for m in data["models"] if str(m).strip()]
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,60}", run) or not models:
            raise ValueError("a trial request needs a run label and at least one model")
        tier = str(data.get("tier") or STANDARD).upper()
        if tier not in {STANDARD, FLEX}:
            raise ValueError("tier is STANDARD or FLEX")
        return Request(run=run, models=models, concurrency=max(1, min(int(data.get("concurrency") or 4), 8)),
                       tier=tier, limit=max(0, int(data.get("limit") or 0)))


_SAMPLE_SQL = text("""
    SELECT s.tenant_id, s.document_id, s.document_type_key
    FROM di_trials.sample s
    WHERE s.run = :run
    ORDER BY md5(s.document_id::text)   -- a fixed order that mixes the types, so a first few covers them all
""")
_DONE_SQL = text("SELECT document_id, model FROM di_trials.result WHERE run = :run AND ok")
_DOCUMENT_SQL = text("""
    SELECT r.extraction_profile_id, dt.document_type_key
    FROM docintel.documents d
    JOIN docintel.processing_runs r
      ON r.tenant_id = d.tenant_id AND r.processing_run_id = d.current_processing_run_id
    JOIN docintel.document_types dt ON dt.document_type_id = d.document_type_id
    WHERE d.tenant_id = :tid AND d.document_id = :doc
""")
_INSERT_SQL = text("""
    INSERT INTO di_trials.result (run, tenant_id, document_id, document_type_key, model, asked_model, tier,
        thinking, ok, error_code, error_detail, http_status, duration_ms, prompt_tokens, response_tokens,
        thoughts_tokens, cached_tokens, fields, checks)
    VALUES (:run, :tid, :doc, :dtk, :model, :asked, :tier, :thinking, :ok, :error, :detail, :status, :ms,
        :pin, :pout, :pthink, :pcached, CAST(:fields AS jsonb), CAST(:checks AS jsonb))
    ON CONFLICT (run, document_id, model) DO UPDATE SET
        tier = EXCLUDED.tier, thinking = EXCLUDED.thinking, ok = EXCLUDED.ok, error_code = EXCLUDED.error_code,
        error_detail = EXCLUDED.error_detail, http_status = EXCLUDED.http_status,
        duration_ms = EXCLUDED.duration_ms, prompt_tokens = EXCLUDED.prompt_tokens,
        response_tokens = EXCLUDED.response_tokens, thoughts_tokens = EXCLUDED.thoughts_tokens,
        cached_tokens = EXCLUDED.cached_tokens, fields = EXCLUDED.fields, checks = EXCLUDED.checks,
        created_at_utc = now()
    WHERE NOT di_trials.result.ok
""")


@dataclass(frozen=True)
class Page:
    """One stored document made ready to be read, exactly as the worker makes it ready."""

    document_type_key: str
    fields: list[ExtractionField]
    image: bytes
    mime_type: str
    prompt: str


async def load_page(tenant_id: str, document_id: uuid.UUID) -> Page | None:
    """The stored page, the fields its extraction profile asks for and the prompt built from
    them, with the worker's own loaders. None when the document is no longer there."""
    from verigence.di.repositories.database import AsyncSessionFactory, set_tenant_context
    from verigence.di.settings import get_settings
    from verigence.di.workers.job_runner import (
        _load_original_artifact,
        _load_profile_fields,
        _provider_field_key,
    )

    async with AsyncSessionFactory() as session, session.begin():
        await set_tenant_context(session, tenant_id)
        row = (await session.execute(_DOCUMENT_SQL, {"tid": tenant_id, "doc": document_id})).first()
        if row is None:
            return None
        profile_fields = await _load_profile_fields(session, row[0])
        data, stored_mime = await _load_original_artifact(session, tenant_id, document_id)
    fields = [
        ExtractionField(field_key=_provider_field_key(pf), aliases=pf.get("aliases") or [],
                        instruction=pf.get("extraction_instruction"))
        for pf in profile_fields
    ]
    type_key = str(row[1])
    image, mime = gemini_adapter.capped_image(data, stored_mime, get_settings().docai_gemini_extraction_max_edge)
    prompt = gemini_adapter._build_prompt(get_schema(type_key), fields)  # noqa: SLF001
    return Page(document_type_key=type_key, fields=fields, image=image, mime_type=mime, prompt=prompt)


async def run(request: Request, *, transport: httpx.AsyncBaseTransport | None = None) -> int:
    """Read the run's sample with each model it asks for. Returns the process exit code.

    It can be run again: a document a model has already read is not read again, and a read
    that failed is made again."""
    from verigence.di.repositories.database import AsyncSessionFactory
    from verigence.di.settings import get_settings

    settings = get_settings()
    api_key = settings.docai_gemini_api_key
    if not api_key:
        print("MODEL_TRIAL=FAIL reason=NO_API_KEY", flush=True)
        return 2
    limits = httpx.Limits(max_connections=request.concurrency * 2)

    async with httpx.AsyncClient(limits=limits, timeout=60.0, transport=transport) as client:
        available = await list_models(client, api_key)
        for name in sorted(n.removeprefix("models/") for n in available if "flash" in n):
            print(f"MODEL_TRIAL_AVAILABLE model={name}", flush=True)
        chosen = pick_models(available, request.models)
        for want, model in chosen.items():
            print(f"MODEL_TRIAL_MODEL asked={want} uses={model or 'NOT_AVAILABLE'}", flush=True)
        arms = [(want, model) for want, model in chosen.items() if model]
        if not arms:
            print("MODEL_TRIAL=FAIL reason=NO_MODEL_AVAILABLE", flush=True)
            return 2

        async with AsyncSessionFactory() as session:
            sample = (await session.execute(_SAMPLE_SQL, {"run": request.run})).all()
            done = {(str(r[0]), str(r[1])) for r in (await session.execute(_DONE_SQL, {"run": request.run})).all()}
        if request.limit:
            sample = sample[: request.limit]
        print(f"MODEL_TRIAL_SAMPLE documents={len(sample)} arms={len(arms)} already_read={len(done)}", flush=True)
        if not sample:
            print("MODEL_TRIAL=FAIL reason=EMPTY_SAMPLE", flush=True)
            return 2

        gate = asyncio.Semaphore(request.concurrency)
        tally: Counter[tuple[str, str]] = Counter()
        tokens: Counter[tuple[str, str]] = Counter()
        timeout = float(settings.docai_gemini_flex_timeout_seconds) if request.tier == FLEX else 120.0

        async def one(tenant_id: str, document_id: uuid.UUID) -> None:
            todo = [(want, model) for want, model in arms if (str(document_id), model) not in done]
            if not todo:
                return
            async with gate:
                try:
                    page = await load_page(tenant_id, document_id)
                except Exception as exc:  # noqa: BLE001 - one document that cannot be loaded is counted, not fatal
                    tally[("-", f"LOAD_{type(exc).__name__}")] += 1
                    return
                if page is None:
                    tally[("-", "DOCUMENT_NOT_FOUND")] += 1
                    return
                for want, model in todo:
                    read = await read_with_model(
                        client, api_key=api_key, model=model, artifact_bytes=page.image,
                        mime_type=page.mime_type, prompt=page.prompt,
                        document_type_key=page.document_type_key, fields=page.fields,
                        thinking_level=settings.docai_gemini_extraction_thinking_level,
                        max_output_tokens=settings.docai_gemini_max_output_tokens,
                        tier=request.tier, timeout=timeout,
                    )
                    async with AsyncSessionFactory() as session, session.begin():
                        await session.execute(_INSERT_SQL, {
                            "run": request.run, "tid": tenant_id, "doc": document_id,
                            "dtk": page.document_type_key, "model": model, "asked": want, "tier": read.tier,
                            "thinking": read.thinking, "ok": read.ok, "error": read.error_code,
                            "detail": read.error_detail, "status": read.http_status, "ms": read.duration_ms,
                            "pin": read.prompt_tokens, "pout": read.response_tokens,
                            "pthink": read.thoughts_tokens, "pcached": read.cached_tokens,
                            "fields": json.dumps(read.fields), "checks": json.dumps(checks_for(read.fields)),
                        })
                    tally[(model, "OK" if read.ok else str(read.error_code))] += 1
                    tokens[(model, "in")] += read.prompt_tokens
                    tokens[(model, "out")] += read.response_tokens + read.thoughts_tokens

        await asyncio.gather(*(one(str(r[0]), r[1]) for r in sample))

    for (model, outcome), count in sorted(tally.items()):
        print(f"MODEL_TRIAL_READS model={model} outcome={outcome} count={count}", flush=True)
    for _, model in arms:
        print(f"MODEL_TRIAL_TOKENS model={model} in={tokens[(model, 'in')]} out={tokens[(model, 'out')]}", flush=True)
    print("MODEL_TRIAL=DONE", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read a chosen sample of stored documents with several models.")
    parser.add_argument("request", type=Path, help="the trial request (JSON): run, models, concurrency, tier")
    args = parser.parse_args(argv)
    return asyncio.run(run(Request.load(args.request)))


if __name__ == "__main__":
    sys.exit(main())
