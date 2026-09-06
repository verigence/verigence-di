"""document_ai/schemas/customer_ledger.py — dealer customer-ledger extract schema.

A customer ledger is the dealer's account statement for one buyer, usually
exported from the DMS or Tally. It shows the money posted against the deal:
booking advance, part payments, cash receipts, loan/finance disbursement,
exchange credit, and the running balance.

Extraction is evidence-only. Preserve every printed source amount independently
so the deterministic audit layer can reconcile the ledger against the invoice,
the payment receipts and the finance sanction later. Never calculate a missing
total or balance.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

CUSTOMER_LEDGER_SCHEMA = SchemaDefinition(
    document_type_key="customer_ledger",
    display_name="Customer Ledger",
    schema_version="1.0",
    fields=[
        FieldSpec(key="dealer_name", field_type="string", required=False, description="Dealership/company name whose books the ledger belongs to, exactly as printed"),
        FieldSpec(key="customer_name", field_type="string", required=True, description="Customer/party/account name the ledger is maintained for, exactly as printed"),
        FieldSpec(key="ledger_account_name", field_type="string", required=False, description="Ledger/account head name exactly as printed when different from the customer name"),
        FieldSpec(key="ledger_account_code", field_type="string", required=False, description="Ledger/account/party code or number exactly as printed"),
        FieldSpec(key="booking_reference_number", field_type="string", required=False, description="Booking/order/deal reference printed on the ledger, if any"),
        FieldSpec(key="source_system", field_type="string", required=False, description="Source system when the document visibly identifies it", enum=["DMS", "TALLY", "DEALER", "UNKNOWN"]),
        FieldSpec(key="period_from", field_type="date", required=False, description="Ledger period start date only when explicitly printed", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="period_to", field_type="date", required=False, description="Ledger period end date only when explicitly printed", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="opening_balance", field_type="number", required=False, description="Opening balance only when explicitly printed; keep the printed sign", normalization="indian_currency"),
        FieldSpec(key="total_debited", field_type="number", required=False, description="Total of the debit column only when explicitly printed as a total; never sum the rows yourself", normalization="indian_currency"),
        FieldSpec(key="total_credited", field_type="number", required=False, description="Total of the credit column only when explicitly printed as a total; never sum the rows yourself", normalization="indian_currency"),
        FieldSpec(key="closing_balance", field_type="number", required=False, description="Closing/running balance at the end of the ledger only when explicitly printed; keep the printed sign", normalization="indian_currency"),
        FieldSpec(key="cash_credit_total", field_type="number", required=False, description="Total of credit entries whose narration/voucher type is cash, only when the ledger prints such a subtotal; do not derive it", normalization="indian_currency"),
        FieldSpec(key="loan_credit", field_type="number", required=False, description="Credit entry representing bank/financier loan or finance disbursement, only when a row explicitly identifies it; do not infer from amount", normalization="indian_currency"),
        FieldSpec(key="exchange_credit", field_type="number", required=False, description="Credit entry representing exchange/trade-in adjustment, only when a row explicitly identifies it", normalization="indian_currency"),
        FieldSpec(key="line_items", field_type="array", required=False, description="JSON array of visible ledger rows. For each row preserve entry_date (date), particulars_raw, voucher_type, voucher_number, debit_amount, credit_amount and running_balance exactly as printed; do not merge rows or compute missing values"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian automobile-dealership customer ledgers exported from a DMS or Tally.\n"
        "The document may be a printed report, an exported PDF, or a scanned page.\n\n"
        "AUDIT EVIDENCE RULES:\n"
        "- Extract only values explicitly visible in the supplied document.\n"
        "- Never calculate, sum, infer, back-solve, or manufacture a missing total or balance.\n"
        "- Only populate total_debited / total_credited / closing_balance when the document prints them as such.\n"
        "- Keep the printed sign of every balance (a credit balance may be printed as negative or marked Cr/Dr).\n"
        "- Classify loan_credit / exchange_credit / cash_credit_total only when a row's own narration or voucher type states it; never infer from the amount.\n"
        "- Do not merge the debit and credit columns.\n\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Currency values may use Indian numbering (for example 8,58,600); normalize only the formatting of a value that is actually visible.",
        "particulars_raw must preserve the full narration text exactly, including voucher/reference identifiers.",
        "voucher_type is the printed type such as Receipt, Payment, Journal, Contra, Sales; return it verbatim.",
        "running_balance is the balance printed on that row only; never carry a value forward yourself.",
        "If the ledger shows only a final figure and no row-level build-up, return the totals/closing_balance and an empty line_items array.",
    ],
)
