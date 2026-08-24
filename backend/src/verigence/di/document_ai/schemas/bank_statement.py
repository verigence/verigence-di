"""document_ai/schemas/bank_statement.py — Indian bank-statement extract schema.

This schema represents a statement excerpt/transaction evidence page, not a full
statement summary. Extraction is evidence-only and preserves masked identifiers.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

BANK_STATEMENT_SCHEMA = SchemaDefinition(
    document_type_key="bank_statement_extract",
    display_name="Bank Statement Extract",
    schema_version="1.1",
    fields=[
        FieldSpec(key="bank_name", field_type="string", required=False, description="Bank/financial institution name if visible"),
        FieldSpec(key="account_holder_name", field_type="string", required=False, description="Account holder/customer name if visible"),
        FieldSpec(key="account_number", field_type="string", required=False, description="Account number exactly as visible; preserve masking and never reconstruct hidden digits"),
        FieldSpec(key="transaction_date", field_type="date", required=True, description="Transaction date exactly as printed", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="value_date", field_type="date", required=False, description="Value date if separately printed", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="transaction_description", field_type="string", required=True, description="Full narration/transaction description exactly as printed"),
        FieldSpec(key="reference_no", field_type="string", required=False, description="Reference/RRN/UTR/NEFT/RTGS/IMPS identifier explicitly present in the narration or reference column"),
        FieldSpec(key="counterparty_name", field_type="string", required=False, description="Counterparty name only when explicitly identifiable from the printed transaction row"),
        FieldSpec(key="debit_amount", field_type="number", required=False, description="Debit amount for the selected row", normalization="indian_currency"),
        FieldSpec(key="credit_amount", field_type="number", required=False, description="Credit amount for the selected row", normalization="indian_currency"),
        FieldSpec(key="running_balance", field_type="number", required=False, description="Running/account balance printed for the selected row", normalization="indian_currency"),
        FieldSpec(key="manually_flagged", field_type="boolean", required=False, description="True only when a visible highlight/circle/underline/tick or other manual mark clearly identifies the row"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian bank statement transaction evidence.\n"
        "Extract only values explicitly visible in the supplied statement image/PDF. Never infer hidden account digits, a counterparty, or a transaction reference.\n"
        "If multiple rows are visible, prefer the visibly highlighted/marked row; if no row is marked and the requested row is ambiguous, return null for row-specific values rather than guessing.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Preserve account-number masking exactly as shown.",
        "reference_no may be an RRN, UTR, NEFT, RTGS, IMPS, or other explicit bank reference; preserve it exactly.",
        "Do not merge debit and credit. Populate only the column that contains a visible amount.",
        "manually_flagged is true only when a visible annotation is present.",
    ],
)
