"""document_ai/schemas/dealer_accounts_statement.py — Dealer Accounts Statement.

document_type_key : dealer_accounts_statement
display_name      : Dealer Accounts Statement
DB category       : PRINTABLE
schema_version    : 1.0

Characteristics: the dealer's own deal-summary sheet (headed "ACCOUNTS
STATEMENT"). The most complete single view of how the deal was priced:

  A. VEHICLE COST     ex-showroom price
                      LESS consumer offer / corporate offer / exchange /
                           exchange claim
                      = TOTAL (A)
  B. ADDITIONAL COST  TCS, insurance (normal / nil-dep), registration,
                      extended warranty, RSA, accessories, fastag, others
  C. NET RECEIVABLE (A + B)
  D. PAYMENT RECEIVED  booking amount, financer amount, bank deposits, cash,
                       **cash discount**
  E. NET AMOUNT RECEIVED
  F. BALANCE (excess / shortage)

Often part-printed / part-handwritten. It is the primary source for the
discounts *the dealer actually applied* (consumer / corporate / exchange /
cash) and for the additional-cost components.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

DEALER_ACCOUNTS_STATEMENT_SCHEMA = SchemaDefinition(
    document_type_key="dealer_accounts_statement",
    display_name="Dealer Accounts Statement",
    schema_version="1.0",
    fields=[
        # ── identity ───────────────────────────────────────────────────────
        FieldSpec(key="serial_number",        field_type="string", required=False, description="Statement serial / SL number (e.g. '401')"),
        FieldSpec(key="statement_date",       field_type="date",   required=False, description="Statement date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="invoice_number",       field_type="string", required=False, description="Vehicle invoice number referenced on the statement"),
        FieldSpec(key="invoice_date",         field_type="date",   required=False, description="Invoice date referenced", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="fsc_name",             field_type="string", required=False, description="FSC (Field Sales Consultant) name"),
        FieldSpec(key="sales_manager",        field_type="string", required=False, description="Sales manager name"),

        FieldSpec(key="customer_name",        field_type="string", required=True,  description="Customer name"),
        FieldSpec(key="customer_pan",         field_type="string", required=False, description="Customer PAN"),
        FieldSpec(key="customer_gstin",       field_type="string", required=False, description="Customer GSTIN"),
        FieldSpec(key="customer_aadhaar",     field_type="string", required=False, description="Customer Aadhaar as printed"),
        FieldSpec(key="customer_address",     field_type="string", required=False, description="Customer address"),

        FieldSpec(key="vehicle_model",        field_type="string", required=True,  description="Vehicle model / variant (e.g. 'Maxx P/U HD 1.7 LLX')"),
        FieldSpec(key="chassis_number",       field_type="string", required=False, description="Chassis number — extract exactly as printed"),
        FieldSpec(key="engine_number",        field_type="string", required=False, description="Engine number"),
        FieldSpec(key="hypothecation_bank",   field_type="string", required=False, description="Bank the vehicle is hypothecated to"),
        FieldSpec(key="pricing_type",         field_type="string", required=False, description="Pricing type as printed (e.g. 'Individual', 'Corporate')"),

        # ── A. vehicle cost ────────────────────────────────────────────────
        FieldSpec(key="ex_showroom_price",    field_type="number", required=True,  description="Ex-showroom price of the vehicle (top of section A)", normalization="indian_currency"),
        FieldSpec(key="consumer_offer_amount", field_type="number", required=False, description="'LESS: CONSUMER OFFER' — the consumer-scheme discount applied, as a positive number", normalization="indian_currency"),
        FieldSpec(key="corporate_offer_amount", field_type="number", required=False, description="'LESS: CORPORATE OFFER' — corporate/privilege discount, as a positive number", normalization="indian_currency"),
        FieldSpec(key="exchange_vehicle_amount", field_type="number", required=False, description="'LESS: EXCHANGED VEHICLE' — value allowed for the trade-in vehicle, positive", normalization="indian_currency"),
        FieldSpec(key="exchange_claim_amount", field_type="number", required=False, description="'LESS: EXCHANGE CLAIM' — exchange bonus / loyalty claim, positive", normalization="indian_currency"),
        FieldSpec(key="vehicle_cost_total",   field_type="number", required=False, description="'TOTAL (A)' — ex-showroom minus the offers above", normalization="indian_currency"),

        # ── B. additional cost to vehicle ─────────────────────────────────
        FieldSpec(key="tcs_amount",           field_type="number", required=False, description="'TCS ON INVOICE'", normalization="indian_currency"),
        FieldSpec(key="insurance_normal_amount", field_type="number", required=False, description="'INSURANCE COST (NORMAL)'", normalization="indian_currency"),
        FieldSpec(key="insurance_nil_dep_amount", field_type="number", required=False, description="'INSURANCE COST (NIL DEP)' — zero-dep insurance premium", normalization="indian_currency"),
        FieldSpec(key="registration_charges", field_type="number", required=False, description="'REGISTRATION COST'", normalization="indian_currency"),
        FieldSpec(key="extended_warranty_amount", field_type="number", required=False, description="'EXTENDED WARRANTY'", normalization="indian_currency"),
        FieldSpec(key="rsa_amount",           field_type="number", required=False, description="'RSA' (roadside assistance)", normalization="indian_currency"),
        FieldSpec(key="accessories_amount",   field_type="number", required=False, description="'ACCESSORIES'", normalization="indian_currency"),
        FieldSpec(key="fastag_amount",        field_type="number", required=False, description="'FAST TAG'", normalization="indian_currency"),
        FieldSpec(key="other_charges",        field_type="number", required=False, description="'IF ANY OTHERS' / other additional charges", normalization="indian_currency"),

        # ── C. net receivable ─────────────────────────────────────────────
        FieldSpec(key="net_receivable_amount", field_type="number", required=True,  description="'NET RECEIVABLE (A + B)'", normalization="indian_currency"),

        # ── D. payments received ─────────────────────────────────────────
        FieldSpec(
            key="payment_lines",
            field_type="array",
            required=False,
            description=(
                "Array of payment-received rows from section D. One object per "
                "row with keys: payment_type (e.g. 'BOOKING AMOUNT', 'FINANCER "
                "AMOUNT', 'DEPOSITED INTO BANK', 'CASH'), mode, reference_number, "
                "date, amount. Money as plain numbers."
            ),
        ),
        FieldSpec(key="booking_amount",       field_type="number", required=False, description="Booking / advance amount received", normalization="indian_currency"),
        FieldSpec(key="financer_amount",      field_type="number", required=False, description="Amount disbursed by the financer", normalization="indian_currency"),
        FieldSpec(key="cash_amount",          field_type="number", required=False, description="Total cash received", normalization="indian_currency"),
        FieldSpec(key="cash_discount_amount", field_type="number", required=False, description="'**CASH DISCOUNT' — additional cash discount given, as a positive number", normalization="indian_currency"),

        # ── E / F ───────────────────────────────────────────────────────
        FieldSpec(key="net_amount_received",  field_type="number", required=False, description="'NET AMOUNT RECEIVED (E)'", normalization="indian_currency"),
        FieldSpec(key="balance_amount",       field_type="number", required=False, description="'BALANCE EXCESS/SHORTAGE (C - E)', signed (negative = shortage)", normalization="indian_currency"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "automotive dealership 'Accounts Statement' deal-summary sheets.\n"
        "You will be shown a dealer accounts statement — sections A (vehicle "
        "cost and offers), B (additional costs), C (net receivable), D "
        "(payments received) and E/F (net received and balance). It may be "
        "part printed and part handwritten.\n\n"
        "Extract each field listed below from the document.\n"
        "Output ONLY valid JSON. For each field use this exact structure:\n"
        '  "<field_key>": {"value": <extracted value or null>, "confidence": "high"|"medium"|"low"}\n\n'
        "Confidence rules:\n"
        '  "high"   — value is clearly written and unambiguous\n'
        '  "medium" — value is handwritten but legible, or inferred from a total\n'
        '  "low"    — value is illegible or absent\n\n'
        "If a field is not found, return: "
        '{"value": null, "confidence": "low"}\n'
        "Never guess a numeric value you cannot read."
    ),
    prompt_notes=[
        "All 'LESS:' lines in section A (consumer offer, corporate offer, "
        "exchanged vehicle, exchange claim) and the cash discount: return a "
        "POSITIVE number even though they reduce the price.",
        "consumer_offer_amount is the consumer-scheme discount the dealer "
        "applied; corporate_offer_amount is the corporate/privilege discount; "
        "exchange_claim_amount is the exchange bonus / loyalty claim; "
        "exchange_vehicle_amount is the trade-in valuation allowed.",
        "vehicle_cost_total = 'TOTAL (A)'. net_receivable_amount = 'NET "
        "RECEIVABLE (A+B)'. These are control totals — extract them even if "
        "handwritten.",
        "payment_lines: one object per row of section D that has an amount. "
        "Keys: payment_type, mode, reference_number, date, amount.",
        "balance_amount: negative when the statement shows a shortage.",
        "Handwritten figures often use '/-' or ',' — normalise to plain numbers "
        "('9,96,500/-' → 996500).",
    ],
)
