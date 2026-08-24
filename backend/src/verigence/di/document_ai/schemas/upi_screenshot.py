"""document_ai/schemas/upi_screenshot.py — Indian UPI screenshot schema.

Uses the same canonical field vocabulary as upi_transaction.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

UPI_SCREENSHOT_SCHEMA = SchemaDefinition(
    document_type_key="upi_screenshot",
    display_name="UPI Screenshot",
    schema_version="1.1",
    fields=[
        FieldSpec(key="app_name", field_type="string", required=False, description="Payment app name if visible"),
        FieldSpec(key="transaction_status", field_type="string", required=True, description="Transaction status exactly as displayed"),
        FieldSpec(key="amount_paid", field_type="number", required=True, description="Amount paid in rupees", normalization="indian_currency"),
        FieldSpec(key="transaction_datetime", field_type="datetime", required=True, description="Transaction date/time exactly as displayed"),
        FieldSpec(key="upi_transaction_id", field_type="string", required=True, description="App-assigned UPI transaction ID/reference exactly as visible"),
        FieldSpec(key="upi_rrn", field_type="string", required=False, description="Bank-side UPI RRN/reference if explicitly visible"),
        FieldSpec(key="payer_name", field_type="string", required=False, description="Payer/sender name if visible"),
        FieldSpec(key="payer_masked_phone", field_type="string", required=False, description="Payer phone exactly as shown, preserving masking"),
        FieldSpec(key="payer_upi_id", field_type="string", required=False, description="Payer UPI ID/VPA if visible"),
        FieldSpec(key="payee_name", field_type="string", required=False, description="Payee/merchant/recipient name if visible"),
        FieldSpec(key="payee_upi_id", field_type="string", required=False, description="Payee/merchant UPI ID/VPA if visible"),
        FieldSpec(key="payment_method", field_type="string", required=False, description="Payment method only if explicitly shown"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian UPI payment app screenshots.\n"
        "Extract only information explicitly visible on screen. Never infer or reconstruct a missing transaction ID, RRN/reference, phone number, VPA, amount, or status.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Do not confuse upi_transaction_id with upi_rrn; return each only when separately visible.",
        "Preserve masked values exactly as displayed.",
        "If a field is not visible or is uncertain, return null with low confidence.",
    ],
)
