"""document_ai/schemas/pan_card.py — Indian PAN Card extraction schema.

PAN Card (Permanent Account Number) issued by the Income Tax Department,
Government of India. Standard card format — printed black on white.

Identity evidence policy:
- extract only identity text explicitly visible on the supplied PAN evidence;
- never infer a relationship marker from an unlabeled parent-name line;
- keep the card holder's name distinct from the father's/relationship name;
- use PAN-specific relationship keys so PAN and Aadhaar evidence cannot be
  accidentally combined into one resolved relationship.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

PAN_CARD_SCHEMA = SchemaDefinition(
    document_type_key="pan_card",
    display_name="PAN Card",
    schema_version="1.1",
    fields=[
        FieldSpec(
            key="pan_number",
            field_type="string",
            required=True,
            description=(
                "10-character Permanent Account Number. "
                "Format: 5 letters + 4 digits + 1 letter (e.g. DJFPK8448P). "
                "Printed below the label 'Permanent Account Number'."
            ),
        ),
        FieldSpec(
            key="pan_name",
            field_type="string",
            required=True,
            description=(
                "Full name of the card holder exactly as printed on the card. "
                "This is the holder's name, NOT the father's or other relationship name."
            ),
        ),
        FieldSpec(
            key="pan_father_name",
            field_type="string",
            required=False,
            description=(
                "Father's name only when the PAN document explicitly provides a separate "
                "father-name line or label. Do not return the card holder's name here."
            ),
        ),
        FieldSpec(
            key="pan_relationship_type",
            field_type="string",
            required=False,
            description=(
                "Explicit PAN relationship marker only when W/O, S/O, or D/O is visibly "
                "printed/written with a related person's name. Never infer S/O merely "
                "because a separate father-name line exists."
            ),
            enum=["W/O", "S/O", "D/O"],
        ),
        FieldSpec(
            key="pan_relationship_name",
            field_type="string",
            required=False,
            description=(
                "Name immediately associated with an explicitly visible PAN W/O, S/O, or D/O "
                "marker. Return null when no such explicit marker is present."
            ),
        ),
        FieldSpec(
            key="date_of_birth",
            field_type="string",
            required=True,
            description=(
                "Date of birth as printed on the card in DD/MM/YYYY format. "
                "Normalize to ISO 8601 format: YYYY-MM-DD."
            ),
            normalization="date_dd_mm_yyyy",
        ),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "government identity documents.\n"
        "You will be shown an image of an Indian PAN Card (Permanent Account Number card) "
        "issued by the Income Tax Department, Government of India.\n\n"
        "Extract only values explicitly visible in the supplied evidence. "
        "Keep the PAN holder name separate from any father/relationship name. "
        "Do not invent a W/O, S/O, or D/O relationship from an unlabeled name line.\n\n"
        "Return ONLY valid JSON. Do not include any explanation or extra text outside the JSON object."
    ),
    prompt_notes=[
        "pan_number is always exactly 10 characters: 5 letters, 4 digits, 1 letter.",
        "pan_name is the card HOLDER's name and must not be replaced by a father/relationship name.",
        "pan_father_name may be extracted from a separately identifiable PAN father-name line even when no relationship prefix is printed.",
        "pan_relationship_type and pan_relationship_name are populated only when W/O, S/O, or D/O is explicitly visible. Never infer the marker from pan_father_name or from gender.",
        "date_of_birth appears as DD/MM/YYYY on the card — return it as YYYY-MM-DD.",
        "If the image is partially obscured, extract what is clearly visible and return null + low confidence for anything uncertain.",
    ],
)
