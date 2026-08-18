"""document_ai/schemas/_fallback.py — Generic fallback schema.

Used when document_type_key has no registered schema in SCHEMA_REGISTRY.
Performs generic full-text extraction using the field list from the DB
extraction profile. Returns raw text values for every field found.

This ensures the pipeline never crashes due to a missing schema — it degrades
gracefully to generic extraction with medium confidence.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

FALLBACK_SCHEMA = SchemaDefinition(
    document_type_key="__fallback__",
    display_name="Generic Document",
    schema_version="1.0",
    fields=[
        FieldSpec(
            key="raw_text",
            field_type="string",
            required=False,
            description="Full text content extracted from the document",
        ),
    ],
    system_prompt=(
        "You are a document data extraction assistant.\n"
        "You will be shown a document image or PDF.\n"
        "Extract all visible text and structured data from the document.\n"
        "For each field requested, return the extracted value exactly as it "
        "appears in the document.\n\n"
        "Output ONLY valid JSON. For each field use this structure:\n"
        '{"value": <extracted value or null>, "confidence": "high"|"medium"|"low"}\n\n'
        'If a field is not found in the document, return {"value": null, "confidence": "low"}.\n'
        "Never guess or infer a value. Return null with confidence low if uncertain."
    ),
    prompt_notes=[
        "Extract all fields exactly as they appear in the document.",
        "Do not infer or compute values — only extract what is explicitly visible.",
    ],
)
