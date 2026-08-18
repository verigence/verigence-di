"""document_ai/schemas/insurance_cover.py — Insurance Cover Note schema.

document_type_key : insurance_cover
display_name      : Insurance Cover Note
DB category       : PRINTABLE  (already seeded in migration 0005)
schema_version    : 1.0

Characteristics: printed motor insurance policy or cover note issued by an
Indian insurer. Fields vary between insurers but core fields are standard.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

INSURANCE_COVER_SCHEMA = SchemaDefinition(
    document_type_key="insurance_cover",
    display_name="Insurance Cover Note",
    schema_version="1.0",
    fields=[
        FieldSpec(key="insurer_name",          field_type="string", required=True,  description="Name of the insurance company"),
        FieldSpec(key="policy_number",         field_type="string", required=True,  description="Insurance policy or cover note number"),
        FieldSpec(
            key="policy_type",
            field_type="string",
            required=False,
            description="Type of motor insurance policy",
            enum=["comprehensive", "third_party", "own_damage", "zero_dep"],
        ),
        FieldSpec(key="insured_name",          field_type="string", required=True,  description="Full name of the insured person or entity"),
        FieldSpec(key="insured_vehicle_reg",   field_type="string", required=False, description="Vehicle registration number covered by this policy"),
        FieldSpec(key="vehicle_make_model",    field_type="string", required=False, description="Make and model of the insured vehicle"),
        FieldSpec(key="premium_amount",        field_type="number", required=False, description="Total insurance premium paid", normalization="indian_currency"),
        FieldSpec(key="sum_insured",           field_type="number", required=False, description="Insured declared value (IDV) or sum insured", normalization="indian_currency"),
        FieldSpec(key="policy_start_date",     field_type="date",   required=False, description="Policy inception / start date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="policy_end_date",       field_type="date",   required=False, description="Policy expiry date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="issue_date",            field_type="date",   required=False, description="Date the policy or cover note was issued", normalization="date_dd_mm_yyyy"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "motor vehicle insurance policies and cover notes.\n"
        "You will be shown an insurance cover note or policy document issued by "
        "an Indian insurer — it may be printed or a PDF.\n\n"
        "Extract each field listed below from the document.\n"
        "Output ONLY valid JSON. For each field use this exact structure:\n"
        '  "<field_key>": {"value": <extracted value or null>, "confidence": "high"|"medium"|"low"}\n\n'
        "Confidence rules:\n"
        '  "high"   — value is clearly printed and unambiguous\n'
        '  "medium" — value is partially legible or inferred\n'
        '  "low"    — value is absent or unclear\n\n'
        "If a field is not found, return: "
        '{"value": null, "confidence": "low"}'
    ),
    prompt_notes=[
        "policy_number: extract the full alphanumeric policy or cover note number.",
        "insured_vehicle_reg: extract the vehicle registration number (e.g. MH12AB1234).",
        "premium_amount and sum_insured: normalise to plain integers without commas.",
        "policy_type: map to the nearest enum value — "
        "'Comprehensive' → 'comprehensive', 'Third Party' → 'third_party', "
        "'Own Damage' → 'own_damage', 'Zero Depreciation' → 'zero_dep'.",
    ],
)
