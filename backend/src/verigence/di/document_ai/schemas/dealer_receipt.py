"""document_ai/schemas/dealer_receipt.py — Dealer Receipt schema.

document_type_key : dealer_receipt
display_name      : Dealer Receipt
DB category       : PRINTABLE
schema_version    : 1.0

Characteristics: clean, printed, tabular. Highest-confidence document type.
receipt_no and payment_reference_no are the primary join keys for R2
reconciliation against bank/UPI records.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

DEALER_RECEIPT_SCHEMA = SchemaDefinition(
    document_type_key="dealer_receipt",
    display_name="Dealer Receipt",
    schema_version="1.0",
    fields=[
        FieldSpec(key="dealer_name",            field_type="string",   required=True,  description="Name of the dealership issuing the receipt"),
        FieldSpec(key="dealer_gstin",           field_type="string",   required=False, description="Dealer GSTIN (GST registration number)"),
        FieldSpec(key="customer_id",            field_type="string",   required=False, description="Customer account or ID number assigned by dealer"),
        FieldSpec(key="customer_name",          field_type="string",   required=True,  description="Full name of the customer"),
        FieldSpec(key="customer_phone",         field_type="string",   required=False, description="Customer contact phone number", normalization="phone_e164"),
        FieldSpec(key="receipt_no",             field_type="string",   required=True,  description="Receipt number — PRIMARY identifier for this payment"),
        FieldSpec(key="receipt_date",           field_type="datetime", required=True,  description="Date and time of the receipt (DD-MM-YYYY HH:mm:ss if available)"),
        FieldSpec(key="receipt_amount",         field_type="number",   required=True,  description="Total amount received", normalization="indian_currency"),
        FieldSpec(
            key="mode_of_payment",
            field_type="string",
            required=True,
            description="Payment mode",
            enum=["cash", "cheque", "rtgs", "neft", "upi", "card", "dd"],
        ),
        FieldSpec(key="payment_reference_no",   field_type="string",   required=False, description="Cheque/DD/RTGS/UTR number — PRIMARY JOIN KEY against bank statement"),
        FieldSpec(key="payment_reference_date", field_type="date",     required=False, description="Date of cheque/DD/transfer", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="bank_name",              field_type="string",   required=False, description="Bank name associated with the payment instrument"),
        FieldSpec(key="bank_location",          field_type="string",   required=False, description="Branch location of the bank"),
        FieldSpec(key="remarks",                field_type="string",   required=False, description="Free-text remarks — often contains vehicle description"),
        FieldSpec(key="amount_in_words",        field_type="string",   required=False, description="Amount written in words"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "automotive dealer payment receipts.\n"
        "You will be shown a dealer-issued receipt — typically printed, tabular, "
        "with clear fields for amount, date, receipt number and payment details.\n\n"
        "Extract each field listed below from the document.\n"
        "Output ONLY valid JSON. For each field use this exact structure:\n"
        '  "<field_key>": {"value": <extracted value or null>, "confidence": "high"|"medium"|"low"}\n\n'
        "Confidence rules:\n"
        '  "high"   — value is clearly printed and unambiguous\n'
        '  "medium" — value is partially legible or inferred from context\n'
        '  "low"    — value is absent or unclear\n\n'
        "If a field is not found, return: "
        '{"value": null, "confidence": "low"}'
    ),
    prompt_notes=[
        "payment_reference_no is the cheque number, DD number, or RTGS/NEFT UTR — "
        "extract it even if it is embedded within a longer remarks field.",
        "receipt_date: extract as DD-MM-YYYY HH:mm:ss if time is present, "
        "otherwise DD-MM-YYYY.",
        "receipt_amount: normalise to plain integer (858600 not '8,58,600').",
    ],
)
