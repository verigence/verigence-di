"""document_ai/schemas/vehicle_rc.py — Vehicle Registration Certificate (RC).

Exchange / trade-in evidence: the RC of the customer's old vehicle. Used to
be served by FALLBACK_SCHEMA's generic prompt with the migration 0046
profile's field list; the keys below are exactly that published profile's.
Indian RCs come as a paper book, a laminated card or a smart card (front
and back); fields sit in labelled boxes whose wording varies by state.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

VEHICLE_RC_SCHEMA = SchemaDefinition(
    document_type_key="vehicle_rc",
    display_name="Vehicle Registration Certificate (RC)",
    schema_version="1.0",
    fields=[
        FieldSpec("vehicle_registration_number", "string", True,
                  "Registration number (Regn. No.) exactly as printed, e.g. OD02AB1234; keep the printed letters and digits, drop only spaces."),
        FieldSpec("owner_name", "string", True,
                  "Registered owner's name exactly as printed (Owner Name / Name of Owner); not the S/W/D of name."),
        FieldSpec("chassis_number", "string", True,
                  "Chassis number (Ch. No. / Chassis No. / VIN) exactly as printed; never correct characters."),
        FieldSpec("engine_number", "string", True,
                  "Engine number (Eng. No. / Motor No.) exactly as printed."),
        FieldSpec("vehicle_model", "string", False, "Maker's name and model exactly as printed (Maker / Model / Maker's Class)."),
        FieldSpec("vehicle_class", "string", False, "Vehicle class exactly as printed, e.g. LMV, Motor Car, M-Cycle/Scooter."),
        FieldSpec("vehicle_fuel_type", "string", False, "Fuel type exactly as printed, e.g. PETROL, DIESEL, CNG, ELECTRIC."),
        FieldSpec("vehicle_seating_capacity", "number", False, "Seating capacity (including driver) as a whole number."),
        FieldSpec("registration_date", "date", False, "Date of registration (Regn. Date / Date of Regn.).",
                  normalization="date_dd_mm_yyyy"),
        FieldSpec("registering_authority", "string", False, "Registering authority / RTO name or code exactly as printed."),
    ],
    system_prompt=(
        "You extract data from an Indian Vehicle Registration Certificate (RC) -- paper book, laminated card or "
        "smart card, front and/or back. Read only what is printed in the labelled boxes. Registration, chassis "
        "and engine numbers are identifiers: copy them character for character and never repair or complete them.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "A smart card may show the registration number on the front and the chassis/engine numbers on the back; use both sides when both are supplied.",
        "Do not take the financier (hypothecation / HP) name as the owner.",
        "If the certificate shows a transfer of ownership, owner_name is the current (latest) owner.",
        "registration_date is the registration date, not the fitness/validity or tax-paid-up-to date.",
        "If a field is not printed or is unclear, return null with low confidence.",
    ],
)
