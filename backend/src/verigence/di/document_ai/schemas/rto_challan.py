"""RTO Challan extraction schema for UC03 final-report evidence."""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

RTO_CHALLAN_SCHEMA = SchemaDefinition(
    document_type_key="rto_challan",
    display_name="RTO Challan",
    schema_version="1.0",
    fields=[
        FieldSpec(
            "registration_number",
            "string",
            False,
            "Vehicle registration number only when explicitly printed or labelled on the RTO paper/challan.",
        ),
        FieldSpec(
            "registration_state",
            "string",
            False,
            "Registration/RTO State only when explicitly printed; never infer it from the registration number or RTO code.",
        ),
        FieldSpec(
            "registration_territory",
            "string",
            False,
            "Registration Territory/UT only when explicitly printed; never derive it from State, registration number, RTO code, or geography knowledge.",
        ),
        FieldSpec(
            "registration_district",
            "string",
            False,
            "Registration/RTO district only when explicitly printed; never infer it from an RTO code, city, State, or geography knowledge.",
        ),
        FieldSpec(
            "ex_showroom_amount",
            "number",
            False,
            "Ex-showroom amount only when explicitly labelled and printed; never calculate it from totals, taxes, fees, or another amount.",
        ),
        FieldSpec(
            "registration_type",
            "string",
            False,
            "Registration type/category exactly as printed; never classify or infer it from vehicle, customer, finance, or tax context.",
        ),
        FieldSpec(
            "hp_charges_amount",
            "number",
            False,
            "Hypothecation/HP charges only when explicitly labelled and printed; never derive or calculate them from finance details.",
        ),
    ],
    system_prompt=(
        "You extract final-report evidence from an automobile RTO Challan or RTO paper. "
        "Return only values explicitly visible on the document. Never decode registration "
        "numbers or RTO codes into geography, and never derive monetary values."
    ),
    prompt_notes=[
        "Preserve printed registration and geography text; do not use outside geography knowledge.",
        "If State, Territory/UT, or District is not explicitly identifiable, return null for that field.",
        "Return ex_showroom_amount and hp_charges_amount only from explicitly labelled printed amounts.",
        "Return registration_type only from explicit source text; do not classify it yourself.",
    ],
)
