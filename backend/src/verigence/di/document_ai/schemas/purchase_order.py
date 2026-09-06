"""document_ai/schemas/purchase_order.py — corporate purchase-order extraction schema.

A corporate customer buying vehicle(s) issues a purchase order to the dealer.
The audit layer reconciles the PO value against the customer invoice and checks
that a corporate deal is backed by a PO.

Extraction is evidence-only. Preserve each printed amount independently; never
calculate a missing total.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

PURCHASE_ORDER_SCHEMA = SchemaDefinition(
    document_type_key="purchase_order",
    display_name="Purchase Order",
    schema_version="1.0",
    fields=[
        FieldSpec("po_number", "string", False, "Purchase order number/reference exactly as printed"),
        FieldSpec("po_date", "date", False, "Purchase order date exactly as printed", normalization="date_dd_mm_yyyy"),
        FieldSpec("buyer_company_name", "string", True, "Ordering company/organisation name exactly as printed"),
        FieldSpec("buyer_gstin", "string", False, "Buyer company GSTIN exactly as printed; null when the document says unregistered"),
        FieldSpec("buyer_address", "string", False, "Buyer company address if explicitly printed"),
        FieldSpec("supplier_name", "string", False, "Dealer/supplier name the PO is addressed to, exactly as printed"),
        FieldSpec("vehicle_model", "string", False, "Ordered vehicle model exactly as printed"),
        FieldSpec("vehicle_variant", "string", False, "Ordered vehicle variant/trim exactly as printed"),
        FieldSpec("sku_code", "string", False, "Vehicle/product/SKU code only when explicitly printed; never infer it"),
        FieldSpec("quantity", "number", False, "Ordered quantity only when explicitly printed"),
        FieldSpec("unit_price", "number", False, "Per-unit price only when explicitly printed", normalization="indian_currency"),
        FieldSpec("po_amount", "number", False, "Total purchase order value only when explicitly printed as a total; never compute it", normalization="indian_currency"),
        FieldSpec("payment_terms", "string", False, "Payment terms text exactly as printed"),
        FieldSpec("authorised_by", "string", False, "Name/designation of the person authorising the PO, exactly as printed"),
        FieldSpec("authoriser_signature_present", "boolean", False, "True only when a visible signature/stamp of the authoriser is present on the document"),
        FieldSpec("line_items", "array", False, "JSON array of visible lines. For each line preserve description_raw and extract only explicitly printed hsn_sac, quantity, unit_rate and amount"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in corporate purchase orders issued to Indian automobile dealerships.\n"
        "Extract only values explicitly visible in the supplied document.\n"
        "- Never calculate, infer, or manufacture a missing total or unit price.\n"
        "- authoriser_signature_present is true only when a signature or authorising stamp is visibly present.\n\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Currency values may use Indian numbering (for example 8,58,600); normalize only the formatting of a value that is actually visible.",
        "po_amount is the printed order total; do not derive it from quantity x unit_price.",
    ],
)
