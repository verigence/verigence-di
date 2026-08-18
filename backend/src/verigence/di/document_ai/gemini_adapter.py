"""document_ai/gemini_adapter.py — Gemini 2.5 Flash Document AI adapter.

D19: Gemini 2.5 Flash replaces Azure Document Intelligence as the production
     OCR/extraction provider.
D20: Uses Document Schema Registry to look up per-type extraction schemas
     and Gemini system prompts.
D21: extract() sends document bytes + schema-driven prompt to Gemini and
     maps the response to FieldResult[].
D22: extract() accepts physical_form_type and document_type_key kwargs.

classify() is pass-through — the document_type_hint_key supplied at upload
is accepted at confidence 100. No Gemini API call is made for classification.

extract() flow:
  1. get_schema(document_type_key) → SchemaDefinition
  2. Build prompt from schema fields + system_prompt + prompt_notes
  3. Send document bytes (image or PDF) + prompt to Gemini REST API (httpx)
  4. Parse and validate JSON response
  5. On parse failure: retry once; on second failure return NOT_FOUND for all
     fields (document reaches NEEDS_REVIEW, pipeline does not crash)
  6. Map confidence: "high"→92.00, "medium"→70.00, "low"→40.00
  7. Return AIInvocationResult with FieldResult[]

Confidence mapping (D21):
  "high"   → Decimal("92.00")
  "medium" → Decimal("70.00")
  "low"    → Decimal("40.00")
  absent   → FoundStatus.NOT_FOUND, confidence=None

Uses direct REST API (httpx) — no google.generativeai SDK dependency.
"""
from __future__ import annotations

import base64
import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import structlog

from verigence.di.document_ai.adapter import (
    AIInvocationResult,
    ClassificationCandidate,
    DocumentAIAdapter,
    ExtractionField,
    FieldResult,
)
from verigence.di.document_ai.schemas import get_schema
from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition
from verigence.di.domain.enums import AICapability, FoundStatus

logger = structlog.get_logger(__name__)

# Confidence string → numeric score mapping (D21)
_CONFIDENCE_MAP: dict[str, Decimal] = {
    "high":   Decimal("92.00"),
    "medium": Decimal("70.00"),
    "low":    Decimal("40.00"),
}

# Gemini REST API endpoint — gemini-3-flash-preview used for this key
_GEMINI_MODEL = "gemini-3-flash-preview"
_GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{_GEMINI_MODEL}:generateContent"
)


