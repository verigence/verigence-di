"""Indian Aadhaar extraction schema used by the existing DI worker flow."""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

AADHAAR_SCHEMA = SchemaDefinition(
    document_type_key="aadhaar",
    display_name="Aadhaar Card",
    schema_version="1.0",
    fields=[
        FieldSpec(
            key="aadhaar_number",
            field_type="string",
            required=True,
            description=(
                "Aadhaar number exactly as visible. If masked, preserve the masking "
                "and never infer hidden digits."
            ),
        ),
        FieldSpec(
            key="aadhaar_name",
            field_type="string",
            required=True,
            description="Full name of the Aadhaar holder exactly as printed.",
        ),
        FieldSpec(
            key="date_of_birth",
            field_type="string",
            required=False,
            description=(
                "Complete date of birth if explicitly printed. If the document only "
                "contains a year of birth, do not invent a month or day."
            ),
            normalization="date_dd_mm_yyyy",
        ),
        FieldSpec(
            key="gender",
            field_type="string",
            required=False,
            description="Gender exactly as printed on the Aadhaar document.",
        ),
        FieldSpec(
            key="aadhaar_address",
            field_type="string",
            required=False,
            description="Postal address printed on the Aadhaar document, if present.",
        ),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "government identity documents. You will be shown an Aadhaar document. "
        "Extract only values explicitly visible in the supplied document. "
        "Never reconstruct masked Aadhaar digits and never infer missing identity "
        "information. Return ONLY valid JSON in the requested field structure."
    ),
    prompt_notes=[
        "Preserve Aadhaar masking exactly when digits are hidden.",
        "Do not confuse enrolment numbers, VID values, QR data, or other numbers with the Aadhaar number.",
        "If only Year of Birth is printed, do not fabricate a complete date of birth.",
        "For multi-page Aadhaar PDFs, use the address section when one is visibly present.",
    ],
)
