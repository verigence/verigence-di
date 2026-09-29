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

from dataclasses import asdict, dataclass
from typing import Any

MAX_TOKENS_FINISH_REASON = "MAX_TOKENS"

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
