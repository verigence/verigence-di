"""Gemini cost controls: explicit thinking level, output cap, full token
accounting (thinking included), compact answers, truncation handling and
trusted single-candidate classification."""
from __future__ import annotations

import json
from typing import Any

import pytest

from verigence.di.api.v2.capture_documents import V2UploadIntentCommand
from verigence.di.document_ai import gemini_adapter, v2_classifier
from verigence.di.document_ai.adapter import ExtractionField
from verigence.di.document_ai.gemini_cost import (
    GeminiUsage,
    generation_config,
    usage_from_response,
)
from verigence.di.document_ai.schemas import get_schema
from verigence.di.settings import get_settings
from verigence.di.workers.capture_v2_classifier import trusted_single_candidate

pytestmark = pytest.mark.no_docker


def test_generation_config_sets_thinking_and_output_cap() -> None:
    config = generation_config(thinking_level="low", max_output_tokens=16384)
    assert config["thinkingConfig"] == {"thinkingLevel": "low"}
    assert config["maxOutputTokens"] == 16384
    assert config["temperature"] == 0 and config["responseMimeType"] == "application/json"
    assert "thinkingConfig" not in generation_config(thinking_level="", max_output_tokens=0)
    assert "maxOutputTokens" not in generation_config(thinking_level="", max_output_tokens=0)


def test_usage_counts_thinking_as_billed_output() -> None:
    usage = usage_from_response({
        "candidates": [{"finishReason": "MAX_TOKENS"}],
        "usageMetadata": {"promptTokenCount": 1800, "candidatesTokenCount": 900,
                          "thoughtsTokenCount": 3100, "totalTokenCount": 5800},
    })
    assert usage.billed_output_tokens == 4000
    assert usage.truncated is True
    assert usage.as_metrics()["thoughts_tokens"] == 3100
    assert usage_from_response({}).billed_output_tokens == 0


def test_settings_default_to_low_cost_thinking() -> None:
    settings = get_settings()
    assert settings.docai_gemini_classification_thinking_level == "minimal"
    assert settings.docai_gemini_extraction_thinking_level == "low"
    assert settings.docai_gemini_max_output_tokens > 0
    with pytest.raises(ValueError):
        type(settings)(docai_gemini_extraction_thinking_level="extreme")


def test_extraction_payload_uses_the_extraction_thinking_level() -> None:
    payload = gemini_adapter._build_payload(b"x", "application/pdf", "prompt")
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    authoring = gemini_adapter._build_payload(b"x", "application/pdf", "prompt", thinking_level="")
    assert "thinkingConfig" not in authoring["generationConfig"]


def test_prompt_asks_for_found_fields_only() -> None:
    prompt = gemini_adapter._build_prompt(
        get_schema("booking_form"),
        [ExtractionField(field_key="customer_name"), ExtractionField(field_key="booking_date")],
    )
    assert "Include ONLY the fields whose value you found" in prompt
    assert "never return null placeholders" in prompt
    assert '"value": null' not in prompt
    assert "|null" not in prompt


def test_missing_fields_are_not_found_and_null_is_still_accepted() -> None:
    fields = [ExtractionField(field_key="customer_name"), ExtractionField(field_key="booking_date"),
              ExtractionField(field_key="booking_amount_paid")]
    raw = json.dumps({
        "customer_name": {"value": "A", "confidence": "high"},
        "booking_date": {"value": None, "confidence": "low", "pageNo": None, "box_2d": None},
    })
    results = {r.field_key: r for r in gemini_adapter._parse_response(raw, get_schema("booking_form"), fields)}
    assert results["customer_name"].found_status.value == "FOUND"
    assert results["customer_name"].page_no is None and results["customer_name"].evidence_region is None
    assert results["booking_date"].found_status.value == "NOT_FOUND"
    assert results["booking_amount_paid"].found_status.value == "NOT_FOUND"


@pytest.mark.asyncio
async def test_a_truncated_answer_is_one_request_and_a_retryable_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """No request is retried within five minutes (decision 2026-09-30): a
    truncated answer is not re-asked from inside the call; it fails as a
    retryable provider result and the job's own rules space the next
    attempt out."""
    calls: list[dict[str, Any]] = []

    async def fake_call(**kwargs: Any) -> tuple[str, int, int, int]:
        calls.append(kwargs)
        kwargs["on_usage"](GeminiUsage(prompt_tokens=1000, response_tokens=500, thoughts_tokens=15000,
                                       finish_reason="MAX_TOKENS"))
        return '{"customer_name": {"value": "A", "conf', 200, 1000, 500

    slept: list[float] = []

    async def no_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(gemini_adapter, "_call_gemini_instrumented", fake_call)
    monkeypatch.setattr(gemini_adapter.asyncio, "sleep", no_sleep)
    adapter = gemini_adapter.GeminiDocumentAIAdapter("AQ.test")
    with pytest.raises(gemini_adapter.GeminiResponseInvalidError) as raised:
        await adapter.extract(b"pdf", "application/pdf", [ExtractionField(field_key="customer_name")],
                              document_type_key="booking_form")

    assert raised.value.retryable is True
    assert len(calls) == 1 and calls[0]["thinking_level"] == "low"
    assert calls[0]["max_output_tokens"] == get_settings().docai_gemini_max_output_tokens
    assert slept == []


async def _no_sleep(_: float) -> None:
    return None


class _Response:
    status_code = 200

    def json(self) -> dict[str, Any]:
        return {
            "candidates": [{"content": {"parts": [{"text": '{"documentTypeKey": "pan_card", "confidence": 97}'}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 700, "candidatesTokenCount": 12, "thoughtsTokenCount": 0},
        }


class _Client:
    body: dict[str, Any] = {}

    async def post(self, url: str, **kwargs: Any) -> _Response:
        type(self).body = kwargs["json"]
        return _Response()


@pytest.mark.asyncio
async def test_classification_uses_minimal_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "docai_mock", False)

    async def client() -> _Client:
        return _Client()

    monkeypatch.setattr(v2_classifier, "_gemini_client", client)
    result = await v2_classifier.classify_document_v2(
        document_bytes=b"not-a-pdf", mime_type="application/octet-stream",
        candidates=[("pan_card", "PAN Card"), ("aadhaar", "Aadhaar")],
    )
    assert result.document_type_key == "pan_card"
    config = _Client.body["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert config["maxOutputTokens"] <= 2048


def test_only_an_explicit_single_candidate_is_trusted() -> None:
    assert trusted_single_candidate("TRUST_SINGLE_CANDIDATE", ["booking_form"]) == "booking_form"
    assert trusted_single_candidate("TRUST_SINGLE_CANDIDATE", ["booking_form", "pan_card"]) is None
    assert trusted_single_candidate("TRUST_SINGLE_CANDIDATE", []) is None
    assert trusted_single_candidate("CLASSIFY", ["booking_form"]) is None


def test_upload_intent_defaults_to_classifying() -> None:
    base = {"phase": "BOOKING", "candidateDocumentTypeKeys": ["booking_form"],
            "files": [{"clientUploadId": "c1", "filename": "a.pdf"}]}
    assert V2UploadIntentCommand(**base).classificationMode == "CLASSIFY"
    assert V2UploadIntentCommand(**base, classificationMode="TRUST_SINGLE_CANDIDATE").classificationMode \
        == "TRUST_SINGLE_CANDIDATE"
    with pytest.raises(ValueError):
        V2UploadIntentCommand(**base, classificationMode="GUESS")
