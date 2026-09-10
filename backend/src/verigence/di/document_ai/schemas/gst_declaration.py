"""document_ai/schemas/gst_declaration.py — Customer GST-status declaration schema.

A standard dealership form ("Declaration of GST (for Sales Department)") the
customer signs at purchase, stating whether they hold a GST number to be
printed on the sales invoice, and that they will not later dispute the GSTIN
recorded (or its absence). Genuinely distinct from customer_kyc (identity
evidence) -- confirmed live: with no document type registered for this form,
DI's classifier had no correct bucket and confidently misfiled a real sample
as customer_kyc instead of surfacing it as unrecognized.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

GST_DECLARATION_SCHEMA = SchemaDefinition(
    document_type_key="gst_declaration",
    display_name="GST Declaration",
    schema_version="1.0",
    fields=[
        FieldSpec("customer_name", "string", True, "Declarant/customer name exactly as printed or handwritten."),
        FieldSpec("relation_name", "string", False, "Father's/husband's/guardian's name if stated (commonly labelled S/O, W/O, D/O)."),
        FieldSpec("address", "string", False, "Customer address exactly as stated."),
        FieldSpec("pin_code", "string", False, "PIN/postal code exactly as stated."),
        FieldSpec("vehicle_model", "string", False, "Vehicle model purchased, exactly as stated."),
        FieldSpec("purchase_date", "date", False, "Date of purchase stated in the declaration.", normalization="date_dd_mm_yyyy"),
        FieldSpec("has_gst_number", "boolean", False, "Three-state: true when the declarant states they hold a GST number, false when they explicitly declare no GST number, null when not clearly stated."),
        FieldSpec("gstin", "string", False, "The declared GSTIN, only when has_gst_number is true and a number is actually written."),
        FieldSpec("customer_signature_present", "boolean", False, "Three-state observation of the customer/owner's signature presence."),
        FieldSpec("sales_personnel_name", "string", False, "Sales personnel name if printed/signed."),
        FieldSpec("sales_personnel_signature_present", "boolean", False, "Three-state observation of the sales personnel's signature presence."),
        FieldSpec("document_date", "date", False, "Date the declaration itself was signed, if separately stated from purchase_date.", normalization="date_dd_mm_yyyy"),
    ],
    system_prompt=(
        "You extract a dealership customer GST-status declaration -- a signed form where the customer states "
        "whether they hold a GST number for invoicing purposes, or explicitly declares they have none, and "
        "agrees not to dispute the recorded GSTIN later. Extract only what the form itself states.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "has_gst_number and gstin are independent: a form can clearly declare no GST number (has_gst_number=false, gstin=null), which is the common case, not a missing field.",
        "Do not infer a GSTIN from a printed dealer GSTIN elsewhere on the page -- gstin is only the customer's own declared number.",
        "Presence observations are true/false/null. Use null for cropped, unreadable or ambiguous evidence.",
    ],
)
