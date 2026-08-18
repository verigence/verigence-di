"""document_ai/schemas/upi_transaction.py — UPI Transaction Screenshot schema.

document_type_key : upi_transaction
display_name      : UPI Transaction
DB category       : ADDITIONAL
schema_version    : 1.0

Characteristics: mobile payment app screenshot (PhonePe, GPay, Paytm).
transaction_id is the PRIMARY join key.
utr_no is the SECONDARY join key — matches bank_statement_extract.reference_no.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

UPI_TRANSACTION_SCHEMA = SchemaDefinition(
    document_type_key="upi_transaction",
    display_name="UPI Transaction",
    schema_version="1.0",
    fields=[
        FieldSpec(key="app_name",            field_type="string",   required=False, description="Payment app name (e.g. PhonePe, GPay, Paytm, BHIM)"),
        FieldSpec(
            key="status",
            field_type="string",
            required=True,
            description="Transaction status",
            enum=["completed", "pending", "failed"],
        ),
        FieldSpec(key="amount",              field_type="number",   required=True,  description="Transaction amount in rupees", normalization="indian_currency"),
        FieldSpec(key="transaction_datetime",field_type="datetime", required=True,  description="Date and time of the transaction"),
        FieldSpec(key="transaction_id",      field_type="string",   required=True,  description="App-assigned transaction ID — PRIMARY JOIN KEY"),
        FieldSpec(key="utr_no",              field_type="string",   required=False, description="UPI/UTR reference number — SECONDARY JOIN KEY, matches bank statement reference_no"),
        FieldSpec(key="payer_name",          field_type="string",   required=False, description="Name of the payer"),
        FieldSpec(key="payer_masked_phone",  field_type="string",   required=False, description="Payer's phone number (may be partially masked)"),
        FieldSpec(key="payee_store_name",    field_type="string",   required=False, description="Name of the payee / merchant / store"),
        FieldSpec(key="payee_id",            field_type="string",   required=False, description="Payee UPI ID or VPA"),
        FieldSpec(
            key="payment_method",
            field_type="string",
            required=False,
            description="Payment method used",
            enum=["qr", "upi_id", "card"],
        ),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian UPI "
        "payment app screenshots.\n"
        "You will be shown a screenshot from a UPI payment application such as "
        "PhonePe, Google Pay, Paytm, or BHIM.\n\n"
        "Extract each field listed below from the screenshot.\n"
        "Output ONLY valid JSON. For each field use this exact structure:\n"
        '  "<field_key>": {"value": <extracted value or null>, "confidence": "high"|"medium"|"low"}\n\n'
        "Confidence rules:\n"
        '  "high"   — value is clearly visible on screen\n'
        '  "medium" — value is partially visible or inferred\n'
        '  "low"    — value is absent or unclear\n\n'
        "If a field is not found, return: "
        '{"value": null, "confidence": "low"}'
    ),
    prompt_notes=[
        "transaction_id: this is the app's own reference (e.g. T2408161234567890 "
        "on PhonePe). It is different from the UTR number.",
        "utr_no: the UPI Transaction Reference — shown as UTR or Ref No on the "
        "success screen. This is what appears in the bank statement.",
        "amount: normalise to plain number without currency symbol or commas.",
        "status: map screen text — 'Payment Successful', 'Success' → 'completed'; "
        "'Failed', 'Declined' → 'failed'; 'Pending', 'In Progress' → 'pending'.",
    ],
)
