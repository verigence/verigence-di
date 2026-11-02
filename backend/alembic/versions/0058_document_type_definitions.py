"""Define the global document types for the V2 classifier.

Revision ID: 0058
Revises: 0057
Create Date: 2026-11-02

The V2 classifier now shows each candidate as "key: display name -- definition",
the definition being docintel.document_types.description. Shown only a key and
a display name, it made near coin-tosses on the live tenant: the dealer's priced
deal sheet between Cost Sheet and Customer Ledger, Form 21 (RTO sale
certificate) pages filed as a vehicle invoice, New Vehicle Delivery Receipts
(no amount) as payment receipts, an internal email printout as a customer
ledger.

This writes a short definition -- what the page is and how it differs from its
neighbour -- onto the GLOBAL rows (owner_tenant_id IS NULL) that exist. A key
with no global row is left alone; tenant-owned rows are never touched. The
0020 placeholder "Schema V2 Wave-1 document type" is not a definition, and is
cleared from any global row still carrying it so it never reaches the prompt.

_DEFINITIONS is a snapshot (a migration must not import app code);
tests/test_document_type_definitions.py pins it to
verigence.di.document_ai.type_definitions.GLOBAL_DOCUMENT_TYPE_DEFINITIONS.
Nothing is re-classified here. Forward-only, like 0055.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None

_WAVE1_PLACEHOLDER = "Schema V2 Wave-1 document type"

_DEFINITIONS: dict[str, str] = {
    'customer_ledger': (
        "The dealer's priced deal sheet for one vehicle and buyer, titled e.g. Account(s) "
        'Statement, Vehicle Account(s) Statement, Offer Letter / Payment Details, Cost Sheet or '
        'NDC: charges (ex-showroom, TCS, insurance, RTO, accessories, warranty, RSA, FASTag), '
        'deductions (scheme, exchange, loyalty, scrappage, corporate, cash discount, old '
        'vehicle), payments received and net/balance. Or a Tally/DMS customer ledger: dated '
        'voucher rows with debit, credit and running balance.'
    ),
    'cost_sheet': (
        "A dealer's price sheet for one vehicle: ex-showroom, RTO, insurance, accessories and "
        'discounts up to an on-road total. When customer_ledger is also a candidate, cost_sheet '
        'is only a bare price quotation with no payments; a deal sheet listing charges, discounts'
        ' and payments received is customer_ledger, whatever its title.'
    ),
    'payment_receipt': (
        'A money receipt for an amount received: receipt number, date, the amount in figures and '
        'in words, and the mode of payment. Not a vehicle delivery acknowledgement such as a New '
        'Vehicle Delivery Receipt, which records the vehicle handed over and no amount.'
    ),
    'dealer_receipt': (
        'A money receipt for an amount received: receipt number, date, the amount in figures and '
        'in words, and the mode of payment. Not a vehicle delivery acknowledgement such as a New '
        'Vehicle Delivery Receipt, which records the vehicle handed over and no amount.'
    ),
    'customer_invoice_dms': (
        'A GST tax invoice: invoice number and date, seller and buyer, the goods with taxable '
        'value, GST (CGST/SGST or IGST) and the invoice total. Not a Form 21 / Sale Certificate, '
        'which prints the invoice number but no prices.'
    ),
    'tax_invoice_tally': (
        'A GST tax invoice: invoice number and date, seller and buyer, the goods with taxable '
        'value, GST (CGST/SGST or IGST) and the invoice total. Not a Form 21 / Sale Certificate, '
        'which prints the invoice number but no prices.'
    ),
    'tax_invoice_dms': (
        'A GST tax invoice: invoice number and date, seller and buyer, the goods with taxable '
        'value, GST (CGST/SGST or IGST) and the invoice total. Not a Form 21 / Sale Certificate, '
        'which prints the invoice number but no prices.'
    ),
    'tax_invoice': (
        'A GST tax invoice: invoice number and date, seller and buyer, the goods with taxable '
        'value, GST (CGST/SGST or IGST) and the invoice total. Not a Form 21 / Sale Certificate, '
        'which prints the invoice number but no prices.'
    ),
    'customer_invoice_dms_v2': (
        'A GST tax invoice: invoice number and date, seller and buyer, the goods with taxable '
        'value, GST (CGST/SGST or IGST) and the invoice total. Not a Form 21 / Sale Certificate, '
        'which prints the invoice number but no prices.'
    ),
    'wholesale_invoice': (
        'A GST tax invoice: invoice number and date, seller and buyer, the goods with taxable '
        'value, GST (CGST/SGST or IGST) and the invoice total. Not a Form 21 / Sale Certificate, '
        'which prints the invoice number but no prices.'
    ),
    'credit_note': (
        'A GST credit note (Rule 53) issued against an earlier invoice: credit note number and '
        'date, the original invoice reference, VIN, taxable value, GST and total. It reduces or '
        'reverses an amount already invoiced; it is not a new sale invoice.'
    ),
    'supporting_document': (
        'Any page that is none of the other candidates, e.g. a Form 21 (Sale Certificate, "See '
        'Rule 47"), a New Vehicle Delivery Receipt (vehicle handed over, no amount), an email or '
        'approval note printout, or a covering letter.'
    ),
    'booking_form': (
        "The dealer's vehicle booking (order) form filled in at booking, printed or handwritten: "
        'booking number and date, customer and contact details, model, variant and colour, the '
        'price build-up with discounts and exchange, the booking amount paid and expected '
        'delivery.'
    ),
    'insurance_cover': (
        'A motor insurance policy or cover note for the vehicle: insurer, policy number and type,'
        ' insured name, registration, chassis and engine numbers, IDV, premium, policy period, '
        'add-on covers, intermediary and any hypothecation to a financier.'
    ),
    'rto_challan': (
        'An RTO challan or RTO fee receipt for registering the vehicle: registration number or '
        'state/district, chassis number, a Particulars table of fees and taxes (road tax, '
        'registration, hypothecation charges), receipt number and date, and the grand total. Not '
        'a Form 21 Sale Certificate, which has no fees.'
    ),
    'bank_approval_letter': (
        "A financier's loan sanction or approval letter for the vehicle: financier and branch, "
        'applicant, the vehicle and price considered, sanctioned amount, tenure, interest rate, '
        'EMI, and the disbursement terms and conditions.'
    ),
    'delivery_order_cover': (
        "The dealer's delivery order (DO) or delivery cover sheet for the vehicle: DO number, "
        'delivery date, customer, booking reference, model, variant and colour, chassis and '
        'engine numbers, who delivered it, and the documents it lists as attached.'
    ),
    'scrappage_certificate_of_deposit': (
        'A Certificate of Deposit (or Transfer Certificate of Deposit) from a registered vehicle '
        'scrapping facility for an old vehicle that was scrapped: certificate number, the old '
        "vehicle's registration and details, owner or holder, issue and validity dates, and the "
        'facility. It never describes the new vehicle.'
    ),
    'valuation_report': (
        'A used-vehicle valuation report for the exchange (trade-in) vehicle: report number and '
        "date, evaluator, the old vehicle's registration, chassis, make and model, odometer, "
        'condition grading, deductions and the final offer value.'
    ),
    'gate_pass': (
        "The dealer's gate pass letting the vehicle out on delivery: the gate pass or delivery "
        'date and the car number as printed.'
    ),
    'vehicle_rc': (
        'An Indian Vehicle Registration Certificate (RC), paper book or smart card, front or '
        'back: registration number, owner name, chassis and engine numbers, model, vehicle class,'
        ' fuel, seating capacity, registration date and registering authority.'
    ),
    'pan_card': (
        "An Income Tax Department PAN card: the 10-character PAN, the holder's name, father's "
        'name and date of birth.'
    ),
    'aadhaar': (
        'An Aadhaar card or e-Aadhaar letter: the 12-digit Aadhaar number (possibly masked), '
        'name, date or year of birth, gender and address.'
    ),
    'bank_statement': (
        "A bank's account statement or extract, issued by the bank (not the dealer's own ledger):"
        ' bank name, account holder and number, and dated transaction rows with narration, '
        'reference, debit, credit and running balance.'
    ),
    'accessory_invoice_dms': (
        'A DMS invoice or challan whose goods are vehicle accessories or parts, not the vehicle '
        'itself: invoice or challan number and date, accessory line items with amounts, GST and '
        'total.'
    ),
    'accessory_invoice_tally': (
        'A Tally/accounting invoice whose goods are vehicle accessories or parts, not the vehicle'
        ' itself: invoice number and date, accessory line items, taxable value, GST and total.'
    ),
    'ew_invoice': (
        'An invoice for an extended-warranty plan on the vehicle: invoice number and date, plan '
        'name, coverage period or tenure, taxable value, GST and total.'
    ),
    'rsa_invoice': (
        'An invoice for a roadside-assistance (RSA) plan on the vehicle: invoice number and date,'
        ' plan name, coverage period or tenure, taxable value, GST and total.'
    ),
    'value_added_service_document': (
        'A document for a value-added service sold with the new vehicle, other than extended '
        'warranty or RSA, e.g. a service package certificate, protection plan or coating: title, '
        'issuer, reference number, date, customer and the service amount.'
    ),
}


def upgrade() -> None:
    conn = op.get_bind()
    for key, definition in _DEFINITIONS.items():
        conn.execute(
            sa.text(
                "UPDATE docintel.document_types SET description=:d, updated_at_utc=now() "
                "WHERE owner_tenant_id IS NULL AND document_type_key=:k "
                "AND description IS DISTINCT FROM :d"
            ),
            {"k": key, "d": definition},
        )
    conn.execute(
        sa.text(
            "UPDATE docintel.document_types SET description=NULL, updated_at_utc=now() "
            "WHERE owner_tenant_id IS NULL AND description=:p"
        ),
        {"p": _WAVE1_PLACEHOLDER},
    )


def downgrade() -> None:
    # Forward-only, as 0055: an earlier description was NULL or a placeholder.
    pass
