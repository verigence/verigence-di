"""What each global document type IS, for the V2 classifier's prompt.

The V2 classifier shows every candidate as ``- key: display_name — definition``
where the definition is ``docintel.document_types.description``. A key and a
display name alone made near coin-tosses on the live tenant (a priced deal
sheet between Cost Sheet and Customer Ledger, Form 21 pages filed as a vehicle
invoice, New Vehicle Delivery Receipts as payment receipts, an email printout
as a customer ledger).

Each definition says what the page is and how it differs from its neighbour.
Migration 0058 writes these onto the GLOBAL rows (owner_tenant_id IS NULL)
that exist; 0059 adds form_21 and delivery_receipt with theirs and rewrites
supporting_document's; 0060 and 0062 rewrite booking_form's, cost_sheet's and supporting_document's. tests/test_document_type_definitions.py pins the
migrations' snapshots (0058 updated by 0059) to this constant. A change here
needs a new migration.
"""
from __future__ import annotations

_VEHICLE_TAX_INVOICE = (
    "A GST tax invoice: invoice number and date, seller and buyer, the goods with taxable value, "
    "GST (CGST/SGST or IGST) and the invoice total. Not a Form 21 / Sale Certificate, which "
    "prints the invoice number but no prices."
)
_MONEY_RECEIPT = (
    "A money receipt for an amount received: receipt number, date, the amount in figures and in "
    "words, and the mode of payment. Not a vehicle delivery acknowledgement such as a New Vehicle "
    "Delivery Receipt, which records the vehicle handed over and no amount."
)

