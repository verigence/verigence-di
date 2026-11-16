"""Gemini request settings and token accounting shared by classification and
extraction.

Cost facts this module encodes (Gemini 3 Flash):

- Output tokens cost several times input tokens, and *thinking* tokens are
  billed as output. Gemini 3 thinks at a HIGH level unless told otherwise, so
  every call sets an explicit ``thinkingLevel`` (settings, default MINIMAL for
  classification and LOW for extraction).
- ``candidatesTokenCount`` excludes thinking; ``thoughtsTokenCount`` carries
  it. Both are recorded so the real billed output is visible per call.
- ``maxOutputTokens`` caps one answer (thinking included) so a runaway
  response cannot bill without bound; ``finishReason == MAX_TOKENS`` marks a
  truncated answer.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

MAX_TOKENS_FINISH_REASON = "MAX_TOKENS"

# The Gemini service tier of the call being made (12 Nov 2026, migration 0067). The worker
# sets it around one job's call; every request built in that task reads it.
STANDARD_TIER = "STANDARD"
FLEX_TIER = "FLEX"
GEMINI_TIER: ContextVar[str] = ContextVar("gemini_tier", default=STANDARD_TIER)


def apply_service_tier(body: dict[str, Any]) -> str:
    """Ask for the Flex tier (half price, answered in minutes) when the job asks for it."""
    tier = GEMINI_TIER.get()
    if tier == FLEX_TIER:
        body["service_tier"] = "flex"
    return tier


def tier_timeout(standard_seconds: float, flex_seconds: float) -> float:
    """A Flex request may wait in Google's queue: it gets the longer wait."""
    return flex_seconds if GEMINI_TIER.get() == FLEX_TIER else standard_seconds


def first_attempt_tier(upload_tier: str | None, first_attempt: bool) -> str:
    """Flex on an upload's first try only: a retry goes to the standard tier."""
    return FLEX_TIER if upload_tier == FLEX_TIER and first_attempt else STANDARD_TIER

# What a call costs (product owner 2026-11-16: "capture the cost"). US$ per million
# tokens (input, output) on the Gemini Developer API paid tier, by model and service
# tier, as Google's price list stood on 2026-11-16; output includes thinking tokens.
# A call is priced once, when it is made, and keeps that cost: a later price change
# is a new entry here and never re-prices history. A model with no entry has no cost
# (None), never a guessed one.
PRICES_USD_PER_MTOK: dict[str, dict[str, tuple[Decimal, Decimal]]] = {
    "gemini-3-flash-preview": {
        STANDARD_TIER: (Decimal("0.50"), Decimal("3.00")),
        FLEX_TIER: (Decimal("0.25"), Decimal("1.50")),
    },
}
# Cached input is billed at a tenth of the input price.
_CACHED_INPUT_SHARE = Decimal("0.1")
_MTOK = Decimal(1_000_000)

# The provider calls of the job in hand, one entry per answered call (failed
# answers included: a refused or unusable answer is billed too). The worker opens
# it around a job and stores what it holds; nothing is collected when it is closed.
AI_USAGE_SINK: ContextVar[list[dict[str, Any]] | None] = ContextVar("ai_usage_sink", default=None)


def price_per_mtok(model: str, tier: str) -> tuple[Decimal, Decimal] | None:
    """(input, output) US$ per million tokens, or None when the model is not priced."""
    tiers = PRICES_USD_PER_MTOK.get(model)
    if not tiers:
        return None
    return tiers.get(tier) or tiers.get(STANDARD_TIER)


def billed_output(prompt_tokens: int, response_tokens: int, thoughts_tokens: int, total_tokens: int) -> int:
    """Output tokens as billed: the answer and the thinking behind it. When the
    provider's total exceeds prompt + answer + reported thinking, the rest was
    produced too and is counted (the larger figure, so cost is never understated)."""
    return max(response_tokens + thoughts_tokens, total_tokens - prompt_tokens, 0)


def cost_usd(
    model: str, tier: str, *, prompt_tokens: int, response_tokens: int, thoughts_tokens: int = 0,
    total_tokens: int = 0, cached_tokens: int = 0,
) -> float | None:
    """What one call costs at list price, or None for a model with no price here."""
    price = price_per_mtok(model, tier)
    if price is None:
        return None
    price_in, price_out = price
    cached = min(max(cached_tokens, 0), max(prompt_tokens, 0))
    fresh = max(prompt_tokens, 0) - cached
    output = billed_output(prompt_tokens, response_tokens, thoughts_tokens, total_tokens)
    cost = (Decimal(fresh) * price_in + Decimal(cached) * price_in * _CACHED_INPUT_SHARE
            + Decimal(output) * price_out) / _MTOK
    return float(round(cost, 6))


