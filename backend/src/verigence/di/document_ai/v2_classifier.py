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
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
from PIL import Image
from pypdf import PdfReader, PdfWriter

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
_GEMINI_CLIENT: httpx.AsyncClient | None = None
_GEMINI_CLIENT_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class V2ClassificationResult:
    document_type_key: str | None
    confidence: Decimal
    provider_request_id: str
    raw_provider_response: dict[str, Any]


class V2ClassificationError(RuntimeError):
    pass


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
    if mime_type == "application/pdf":
        reader = PdfReader(io.BytesIO(document_bytes))
        if not reader.pages:
            raise V2ClassificationError("PDF contains no pages")
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
        raise V2ClassificationError("V2 classifier requires at least one candidate type")

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
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    client = await _gemini_client()
    response = await client.post(
        _GEMINI_API_URL,
        headers={"x-goog-api-key": settings.docai_gemini_api_key},
        json=body,
    )
    if response.status_code != 200:
        raise V2ClassificationError(
            f"Gemini classification failed with HTTP {response.status_code}"
        )

    raw = response.json()
    try:
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        observed = str(parsed["documentTypeKey"]).strip()
        confidence = Decimal(str(parsed["confidence"]))
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise V2ClassificationError("Gemini returned an invalid classification payload") from exc

    allowed = {key for key, _ in effective_candidates}
    if observed == "UNKNOWN":
        selected: str | None = None
    elif observed in allowed:
        selected = observed
    else:
        selected = None
        confidence = Decimal("0")

    if confidence < 0 or confidence > 100:
        raise V2ClassificationError("Gemini classification confidence is outside 0-100")

    return V2ClassificationResult(
        document_type_key=selected,
        confidence=confidence,
        provider_request_id=str(uuid.uuid4()),
        raw_provider_response=raw,
    )
