"""document_ai/schemas/payment_receipt.py — Delivery-side dealer payment receipt schema.

Delivery's registered receipt type (payment_receipt) had no dedicated extraction
schema -- it silently fell back to FALLBACK_SCHEMA's generic "extract whatever
text you see" prompt, unlike Booking's own receipt type (dealer_receipt), which
has always had one. Same real-world document (a dealership money receipt) in
both stages, so the field shape below intentionally mirrors dealer_receipt.py
rather than diverging from it.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

PAYMENT_RECEIPT_SCHEMA = SchemaDefinition(
    document_type_key="payment_receipt",
    display_name="Payment Receipt",
    schema_version="1.0",
    fields=[
        FieldSpec(key="dealer_name", field_type="string", required=True, description="Dealership name exactly as printed"),
        FieldSpec(key="dealer_gstin", field_type="string", required=False, description="Dealer GSTIN if explicitly printed"),
        FieldSpec(key="customer_name", field_type="string", required=True, description="Customer/payer name exactly as printed"),
        FieldSpec(key="customer_phone", field_type="string", required=False, description="Customer contact number if explicitly printed"),
        FieldSpec(key="receipt_number", field_type="string", required=True, description="Receipt/voucher number exactly as printed"),
        FieldSpec(key="receipt_date", field_type="date", required=True, description="Receipt/payment date exactly as printed", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="amount_paid", field_type="number", required=True, description="Amount received/paid", normalization="indian_currency"),
        FieldSpec(key="payment_mode", field_type="string", required=False, description="Payment mode exactly as printed, for example cash, cheque, UPI, card, NEFT, RTGS, DD or pay order"),
        FieldSpec(key="payment_reference_no", field_type="string", required=False, description="Cheque/DD/UTR/RRN/transaction/reference number exactly as printed"),
        FieldSpec(key="payment_reference_date", field_type="date", required=False, description="Payment instrument/reference date if printed", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="bank_name", field_type="string", required=False, description="Bank name if printed"),
        FieldSpec(key="bank_location", field_type="string", required=False, description="Bank branch/location if printed"),
        FieldSpec(key="invoice_reference_number", field_type="string", required=False, description="Linked invoice/bill number this receipt is against, if printed (Delivery receipts are typically raised against an invoice, not a booking)"),
        FieldSpec(key="remarks", field_type="string", required=False, description="Receipt remarks exactly as printed"),
        FieldSpec(key="amount_in_words", field_type="string", required=False, description="Amount in words if printed"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian automotive dealer payment receipts "
        "issued at vehicle delivery. Extract only information explicitly visible in the supplied receipt. Never "
        "infer a payment reference, invoice reference, bank, amount, or customer detail.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Preserve receipt_number and payment_reference_no exactly as visible.",
        "Do not convert one reference type into another; extract the label/value shown on the receipt.",
        "invoice_reference_number is whatever bill/invoice number the receipt states it is against -- do not confuse it with the receipt's own number.",
        "Normalize Indian currency formatting only for a clearly visible amount.",
        "If a field is not printed or is unclear, return null with low confidence.",
    ],
)
