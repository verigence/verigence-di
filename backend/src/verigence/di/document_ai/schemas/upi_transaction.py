"""document_ai/schemas/upi_transaction.py — Indian UPI transaction schema.

Distinguishes the app transaction ID from the bank-side UPI RRN/reference.
Extraction is evidence-only; no missing reference is inferred.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

UPI_TRANSACTION_SCHEMA = SchemaDefinition(
    document_type_key="upi_transaction",
    display_name="UPI Transaction",
    schema_version="1.1",
    fields=[
        FieldSpec(key="app_name", field_type="string", required=False, description="Payment app name if visible, e.g. PhonePe, Google Pay, Paytm, BHIM"),
        FieldSpec(key="transaction_status", field_type="string", required=True, description="Transaction status exactly as indicated on screen"),
        FieldSpec(key="amount_paid", field_type="number", required=True, description="Transaction amount in rupees", normalization="indian_currency"),
        FieldSpec(key="transaction_datetime", field_type="datetime", required=True, description="Transaction date/time exactly as displayed"),
        FieldSpec(key="upi_transaction_id", field_type="string", required=True, description="App-assigned UPI transaction ID/reference exactly as visible"),
        FieldSpec(key="upi_rrn", field_type="string", required=False, description="Bank-side UPI RRN/reference exactly as visible; do not invent if absent"),
        FieldSpec(key="payer_name", field_type="string", required=False, description="Payer/sender name if visible"),
        FieldSpec(key="payer_masked_phone", field_type="string", required=False, description="Payer phone number exactly as visible, preserving masking"),
        FieldSpec(key="payer_upi_id", field_type="string", required=False, description="Payer UPI ID/VPA if visible"),
        FieldSpec(key="payee_name", field_type="string", required=False, description="Payee/merchant/recipient name if visible"),
        FieldSpec(key="payee_upi_id", field_type="string", required=False, description="Payee/merchant UPI ID/VPA if visible"),
        FieldSpec(key="payment_method", field_type="string", required=False, description="Payment method only if explicitly shown"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian UPI payment records.\n"
        "Extract only information explicitly visible in the supplied document/screenshot.\n"
        "Do not confuse the app transaction ID with the bank-side RRN/reference. Never manufacture a missing identifier.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "upi_transaction_id is the application/payment transaction identifier exactly as displayed.",
        "upi_rrn is the bank-side UPI RRN/reference only when a separate RRN/reference is explicitly displayed.",
        "Preserve masked phone numbers and VPAs exactly as shown.",
        "Normalize INR formatting only for a visible amount; do not infer status or references from context.",
    ],
)
