"""Indian Aadhaar extraction schema used by the existing DI worker flow.

Identity evidence policy:
- preserve Aadhaar masking exactly;
- extract only relationship markers and names explicitly visible on the supplied
  Aadhaar evidence;
- never infer family relationships from names, gender, address, or other context;
- preserve the complete printed address and extract address components only when
  they are explicitly identifiable from the document itself;
- never derive state/district from pincode inside DI;
- use Aadhaar-specific relationship keys so PAN and Aadhaar evidence cannot be
  accidentally combined into one resolved relationship.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

AADHAAR_SCHEMA = SchemaDefinition(
    document_type_key="aadhaar",
    display_name="Aadhaar Card",
    schema_version="1.2",
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
            description="Complete postal address printed on the Aadhaar document, if present.",
        ),
        FieldSpec(
            key="address_pincode",
            field_type="string",
            required=False,
            description=(
                "Postal PIN code only when explicitly identifiable in the printed Aadhaar address; "
                "never infer or repair missing digits."
            ),
        ),
        FieldSpec(
            key="address_state",
            field_type="string",
            required=False,
            description=(
                "State/UT only when explicitly identifiable from the printed Aadhaar address; "
                "do not derive it from the PIN code."
            ),
        ),
        FieldSpec(
            key="address_district",
            field_type="string",
            required=False,
            description=(
                "District only when explicitly identifiable from the printed Aadhaar address; "
                "do not infer district from city, state, PIN code, or external geography knowledge."
            ),
        ),
        FieldSpec(
            key="aadhaar_relationship_type",
            field_type="string",
            required=False,
            description=(
                "Explicit Aadhaar relationship marker only when W/O, S/O, or D/O is visibly "
                "printed/written with a related person's name. Never infer a relationship "
                "from the address, surname, gender, or surrounding text."
            ),
            enum=["W/O", "S/O", "D/O"],
        ),
        FieldSpec(
            key="aadhaar_relationship_name",
            field_type="string",
            required=False,
            description=(
                "Name immediately associated with an explicitly visible Aadhaar W/O, S/O, or D/O "
                "marker. Return null when no such explicit marker is present."
            ),
        ),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "government identity documents. You will be shown an Aadhaar document. "
        "Extract only values explicitly visible in the supplied document. "
        "Never reconstruct masked Aadhaar digits and never infer missing identity, relationship, "
        "or geographic information. Return ONLY valid JSON in the requested field structure."
    ),
    prompt_notes=[
        "Preserve Aadhaar masking exactly when digits are hidden.",
        "Do not confuse enrolment numbers, VID values, QR data, or other numbers with the Aadhaar number.",
        "If only Year of Birth is printed, do not fabricate a complete date of birth.",
        "For multi-page Aadhaar PDFs, use the address section when one is visibly present.",
        "Keep aadhaar_address as the complete printed address even when component fields are populated.",
        "Populate address_pincode, address_state, and address_district only when each component is explicitly identifiable from the document. Do not derive state/district from pincode.",
        "aadhaar_relationship_type and aadhaar_relationship_name are populated only when W/O, S/O, or D/O is explicitly visible. Do not infer a relationship from a care-of line or an unlabeled name.",
    ],
)
