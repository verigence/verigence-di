"""document_ai/schemas/delivery_order.py — Indian automotive delivery-order schema.

Extraction-only and aligned to the canonical vehicle/document vocabulary used by DI.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

DELIVERY_ORDER_SCHEMA = SchemaDefinition(
    document_type_key="delivery_order_cover",
    display_name="Delivery Order Cover",
    schema_version="1.1",
    fields=[
        FieldSpec(key="dealer_name", field_type="string", required=False, description="Dealership name if explicitly visible"),
        FieldSpec(key="delivery_order_number", field_type="string", required=False, description="Delivery order/DO number exactly as visible"),
        FieldSpec(key="delivery_date", field_type="date", required=False, description="Vehicle delivery/handover date if explicitly visible", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="customer_name", field_type="string", required=True, description="Customer receiving the vehicle"),
        FieldSpec(key="booking_reference_number", field_type="string", required=False, description="Linked booking/order/reference number if visible"),
        FieldSpec(key="vehicle_model", field_type="string", required=False, description="Vehicle model exactly as visible"),
        FieldSpec(key="vehicle_variant", field_type="string", required=False, description="Vehicle variant/trim exactly as visible"),
        FieldSpec(key="vehicle_color", field_type="string", required=False, description="Vehicle colour exactly as visible"),
        FieldSpec(key="chassis_number", field_type="string", required=False, description="Chassis/VIN exactly as visible; never reconstruct missing characters"),
        FieldSpec(key="engine_number", field_type="string", required=False, description="Engine number exactly as visible; never reconstruct missing characters"),
        FieldSpec(key="vehicle_registration_number", field_type="string", required=False, description="Vehicle registration number if explicitly visible"),
        FieldSpec(key="delivered_by", field_type="string", required=False, description="Sales/delivery executive name if explicitly visible"),
        FieldSpec(key="embedded_document_types", field_type="array", required=False, description="Other document types explicitly listed as included/attached; do not infer from an unseen bundle"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian automotive vehicle delivery documents.\n"
        "Extract only values explicitly visible in the supplied document. Never infer a VIN, engine number, registration number, booking reference, delivery date, or bundled document.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Preserve chassis/VIN and engine numbers exactly as visible.",
        "embedded_document_types may contain only document types explicitly mentioned or visibly listed on the supplied page/document.",
        "If a value is absent, obscured, or uncertain, return null with low confidence.",
    ],
)
