"""document_ai/schemas/delivery_order.py — Delivery Order Cover schema.

document_type_key : delivery_order_cover
display_name      : Delivery Order Cover
DB category       : PRINTABLE
schema_version    : 1.0

Characteristics: wrapper or cover page of a multi-page delivery order PDF.
Other pages (receipts, checklists, feedback forms) within the same PDF
are uploaded as separate documents with their own document_type_key.

embedded_document_types is a list field — populated by the uploader or
operator when they know what other document types are bundled in the PDF.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

DELIVERY_ORDER_SCHEMA = SchemaDefinition(
    document_type_key="delivery_order_cover",
    display_name="Delivery Order Cover",
    schema_version="1.0",
    fields=[
        FieldSpec(key="customer_name",           field_type="string", required=True,  description="Full name of the customer receiving the vehicle"),
        FieldSpec(key="vehicle_model",           field_type="string", required=False, description="Vehicle model and variant delivered"),
        FieldSpec(key="chassis_no",              field_type="string", required=False, description="Vehicle chassis number (VIN)"),
        FieldSpec(key="engine_no",               field_type="string", required=False, description="Vehicle engine number"),
        FieldSpec(key="delivery_date",           field_type="date",   required=False, description="Date of vehicle delivery", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="delivered_by",            field_type="string", required=False, description="Name of the sales/delivery executive"),
        FieldSpec(key="embedded_document_types", field_type="array",  required=False, description="List of document type keys found within this PDF bundle"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "automotive vehicle delivery order documents.\n"
        "You will be shown the cover page or summary page of a vehicle delivery "
        "order — this is typically a printed form confirming vehicle handover.\n\n"
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
        "chassis_no (VIN): typically 17 characters, printed on a label or stamped. "
        "Extract exactly as printed — do not normalise.",
        "engine_no: separate from chassis_no — shorter alphanumeric code.",
        "embedded_document_types: if the document mentions other bundled documents "
        "(e.g. insurance, receipt, checklist), list their types as an array of strings. "
        "If not mentioned, return null.",
        "delivery_date: extract as DD-MM-YYYY.",
    ],
)
