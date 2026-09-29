"""UC03 Document Capture V2 classifier.

This module is intentionally separate from the legacy DocumentAIAdapter.classify
contract. Legacy Gemini classification is caller-hint pass-through and remains
unchanged. V2 must determine the document type from the uploaded bytes.

The original design calls for a cheap first-page classification pass. Images are
downscaled to a 768px long edge. PDFs are reduced to page 1 using the existing
pypdf dependency before being sent to Gemini.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
import structlog
from PIL import Image
from pypdf import PdfReader, PdfWriter

from verigence.di.document_ai.gemini_cost import generation_config, usage_from_response
from verigence.di.document_ai.invoice_taxonomy import (
    GENERIC_INVOICE_TYPE_KEY,
    INVOICE_CLASSIFICATION_HINTS,
    INVOICE_SPECIFIC_DOCUMENT_TYPE_KEYS,
)
from verigence.di.settings import get_settings

_GEMINI_MODEL = "gemini-3-flash-preview"
_GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{_GEMINI_MODEL}:generateContent"
)
_logger = structlog.get_logger(__name__)
_GEMINI_CLIENT: httpx.AsyncClient | None = None
_GEMINI_CLIENT_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class V2ClassificationResult:
    document_type_key: str | None
    confidence: Decimal
    provider_request_id: str
    raw_provider_response: dict[str, Any]


class V2ClassificationError(RuntimeError):
    """Classification failure carrying a stable code and retryability, so
    ``technical_failure`` can tell a rate limit from a corrupt upload."""

    def __init__(
        self,
        message: str,
        *,
        technical_code: str,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        self.technical_code = technical_code
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


def _http_failure(status_code: int) -> V2ClassificationError:
    if status_code == 429:
        code, retryable = "DOCUMENT_AI_RATE_LIMITED", True
    elif status_code in {408, 500, 502, 503, 504}:
        code, retryable = "DOCUMENT_AI_UNAVAILABLE", True
    else:
        code, retryable = "DOCUMENT_AI_REQUEST_REJECTED", False
    return V2ClassificationError(
        f"Gemini classification failed with HTTP {status_code}",
        technical_code=code,
        retryable=retryable,
        status_code=status_code,
    )


async def _gemini_client() -> httpx.AsyncClient:
    """Reuse HTTP/TLS connections across the V2 classifier worker pool."""
    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is not None and not _GEMINI_CLIENT.is_closed:
        return _GEMINI_CLIENT
    async with _GEMINI_CLIENT_LOCK:
        if _GEMINI_CLIENT is None or _GEMINI_CLIENT.is_closed:
            _GEMINI_CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_connections=12, max_keepalive_connections=12),
            )
        return _GEMINI_CLIENT


async def close_v2_classifier_client() -> None:
    """Close the shared provider client during worker shutdown."""
    global _GEMINI_CLIENT
    client = _GEMINI_CLIENT
    _GEMINI_CLIENT = None
    if client is not None and not client.is_closed:
        await client.aclose()


def _first_page_payload(document_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    try:
        return _first_page_payload_unchecked(document_bytes, mime_type)
    except V2ClassificationError:
        raise
    except Exception as exc:
        # pypdf/PIL cannot open the file: the upload is unreadable, and will be
        # just as unreadable on a retry.
        raise V2ClassificationError(
            f"Document could not be opened ({type(exc).__name__})",
            technical_code="INVALID_FILE_CONTENT",
            retryable=False,
        ) from exc


def _first_page_payload_unchecked(document_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    if mime_type == "application/pdf":
        reader = PdfReader(io.BytesIO(document_bytes))
        if not reader.pages:
            raise V2ClassificationError(
                "PDF contains no pages",
                technical_code="INVALID_FILE_CONTENT",
                retryable=False,
            )
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue(), "application/pdf"

    if mime_type.startswith("image/"):
        with Image.open(io.BytesIO(document_bytes)) as source_image:
            image: Image.Image = source_image.convert("RGB")
            longest = max(image.width, image.height)
            if longest > 768:
                ratio = 768 / longest
                image = image.resize(
                    (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
                )
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=True)
            return output.getvalue(), "image/jpeg"

    return document_bytes, mime_type


def _with_invoice_fallback(candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Add one internal generic invoice candidate without another provider call."""
    keys = {key for key, _ in candidates}
    if (
        GENERIC_INVOICE_TYPE_KEY not in keys
        and any(key in INVOICE_SPECIFIC_DOCUMENT_TYPE_KEYS for key in keys)
    ):
        return [*candidates, (GENERIC_INVOICE_TYPE_KEY, "Other Invoice")]
    return candidates


def _candidate_line(key: str, label: str) -> str:
    semantic_hint = INVOICE_CLASSIFICATION_HINTS.get(key)
    if semantic_hint is None:
        return f"- {key}: {label}"
    return f"- {key}: {label}. Invoice discriminator: {semantic_hint}."


def _prompt(candidates: list[tuple[str, str]]) -> str:
    choices = "\n".join(_candidate_line(key, label) for key, label in candidates)
    return (
        "Classify the uploaded automobile-dealership audit document. "
        "Choose exactly one of the candidate document types below, or UNKNOWN if the "
        "document is not clearly one of them. Do not infer a type from file name. "
        "For invoice candidates, distinguish the goods/service being invoiced from the "
        "invoice heading: a document titled Tax Invoice can still be a vehicle, accessory, "
        "EW, RSA, or another invoice. Prefer a specific invoice candidate only when its "
        "purpose/source is supported by visible evidence. Use invoice_generic only when "
        "the document is clearly an invoice but none of the specific invoice candidates "
        "can be established reliably. This is one classification call; do not request a "
        "separate invoice subtype pass.\n\n"
        f"Candidates:\n{choices}\n- UNKNOWN: none of the candidates\n\n"
        "Return ONLY JSON in this form: "
        '{"documentTypeKey":"<candidate key or UNKNOWN>","confidence":<0-100 integer>}. '
        "Use confidence below 90 when the visible evidence is ambiguous."
    )


