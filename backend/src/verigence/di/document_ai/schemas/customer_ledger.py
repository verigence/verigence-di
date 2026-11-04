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
    schema_version="1.1",
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
        FieldSpec(key="statement_title", field_type="string", required=False, description="Title printed at the top of the dealer's own account statement form, verbatim (for example Account Statement, Vehicle Account Statement, Accounts Statement); empty for a DMS or Tally ledger export"),
        FieldSpec(key="vehicle_model", field_type="string", required=False, description="Vehicle model printed on the account statement form, exactly as printed"),
        FieldSpec(key="vin_number", field_type="string", required=False, description="Vehicle VIN / chassis number printed on the account statement form, exactly as printed"),
        FieldSpec(key="invoice_number", field_type="string", required=False, description="Invoice number printed on the account statement form, exactly as printed"),
        FieldSpec(key="invoice_date", field_type="date", required=False, description="Invoice date printed on the account statement form", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="booking_date", field_type="date", required=False, description="Booking date printed on the account statement form", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="delivery_date", field_type="date", required=False, description="Delivery date printed on the account statement form", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="gross_value", field_type="number", required=False, description="The amount printed against Gross Value on the account statement form, before the discount", normalization="indian_currency"),
        FieldSpec(key="discount_value", field_type="number", required=False, description="The amount printed against Less: Discount on the account statement form", normalization="indian_currency"),
        FieldSpec(key="net_value", field_type="number", required=False, description="The final amount the customer is to pay, as printed against Net Value, Net Receivable (A+B) or Final Price on the account statement form; never Gross Value, Total Cost or Total (A)", normalization="indian_currency"),
        FieldSpec(key="total_cost", field_type="number", required=False, description="The amount printed against Total Cost on a Vehicle Account Statement (the figure before the other discount)", normalization="indian_currency"),
        FieldSpec(key="total_receipts", field_type="number", required=False, description="The amount printed against Total Receipts, Total Receipt or Net Amount Received (E) on the account statement form", normalization="indian_currency"),
        FieldSpec(key="balance_amount", field_type="number", required=False, description="The amount printed against Short / Excess, Due or Balance Excess/Shortage (C-E) on the account statement form, as printed", normalization="indian_currency"),
        FieldSpec(key="discount_details", field_type="array", required=False, description="JSON array of the rows of the Discount Details box of the account statement form that carry an amount, each as label (verbatim: Scheme, Loyalty, Accessory, Insurance, Other, MR, Exchange Bonus, Extended Warranty) and amount; empty when the form has no such box"),
        FieldSpec(key="discount_details_total", field_type="number", required=False, description="The amount printed against Total in the Discount Details box of the account statement form", normalization="indian_currency"),
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
        "DEALER ACCOUNT STATEMENT FORMS (handwritten forms titled Account Statement, Vehicle Account Statement or Accounts Statement): "
        "read the summary figures into their own fields - gross_value, discount_value, net_value, total_cost, total_receipts, balance_amount - "
        "exactly as written, never calculated, and never copy one of them into another. Do not put those summary rows, or the rows of the Discount Details box, in line_items; "
        "line_items carries only the particulars (charges), the payments received and the discount rows of the main table. The Discount Details box goes to discount_details.",
        "net_value is the amount the customer finally pays: the figure against Net Value, Net Receivable (A+B) or Final Price. Gross Value, Total Cost and Total (A) are not net_value.",
        "VEHICLE ACCOUNTS STATEMENT FORMS IN TWO COLUMNS (titled Final Vehicle Accounts Statement or Vehicle Account "
        "Statement: a table with 'Vehicle a/c details' and a Dr. Amount column on the left - Vehicle cost, TCS, "
        "Insurance amount, Registration, Permit, Accessories, Fastag charges, Shield warranty, RSA charges, VLTD, "
        "MMFSL Cheque, Workshop billing amount, Home dly. charges, Misc (if any) - and 'Payment a/c details' with a "
        "Date and a Cr. Amount column on the right - Finance D/O, MR No. rows, Corporate Discount, Scheme Discount, "
        "Exchange/Loyalty, Exchange Value, Other Discount (if any) - then Total Cost, Refund, Total Receipt and Due "
        "under it): every left row with an amount written against it goes in line_items with particulars_raw = its "
        "printed label (a label struck out with another item written over it is the written item, for example 'RSA "
        "Charges' struck out and 'Charges' or 'Accessories' written) and the amount as debit_amount. Every right row "
        "with an amount goes in line_items as credit_amount: the finance row as particulars_raw 'FINANCE D/O' followed "
        "by the number written on it, entry_date its date; each MR row as 'MR NO' followed by the receipt number "
        "written on it, voucher_number = that number, entry_date its date; the discount and exchange rows by their "
        "printed label followed by any word written on the row (for example 'EXCHANGE LOYALTY BONUS'). total_cost is "
        "the amount against Total Cost, total_receipts the amount against Total Receipt, balance_amount the amount "
        "against Refund or Due as written. Read the amounts exactly as written, ignoring a trailing '/' or '/-'.",
        "Whenever the form prints amounts against its rows, line_items must carry those rows: never return only the "
        "totals of a form whose rows have amounts written against them.",
        "Leave every statement field empty on a DMS or Tally ledger export; an empty box on the form is empty, not zero.",
        "OFFER LETTER / PAYMENT DETAILS FORMS (a numbered grid with the charges on the left - Vehicle Price, Scheme, "
        "Ex Showroom (1-2), TCS, Handling Charge, Insurance Amount, Temporary Registration, RTO, RTO Choice No., RSA, "
        "Extended Warranty, 3M, Accessories, Permit, Others, Onroad Price, Balance Payment - and the deductions and "
        "payments on the right - Exchange Vehicle Amt, Exchange/Loyalty Bonus, Corporate Discount, Additional Discount, "
        "Booking Amount, Finance Amount, Sub Total, Downpayment, 1st EMI, Finance Fees, Misc Payment, Final Payment - "
        "then a table of dated cash receipts): put every grid row that has an amount written against it in line_items, "
        "particulars_raw = the printed row label followed by any words handwritten on that row (for example "
        "'ACCESSORIES Free'), with the amount as debit_amount for a left-hand row and as credit_amount for a right-hand "
        "row. Put each row of the receipt table in line_items too: entry_date = its date, voucher_number = its cash "
        "receipt number, particulars_raw = 'RECEIPT ' followed by the receipt number, credit_amount = its amount, "
        "voucher_type = its Cash/DD/RTGS mode. net_value is the amount against Onroad Price; total_receipts is the "
        "amount against Final Payment; balance_amount is the amount against Balance Payment. Skip rows with no amount.",
        "On that grid a printed row label struck out with another item handwritten over or beside it is that "
        "handwritten item: particulars_raw = the handwritten item only (for example 'RSA' struck out and 'Fastag' "
        "written -> 'FASTAG'; 'OTHERS' with 'FT' written -> 'OTHERS FASTAG'). An amount handwritten beside the "
        "words of a row ('Fastag 600') is that row's amount (debit_amount 600), never part of particulars_raw and "
        "never left at 0.",
    ],
)
