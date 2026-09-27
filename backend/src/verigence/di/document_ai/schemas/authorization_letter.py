"""document_ai/schemas/authorization_letter.py — Authorization Letter.

A letter in which a customer or vehicle owner authorizes another person or
the dealer to act for them (e.g. collect the vehicle, sign transfer forms).
Keys are exactly the migration 0046 published profile's.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

AUTHORIZATION_LETTER_SCHEMA = SchemaDefinition(
    document_type_key="authorization_letter",
    display_name="Authorization Letter",
    schema_version="1.0",
    fields=[
        FieldSpec("authorizer_name", "string", True,
                  "Name of the person granting the authorization (who writes/signs the letter)."),
        FieldSpec("authorized_person_name", "string", True,
                  "Name of the person or entity being authorized."),
        FieldSpec("vehicle_registration_number", "string", False,
                  "Registration number of the vehicle the authorization is about, if written."),
        FieldSpec("authorization_purpose", "string", False,
                  "What the authorized person may do, in the letter's own words (short)."),
        FieldSpec("authorization_date", "date", False, "Date of the letter.", normalization="date_dd_mm_yyyy"),
    ],
    system_prompt=(
        "You extract data from an authorization letter written to an automobile dealership, frequently "
        "handwritten. Read only what is written.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Typical wording: 'I, <authorizer>, hereby authorize <authorized person> to ...'.",
        "authorization_purpose is a short phrase taken from the letter, e.g. 'take delivery of the vehicle'.",
        "If a field is not written or is unclear, return null with low confidence.",
    ],
)
