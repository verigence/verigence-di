"""document_ai/schemas/pan_card.py — Indian PAN Card extraction schema.

PAN Card (Permanent Account Number) issued by the Income Tax Department,
Government of India. Standard card format — printed black on white.

Expected fields:
  pan_number    : 10-character alphanumeric PAN (e.g. DJFPK8448P)
  pan_name      : Name of the card holder (first line after INCOME TAX DEPT header)
  date_of_birth : Date of birth in DD/MM/YYYY on card → normalized YYYY-MM-DD
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

PAN_CARD_SCHEMA = SchemaDefinition(
    document_type_key="pan_card",
    display_name="PAN Card",
    schema_version="1.0",
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
                "This is the FIRST name line — the name of the individual, "
                "NOT the father's name. "
                "Appears near the top of the card after the issuer header."
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
        "The card always contains:\n"
        "  - Header: 'INCOME TAX DEPARTMENT' and 'GOVT. OF INDIA'\n"
        "  - Holder's full name (bold, prominent)\n"
        "  - Father's name (printed below holder's name — do NOT confuse with holder's name)\n"
        "  - Date of birth in DD/MM/YYYY format\n"
        "  - The text 'Permanent Account Number' followed by the 10-character PAN\n"
        "  - A photo of the holder and a signature\n\n"
        "Extract the fields requested below. Return ONLY valid JSON. "
        "Do not include any explanation or extra text outside the JSON object."
    ),
    prompt_notes=[
        "pan_number is always exactly 10 characters: 5 letters, 4 digits, 1 letter.",
        "pan_name is the card HOLDER's name — the first name line. "
        "It is NOT the father's name (which appears on the second name line).",
        "date_of_birth appears as DD/MM/YYYY on the card — return it as YYYY-MM-DD.",
        "If the image is partially obscured, extract what is clearly visible and "
        "return null + low confidence for anything uncertain.",
    ],
)