GLOBAL_DOCUMENT_TYPE_DEFINITIONS: dict[str, str] = {
    "customer_ledger": (
        "The dealer's priced deal sheet for one vehicle and buyer, titled e.g. Account(s) "
        "Statement, Vehicle Account(s) Statement, Offer Letter / Payment Details, Cost Sheet or "
        "NDC: charges (ex-showroom, TCS, insurance, RTO, accessories, warranty, RSA, FASTag), "
        "deductions (scheme, exchange, loyalty, scrappage, corporate, cash discount, old "
        "vehicle), payments received and net/balance. Or a Tally/DMS customer ledger: dated "
        "voucher rows with debit, credit and running balance."
    ),
    "cost_sheet": (
        "A dealer's price sheet for one vehicle: ex-showroom, RTO, insurance, accessories and "
        "discounts up to an on-road total. When customer_ledger is also a candidate, cost_sheet "
        "is only a bare price quotation with no payments; a deal sheet listing charges, "
        "discounts and payments received is customer_ledger, whatever its title. A Transaction "
        "Regularization Form or a discount approval sheet (internal discount sanction) is "
        "supporting_document."
    ),
    "payment_receipt": _MONEY_RECEIPT,
    "dealer_receipt": _MONEY_RECEIPT,
    "customer_invoice_dms": _VEHICLE_TAX_INVOICE,
    "tax_invoice_tally": _VEHICLE_TAX_INVOICE,
    "tax_invoice_dms": _VEHICLE_TAX_INVOICE,
    "tax_invoice": _VEHICLE_TAX_INVOICE,
    "customer_invoice_dms_v2": _VEHICLE_TAX_INVOICE,
    "wholesale_invoice": _VEHICLE_TAX_INVOICE,
    "credit_note": (
        "A GST credit note (Rule 53) issued against an earlier invoice: credit note number and "
        "date, the original invoice reference, VIN, taxable value, GST and total. It reduces or "
        "reverses an amount already invoiced; it is not a new sale invoice."
    ),
    # 0059: a Form 21 and a delivery receipt have their own types now; they
    # fall here only when those types are not among the candidates.
    "supporting_document": (
        "Any page that is none of the other candidates, e.g. an email or approval note printout, "
        "a Transaction Regularization Form or a covering letter. A Form 21 (Sale Certificate, \"See Rule 47\") is form_21 and a New "
        "Vehicle Delivery Receipt (vehicle handed over, no amount) is delivery_receipt when those "
        "are candidates; otherwise they are supporting_document."
    ),
    "booking_form": (
        "The dealer's vehicle booking (order) form filled in at booking: booking number and date, "
        "customer details, model, variant and colour, price build-up, booking amount paid, expected "
        "delivery. Not an Offer Letter / Payment Details sheet (charges up to Onroad Price, Finance "
        "Amount, Final Payment, cash receipts table), which is customer_ledger."
    ),
    "insurance_cover": (
        "A motor insurance policy or cover note for the vehicle: insurer, policy number and type, "
        "insured name, registration, chassis and engine numbers, IDV, premium, policy period, "
        "add-on covers, intermediary and any hypothecation to a financier."
    ),
    "rto_challan": (
        "An RTO challan or RTO fee receipt for registering the vehicle: registration number or "
        "state/district, chassis number, a Particulars table of fees and taxes (road tax, "
        "registration, hypothecation charges), receipt number and date, and the grand total. "
        "Not a Form 21 Sale Certificate, which has no fees."
    ),
    "bank_approval_letter": (
        "A financier's loan sanction or approval letter for the vehicle: financier and branch, "
        "applicant, the vehicle and price considered, sanctioned amount, tenure, interest rate, "
        "EMI, and the disbursement terms and conditions."
    ),
    "delivery_order_cover": (
        "The dealer's delivery order (DO) or delivery cover sheet for the vehicle: DO number, "
        "delivery date, customer, booking reference, model, variant and colour, chassis and "
        "engine numbers, who delivered it, and the documents it lists as attached."
    ),
    "scrappage_certificate_of_deposit": (
        "A Certificate of Deposit (or Transfer Certificate of Deposit) from a registered vehicle "
        "scrapping facility for an old vehicle that was scrapped: certificate number, the old "
        "vehicle's registration and details, owner or holder, issue and validity dates, and the "
        "facility. It never describes the new vehicle."
    ),
    "valuation_report": (
        "A used-vehicle valuation report for the exchange (trade-in) vehicle: report number and "
        "date, evaluator, the old vehicle's registration, chassis, make and model, odometer, "
        "condition grading, deductions and the final offer value."
    ),
    "gate_pass": (
        "The dealer's gate pass letting the vehicle out on delivery: the gate pass or delivery "
        "date and the car number as printed."
    ),
    "vehicle_rc": (
        "An Indian Vehicle Registration Certificate (RC), paper book or smart card, front or "
        "back: registration number, owner name, chassis and engine numbers, model, vehicle "
        "class, fuel, seating capacity, registration date and registering authority."
    ),
    "pan_card": (
        "An Income Tax Department PAN card: the 10-character PAN, the holder's name, father's "
        "name and date of birth."
    ),
    "aadhaar": (
        "An Aadhaar card or e-Aadhaar letter: the 12-digit Aadhaar number (possibly masked), "
        "name, date or year of birth, gender and address."
    ),
    "bank_statement": (
        "A bank's account statement or extract, issued by the bank (not the dealer's own "
        "ledger): bank name, account holder and number, and dated transaction rows with "
        "narration, reference, debit, credit and running balance."
    ),
    "accessory_invoice_dms": (
        "A DMS invoice or challan whose goods are vehicle accessories or parts, not the vehicle "
        "itself: invoice or challan number and date, accessory line items with amounts, GST and "
        "total."
    ),
    "accessory_invoice_tally": (
        "A Tally/accounting invoice whose goods are vehicle accessories or parts, not the vehicle "
        "itself: invoice number and date, accessory line items, taxable value, GST and total."
    ),
    "ew_invoice": (
        "An invoice for an extended-warranty plan on the vehicle: invoice number and date, plan "
        "name, coverage period or tenure, taxable value, GST and total."
    ),
    "rsa_invoice": (
        "An invoice for a roadside-assistance (RSA) plan on the vehicle: invoice number and date, "
        "plan name, coverage period or tenure, taxable value, GST and total."
    ),
    "value_added_service_document": (
        "A document for a value-added service sold with the new vehicle, other than extended "
        "warranty or RSA, e.g. a service package certificate, protection plan or coating: title, "
        "issuer, reference number, date, customer and the service amount."
    ),
    # Added by migration 0059 with their global rows.
    "form_21": (
        "The RTO Form 21 Sale Certificate (\"FORM 21, See Rule 47(a) and (d)\", or titled only "
        "Sale(s) Certificate) a dealer issues to register the vehicle: delivery to the buyer on "
        "a date, the buyer's name and address, any financier (hypothecation), maker, model, "
        "chassis and engine numbers, colour, month/year of manufacture. It may print the "
        "invoice number but has no prices, tax or total."
    ),
    "delivery_receipt": (
        "The customer's acknowledgement of taking delivery of the new vehicle, titled e.g. New "
        "Vehicle Delivery Receipt or Delivery Note: receipt or note number, delivery date, "
        "customer, model, chassis and engine numbers and any financier. It records the vehicle "
        "handed over and no amount: not a money receipt, not the dealer's delivery order (DO) "
        "cover sheet listing attached documents, not a gate pass."
    ),
}