def call_metrics(model: str, usage: GeminiUsage) -> dict[str, Any]:
    """One answered provider call as it is billed: tokens, tier, prices, cost."""
    price = price_per_mtok(model, usage.service_tier)
    return {
        "model": model,
        "service_tier": usage.service_tier,
        "prompt_tokens": usage.prompt_tokens,
        "response_tokens": usage.response_tokens,
        "thoughts_tokens": usage.thoughts_tokens,
        "cached_tokens": usage.cached_tokens,
        "total_tokens": usage.total_tokens,
        "billed_output_tokens": billed_output(
            usage.prompt_tokens, usage.response_tokens, usage.thoughts_tokens, usage.total_tokens),
        "price_input_per_mtok": float(price[0]) if price else None,
        "price_output_per_mtok": float(price[1]) if price else None,
        "cost_usd": cost_usd(
            model, usage.service_tier, prompt_tokens=usage.prompt_tokens,
            response_tokens=usage.response_tokens, thoughts_tokens=usage.thoughts_tokens,
            total_tokens=usage.total_tokens, cached_tokens=usage.cached_tokens),
    }


def note_call(model: str, usage: GeminiUsage) -> dict[str, Any]:
    """Price an answered call and add it to the open sink, if a job opened one."""
    metrics = call_metrics(model, usage)
    sink = AI_USAGE_SINK.get()
    if sink is not None:
        sink.append(metrics)
    return metrics


def summarise_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Several calls of one job as one stored figure. ``cost_usd`` is None when any
    call's model has no price, so a partly priced total is never shown as the cost."""
    if not calls:
        return {}
    priced = [float(c["cost_usd"]) for c in calls if c.get("cost_usd") is not None]
    last = calls[-1]
    return {
        "model": last.get("model"),
        "service_tier": last.get("service_tier"),
        "provider_calls": len(calls),
        "billed_prompt_tokens": sum(_int(c.get("prompt_tokens")) for c in calls),
        "response_tokens": sum(_int(c.get("response_tokens")) for c in calls),
        "thoughts_tokens": sum(_int(c.get("thoughts_tokens")) for c in calls),
        "cached_tokens": sum(_int(c.get("cached_tokens")) for c in calls),
        "total_tokens": sum(_int(c.get("total_tokens")) for c in calls),
        "billed_output_tokens": sum(_int(c.get("billed_output_tokens")) for c in calls),
        "price_input_per_mtok": last.get("price_input_per_mtok"),
        "price_output_per_mtok": last.get("price_output_per_mtok"),
        "cost_usd": round(sum(priced), 6) if len(priced) == len(calls) else None,
    }


# Finish reasons meaning the provider refused the content itself: the same
# document at temperature 0 is refused again, so these are not retried.
BLOCKED_FINISH_REASONS = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY", "LANGUAGE"}
)


def generation_config(*, thinking_level: str, max_output_tokens: int) -> dict[str, Any]:
    """``generationConfig`` for a JSON answer at temperature 0."""
    config: dict[str, Any] = {
        "temperature": 0,
        "responseMimeType": "application/json",
    }
    if max_output_tokens > 0:
        config["maxOutputTokens"] = max_output_tokens
    if thinking_level:
        config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    return config


@dataclass(frozen=True)
class GeminiUsage:
    prompt_tokens: int = 0
    response_tokens: int = 0
    thoughts_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str | None = None
    block_reason: str | None = None
    response_id: str | None = None
    model_version: str | None = None
    service_tier: str = field(default_factory=GEMINI_TIER.get)

    @property
    def billed_output_tokens(self) -> int:
        """Output as billed: the answer plus the thinking behind it."""
        return self.response_tokens + self.thoughts_tokens

    @property
    def truncated(self) -> bool:
        return self.finish_reason == MAX_TOKENS_FINISH_REASON

    @property
    def blocked(self) -> bool:
        return self.block_reason is not None or self.finish_reason in BLOCKED_FINISH_REASONS

    def as_metrics(self) -> dict[str, Any]:
        return {**asdict(self), "billed_output_tokens": self.billed_output_tokens}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def usage_from_response(data: dict[str, Any]) -> GeminiUsage:
    usage = data.get("usageMetadata") or {}
    candidates = data.get("candidates") or []
    finish = candidates[0].get("finishReason") if candidates and isinstance(candidates[0], dict) else None
    feedback = data.get("promptFeedback") or {}
    block = feedback.get("blockReason") if isinstance(feedback, dict) else None
    return GeminiUsage(
        prompt_tokens=_int(usage.get("promptTokenCount")),
        response_tokens=_int(usage.get("candidatesTokenCount")),
        thoughts_tokens=_int(usage.get("thoughtsTokenCount")),
        cached_tokens=_int(usage.get("cachedContentTokenCount")),
        total_tokens=_int(usage.get("totalTokenCount")),
        finish_reason=str(finish) if finish else None,
        block_reason=str(block) if block else None,
        response_id=_str_or_none(data.get("responseId")),
        model_version=_str_or_none(data.get("modelVersion")),
    )


def _str_or_none(value: Any) -> str | None:
    return str(value)[:128] if isinstance(value, str) and value else None
