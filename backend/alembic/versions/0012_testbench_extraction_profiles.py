"""Provision global extraction profiles for the full DI test bench.

Configuration-only migration. No REST API contract, worker orchestration, or
production journey is changed. The existing DI worker resolves these global
ACTIVE Document Types and global PUBLISHED Extraction Profiles through the
same path used by application uploads.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-24
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_MIGRATION_ACTOR = "migration.0012.testbench-profiles"

# document_type_key -> (display_name, category)
_DOCUMENT_TYPES: dict[str, tuple[str, str]] = {
    "booking_form": ("Booking Form", "HANDWRITTEN"),
    "booking_docket": ("Booking Docket", "PRINTABLE"),
    "pan_card": ("PAN Card", "GOVT_ID"),
    "aadhaar": ("Aadhaar Card", "GOVT_ID"),
    "passport": ("Passport", "GOVT_ID"),
    "driving_licence": ("Driving Licence", "GOVT_ID"),
    "voter_id": ("Voter ID", "GOVT_ID"),
    "corporate_id": ("Corporate ID", "PRINTABLE"),
    "bank_statement": ("Bank Statement", "PRINTABLE"),
    "bank_statement_extract": ("Bank Statement Extract", "PRINTABLE"),
    "loan_statement": ("Loan Statement", "PRINTABLE"),
    "customer_ledger": ("Customer Ledger", "PRINTABLE"),
    "insurance_cover": ("Insurance Cover Note", "PRINTABLE"),
    "utility_bill": ("Utility Bill", "PRINTABLE"),
    "salary_slip": ("Salary Slip", "PRINTABLE"),
    "signed_declaration": ("Signed Declaration", "HANDWRITTEN"),
    "supporting_document": ("Supporting Document", "ADDITIONAL"),
    "dealer_receipt": ("Dealer Receipt", "PRINTABLE"),
    "upi_transaction": ("UPI Transaction", "ADDITIONAL"),
    "delivery_order_cover": ("Delivery Order Cover", "PRINTABLE"),
    "upi_screenshot": ("UPI Screenshot", "ADDITIONAL"),
}

# field_key, display_name, data_type, expected, score_included, score_weight,
# display_sequence, extraction_instruction, aliases
F = tuple[Any, ...]

_PROFILES: dict[str, tuple[str, list[F]]] = {
    "booking_docket": (
        "Booking Docket Baseline Extraction",
        [
            ("dealer_name", "Dealer Name", "STRING", True, True, 1.0, 10, "Extract the dealership name.", ["dealer", "dealership"]),
            ("dealer_branch", "Dealer Branch", "STRING", False, False, 0.0, 20, "Extract the dealer branch or outlet if present.", ["branch", "outlet"]),
            ("booking_reference_number", "Booking Reference Number", "IDENTIFIER", True, True, 1.0, 30, "Extract the booking, order, enquiry, or reference number.", ["booking no", "order no", "reference no"]),
            ("booking_date", "Booking Date", "DATE", True, True, 1.0, 40, "Extract the booking date; return YYYY-MM-DD when complete.", ["booking date", "date"]),
            ("customer_name", "Customer Name", "STRING", True, True, 1.0, 50, "Extract the full customer name.", ["customer", "name"]),
            ("customer_phone", "Customer Phone", "PHONE", False, False, 0.0, 60, "Extract the customer mobile or contact number.", ["mobile", "phone", "contact"]),
            ("vehicle_model", "Vehicle Model", "STRING", True, True, 1.0, 70, "Extract the booked vehicle model.", ["model"]),
            ("vehicle_variant", "Vehicle Variant", "STRING", False, False, 0.0, 80, "Extract the vehicle variant or trim.", ["variant", "trim"]),
            ("vehicle_color", "Vehicle Color", "STRING", False, False, 0.0, 90, "Extract the booked or preferred vehicle colour.", ["color", "colour"]),
            ("booking_amount_paid", "Booking Amount Paid", "CURRENCY", False, False, 0.0, 100, "Extract the booking advance or amount paid.", ["booking amount", "advance"]),
            ("total_price", "Total Price", "CURRENCY", False, False, 0.0, 110, "Extract the total/on-road price if present.", ["total", "on road price"]),
            ("sales_person", "Sales Person", "STRING", False, False, 0.0, 120, "Extract the sales executive or consultant name.", ["sales executive", "sales consultant"]),
        ],
    ),
    "passport": (
        "Passport Baseline Extraction",
        [
            ("passport_number", "Passport Number", "IDENTIFIER", True, True, 1.0, 10, "Extract the passport number exactly as printed.", ["passport no", "passport number"]),
            ("passport_name", "Passport Holder Name", "STRING", True, True, 1.0, 20, "Extract the passport holder's full name.", ["name", "given name", "surname"]),
            ("nationality", "Nationality", "STRING", False, False, 0.0, 30, "Extract nationality as printed.", ["nationality"]),
            ("date_of_birth", "Date of Birth", "DATE", True, True, 1.0, 40, "Extract date of birth; return YYYY-MM-DD when complete.", ["dob", "date of birth"]),
            ("gender", "Gender", "STRING", False, False, 0.0, 50, "Extract sex/gender as printed.", ["sex", "gender"]),
            ("issue_date", "Issue Date", "DATE", False, False, 0.0, 60, "Extract passport issue date.", ["date of issue", "issue date"]),
            ("expiry_date", "Expiry Date", "DATE", True, True, 1.0, 70, "Extract passport expiry date.", ["date of expiry", "expiry date"]),
            ("place_of_issue", "Place of Issue", "STRING", False, False, 0.0, 80, "Extract place of issue if present.", ["place of issue"]),
        ],
    ),
    "driving_licence": (
        "Driving Licence Baseline Extraction",
        [
            ("driving_licence_number", "Driving Licence Number", "IDENTIFIER", True, True, 1.0, 10, "Extract the driving licence number exactly as printed.", ["dl no", "licence no", "license no"]),
            ("licence_name", "Licence Holder Name", "STRING", True, True, 1.0, 20, "Extract the licence holder's full name.", ["name", "holder name"]),
            ("date_of_birth", "Date of Birth", "DATE", True, True, 1.0, 30, "Extract date of birth; return YYYY-MM-DD when complete.", ["dob", "date of birth"]),
            ("issue_date", "Issue Date", "DATE", False, False, 0.0, 40, "Extract licence issue date.", ["issue date", "date of issue"]),
            ("expiry_date", "Expiry Date", "DATE", True, True, 1.0, 50, "Extract licence validity/expiry date.", ["valid till", "validity", "expiry"]),
            ("licence_address", "Licence Address", "STRING", False, False, 0.0, 60, "Extract the address printed on the licence.", ["address"]),
            ("vehicle_class", "Vehicle Class", "STRING", False, False, 0.0, 70, "Extract authorised vehicle class/category values.", ["class of vehicle", "cov"]),
        ],
    ),
    "voter_id": (
        "Voter ID Baseline Extraction",
        [
            ("voter_id_number", "Voter ID Number", "IDENTIFIER", True, True, 1.0, 10, "Extract the EPIC/Voter ID number exactly as printed.", ["epic no", "voter id", "identity card no"]),
            ("voter_name", "Voter Name", "STRING", True, True, 1.0, 20, "Extract the voter's full name.", ["name", "elector name"]),
            ("date_of_birth", "Date of Birth", "DATE", False, False, 0.0, 30, "Extract date of birth if complete; do not invent missing components.", ["dob", "date of birth"]),
            ("gender", "Gender", "STRING", False, False, 0.0, 40, "Extract gender as printed.", ["sex", "gender"]),
            ("voter_address", "Voter Address", "STRING", False, False, 0.0, 50, "Extract the address if present.", ["address"]),
        ],
    ),
    "corporate_id": (
        "Corporate ID Baseline Extraction",
        [
            ("employee_id", "Employee ID", "IDENTIFIER", True, True, 1.0, 10, "Extract the employee/staff ID.", ["employee id", "emp id", "staff id"]),
            ("employee_name", "Employee Name", "STRING", True, True, 1.0, 20, "Extract the employee's full name.", ["name", "employee name"]),
            ("company_name", "Company Name", "STRING", True, True, 1.0, 30, "Extract the employer/company name.", ["company", "organisation", "organization"]),
            ("designation", "Designation", "STRING", False, False, 0.0, 40, "Extract designation/title if present.", ["designation", "title"]),
            ("valid_until", "Valid Until", "DATE", False, False, 0.0, 50, "Extract validity/expiry date if present.", ["valid till", "valid until", "expiry"]),
        ],
    ),
    "bank_statement": (
        "Bank Statement Baseline Extraction",
        [
            ("bank_name", "Bank Name", "STRING", True, True, 1.0, 10, "Extract the bank or financial institution name.", ["bank", "bank name"]),
            ("account_holder_name", "Account Holder Name", "STRING", True, True, 1.0, 20, "Extract the account holder/customer name.", ["account holder", "customer name", "name"]),
            ("account_number", "Account Number", "IDENTIFIER", True, True, 1.0, 30, "Extract the account number exactly as visible; preserve masking and never infer hidden digits.", ["account no", "a/c no", "account number"]),
            ("ifsc_code", "IFSC Code", "IDENTIFIER", False, False, 0.0, 40, "Extract IFSC code if present.", ["ifsc", "ifsc code"]),
            ("statement_start_date", "Statement Start Date", "DATE", False, False, 0.0, 50, "Extract the statement period start date.", ["from date", "statement from", "period from"]),
            ("statement_end_date", "Statement End Date", "DATE", False, False, 0.0, 60, "Extract the statement period end date.", ["to date", "statement to", "period to"]),
            ("opening_balance", "Opening Balance", "CURRENCY", False, False, 0.0, 70, "Extract the opening balance as a numeric amount.", ["opening balance"]),
            ("closing_balance", "Closing Balance", "CURRENCY", True, True, 1.0, 80, "Extract the closing/available balance as a numeric amount.", ["closing balance", "available balance"]),
            ("total_credits", "Total Credits", "CURRENCY", False, False, 0.0, 90, "Extract total credits if explicitly stated.", ["total credits", "credit total"]),
            ("total_debits", "Total Debits", "CURRENCY", False, False, 0.0, 100, "Extract total debits if explicitly stated.", ["total debits", "debit total"]),
        ],
    ),
    "bank_statement_extract": (
        "Bank Statement Extract Baseline Extraction",
        [
            ("bank_name", "Bank Name", "STRING", True, True, 1.0, 10, "Extract the bank name.", ["bank"]),
            ("account_holder_name", "Account Holder Name", "STRING", True, True, 1.0, 20, "Extract the account holder/customer name.", ["account holder", "customer name"]),
            ("account_number", "Account Number", "IDENTIFIER", True, True, 1.0, 30, "Extract the account number as visible; preserve masking.", ["account no", "a/c no"]),
            ("transaction_date", "Transaction Date", "DATE", False, False, 0.0, 40, "Extract the principal transaction date shown in the extract.", ["transaction date", "date"]),
            ("transaction_description", "Transaction Description", "STRING", False, False, 0.0, 50, "Extract the principal transaction narration/description.", ["narration", "description", "particulars"]),
            ("transaction_amount", "Transaction Amount", "CURRENCY", False, False, 0.0, 60, "Extract the principal transaction amount.", ["amount", "transaction amount"]),
            ("closing_balance", "Closing Balance", "CURRENCY", False, False, 0.0, 70, "Extract balance after/latest balance if present.", ["balance", "closing balance"]),
        ],
    ),
    "loan_statement": (
        "Loan Statement Baseline Extraction",
        [
            ("lender_name", "Lender Name", "STRING", True, True, 1.0, 10, "Extract the lender/bank/NBFC name.", ["lender", "bank", "financial institution"]),
            ("borrower_name", "Borrower Name", "STRING", True, True, 1.0, 20, "Extract the borrower/customer name.", ["borrower", "customer"]),
            ("loan_account_number", "Loan Account Number", "IDENTIFIER", True, True, 1.0, 30, "Extract the loan account/reference number.", ["loan account no", "loan no", "loan id"]),
            ("loan_statement_date", "Statement Date", "DATE", False, False, 0.0, 40, "Extract statement/as-on date.", ["statement date", "as on"]),
            ("principal_outstanding", "Principal Outstanding", "CURRENCY", True, True, 1.0, 50, "Extract outstanding principal/loan balance.", ["principal outstanding", "outstanding balance"]),
            ("emi_amount", "EMI Amount", "CURRENCY", False, False, 0.0, 60, "Extract EMI/installment amount.", ["emi", "instalment", "installment"]),
            ("overdue_amount", "Overdue Amount", "CURRENCY", False, False, 0.0, 70, "Extract overdue/past-due amount.", ["overdue", "past due"]),
            ("next_due_date", "Next Due Date", "DATE", False, False, 0.0, 80, "Extract next EMI/payment due date.", ["next due date", "due date"]),
            ("interest_rate", "Interest Rate", "STRING", False, False, 0.0, 90, "Extract applicable interest rate exactly as stated.", ["interest rate", "roi"]),
        ],
    ),
    "customer_ledger": (
        "Customer Ledger Baseline Extraction",
        [
            ("dealer_name", "Dealer Name", "STRING", False, False, 0.0, 10, "Extract dealer/company name maintaining the ledger.", ["dealer", "company"]),
            ("customer_name", "Customer Name", "STRING", True, True, 1.0, 20, "Extract customer/account name.", ["customer", "account name"]),
            ("ledger_reference", "Ledger Reference", "IDENTIFIER", False, False, 0.0, 30, "Extract customer/ledger/account reference if present.", ["ledger no", "customer code", "account code"]),
            ("ledger_start_date", "Ledger Start Date", "DATE", False, False, 0.0, 40, "Extract ledger period start date.", ["from date", "period from"]),
            ("ledger_end_date", "Ledger End Date", "DATE", False, False, 0.0, 50, "Extract ledger period end date.", ["to date", "period to"]),
            ("opening_balance", "Opening Balance", "CURRENCY", False, False, 0.0, 60, "Extract opening balance.", ["opening balance"]),
            ("closing_balance", "Closing Balance", "CURRENCY", True, True, 1.0, 70, "Extract closing/balance due amount.", ["closing balance", "balance due"]),
            ("total_debits", "Total Debits", "CURRENCY", False, False, 0.0, 80, "Extract total debits if shown.", ["total debits"]),
            ("total_credits", "Total Credits", "CURRENCY", False, False, 0.0, 90, "Extract total credits if shown.", ["total credits"]),
        ],
    ),
    "insurance_cover": (
        "Insurance Cover Note Baseline Extraction",
        [
            ("insurer_name", "Insurer Name", "STRING", True, True, 1.0, 10, "Extract the insurance company name.", ["insurer", "insurance company"]),
            ("policy_number", "Policy Number", "IDENTIFIER", True, True, 1.0, 20, "Extract policy/cover-note number.", ["policy no", "cover note no"]),
            ("insured_name", "Insured Name", "STRING", True, True, 1.0, 30, "Extract insured/proposer name.", ["insured", "proposer"]),
            ("vehicle_registration_number", "Vehicle Registration Number", "IDENTIFIER", False, False, 0.0, 40, "Extract vehicle registration number if available.", ["registration no", "vehicle no"]),
            ("vehicle_model", "Vehicle Model", "STRING", False, False, 0.0, 50, "Extract insured vehicle model.", ["model"]),
            ("chassis_number", "Chassis Number", "IDENTIFIER", False, False, 0.0, 60, "Extract chassis/VIN number exactly as visible.", ["chassis no", "vin"]),
            ("engine_number", "Engine Number", "IDENTIFIER", False, False, 0.0, 70, "Extract engine number exactly as visible.", ["engine no"]),
            ("policy_start_date", "Policy Start Date", "DATE", True, True, 1.0, 80, "Extract policy inception/start date.", ["policy start", "from"]),
            ("policy_end_date", "Policy End Date", "DATE", True, True, 1.0, 90, "Extract policy expiry/end date.", ["policy end", "valid till", "to"]),
            ("premium_amount", "Premium Amount", "CURRENCY", False, False, 0.0, 100, "Extract total premium amount.", ["premium", "total premium"]),
            ("idv_amount", "IDV Amount", "CURRENCY", False, False, 0.0, 110, "Extract insured declared value if present.", ["idv", "insured declared value"]),
        ],
    ),
    "utility_bill": (
        "Utility Bill Baseline Extraction",
        [
            ("utility_provider", "Utility Provider", "STRING", True, True, 1.0, 10, "Extract utility/service provider name.", ["provider", "utility"]),
            ("consumer_number", "Consumer Number", "IDENTIFIER", True, True, 1.0, 20, "Extract consumer/account/service number.", ["consumer no", "account no", "service no"]),
            ("customer_name", "Customer Name", "STRING", True, True, 1.0, 30, "Extract customer/consumer name.", ["consumer name", "customer name"]),
            ("service_address", "Service Address", "STRING", False, False, 0.0, 40, "Extract service/billing address.", ["service address", "billing address", "address"]),
            ("bill_date", "Bill Date", "DATE", False, False, 0.0, 50, "Extract bill/invoice date.", ["bill date", "invoice date"]),
            ("due_date", "Due Date", "DATE", False, False, 0.0, 60, "Extract payment due date.", ["due date", "pay by"]),
            ("bill_amount", "Bill Amount", "CURRENCY", True, True, 1.0, 70, "Extract amount due/total bill amount.", ["amount due", "bill amount", "total amount"]),
            ("billing_period", "Billing Period", "STRING", False, False, 0.0, 80, "Extract billing/consumption period.", ["billing period", "period"]),
        ],
    ),
    "salary_slip": (
        "Salary Slip Baseline Extraction",
        [
            ("employer_name", "Employer Name", "STRING", True, True, 1.0, 10, "Extract employer/company name.", ["employer", "company"]),
            ("employee_name", "Employee Name", "STRING", True, True, 1.0, 20, "Extract employee full name.", ["employee name", "name"]),
            ("employee_id", "Employee ID", "IDENTIFIER", False, False, 0.0, 30, "Extract employee/staff ID if present.", ["employee id", "emp no"]),
            ("designation", "Designation", "STRING", False, False, 0.0, 40, "Extract designation/title.", ["designation", "title"]),
            ("pay_period", "Pay Period", "STRING", True, True, 1.0, 50, "Extract salary month/pay period exactly as stated.", ["pay period", "salary month", "month"]),
            ("basic_salary", "Basic Salary", "CURRENCY", False, False, 0.0, 60, "Extract basic pay amount.", ["basic", "basic salary"]),
            ("gross_salary", "Gross Salary", "CURRENCY", True, True, 1.0, 70, "Extract gross earnings/salary.", ["gross", "gross earnings"]),
            ("deductions_total", "Total Deductions", "CURRENCY", False, False, 0.0, 80, "Extract total deductions.", ["total deductions", "deductions"]),
            ("net_salary", "Net Salary", "CURRENCY", True, True, 1.0, 90, "Extract net pay/take-home salary.", ["net pay", "net salary", "take home"]),
        ],
    ),
    "signed_declaration": (
        "Signed Declaration Baseline Extraction",
        [
            ("declarant_name", "Declarant Name", "STRING", True, True, 1.0, 10, "Extract the person making/signing the declaration.", ["declarant", "name"]),
            ("declaration_date", "Declaration Date", "DATE", False, False, 0.0, 20, "Extract the signed/declaration date if present.", ["date", "signed on"]),
            ("declaration_text", "Declaration Text", "STRING", True, True, 1.0, 30, "Extract the main declaration/undertaking text without inventing missing words.", ["declaration", "undertaking"]),
            ("signature_present", "Signature Present", "STRING", False, False, 0.0, 40, "Return YES only if a visible handwritten/digital signature mark is present; otherwise NO or UNKNOWN.", ["signature", "signed"]),
        ],
    ),
    "supporting_document": (
        "Supporting Document Baseline Extraction",
        [
            ("document_title", "Document Title", "STRING", True, True, 1.0, 10, "Extract the document's visible title/type.", ["title", "document type"]),
            ("issuing_entity", "Issuing Entity", "STRING", False, False, 0.0, 20, "Extract organisation/authority issuing the document.", ["issued by", "issuer", "authority"]),
            ("reference_number", "Reference Number", "IDENTIFIER", False, False, 0.0, 30, "Extract the primary reference/certificate/document number if present.", ["reference no", "document no", "certificate no"]),
            ("document_date", "Document Date", "DATE", False, False, 0.0, 40, "Extract the primary issue/document date if present.", ["date", "issued on"]),
            ("subject_name", "Subject Name", "STRING", False, False, 0.0, 50, "Extract the person/entity the document relates to.", ["name", "subject"]),
        ],
    ),
    "dealer_receipt": (
        "Dealer Receipt Baseline Extraction",
        [
            ("dealer_name", "Dealer Name", "STRING", True, True, 1.0, 10, "Extract dealership name.", ["dealer", "dealership"]),
            ("receipt_number", "Receipt Number", "IDENTIFIER", True, True, 1.0, 20, "Extract receipt/voucher number.", ["receipt no", "voucher no"]),
            ("receipt_date", "Receipt Date", "DATE", True, True, 1.0, 30, "Extract receipt/payment date.", ["receipt date", "date"]),
            ("customer_name", "Customer Name", "STRING", True, True, 1.0, 40, "Extract payer/customer name.", ["customer", "received from"]),
            ("amount_paid", "Amount Paid", "CURRENCY", True, True, 1.0, 50, "Extract amount received/paid.", ["amount", "amount received"]),
            ("payment_mode", "Payment Mode", "STRING", False, False, 0.0, 60, "Extract cash/card/UPI/cheque/NEFT/RTGS or other mode.", ["payment mode", "mode"]),
            ("payment_reference_no", "Payment Reference Number", "IDENTIFIER", False, False, 0.0, 70, "Extract transaction/UTR/cheque/payment reference if present.", ["utr", "transaction id", "reference no", "cheque no"]),
            ("booking_reference_number", "Booking Reference Number", "IDENTIFIER", False, False, 0.0, 80, "Extract linked booking/order/reference number if present.", ["booking no", "order no"]),
        ],
    ),
    "upi_transaction": (
        "UPI Transaction Baseline Extraction",
        [
            ("payer_name", "Payer Name", "STRING", False, False, 0.0, 10, "Extract payer/sender name if shown.", ["payer", "from", "sender"]),
            ("payee_name", "Payee Name", "STRING", True, True, 1.0, 20, "Extract payee/merchant/recipient name.", ["payee", "to", "merchant"]),
            ("upi_transaction_id", "UPI Transaction ID", "IDENTIFIER", True, True, 1.0, 30, "Extract UPI transaction/reference ID exactly as visible.", ["transaction id", "upi transaction id", "reference id"]),
            ("utr_number", "UTR Number", "IDENTIFIER", False, False, 0.0, 40, "Extract UTR/RRN if present.", ["utr", "rrn"]),
            ("transaction_date", "Transaction Date", "DATE", True, True, 1.0, 50, "Extract transaction date.", ["date", "transaction date"]),
            ("transaction_time", "Transaction Time", "STRING", False, False, 0.0, 60, "Extract transaction time exactly as displayed.", ["time", "transaction time"]),
            ("amount_paid", "Amount Paid", "CURRENCY", True, True, 1.0, 70, "Extract transferred/paid amount.", ["amount", "paid"]),
            ("transaction_status", "Transaction Status", "STRING", True, True, 1.0, 80, "Extract status such as SUCCESS, COMPLETED, FAILED, PENDING exactly as indicated.", ["status", "successful", "completed"]),
            ("payer_upi_id", "Payer UPI ID", "IDENTIFIER", False, False, 0.0, 90, "Extract payer UPI ID/VPA if visible.", ["payer upi id", "from upi id"]),
            ("payee_upi_id", "Payee UPI ID", "IDENTIFIER", False, False, 0.0, 100, "Extract payee/merchant UPI ID/VPA if visible.", ["payee upi id", "merchant upi id", "to upi id"]),
        ],
    ),
    "delivery_order_cover": (
        "Delivery Order Cover Baseline Extraction",
        [
            ("dealer_name", "Dealer Name", "STRING", True, True, 1.0, 10, "Extract dealership name.", ["dealer", "dealership"]),
            ("delivery_order_number", "Delivery Order Number", "IDENTIFIER", True, True, 1.0, 20, "Extract delivery order/DO number.", ["do no", "delivery order no"]),
            ("delivery_date", "Delivery Date", "DATE", True, True, 1.0, 30, "Extract delivery/handover date.", ["delivery date", "handover date"]),
            ("customer_name", "Customer Name", "STRING", True, True, 1.0, 40, "Extract customer name.", ["customer", "name"]),
            ("booking_reference_number", "Booking Reference Number", "IDENTIFIER", False, False, 0.0, 50, "Extract linked booking/order reference.", ["booking no", "order no"]),
            ("vehicle_model", "Vehicle Model", "STRING", True, True, 1.0, 60, "Extract vehicle model.", ["model"]),
            ("vehicle_variant", "Vehicle Variant", "STRING", False, False, 0.0, 70, "Extract vehicle variant/trim.", ["variant", "trim"]),
            ("vehicle_color", "Vehicle Color", "STRING", False, False, 0.0, 80, "Extract vehicle colour.", ["color", "colour"]),
            ("chassis_number", "Chassis Number", "IDENTIFIER", True, True, 1.0, 90, "Extract chassis/VIN number exactly as visible.", ["chassis no", "vin"]),
            ("engine_number", "Engine Number", "IDENTIFIER", False, False, 0.0, 100, "Extract engine number.", ["engine no"]),
            ("vehicle_registration_number", "Vehicle Registration Number", "IDENTIFIER", False, False, 0.0, 110, "Extract registration number if available.", ["registration no", "vehicle no"]),
        ],
    ),
    "upi_screenshot": (
        "UPI Screenshot Baseline Extraction",
        [
            ("payee_name", "Payee Name", "STRING", True, True, 1.0, 10, "Extract recipient/merchant name shown on the payment screenshot.", ["paid to", "to", "merchant"]),
            ("upi_transaction_id", "UPI Transaction ID", "IDENTIFIER", True, True, 1.0, 20, "Extract transaction/reference ID exactly as visible.", ["transaction id", "reference id"]),
            ("utr_number", "UTR Number", "IDENTIFIER", False, False, 0.0, 30, "Extract UTR/RRN if present.", ["utr", "rrn"]),
            ("transaction_date", "Transaction Date", "DATE", True, True, 1.0, 40, "Extract payment date.", ["date", "transaction date"]),
            ("transaction_time", "Transaction Time", "STRING", False, False, 0.0, 50, "Extract payment time if shown.", ["time"]),
            ("amount_paid", "Amount Paid", "CURRENCY", True, True, 1.0, 60, "Extract amount paid.", ["amount", "paid"]),
            ("transaction_status", "Transaction Status", "STRING", True, True, 1.0, 70, "Extract success/completion/failure status exactly as indicated.", ["status", "successful", "completed"]),
            ("payee_upi_id", "Payee UPI ID", "IDENTIFIER", False, False, 0.0, 80, "Extract recipient/merchant UPI ID if visible.", ["upi id", "merchant upi id"]),
        ],
    ),
}

# 0011 already owns these published profiles. They are intentionally left in
# place; 0012 only ensures the document types still exist and fills every
# remaining test-bench type.
_ALREADY_PROVISIONED = {"booking_form", "pan_card", "aadhaar"}


def _ensure_document_type(conn: Any, key: str, display_name: str, category: str) -> None:
    conn.execute(
        sa.text("""
            INSERT INTO docintel.document_types (
                document_type_id, owner_tenant_id, document_type_key,
                display_name, description, category, status,
                created_at_utc, updated_at_utc
            )
            SELECT gen_random_uuid(), NULL, :key, :display_name, NULL,
                   :category, 'ACTIVE', now(), now()
            WHERE NOT EXISTS (
                SELECT 1 FROM docintel.document_types
                WHERE owner_tenant_id IS NULL AND document_type_key=:key
            )
        """),
        {"key": key, "display_name": display_name, "category": category},
    )


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str, data_type: str) -> None:
    existing_type = conn.execute(
        sa.text("""
            SELECT data_type FROM docintel.canonical_fields
            WHERE owner_tenant_id IS NULL AND field_key=:field_key
        """),
        {"field_key": field_key},
    ).scalar_one_or_none()
    if existing_type is not None:
        if existing_type != data_type:
            raise RuntimeError(
                f"Canonical field {field_key} already exists as {existing_type}, requested {data_type}"
            )
        return

    conn.execute(
        sa.text("""
            INSERT INTO docintel.canonical_fields (
                canonical_field_id, owner_tenant_id, field_key, display_name,
                data_type, description, status, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), NULL, :field_key, :display_name,
                :data_type, NULL, 'ACTIVE', now(), now()
            )
        """),
        {"field_key": field_key, "display_name": display_name, "data_type": data_type},
    )


def _ensure_profile(conn: Any, key: str, profile_name: str, fields: list[F]) -> None:
    dt_id = conn.execute(
        sa.text("""
            SELECT document_type_id
            FROM docintel.document_types
            WHERE owner_tenant_id IS NULL AND document_type_key=:key AND status='ACTIVE'
        """),
        {"key": key},
    ).scalar_one()

    published_id = conn.execute(
        sa.text("""
            SELECT profile_id
            FROM docintel.extraction_profiles
            WHERE document_type_id=:dt_id
              AND scope_tenant_id IS NULL
              AND status='PUBLISHED'
            ORDER BY version_no DESC
            LIMIT 1
        """),
        {"dt_id": dt_id},
    ).scalar_one_or_none()
    if published_id is not None:
        return

    version_no = conn.execute(
        sa.text("""
            SELECT COALESCE(MAX(version_no),0)+1
            FROM docintel.extraction_profiles
            WHERE document_type_id=:dt_id AND scope_tenant_id IS NULL
        """),
        {"dt_id": dt_id},
    ).scalar_one()

    profile_id = conn.execute(
        sa.text("""
            INSERT INTO docintel.extraction_profiles (
                profile_id, document_type_id, scope_tenant_id, version_no,
                profile_name, status, classification_hint,
                created_by_actor_id, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), :dt_id, NULL, :version_no,
                :profile_name, 'DRAFT', :key,
                :actor_id, now(), now()
            ) RETURNING profile_id
        """),
        {
            "dt_id": dt_id,
            "version_no": version_no,
            "profile_name": profile_name,
            "key": key,
            "actor_id": _MIGRATION_ACTOR,
        },
    ).scalar_one()

    for (
        field_key, _display_name, _data_type, expected, score_included,
        score_weight, display_sequence, instruction, aliases,
    ) in fields:
        canonical_field_id = conn.execute(
            sa.text("""
                SELECT canonical_field_id
                FROM docintel.canonical_fields
                WHERE owner_tenant_id IS NULL AND field_key=:field_key
            """),
            {"field_key": field_key},
        ).scalar_one()
        conn.execute(
            sa.text("""
                INSERT INTO docintel.extraction_profile_fields (
                    profile_field_id, profile_id, canonical_field_id,
                    enabled, expected, extraction_instruction, aliases,
                    score_included, score_weight, use_for_subject_matching,
                    subject_identifier_type, manual_correction_allowed,
                    display_sequence, created_at_utc, updated_at_utc
                ) VALUES (
                    gen_random_uuid(), :profile_id, :canonical_field_id,
                    true, :expected, :instruction, CAST(:aliases AS jsonb),
                    :score_included, :score_weight, false,
                    NULL, true, :display_sequence, now(), now()
                )
            """),
            {
                "profile_id": profile_id,
                "canonical_field_id": canonical_field_id,
                "expected": expected,
                "instruction": instruction,
                "aliases": json.dumps(aliases),
                "score_included": score_included,
                "score_weight": score_weight,
                "display_sequence": display_sequence,
            },
        )

    conn.execute(
        sa.text("""
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED',
                published_by_actor_id=:actor_id,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:profile_id AND status='DRAFT'
        """),
        {"actor_id": _MIGRATION_ACTOR, "profile_id": profile_id},
    )


def upgrade() -> None:
    conn = op.get_bind()

    for key, (display_name, category) in _DOCUMENT_TYPES.items():
        _ensure_document_type(conn, key, display_name, category)

    seen: set[str] = set()
    for _key, (_profile_name, fields) in _PROFILES.items():
        for field_key, display_name, data_type, *_rest in fields:
            if field_key in seen:
                continue
            seen.add(field_key)
            _ensure_canonical_field(conn, field_key, display_name, data_type)

    for key, (profile_name, fields) in _PROFILES.items():
        if key in _ALREADY_PROVISIONED:
            continue
        _ensure_profile(conn, key, profile_name, fields)


def downgrade() -> None:
    # Published configuration is historical evidence. Retire only profiles
    # created by this migration; do not delete canonical fields or document types.
    op.get_bind().execute(
        sa.text("""
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE created_by_actor_id=:actor_id AND status='PUBLISHED'
        """),
        {"actor_id": _MIGRATION_ACTOR},
    )
