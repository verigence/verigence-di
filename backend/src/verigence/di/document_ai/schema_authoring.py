"""AI-assisted extraction-schema authoring for DI Configuration Administration.

This module is intentionally separate from the runtime extraction pipeline.
Gemini may propose configuration, but it cannot write or publish configuration.
Every proposal is deterministically validated before it is persisted or materialised.

Runtime classification remains caller-hint pass-through and is not changed here.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from verigence.di.document_ai.adapter import ExtractionField, FieldResult, get_document_ai_adapter
from verigence.di.document_ai.gemini_adapter import (
    _GEMINI_MODEL,
    _call_gemini_instrumented,
)
from verigence.di.settings import get_settings

_ALLOWED_DATA_TYPES = frozenset({
    "STRING", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "DATETIME",
    "CURRENCY", "IDENTIFIER", "PHONE", "EMAIL", "JSON",
})
_ALLOWED_FORM_TYPES = frozenset({"GOVT_ID", "PRINTABLE", "HANDWRITTEN", "ADDITIONAL"})
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,119}$")
_MAX_FIELDS = 80


@dataclass(frozen=True)
class SchemaProposalResult:
    proposal: dict[str, Any]
    model: str
    prompt_tokens: int
    response_tokens: int


def _clean_string(value: Any, *, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _normalise_string_list(value: Any, *, maximum_items: int = 20, maximum_chars: int = 160) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value[:maximum_items]:
        text = _clean_string(item, maximum=maximum_chars)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def validate_schema_proposal(payload: Any) -> dict[str, Any]:
    """Validate and canonicalise an untrusted Gemini/admin proposal.

    No field is permitted to be marked as derived/calculated. Proposed fields must
    carry at least one visible evidence label/anchor from the sample. This does not
    prove semantic correctness; it gives the human reviewer an explicit evidence
    anchor and blocks free-form schema invention.
    """
    if not isinstance(payload, dict):
        raise ValueError("Schema proposal must be a JSON object")

    document_type_key = _clean_string(payload.get("documentTypeKey"), maximum=120).lower()
    if not _KEY_RE.fullmatch(document_type_key):
        raise ValueError("documentTypeKey must be lower snake_case and 2-120 characters")

    display_name = _clean_string(payload.get("displayName"), maximum=240)
    if not display_name:
        raise ValueError("displayName is required")

    physical_form_type = _clean_string(payload.get("physicalFormType"), maximum=20).upper() or "PRINTABLE"
    if physical_form_type not in _ALLOWED_FORM_TYPES:
        raise ValueError(f"Unsupported physicalFormType: {physical_form_type}")

    raw_fields = payload.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValueError("At least one proposed field is required")
    if len(raw_fields) > _MAX_FIELDS:
        raise ValueError(f"A proposal may contain at most {_MAX_FIELDS} fields")

    fields: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(raw_fields, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Field {index} must be a JSON object")
        if raw.get("derived") is True or raw.get("calculated") is True:
            raise ValueError(f"Field {index} is derived/calculated; only directly evidenced fields are allowed")

        field_key = _clean_string(raw.get("fieldKey"), maximum=160).lower()
        if not _KEY_RE.fullmatch(field_key):
            raise ValueError(f"Field {index} fieldKey must be lower snake_case")
        if field_key in seen_keys:
            raise ValueError(f"Duplicate fieldKey: {field_key}")
        seen_keys.add(field_key)

        field_display_name = _clean_string(raw.get("displayName"), maximum=240)
        if not field_display_name:
            raise ValueError(f"Field {field_key} displayName is required")

        data_type = _clean_string(raw.get("dataType"), maximum=30).upper() or "STRING"
        if data_type not in _ALLOWED_DATA_TYPES:
            raise ValueError(f"Field {field_key} has unsupported dataType {data_type}")

        evidence_labels = _normalise_string_list(
            raw.get("evidenceLabels") if "evidenceLabels" in raw else raw.get("observedLabels")
        )
        if not evidence_labels:
            raise ValueError(
                f"Field {field_key} has no evidenceLabels; every proposed field must identify visible sample evidence"
            )

        aliases = _normalise_string_list(raw.get("aliases"))
        instruction = _clean_string(raw.get("extractionInstruction"), maximum=1000)
        if not instruction:
            instruction = f"Extract {field_display_name} only when it is explicitly visible in the document; otherwise return null."
        anti_hallucination = " Never infer, calculate, reconstruct, or guess a missing value."
        if "never infer" not in instruction.casefold() and "never guess" not in instruction.casefold():
            instruction = (instruction.rstrip(" .") + "." + anti_hallucination)[:1200]

        fields.append({
            "fieldKey": field_key,
            "displayName": field_display_name,
            "dataType": data_type,
            "required": bool(raw.get("required", False)),
            "evidenceLabels": evidence_labels,
            "aliases": aliases,
            "extractionInstruction": instruction,
            "description": _clean_string(raw.get("description"), maximum=600) or None,
            "scoreIncluded": bool(raw.get("scoreIncluded", raw.get("required", False))),
            "scoreWeight": float(raw.get("scoreWeight", 1.0 if raw.get("required", False) else 0.0)),
            "derived": False,
        })

    warnings = _normalise_string_list(payload.get("warnings"), maximum_items=30, maximum_chars=500)
    return {
        "documentTypeKey": document_type_key,
        "displayName": display_name,
        "description": _clean_string(payload.get("description"), maximum=1000) or None,
        "physicalFormType": physical_form_type,
        "fields": fields,
        "warnings": warnings,
        "authoringPolicy": {
            "manualApprovalRequired": True,
            "directDatabaseWriteByModel": False,
            "derivedFieldsAllowed": False,
            "missingValuesMustBeNull": True,
        },
    }


def _authoring_prompt(
    *,
    requested_display_name: str | None,
    description: str | None,
    canonical_field_keys: list[str],
) -> str:
    catalogue = ", ".join(canonical_field_keys[:500]) if canonical_field_keys else "(none supplied)"
    context_lines = []
    if requested_display_name:
        context_lines.append(f"Admin-provided tentative display name: {requested_display_name}")
    if description:
        context_lines.append(f"Admin-provided context: {description}")
    context = "\n".join(context_lines) if context_lines else "No document name or business context was supplied."

    return f"""You are assisting an administrator to AUTHOR an extraction schema for one sample document.
