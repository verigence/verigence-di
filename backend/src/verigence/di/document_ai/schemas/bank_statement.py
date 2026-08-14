"""document_ai/schemas/bank_statement.py — Bank Statement Extract schema.

document_type_key : bank_statement_extract
display_name      : Bank Statement Extract
DB category       : PRINTABLE
schema_version    : 1.0

Characteristics: screenshot or scanned excerpt of a bank statement
transaction table. May include manual annotations (highlighting, circles,
underlines) indicating a verified match.

reference_no is the PRIMARY JOIN KEY against dealer_receipt.payment_reference_no.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

BANK_STATEMENT_SCHEMA = SchemaDefinition(
    document_type_key="bank_statement_extract",
    display_name="Bank Statement Extract",
    schema_version="1.0",
    fields=[
        FieldSpec(key="transaction_date",  field_type="date",    required=True,  description="Date of the transaction", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="value_date",        field_type="date",    required=False, description="Value date of the transaction", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="description",       field_type="string",  required=True,  description="Full transaction description text as printed"),
        FieldSpec(key="reference_no",      field_type="string",  required=False, description="Reference number extracted from description (NEFT/RTGS/UTR/IMPS) — PRIMARY JOIN KEY"),
        FieldSpec(key="counterparty_name", field_type="string",  required=False, description="Counterparty name extracted from description if identifiable"),
        FieldSpec(key="debit_amount",      field_type="number",  required=False, description="Amount debited in this transaction", normalization="indian_currency"),
        FieldSpec(key="credit_amount",     field_type="number",  required=False, description="Amount credited in this transaction", normalization="indian_currency"),
        FieldSpec(key="running_balance",   field_type="number",  required=False, description="Account balance after this transaction", normalization="indian_currency"),
        FieldSpec(key="manually_flagged",  field_type="boolean", required=False, description="True if the row has visible manual annotation (highlight, circle, underline)"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "bank statement transaction rows.\n"
        "You will be shown a screenshot or scan of a bank statement — it may show "
        "one or more transaction rows from a table.\n\n"
        "Extract each field listed below from the document.\n"
        "Output ONLY valid JSON. For each field use this exact structure:\n"
        '  "<field_key>": {"value": <extracted value or null>, "confidence": "high"|"medium"|"low"}\n\n'
        "Confidence rules:\n"
        '  "high"   — value is clearly visible and unambiguous\n'
        '  "medium" — value is partially visible or inferred\n'
        '  "low"    — value is absent or unclear\n\n'
        "If a field is not found, return: "
        '{"value": null, "confidence": "low"}'
    ),
    prompt_notes=[
        "description strings often contain embedded reference numbers, for example: "
        "'BY TRANSFER-NEFT*ICIC0SF0002*IN42613257395659*DIBYENDU KUNDU*B-'. "
        "Extract the alphanumeric reference after the NEFT/RTGS/IMPS/UTR marker "
        "into reference_no (e.g. 'IN42613257395659' or 'KKBK0007395659').",
        "counterparty_name: extract the sender/receiver name from the description "
        "text if identifiable (e.g. 'DIBYENDU KUNDU' in the example above).",
        "manually_flagged: set to true if any part of the transaction row has a "
        "visible manual annotation — yellow highlight, circle, underline, or "
        "handwritten tick mark.",
        "If multiple transaction rows are visible, extract the one that is "
        "highlighted or most prominent. If ambiguous, extract the first row.",
    ],
)
