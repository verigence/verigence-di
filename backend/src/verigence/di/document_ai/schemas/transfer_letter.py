"""document_ai/schemas/transfer_letter.py — Vehicle Transfer Letter.

Exchange / trade-in evidence in which the old vehicle's owner transfers it to
the dealer (often handwritten or on a dealer letterhead). Keys are exactly
the migration 0046 published profile's.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

TRANSFER_LETTER_SCHEMA = SchemaDefinition(
    document_type_key="transfer_letter",
    display_name="Vehicle Transfer Letter",
    schema_version="1.0",
    fields=[
        FieldSpec("transferor_name", "string", True,
                  "Name of the person transferring (selling) the vehicle -- the current owner who signs the letter."),
        FieldSpec("transferee_name", "string", True,
                  "Name of the person or dealership receiving (buying) the vehicle."),
        FieldSpec("vehicle_registration_number", "string", True,
                  "Registration number of the vehicle being transferred, exactly as written."),
        FieldSpec("chassis_number", "string", False, "Chassis number if written, exactly as written."),
        FieldSpec("transfer_date", "date", True, "Date of the letter / transfer.", normalization="date_dd_mm_yyyy"),
        FieldSpec("sale_consideration_amount", "number", False,
                  "Sale consideration / agreed value of the vehicle if stated.", normalization="indian_currency"),
    ],
    system_prompt=(
        "You extract data from a vehicle transfer / sale letter written by an old vehicle's owner handing it to "
        "an automobile dealer, frequently handwritten. Read only what is written; do not infer names or amounts "
        "from signatures, stamps or the dealer letterhead unless the text states them.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Typical wording: 'I, <transferor>, ... hereby sell/transfer my vehicle No. <reg no> to <transferee>'.",
        "If the transferee is only implied by the letterhead (no name in the text), return null for transferee_name.",
        "sale_consideration_amount must be an amount stated as the sale/agreed value, not a registration fee.",
        "If a field is not written or is unclear, return null with low confidence.",
    ],
)