async def classify_document_v2(
    *,
    document_bytes: bytes,
    mime_type: str,
    candidates: list[tuple[str, str]],
) -> V2ClassificationResult:
    if not candidates:
        raise V2ClassificationError(
            "V2 classifier requires at least one candidate type",
            technical_code="CLASSIFICATION_NO_CANDIDATES",
            retryable=False,
        )

    effective_candidates = _with_invoice_fallback(candidates)
    settings = get_settings()
    if settings.docai_mock:
        key = effective_candidates[0][0]
        return V2ClassificationResult(
            document_type_key=key,
            confidence=Decimal("95.00"),
            provider_request_id=str(uuid.uuid4()),
            raw_provider_response={"mock": True, "documentTypeKey": key},
        )

    payload_bytes, effective_mime = _first_page_payload(document_bytes, mime_type)
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": effective_mime,
                            "data": base64.b64encode(payload_bytes).decode("ascii"),
                        }
                    },
                    {"text": _prompt(effective_candidates)},
                ]
            }
        ],
        # The answer is a one-line JSON object: minimal thinking, small cap.
        "generationConfig": generation_config(
            thinking_level=settings.docai_gemini_classification_thinking_level,
            max_output_tokens=min(settings.docai_gemini_max_output_tokens, 2048),
        ),
    }
    log = _logger.bind(
        gemini_model=_GEMINI_MODEL,
        candidate_count=len(effective_candidates),
        payload_bytes=len(payload_bytes),
        payload_mime=effective_mime,
    )
    client = await _gemini_client()
    started = time.monotonic()
    try:
        response = await client.post(
            _GEMINI_API_URL,
            headers={"x-goog-api-key": settings.docai_gemini_api_key},
            json=body,
        )
    except httpx.HTTPError as exc:
        log.warning(
            "gemini_classification_transport_error",
            error_code="DOCUMENT_AI_UNAVAILABLE",
            exception_type=type(exc).__name__,
            duration_ms=_elapsed_ms(started),
        )
        raise V2ClassificationError(
            f"Gemini classification transport failure ({type(exc).__name__})",
            technical_code="DOCUMENT_AI_UNAVAILABLE",
            retryable=True,
        ) from exc
    duration_ms = _elapsed_ms(started)
    if response.status_code != 200:
        failure = _http_failure(response.status_code)
        log.warning(
            "gemini_classification_http_error",
            http_status=response.status_code,
            error_code=failure.technical_code,
            retryable=failure.retryable,
            duration_ms=duration_ms,
        )
        raise failure

    try:
        raw = response.json()
    except ValueError as exc:
        log.warning(
            "gemini_classification_invalid_response",
            http_status=response.status_code,
            error_code="DOCUMENT_AI_RESPONSE_INVALID",
            reason="body_not_json",
            duration_ms=duration_ms,
        )
        raise V2ClassificationError(
            "Gemini returned a non-JSON classification body",
            technical_code="DOCUMENT_AI_RESPONSE_INVALID",
            retryable=True,
        ) from exc
    usage = usage_from_response(raw if isinstance(raw, dict) else {})
    log.info(
        "gemini_classification_usage",
        http_status=response.status_code,
        duration_ms=duration_ms,
        thinking_level=settings.docai_gemini_classification_thinking_level or "model-default",
        **usage.as_metrics(),
    )
    if usage.blocked:
        log.warning(
            "gemini_classification_blocked",
            error_code="DOCUMENT_AI_CONTENT_BLOCKED",
            finish_reason=usage.finish_reason,
            block_reason=usage.block_reason,
        )
        raise V2ClassificationError(
            "Gemini declined to classify the document content",
            technical_code="DOCUMENT_AI_CONTENT_BLOCKED",
            retryable=False,
        )
    try:
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        observed = str(parsed["documentTypeKey"]).strip()
        confidence = Decimal(str(parsed["confidence"]))
    except (KeyError, IndexError, TypeError, ValueError, ArithmeticError) as exc:
        log.warning(
            "gemini_classification_invalid_response",
            http_status=response.status_code,
            error_code="DOCUMENT_AI_RESPONSE_INVALID",
            reason="payload_unparseable",
            exception_type=type(exc).__name__,
            finish_reason=usage.finish_reason,
        )
        raise V2ClassificationError(
            "Gemini returned an invalid classification payload",
            technical_code="DOCUMENT_AI_RESPONSE_INVALID",
            retryable=True,
        ) from exc

    allowed = {key for key, _ in effective_candidates}
    if observed == "UNKNOWN":
        selected: str | None = None
    elif observed in allowed:
        selected = observed
    else:
        selected = None
        confidence = Decimal("0")

    if confidence < 0 or confidence > 100:
        log.warning(
            "gemini_classification_invalid_response",
            error_code="DOCUMENT_AI_RESPONSE_INVALID",
            reason="confidence_out_of_range",
        )
        raise V2ClassificationError(
            "Gemini classification confidence is outside 0-100",
            technical_code="DOCUMENT_AI_RESPONSE_INVALID",
            retryable=True,
        )

    return V2ClassificationResult(
        document_type_key=selected,
        confidence=confidence,
        provider_request_id=usage.response_id or str(uuid.uuid4()),
        raw_provider_response=raw,
    )


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)
