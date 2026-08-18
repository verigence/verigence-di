"""document_ai/schemas/base.py — Provider-neutral document schema types.

A SchemaDefinition captures everything needed to extract fields from a
document using any AI provider:
  - The field list (keys, types, required flags, enums, normalisation hints)
  - The Gemini system prompt for this document type
  - Per-type prompt notes (special extraction instructions)

This package is provider-neutral. It defines *what* to extract and *how to
prompt*, not which API to call.

D20: Document Schema Registry — one file per document type, registered in
     __init__.py. Adding a new type = one new file + one registry entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldSpec:
    """Specification for one extractable field.

    key          — must match canonical_field_key in the DB extraction profile
    field_type   — "string" | "number" | "date" | "datetime" | "boolean" | "array"
    required     — True = absence reduces confidence score
    description  — human-readable hint included in the Gemini prompt
    enum         — allowed values when the field is constrained
    normalization — post-extraction normalisation hint:
                    "indian_currency"  → strip commas, parse Indian numbering → int
                    "date_dd_mm_yyyy"  → normalise to ISO-8601 YYYY-MM-DD
                    "phone_e164"       → normalise phone to E.164
    """
    key: str
    field_type: str
    required: bool
    description: str | None = None
    enum: list[str] | None = None
    normalization: str | None = None


@dataclass(frozen=True)
class SchemaDefinition:
    """Complete extraction schema for one document type.

    document_type_key — must match document_types.document_type_key in DB
    display_name      — must match document_types.display_name in DB
    schema_version    — bump when fields change; stored in document_search_index
    fields            — ordered list of FieldSpec
    system_prompt     — Gemini system prompt for this document type
    prompt_notes      — extra instructions appended to the user message
    """
    document_type_key: str
    display_name: str
    schema_version: str
    fields: list[FieldSpec]
    system_prompt: str
    prompt_notes: list[str] = field(default_factory=list)
