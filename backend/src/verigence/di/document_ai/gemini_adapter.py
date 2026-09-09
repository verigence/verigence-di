"""document_ai/gemini_adapter.py — Gemini Document AI adapter.

D19: Gemini replaces Azure Document Intelligence as the production OCR/extraction
provider. Runtime classification remains caller-hint pass-through. Extraction is
schema-driven and now also requests optional source localization for every field.

Localization contract:
- pageNo is 1-based when the model can identify the source page.
- box_2d is [ymin, xmin, ymax, xmax] normalized to 0..1000.
- uncertain or invalid location data is discarded; a value is never rejected only
  because localization is unavailable.
- no page number or bounding box may be guessed.
"""
from __future__ import annotations

import asyncio
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

_CONFIDENCE_MAP: dict[str, Decimal] = {
    "high": Decimal("92.00"),
    "medium": Decimal("70.00"),
    "low": Decimal("40.00"),
}

_GEMINI_MODEL = "gemini-3-flash-preview"
_GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{_GEMINI_MODEL}:generateContent"
)


class GeminiApiError(RuntimeError):
    """Gemini request-level failure that must not become fake NOT_FOUND facts."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.retryable = status_code in {408, 429, 500, 502, 503, 504}
        super().__init__(f"Gemini API error {status_code}: {detail}")


class GeminiDocumentAIAdapter(DocumentAIAdapter):
    """Gemini document AI adapter."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def adapter_key(self) -> str:
        return "gemini_2_5_flash_v1"

    async def classify(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        candidate_type_keys: list[str],
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        """Pass-through classification — hint key accepted at confidence 100."""
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

    async def extract(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        fields: list[ExtractionField],
        correlation_id: str | None = None,
        physical_form_type: str = "PRINTABLE",
        document_type_key: str | None = None,
    ) -> AIInvocationResult:
        """Extract fields and optional positional evidence using the schema registry."""
        import time as _t

        log = logger.bind(
            adapter=self.adapter_key,
            document_type_key=document_type_key,
            physical_form_type=physical_form_type,
            correlation_id=correlation_id,
        )

        schema = get_schema(document_type_key or "")
        required_count = sum(1 for f in schema.fields if f.required)
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
            evidence_localization_requested=True,
        )

        provider_request_id = str(uuid.uuid4())
        raw_response: str | None = None
        field_results: list[FieldResult] | None = None
        last_error: str | None = None
        call_start = _t.monotonic()
        prompt_tokens = 0
        response_tokens = 0
        http_status = 0

        for attempt in range(2):
            try:
                raw_response, http_status, prompt_tokens, response_tokens = (
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
            except (json.JSONDecodeError, ValueError) as exc:
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
                    await asyncio.sleep(1)
                    continue
                raise
            except GeminiApiError as exc:
                last_error = str(exc)
                http_status = exc.status_code
                log.error(
                    "gemini_api_error",
                    document_type_key=document_type_key,
                    gemini_model=_GEMINI_MODEL,
                    http_status=http_status,
                    exc_type=type(exc).__name__,
                    exc_msg=last_error,
                    duration_ms=round((_t.monotonic() - call_start) * 1000, 1),
                )
                if attempt == 0 and exc.retryable:
                    log.warning(
                        "gemini_retry",
                        document_type_key=document_type_key,
                        attempt=attempt + 1,
                        reason=f"http_{http_status}",
                    )
                    await asyncio.sleep(2)
                    continue
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                log.error(
                    "gemini_api_error",
                    document_type_key=document_type_key,
                    gemini_model=_GEMINI_MODEL,
                    http_status=http_status,
                    exc_type=type(exc).__name__,
                    exc_msg=last_error,
                    duration_ms=round((_t.monotonic() - call_start) * 1000, 1),
                )
                if attempt == 0:
                    log.warning(
                        "gemini_retry",
                        document_type_key=document_type_key,
                        attempt=attempt + 1,
                        reason="transport_error",
                    )
                    await asyncio.sleep(2)
                    continue
                raise

        if field_results is None:
            raise RuntimeError("Gemini extraction ended without a provider result")

        duration_ms = round((_t.monotonic() - call_start) * 1000, 1)
        fields_found = sum(1 for fr in field_results if fr.found_status == FoundStatus.FOUND)
        fields_null = sum(1 for fr in field_results if fr.found_status != FoundStatus.FOUND)
        fields_low = sum(
            1
            for fr in field_results
            if fr.confidence is not None and fr.confidence <= Decimal("40.00")
        )
        localized_fields = sum(1 for fr in field_results if fr.evidence_region is not None)
        page_localized_fields = sum(1 for fr in field_results if fr.page_no is not None)

        log.info(
            "gemini_response",
            document_type_key=document_type_key,
            gemini_model=_GEMINI_MODEL,
            http_status=http_status,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            response_tokens=response_tokens,
            fields_extracted=fields_found,
            fields_null=fields_null,
            fields_low_confidence=fields_low,
            fields_with_page=page_localized_fields,
            fields_with_evidence_region=localized_fields,
        )

        if fields_found == 0 and fields:
            log.warning(
                "gemini_all_fields_null",
                document_type_key=document_type_key,
                gemini_model=_GEMINI_MODEL,
                duration_ms=duration_ms,
                likely_cause="empty_response" if not raw_response else "parse_failed_or_all_low",
            )

        for fr in field_results:
            log.debug(
                "gemini_field_detail",
                document_type_key=document_type_key,
                field_key=fr.field_key,
                raw_value=fr.raw_value,
                confidence_str=str(fr.confidence) if fr.confidence is not None else None,
                page_no=fr.page_no,
                evidence_region=fr.evidence_region,
            )

        usage: dict[str, Any] = {
            "model": _GEMINI_MODEL,
            "document_type_key": document_type_key,
            "schema_version": schema.schema_version,
            "fields_requested": len(fields),
            "fields_found": fields_found,
            "fields_with_page": page_localized_fields,
            "fields_with_evidence_region": localized_fields,
            "prompt_tokens": prompt_tokens,
            "response_tokens": response_tokens,
            "duration_ms": duration_ms,
        }

        return AIInvocationResult(
            capability=AICapability.VISION_EXTRACTION,
            adapter_key=self.adapter_key,
            provider_request_id=provider_request_id,
            results=field_results,
            usage_metrics=usage,
        )


def _build_prompt(schema: SchemaDefinition, db_fields: list[ExtractionField]) -> str:
    """Build a schema-driven prompt with optional source localization."""
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
        "Return one JSON object only. Do not wrap the object in an array.",
        "{",
    ]

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
                "phone_e164": "normalise to E.164 format (+91XXXXXXXXXX)",
            }
            description_parts.append(
                norm_hints.get(spec.normalization, spec.normalization)
            )

        description = "; ".join(description_parts) if description_parts else ""
        aliases_str = (
            f" (also known as: {', '.join(db_field.aliases)})" if db_field.aliases else ""
        )
        lines.append(
            f'  "{db_field.field_key}": '
            f'{{"value": <{field_type}>, "confidence": "high"|"medium"|"low", '
            '"pageNo": <1-based integer|null>, '
            '"box_2d": <[ymin,xmin,ymax,xmax] normalized 0..1000|null>}},'
            f"  // {required_flag}{aliases_str} {description}".rstrip(),
        )

    lines += [
        "}",
        "",
        (
            'Use {"value": null, "confidence": "low", "pageNo": null, '
            '"box_2d": null} for any field not found.'
        ),
        "Never guess — return null + low confidence if a value is uncertain.",
        (
            "For each FOUND value, return pageNo and box_2d only when you can localize "
            "the exact printed or handwritten value on the source document."
        ),
        (
            "box_2d must be [ymin, xmin, ymax, xmax] with coordinates normalized from "
            "0 to 1000 relative to that page/image."
        ),
        (
            "For a single image pageNo is 1. For a PDF pageNo is the 1-based PDF page. "
            "If page or box location is uncertain, return null for that location metadata."
        ),
        "Never infer, approximate, or invent a page number or bounding box.",
    ]

    if schema.prompt_notes:
        lines.append("")
        lines.append("Additional extraction rules:")
        for note in schema.prompt_notes:
            lines.append(f"- {note}")

    return "\n".join(lines)


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
    """Send document bytes + prompt to Gemini with token instrumentation."""
    payload = _build_payload(artifact_bytes, mime_type, prompt)

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            _GEMINI_API_URL,
            headers={"x-goog-api-key": api_key},
            json=payload,
        )

    http_status = resp.status_code
    if http_status != 200:
        raise GeminiApiError(http_status, resp.text[:500])

    data = resp.json()
    usage = data.get("usageMetadata", {})
    prompt_tokens = usage.get("promptTokenCount", 0)
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
    text, _, _, _ = await _call_gemini_instrumented(
        api_key, artifact_bytes, mime_type, prompt
    )
    return text