You are NOT extracting transaction values for business use and you are NOT allowed to publish or persist configuration.

HARD SAFETY / AUDIT RULES:
1. Never guess or hallucinate fields. Propose a field only when this sample visibly supports that field through a printed label, table header, repeated form caption, or unambiguous visible document structure.
2. Never derive, calculate, sum, subtract, reconstruct hidden characters, or infer missing values.
3. Do not invent aliases that are not visibly present in this sample.
4. Set required=false by default. A single sample cannot prove that a field is universally mandatory.
5. evidenceLabels must quote concise visible labels/anchors from this sample for every field. If you cannot name visible evidence, do not propose the field.
6. Prefer an existing canonical field key ONLY when it is an exact semantic match. Otherwise propose a new lower_snake_case key.
7. This system is India-oriented; preserve identifiers exactly as printed and do not expand masked values.
8. Keep the proposal practical: include business/audit-relevant fields, not decorative text.

{context}

Existing canonical field keys available for exact reuse:
{catalogue}

Return ONLY valid JSON with this shape:
{{
  "documentTypeKey": "lower_snake_case",
  "displayName": "Human readable name",
  "description": "What this document evidences",
  "physicalFormType": "GOVT_ID|PRINTABLE|HANDWRITTEN|ADDITIONAL",
  "fields": [
    {{
      "fieldKey": "canonical_or_new_key",
      "displayName": "Human label",
      "dataType": "STRING|INTEGER|DECIMAL|BOOLEAN|DATE|DATETIME|CURRENCY|IDENTIFIER|PHONE|EMAIL|JSON",
      "required": false,
      "evidenceLabels": ["visible sample label or anchor"],
      "aliases": ["only labels actually visible in this sample"],
      "extractionInstruction": "Extract only when explicitly visible; otherwise return null. Never infer, calculate, reconstruct, or guess.",
      "description": "Short semantic description",
      "scoreIncluded": false,
      "scoreWeight": 0.0,
      "derived": false
    }}
  ],
  "warnings": ["ambiguities the admin should review"]
}}
"""


def _mock_proposal(requested_display_name: str | None) -> dict[str, Any]:
    display = (requested_display_name or "Custom Supporting Document").strip() or "Custom Supporting Document"
    key = re.sub(r"[^a-z0-9]+", "_", display.lower()).strip("_")[:100] or "custom_supporting_document"
    return {
        "documentTypeKey": key,
        "displayName": display,
        "description": "Mock authoring proposal used only when DI_DOCAI_MOCK=true.",
        "physicalFormType": "PRINTABLE",
        "fields": [{
            "fieldKey": "document_reference",
            "displayName": "Document Reference",
            "dataType": "IDENTIFIER",
            "required": False,
            "evidenceLabels": ["Reference"],
            "aliases": ["Reference"],
            "extractionInstruction": "Extract only when an explicit reference is visible; otherwise return null. Never infer, calculate, reconstruct, or guess.",
            "description": "Mock-only field for deterministic CI tests.",
            "scoreIncluded": False,
            "scoreWeight": 0.0,
            "derived": False,
        }],
        "warnings": ["Mock mode: proposal was not generated from document content."],
    }


async def generate_schema_proposal(
    *,
    artifact_bytes: bytes,
    mime_type: str,
    requested_display_name: str | None,
    description: str | None,
    canonical_field_keys: list[str],
) -> SchemaProposalResult:
    settings = get_settings()
    if settings.docai_mock:
        proposal = validate_schema_proposal(_mock_proposal(requested_display_name))
        return SchemaProposalResult(proposal=proposal, model="mock_v1", prompt_tokens=0, response_tokens=0)

    if not settings.docai_gemini_api_key:
        raise RuntimeError("Gemini configuration-authoring is unavailable because DI_DOCAI_GEMINI_API_KEY is not configured")

    prompt = _authoring_prompt(
        requested_display_name=requested_display_name,
        description=description,
        canonical_field_keys=canonical_field_keys,
    )
    raw_text, _http_status, prompt_tokens, response_tokens = await _call_gemini_instrumented(
        api_key=settings.docai_gemini_api_key,
        artifact_bytes=artifact_bytes,
        mime_type=mime_type,
        prompt=prompt,
    )
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini returned invalid JSON for the configuration proposal") from exc
    proposal = validate_schema_proposal(raw)
    return SchemaProposalResult(
        proposal=proposal,
        model=_GEMINI_MODEL,
        prompt_tokens=int(prompt_tokens or 0),
        response_tokens=int(response_tokens or 0),
    )


async def test_schema_proposal(
    *,
    artifact_bytes: bytes,
    mime_type: str,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Run non-persistent sample extraction using proposal fields.

    This deliberately does not create a Subject, Document, field version, or rule result.
    It is an authoring-time preview only.
    """
    validated = validate_schema_proposal(proposal)
    fields = [
        ExtractionField(
            field_key=item["fieldKey"],
            aliases=list(dict.fromkeys(item["evidenceLabels"] + item["aliases"])),
            instruction=item["extractionInstruction"],
        )
        for item in validated["fields"]
    ]
    adapter = get_document_ai_adapter()
    result = await adapter.extract(
        artifact_bytes=artifact_bytes,
        mime_type=mime_type,
        fields=fields,
        physical_form_type=validated["physicalFormType"],
        document_type_key=validated["documentTypeKey"],
    )
    rows: list[dict[str, Any]] = []
    for item in result.results:
        if not isinstance(item, FieldResult):
            continue
        rows.append({
            "fieldKey": item.field_key,
            "foundStatus": item.found_status.value if hasattr(item.found_status, "value") else str(item.found_status),
            "value": item.raw_value,
            "confidence": float(item.confidence) if item.confidence is not None else None,
            "pageNo": item.page_no,
        })
    return {
        "documentTypeKey": validated["documentTypeKey"],
        "fields": rows,
        "usage": result.usage_metrics,
        "providerRequestId": result.provider_request_id,
        "persistedAsBusinessEvidence": False,
    }
