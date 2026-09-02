"""Gate Pass extraction schema for UC03 Delivery evidence."""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition


GATE_PASS_SCHEMA = SchemaDefinition(
    document_type_key="gate_pass",
    display_name="Gate Pass",
    schema_version="1.0",
    fields=[
        FieldSpec(
            "delivery_date",
            "string",
            False,
            "Delivery/gate-pass date exactly as printed; normalize only when unambiguous.",
            normalization="date_dd_mm_yyyy",
        ),
        FieldSpec(
            "car_number_as_printed",
            "string",
            False,
            "Car/vehicle number exactly as printed, without assuming what identifier type it is.",
        ),
        FieldSpec(
            "vehicle_registration_number",
            "string",
            False,
            (
                "Vehicle registration number only when the document explicitly labels the value "
                "as registration number or the printed format is unambiguously a registration number."
            ),
        ),
    ],
    system_prompt=(
        "You extract delivery evidence from an automobile dealership Gate Pass. Preserve only "
        "what is printed. Never reinterpret an ambiguous Car No. as a registration number."
    ),
    prompt_notes=[
        "Return delivery_date only from an explicit delivery/gate-pass date on this document.",
        "Always preserve an observed car/vehicle identifier in car_number_as_printed.",
        (
            "Populate vehicle_registration_number only when its meaning is unambiguous; otherwise "
            "leave it null even when car_number_as_printed is populated."
        ),
    ],
)
