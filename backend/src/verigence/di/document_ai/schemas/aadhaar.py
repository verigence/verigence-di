"""Indian Aadhaar extraction schema used by the existing DI worker flow.

Identity evidence policy:
- preserve Aadhaar masking exactly;
- extract only relationship markers and names explicitly visible on the supplied
  Aadhaar evidence;
- never infer family relationships from names, gender, address, or other context.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

AADHAAR_SCHEMA = SchemaDefinition(
    document_type_key="aadhaar",
    display_name="Aadhaar Card",
    schema_version="1.1",
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
        FieldSpec(
            key="relationship_type",
            field_type="string",
            required=False,
            description=(
                "Explicit relationship marker only when W/O, S/O, or D/O is visibly "
                "printed/written with a related person's name. Never infer a relationship "
                "from the address, surname, gender, or surrounding text."
            ),
            enum=["W/O", "S/O", "D/O"],
        ),
        FieldSpec(
            key="relationship_name",
            field_type="string",
            required=False,
            description=(
                "Name immediately associated with an explicitly visible W/O, S/O, or D/O "
                "marker. Return null when no such explicit marker is present."
            ),
        ),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "government identity documents. You will be shown an Aadhaar document. "
        "Extract only values explicitly visible in the supplied document. "
        "Never reconstruct masked Aadhaar digits and never infer missing identity "
        "or relationship information. Return ONLY valid JSON in the requested field structure."
    ),
    prompt_notes=[
        "Preserve Aadhaar masking exactly when digits are hidden.",
        "Do not confuse enrolment numbers, VID values, QR data, or other numbers with the Aadhaar number.",
        "If only Year of Birth is printed, do not fabricate a complete date of birth.",
        "For multi-page Aadhaar PDFs, use the address section when one is visibly present.",
        "relationship_type and relationship_name are populated only when W/O, S/O, or D/O is explicitly visible. Do not infer a relationship from a care-of line or an unlabeled name.",
    ],
)