def _parse_page_no(field_data: dict[str, Any]) -> int | None:
    page_no = field_data.get("pageNo")
    if isinstance(page_no, bool) or not isinstance(page_no, int) or page_no < 1:
        return None
    return page_no


def _parse_evidence_region(field_data: dict[str, Any]) -> dict[str, Any] | None:
    box = field_data.get("box_2d")
    if not isinstance(box, list) or len(box) != 4:
        return None

    normalized: list[float] = []
    for value in box:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        coordinate = float(value)
        if coordinate < 0 or coordinate > 1000:
            return None
        normalized.append(coordinate)

    ymin, xmin, ymax, xmax = normalized
    if ymin >= ymax or xmin >= xmax:
        return None

    rendered_box: list[int | float] = [
        int(value) if value.is_integer() else value for value in normalized
    ]
    return {
        "type": "BOX_2D",
        "coordinateSystem": "NORMALIZED_1000",
        "box": rendered_box,
    }


def _parse_response(
    raw_text: str,
    schema: SchemaDefinition,
    db_fields: list[ExtractionField],
) -> list[FieldResult]:
    """Parse Gemini JSON response into provider-neutral field results."""
    del schema
    text_value = raw_text.strip()
    if text_value.startswith("```"):
        lines = text_value.split("\n")
        text_value = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(text_value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Gemini response is not valid JSON: {exc}\nRaw: {raw_text[:500]}"
        ) from exc

    # Gemini can occasionally wrap the requested object in a one-element JSON
    # array even when responseMimeType=application/json and the prompt requests an
    # object. Accept that harmless wrapper, but reject ambiguous multi-item arrays.
    if isinstance(data, list):
        if len(data) == 1 and isinstance(data[0], dict):
            data = data[0]
        else:
            raise ValueError(
                "Gemini response must be one JSON object or a single-item array "
                f"containing one object. Raw: {raw_text[:500]}"
            )

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
        conf_str = str(field_data.get("confidence", "low")).lower()

        if raw_value is None:
            results.append(_not_found_result(key))
            continue

        confidence = _CONFIDENCE_MAP.get(conf_str, Decimal("40.00"))
        str_value = str(raw_value) if not isinstance(raw_value, str) else raw_value

        results.append(
            FieldResult(
                field_key=key,
                found_status=FoundStatus.FOUND,
                raw_value=str_value,
                normalized_value=raw_value,
                confidence=confidence,
                page_no=_parse_page_no(field_data),
                evidence_region=_parse_evidence_region(field_data),
                provider_raw={"gemini_field_response": field_data},
            )
        )

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
    """Return NOT_FOUND for every field when all Gemini attempts fail."""
    return [_not_found_result(f.field_key) for f in fields]