class GeminiDocumentAIAdapter(DocumentAIAdapter):
    """Gemini 2.5 Flash document AI adapter.

    Requires:
        api_key: Google AI Studio API key (DI_DOCAI_GEMINI_API_KEY)

    Mock mode (DI_DOCAI_MOCK=true) uses MockDocumentAIAdapter instead —
    this class is never instantiated in CI or local dev.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def adapter_key(self) -> str:
        return "gemini_2_5_flash_v1"

    # ── classify() ────────────────────────────────────────────────────────────

    async def classify(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        candidate_type_keys: list[str],
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        """Pass-through classification — hint key accepted at confidence 100.

        No Gemini API call is made. Classification is resolved at upload time
        from the caller-supplied documentTypeKey (D21).
        """
        chosen = hint or (candidate_type_keys[0] if candidate_type_keys else "UNKNOWN")
        return AIInvocationResult(
            capability=AICapability.CLASSIFICATION,
            adapter_key=self.adapter_key,
            provider_request_id=str(uuid.uuid4()),
            results=[
                ClassificationCandidate(
                    document_type_key=chosen,
                    confidence=Decimal("100.00"),
                    method="GEMINI_HINT_PASSTHROUGH",
                    raw_provider_response={"hint": hint},
                )
            ],
            usage_metrics={"pages": 0, "api_calls": 0},
        )

    # ── extract() ─────────────────────────────────────────────────────────────

    async def extract(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        fields: list[ExtractionField],
        correlation_id: str | None = None,
        physical_form_type: str = "PRINTABLE",
        document_type_key: str | None = None,
    ) -> AIInvocationResult:
        """Extract fields via Gemini 2.5 Flash using schema registry.

        Looks up the SchemaDefinition for document_type_key, builds a
        schema-driven prompt, calls Gemini REST API, validates the response.
        Falls back to FALLBACK_SCHEMA for unregistered types.
        """
        import time as _t
        log = logger.bind(
            adapter=self.adapter_key,
            document_type_key=document_type_key,
            physical_form_type=physical_form_type,
            correlation_id=correlation_id,
        )

        schema = get_schema(document_type_key or "")
        required_count = sum(1 for f in schema.fields if f.required)

        # Build the prompt — merge DB field list with schema registry metadata
        prompt = _build_prompt(schema, fields)

        log.debug("gemini_prompt", document_type_key=document_type_key, prompt=prompt)
        log.info(
            "gemini_request",
            document_type_key=document_type_key,
            physical_form_type=physical_form_type,
            gemini_model=_GEMINI_MODEL,
            file_bytes=len(artifact_bytes),
            file_mime=mime_type,
            schema_field_count=len(fields),
            required_field_count=required_count,
        )

        # Call Gemini REST API — retry once on parse failure
        provider_request_id = str(uuid.uuid4())
        raw_response: str | None = None
        field_results: list[FieldResult] | None = None
        last_error: str | None = None
        _call_start = _t.monotonic()
        _prompt_tokens = 0
        _response_tokens = 0
        _http_status = 0

        for attempt in range(2):
            try:
                raw_response, _http_status, _prompt_tokens, _response_tokens = (
                    await _call_gemini_instrumented(
                        api_key=self._api_key,
                        artifact_bytes=artifact_bytes,
                        mime_type=mime_type,
                        prompt=prompt,
                    )
                )
                log.debug(
                    "gemini_raw_response",
                    document_type_key=document_type_key,
                    raw_response=raw_response,
                )
                field_results = _parse_response(raw_response, schema, fields)
                break
            except json.JSONDecodeError as exc:
                last_error = str(exc)
                log.warning(
                    "gemini_parse_failure",
                    document_type_key=document_type_key,
                    attempt=attempt + 1,
                    parse_error=last_error,
                    raw_snippet=(raw_response or "")[:300],
                )
                if attempt == 0:
                    log.warning(
                        "gemini_retry",
                        document_type_key=document_type_key,
                        attempt=attempt + 1,
                        reason="parse_failure",
                    )
                    continue
                field_results = _make_not_found_results(fields)
            except Exception as exc:
                last_error = str(exc)
                log.error(
                    "gemini_api_error",
                    document_type_key=document_type_key,
                    gemini_model=_GEMINI_MODEL,
                    http_status=_http_status,
                    exc_type=type(exc).__name__,
                    exc_msg=last_error,
                    duration_ms=round((_t.monotonic() - _call_start) * 1000, 1),
                )
                if attempt == 0:
                    log.warning(
                        "gemini_retry",
                        document_type_key=document_type_key,
                        attempt=attempt + 1,
                        reason="api_error",
                    )
                    continue
                field_results = _make_not_found_results(fields)

        if field_results is None:
            field_results = _make_not_found_results(fields)

        _duration_ms = round((_t.monotonic() - _call_start) * 1000, 1)
        _fields_found = sum(1 for fr in field_results if fr.found_status == FoundStatus.FOUND)
        _fields_null  = sum(1 for fr in field_results if fr.found_status != FoundStatus.FOUND)
        _fields_low   = sum(
            1 for fr in field_results
            if fr.confidence is not None and fr.confidence <= Decimal("40.00")
        )

        log.info(
            "gemini_response",
            document_type_key=document_type_key,
            gemini_model=_GEMINI_MODEL,
            http_status=_http_status,
            duration_ms=_duration_ms,
            prompt_tokens=_prompt_tokens,
            response_tokens=_response_tokens,
            fields_extracted=_fields_found,
            fields_null=_fields_null,
            fields_low_confidence=_fields_low,
        )

        if _fields_found == 0 and len(fields) > 0:
            log.warning(
                "gemini_all_fields_null",
                document_type_key=document_type_key,
                gemini_model=_GEMINI_MODEL,
                duration_ms=_duration_ms,
                likely_cause="empty_response" if not raw_response else "parse_failed_or_all_low",
            )

        for fr in field_results:
            log.debug(
                "gemini_field_detail",
                document_type_key=document_type_key,
                field_key=fr.field_key,
                raw_value=fr.raw_value,
                confidence_str=str(fr.confidence) if fr.confidence is not None else None,
            )

        usage: dict[str, Any] = {
            "model": _GEMINI_MODEL,
            "document_type_key": document_type_key,
            "schema_version": schema.schema_version,
            "fields_requested": len(fields),
            "fields_found": _fields_found,
            "prompt_tokens": _prompt_tokens,
            "response_tokens": _response_tokens,
            "duration_ms": _duration_ms,
        }

        return AIInvocationResult(
            capability=AICapability.VISION_EXTRACTION,
            adapter_key=self.adapter_key,
            provider_request_id=provider_request_id,
            results=field_results,
            usage_metrics=usage,
        )


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_prompt(schema: SchemaDefinition, db_fields: list[ExtractionField]) -> str:
    """Build the Gemini user message from schema + DB field list.

    Merges schema field metadata (type, required, enum, description) with
    DB field metadata (aliases, extraction_instruction).
    """
    # Build a lookup from schema fields by key
    schema_field_map: dict[str, FieldSpec] = {f.key: f for f in schema.fields}

    lines: list[str] = []
    if schema.system_prompt:
        lines.append(schema.system_prompt)
        lines.append("")

    lines += [
        f"Document type: {schema.display_name}",
        "",
        "Extract the following fields from this document.",
        "Return ONLY valid JSON with exactly this structure:",
        "{",
    ]

    # Determine which fields to extract — use DB profile fields as the source
    # of truth for which fields are enabled; enrich with schema metadata
    for db_field in db_fields:
        spec = schema_field_map.get(db_field.field_key)
        field_type = spec.field_type if spec else "string"
        required_flag = "(required)" if (spec and spec.required) else "(optional)"
        description_parts: list[str] = []
        if spec and spec.description:
            description_parts.append(spec.description)
        if db_field.instruction:
            description_parts.append(db_field.instruction)
        if spec and spec.enum:
            description_parts.append(f"allowed values: {', '.join(spec.enum)}")
        if spec and spec.normalization:
            norm_hints = {
                "indian_currency": "normalise to plain integer (strip commas/Indian formatting)",
                "date_dd_mm_yyyy": "normalise to YYYY-MM-DD format",
                "phone_e164":      "normalise to E.164 format (+91XXXXXXXXXX)",
            }
            hint = norm_hints.get(spec.normalization, spec.normalization)
            description_parts.append(hint)

        description = "; ".join(description_parts) if description_parts else ""
        aliases_str = (
            f" (also known as: {', '.join(db_field.aliases)})" if db_field.aliases else ""
        )
        lines.append(
            f'  "{db_field.field_key}": {{"value": <{field_type}>, "confidence": "high"|"medium"|"low"}},'
            f"  // {required_flag}{aliases_str} {description}".rstrip()
        )

    lines += [
        "}",
        "",
        'Use {"value": null, "confidence": "low"} for any field not found.',
        "Never guess — return null + low confidence if a value is uncertain.",
    ]

    # Append schema-level prompt notes
    if schema.prompt_notes:
        lines.append("")
        lines.append("Additional extraction rules:")
        for note in schema.prompt_notes:
            lines.append(f"- {note}")

    return "\n".join(lines)


# ── Gemini REST API call ───────────────────────────────────────────────────────

def _build_payload(artifact_bytes: bytes, mime_type: str, prompt: str) -> dict[str, Any]:
    effective_mime = mime_type if mime_type else "application/octet-stream"
    image_b64 = base64.b64encode(artifact_bytes).decode("ascii")
    return {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": effective_mime, "data": image_b64}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }


async def _call_gemini_instrumented(
    api_key: str,
    artifact_bytes: bytes,
    mime_type: str,
    prompt: str,
) -> tuple[str, int, int, int]:
    """Send document bytes + prompt to Gemini. Returns (text, http_status, prompt_tokens, response_tokens).

    Uses httpx directly — no google.generativeai SDK dependency.
    """
    payload = _build_payload(artifact_bytes, mime_type, prompt)

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            _GEMINI_API_URL,
            params={"key": api_key},
            json=payload,
        )

    http_status = resp.status_code
    if http_status != 200:
        raise RuntimeError(
            f"Gemini API error {http_status}: {resp.text[:500]}"
        )

    data = resp.json()
    usage = data.get("usageMetadata", {})
    prompt_tokens   = usage.get("promptTokenCount", 0)
    response_tokens = usage.get("candidatesTokenCount", 0)

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise ValueError(f"Unexpected Gemini response shape: {data}") from exc

    return text, http_status, prompt_tokens, response_tokens


async def _call_gemini(
    api_key: str,
    artifact_bytes: bytes,
    mime_type: str,
    prompt: str,
) -> str:
    """Backward-compatible wrapper — returns text only."""
    text, _, _, _ = await _call_gemini_instrumented(api_key, artifact_bytes, mime_type, prompt)
    return text


# ── Response parser ────────────────────────────────────────────────────────────

def _parse_response(
    raw_text: str,
    schema: SchemaDefinition,
    db_fields: list[ExtractionField],
) -> list[FieldResult]:
    """Parse Gemini JSON response → list[FieldResult].

    Raises ValueError on JSON parse failure so the caller can retry.
    """
    # Strip markdown code fences if Gemini wraps the JSON
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini response is not valid JSON: {exc}\nRaw: {raw_text[:500]}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Gemini response is not a JSON object. Raw: {raw_text[:500]}")

    results: list[FieldResult] = []
    for db_field in db_fields:
        key = db_field.field_key
        field_data = data.get(key)

        if field_data is None or not isinstance(field_data, dict):
            results.append(_not_found_result(key))
            continue

        raw_value = field_data.get("value")
        conf_str  = str(field_data.get("confidence", "low")).lower()

        if raw_value is None:
            results.append(_not_found_result(key))
            continue

        confidence = _CONFIDENCE_MAP.get(conf_str, Decimal("40.00"))
        str_value  = str(raw_value) if not isinstance(raw_value, str) else raw_value

        results.append(FieldResult(
            field_key=key,
            found_status=FoundStatus.FOUND,
            raw_value=str_value,
            normalized_value=raw_value,  # rules layer applies further normalisation
            confidence=confidence,
            page_no=None,
            evidence_region=None,
            provider_raw={"gemini_field_response": field_data},
        ))

    return results


def _not_found_result(field_key: str) -> FieldResult:
    return FieldResult(
        field_key=field_key,
        found_status=FoundStatus.NOT_FOUND,
        raw_value=None,
        normalized_value=None,
        confidence=None,
        page_no=None,
        evidence_region=None,
        provider_raw={},
    )


def _make_not_found_results(fields: list[ExtractionField]) -> list[FieldResult]:
    """Return NOT_FOUND for every field — used when all Gemini attempts fail."""
    return [_not_found_result(f.field_key) for f in fields]
