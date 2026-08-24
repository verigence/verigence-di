"""document_ai/schemas/insurance_cover.py — Indian motor insurance extraction schema.

Extraction-only policy. Vehicle identifiers and add-ons are extracted only when
explicitly present. Add-ons are not treated as policy types.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

INSURANCE_COVER_SCHEMA = SchemaDefinition(
    document_type_key="insurance_cover",
    display_name="Insurance Cover Note",
    schema_version="1.1",
    fields=[
        FieldSpec(key="insurer_name", field_type="string", required=True, description="Insurance company name exactly as printed"),
        FieldSpec(key="policy_number", field_type="string", required=True, description="Policy/cover-note number exactly as printed"),
        FieldSpec(
            key="policy_type",
            field_type="string",
            required=False,
            description="Policy type only when explicitly stated",
            enum=["comprehensive", "third_party", "standalone_own_damage"],
        ),
        FieldSpec(key="insured_name", field_type="string", required=True, description="Insured/proposer name exactly as printed"),
        FieldSpec(key="vehicle_registration_number", field_type="string", required=False, description="Vehicle registration number if explicitly visible"),
        FieldSpec(key="vehicle_model", field_type="string", required=False, description="Vehicle make/model/variant exactly as visible"),
        FieldSpec(key="chassis_number", field_type="string", required=False, description="Chassis/VIN exactly as visible; never reconstruct missing characters"),
        FieldSpec(key="engine_number", field_type="string", required=False, description="Engine number exactly as visible; never reconstruct missing characters"),
        FieldSpec(key="premium_amount", field_type="number", required=False, description="Total premium amount if explicitly stated", normalization="indian_currency"),
        FieldSpec(key="idv_amount", field_type="number", required=False, description="Insured Declared Value (IDV) if explicitly stated", normalization="indian_currency"),
        FieldSpec(key="policy_start_date", field_type="date", required=False, description="Policy inception/start date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="policy_end_date", field_type="date", required=False, description="Policy expiry/end date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="issue_date", field_type="date", required=False, description="Policy/cover-note issue date if present", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="add_ons", field_type="array", required=False, description="Add-on covers explicitly listed, such as zero depreciation, RSA, engine protect, consumables, key cover, etc.; return null if none are printed"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian motor insurance policies and cover notes.\n"
        "Extract only values explicitly visible in the supplied document. Never infer missing vehicle identifiers, dates, amounts, policy type, or add-ons.\n"
        "Zero depreciation and similar covers are add-ons, not policy types.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Preserve chassis/VIN, engine number, registration number, and policy number exactly as visible.",
        "add_ons: return only covers explicitly listed in the document; otherwise return null with low confidence.",
        "policy_type: do not infer from premium components or add-ons; extract only an explicitly stated policy type.",
        "Normalize INR formatting only for amounts that are explicitly present.",
    ],
)
