"""Publish India-aligned extraction-only profiles for the DI test bench.

No API contract or classifier behaviour changes. Callers continue to supply the
Document Type explicitly. Published profiles are versioned: previous published
profiles are RETIRED, never deleted, so historical processing evidence remains
referentially intact.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-24
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_MIGRATION_ACTOR = "migration.0014.india-extraction-v1"
F = tuple[Any, ...]

# field_key, display_name, data_type, expected, score_included, score_weight,
# display_sequence, extraction_instruction, aliases
_PROFILES: dict[str, tuple[str, list[F]]] = {
    "corporate_id": (
        "Employee / Corporate ID Card India Extraction v1",
        [
            ("corporate_name", "Corporate Name", "STRING", True, True, 1.0, 10, "Extract the company/corporate name exactly as printed on the employee ID card.", ["company", "corporate", "organisation", "organization", "employer"]),
            ("employee_name", "Employee Name", "STRING", True, True, 1.0, 20, "Extract the employee's full name exactly as printed.", ["employee name", "name"]),
            ("employee_number", "Employee Number", "IDENTIFIER", False, False, 0.0, 30, "Extract employee/staff/personnel number only when it is explicitly printed; otherwise return null.", ["employee no", "employee id", "emp no", "emp id", "staff no", "staff id", "personnel no"]),
            ("designation", "Designation", "STRING", False, False, 0.0, 40, "Extract designation/title only when printed.", ["designation", "title", "role"]),
            ("valid_until", "Valid Until", "DATE", False, False, 0.0, 50, "Extract card validity/expiry date only when printed.", ["valid till", "valid until", "expiry", "expires"]),
        ],
    ),
    "salary_slip": (
        "Salary Slip India Extraction v2",
        [
            ("employer_name", "Employer Name", "STRING", True, True, 1.0, 10, "Extract employer/company name exactly as printed.", ["employer", "company"]),
            ("employee_name", "Employee Name", "STRING", True, True, 1.0, 20, "Extract employee full name exactly as printed.", ["employee name", "name"]),
            ("employee_number", "Employee Number", "IDENTIFIER", False, False, 0.0, 30, "Extract employee/staff/personnel number only when printed.", ["employee id", "employee no", "emp id", "emp no", "staff id"]),
            ("designation", "Designation", "STRING", False, False, 0.0, 40, "Extract designation/title if printed.", ["designation", "title"]),
            ("pay_period", "Pay Period", "STRING", True, True, 1.0, 50, "Extract salary month/pay period exactly as stated.", ["pay period", "salary month", "month"]),
            ("basic_salary", "Basic Salary", "CURRENCY", False, False, 0.0, 60, "Extract basic pay amount only when explicitly stated.", ["basic", "basic salary", "basic pay"]),
            ("gross_salary", "Gross Salary", "CURRENCY", True, True, 1.0, 70, "Extract gross earnings/salary only when explicitly stated.", ["gross", "gross earnings", "gross salary"]),
            ("deductions_total", "Total Deductions", "CURRENCY", False, False, 0.0, 80, "Extract total deductions only when explicitly stated; do not sum individual deductions.", ["total deductions", "deductions"]),
            ("net_salary", "Net Salary", "CURRENCY", True, True, 1.0, 90, "Extract net pay/take-home amount only when explicitly stated.", ["net pay", "net salary", "take home", "take-home"]),
        ],
    ),
    "bank_statement_extract": (
        "Bank Statement Extract India Extraction v2",
        [
            ("bank_name", "Bank Name", "STRING", False, False, 0.0, 10, "Extract bank/financial institution name if visible.", ["bank", "bank name"]),
            ("account_holder_name", "Account Holder Name", "STRING", False, False, 0.0, 20, "Extract account holder/customer name if visible.", ["account holder", "customer name"]),
            ("account_number", "Account Number", "IDENTIFIER", False, False, 0.0, 30, "Extract account number exactly as visible; preserve masking and never infer hidden digits.", ["account no", "a/c no", "account number"]),
            ("transaction_date", "Transaction Date", "DATE", True, True, 1.0, 40, "Extract the transaction date for the selected/visible transaction row.", ["transaction date", "date"]),
            ("value_date", "Value Date", "DATE", False, False, 0.0, 50, "Extract value date only when separately shown.", ["value date"]),
            ("transaction_description", "Transaction Description", "STRING", True, True, 1.0, 60, "Extract the complete narration/description for the selected transaction row exactly as printed.", ["narration", "description", "particulars"]),
            ("reference_no", "Reference Number", "IDENTIFIER", False, False, 0.0, 70, "Extract an explicit bank reference/RRN/UTR/NEFT/RTGS/IMPS identifier from the row or narration; never invent one.", ["reference no", "rrn", "utr", "neft", "rtgs", "imps"]),
            ("counterparty_name", "Counterparty Name", "STRING", False, False, 0.0, 80, "Extract counterparty name only when explicitly identifiable in the selected row/narration.", ["beneficiary", "counterparty", "sender", "receiver"]),
            ("debit_amount", "Debit Amount", "CURRENCY", False, False, 0.0, 90, "Extract debit amount from the selected row only when populated.", ["debit", "withdrawal"]),
            ("credit_amount", "Credit Amount", "CURRENCY", False, False, 0.0, 100, "Extract credit amount from the selected row only when populated.", ["credit", "deposit"]),
            ("running_balance", "Running Balance", "CURRENCY", False, False, 0.0, 110, "Extract running/account balance printed for the selected row.", ["balance", "running balance"]),
            ("manually_flagged", "Manually Flagged", "BOOLEAN", False, False, 0.0, 120, "Return true only when the selected row has a clearly visible highlight, circle, underline, tick, or similar manual mark.", ["highlighted", "marked"]),
        ],
    ),
    "insurance_cover": (
        "Insurance Cover Note India Extraction v2",
        [
            ("insurer_name", "Insurer Name", "STRING", True, True, 1.0, 10, "Extract insurance company name exactly as printed.", ["insurer", "insurance company"]),
            ("policy_number", "Policy Number", "IDENTIFIER", True, True, 1.0, 20, "Extract policy/cover-note number exactly as printed.", ["policy no", "cover note no"]),
            ("policy_type", "Policy Type", "STRING", False, False, 0.0, 30, "Extract policy type only when explicitly stated; do not infer it from add-ons or premium components.", ["policy type", "cover type"]),
            ("insured_name", "Insured Name", "STRING", True, True, 1.0, 40, "Extract insured/proposer name exactly as printed.", ["insured", "proposer"]),
            ("vehicle_registration_number", "Vehicle Registration Number", "IDENTIFIER", False, False, 0.0, 50, "Extract vehicle registration number only when visible.", ["registration no", "vehicle no", "regn no"]),
            ("vehicle_model", "Vehicle Model", "STRING", False, False, 0.0, 60, "Extract vehicle make/model/variant exactly as printed.", ["make model", "vehicle model", "model"]),
            ("chassis_number", "Chassis Number", "IDENTIFIER", False, False, 0.0, 70, "Extract chassis/VIN exactly as visible; never reconstruct missing characters.", ["chassis no", "vin"]),
            ("engine_number", "Engine Number", "IDENTIFIER", False, False, 0.0, 80, "Extract engine number exactly as visible; never reconstruct missing characters.", ["engine no"]),
            ("premium_amount", "Premium Amount", "CURRENCY", False, False, 0.0, 90, "Extract total premium amount only when explicitly stated.", ["premium", "total premium"]),
            ("idv_amount", "IDV Amount", "CURRENCY", False, False, 0.0, 100, "Extract Insured Declared Value (IDV) only when explicitly stated.", ["idv", "insured declared value", "sum insured"]),
            ("policy_start_date", "Policy Start Date", "DATE", False, False, 0.0, 110, "Extract policy inception/start date.", ["policy start", "inception", "valid from", "from"]),
            ("policy_end_date", "Policy End Date", "DATE", False, False, 0.0, 120, "Extract policy expiry/end date.", ["policy end", "expiry", "valid till", "to"]),
            ("issue_date", "Issue Date", "DATE", False, False, 0.0, 130, "Extract issue date only when printed.", ["issue date", "issued on"]),
            ("add_ons", "Add-ons", "JSON", False, False, 0.0, 140, "Extract only add-on covers explicitly listed in the document; return null when none are printed.", ["add on", "add-on", "zero dep", "zero depreciation", "rsa", "engine protect", "consumables"]),
        ],
    ),
    "dealer_receipt": (
        "Dealer Receipt India Extraction v2",
        [
            ("dealer_name", "Dealer Name", "STRING", True, True, 1.0, 10, "Extract dealership name exactly as printed.", ["dealer", "dealership"]),
            ("dealer_gstin", "Dealer GSTIN", "IDENTIFIER", False, False, 0.0, 20, "Extract dealer GSTIN only when explicitly printed.", ["gstin", "gst no"]),
            ("customer_name", "Customer Name", "STRING", True, True, 1.0, 30, "Extract payer/customer name exactly as printed.", ["customer", "received from", "payer"]),
            # Reuse deployed immutable customer_phone STRING canonical.
            ("customer_phone", "Customer Phone", "STRING", False, False, 0.0, 40, "Extract customer contact number only when printed.", ["mobile", "phone", "contact"]),
            ("receipt_number", "Receipt Number", "IDENTIFIER", True, True, 1.0, 50, "Extract receipt/voucher number exactly as printed.", ["receipt no", "voucher no"]),
            ("receipt_date", "Receipt Date", "DATE", True, True, 1.0, 60, "Extract receipt/payment date exactly as printed.", ["receipt date", "date"]),
            ("amount_paid", "Amount Paid", "CURRENCY", True, True, 1.0, 70, "Extract amount received/paid only when explicitly stated.", ["amount", "amount received", "paid"]),
            ("payment_mode", "Payment Mode", "STRING", False, False, 0.0, 80, "Extract payment mode exactly as printed.", ["payment mode", "mode of payment", "mode"]),
            ("payment_reference_no", "Payment Reference Number", "IDENTIFIER", False, False, 0.0, 90, "Extract cheque/DD/UTR/RRN/transaction/reference number exactly as printed; never manufacture a missing reference.", ["reference no", "utr", "rrn", "transaction id", "cheque no", "dd no"]),
            ("payment_reference_date", "Payment Reference Date", "DATE", False, False, 0.0, 100, "Extract payment instrument/reference date only when printed.", ["reference date", "cheque date", "dd date"]),
            ("bank_name", "Bank Name", "STRING", False, False, 0.0, 110, "Extract associated bank name only when printed.", ["bank", "bank name"]),
            ("bank_location", "Bank Location", "STRING", False, False, 0.0, 120, "Extract bank branch/location only when printed.", ["bank branch", "branch", "location"]),
            ("booking_reference_number", "Booking Reference Number", "STRING", False, False, 0.0, 130, "Extract linked booking/order/reference number only when printed.", ["booking no", "order no"]),
            ("remarks", "Remarks", "STRING", False, False, 0.0, 140, "Extract remarks exactly as printed.", ["remarks", "narration"]),
            ("amount_in_words", "Amount in Words", "STRING", False, False, 0.0, 150, "Extract amount-in-words text only when printed.", ["amount in words", "rupees"]),
        ],
    ),
    "upi_transaction": (
        "UPI Transaction India Extraction v2",
        [
            ("app_name", "App Name", "STRING", False, False, 0.0, 10, "Extract payment app name only when visible.", ["phonepe", "google pay", "gpay", "paytm", "bhim"]),
            ("transaction_status", "Transaction Status", "STRING", True, True, 1.0, 20, "Extract transaction status exactly as displayed; do not infer success/failure from styling alone.", ["status", "successful", "completed", "failed", "pending"]),
            ("amount_paid", "Amount Paid", "CURRENCY", True, True, 1.0, 30, "Extract transaction amount exactly as visible.", ["amount", "paid"]),
            ("transaction_datetime", "Transaction Date/Time", "DATETIME", True, True, 1.0, 40, "Extract transaction date/time exactly as displayed; normalize only when a complete value is visible.", ["transaction date", "date", "time", "paid on"]),
            ("upi_transaction_id", "UPI Transaction ID", "IDENTIFIER", True, True, 1.0, 50, "Extract the app/payment transaction ID exactly as visible.", ["transaction id", "upi transaction id", "reference id"]),
            ("upi_rrn", "UPI RRN", "IDENTIFIER", False, False, 0.0, 60, "Extract the bank-side UPI RRN/reference only when separately and explicitly visible.", ["rrn", "reference no", "bank reference"]),
            ("payer_name", "Payer Name", "STRING", False, False, 0.0, 70, "Extract payer/sender name only when visible.", ["payer", "from", "sender"]),
            ("payer_masked_phone", "Payer Masked Phone", "STRING", False, False, 0.0, 80, "Extract payer phone exactly as visible and preserve masking.", ["phone", "mobile"]),
            ("payer_upi_id", "Payer UPI ID", "IDENTIFIER", False, False, 0.0, 90, "Extract payer UPI ID/VPA only when visible.", ["payer upi id", "from upi id", "vpa"]),
            ("payee_name", "Payee Name", "STRING", False, False, 0.0, 100, "Extract payee/merchant/recipient name only when visible.", ["payee", "paid to", "merchant", "recipient"]),
            ("payee_upi_id", "Payee UPI ID", "IDENTIFIER", False, False, 0.0, 110, "Extract payee/merchant UPI ID/VPA only when visible.", ["payee upi id", "merchant upi id", "to upi id", "vpa"]),
            ("payment_method", "Payment Method", "STRING", False, False, 0.0, 120, "Extract payment method only when explicitly shown.", ["payment method", "paid using"]),
        ],
    ),
    "upi_screenshot": (
        "UPI Screenshot India Extraction v2",
        [
            ("app_name", "App Name", "STRING", False, False, 0.0, 10, "Extract payment app name only when visible.", ["phonepe", "google pay", "gpay", "paytm", "bhim"]),
            ("transaction_status", "Transaction Status", "STRING", True, True, 1.0, 20, "Extract transaction status exactly as displayed.", ["status", "successful", "completed", "failed", "pending"]),
            ("amount_paid", "Amount Paid", "CURRENCY", True, True, 1.0, 30, "Extract amount paid exactly as visible.", ["amount", "paid"]),
            ("transaction_datetime", "Transaction Date/Time", "DATETIME", True, True, 1.0, 40, "Extract transaction date/time exactly as displayed.", ["transaction date", "date", "time", "paid on"]),
            ("upi_transaction_id", "UPI Transaction ID", "IDENTIFIER", True, True, 1.0, 50, "Extract app/payment transaction ID exactly as visible.", ["transaction id", "reference id"]),
            ("upi_rrn", "UPI RRN", "IDENTIFIER", False, False, 0.0, 60, "Extract bank-side UPI RRN/reference only when separately visible.", ["rrn", "reference no", "bank reference"]),
            ("payer_name", "Payer Name", "STRING", False, False, 0.0, 70, "Extract payer/sender name only when visible.", ["payer", "from", "sender"]),
            ("payer_masked_phone", "Payer Masked Phone", "STRING", False, False, 0.0, 80, "Extract payer phone exactly as shown and preserve masking.", ["phone", "mobile"]),
            ("payer_upi_id", "Payer UPI ID", "IDENTIFIER", False, False, 0.0, 90, "Extract payer UPI ID/VPA only when visible.", ["payer upi id", "from upi id", "vpa"]),
            ("payee_name", "Payee Name", "STRING", False, False, 0.0, 100, "Extract recipient/merchant name only when visible.", ["paid to", "to", "merchant", "recipient"]),
            ("payee_upi_id", "Payee UPI ID", "IDENTIFIER", False, False, 0.0, 110, "Extract recipient/merchant UPI ID/VPA only when visible.", ["upi id", "merchant upi id", "to upi id", "vpa"]),
            ("payment_method", "Payment Method", "STRING", False, False, 0.0, 120, "Extract payment method only when explicitly shown.", ["payment method", "paid using"]),
        ],
    ),
    "delivery_order_cover": (
        "Delivery Order Cover India Extraction v2",
        [
            ("dealer_name", "Dealer Name", "STRING", False, False, 0.0, 10, "Extract dealership name only when visible.", ["dealer", "dealership"]),
            ("delivery_order_number", "Delivery Order Number", "IDENTIFIER", False, False, 0.0, 20, "Extract delivery order/DO number only when visible.", ["do no", "delivery order no"]),
            ("delivery_date", "Delivery Date", "DATE", False, False, 0.0, 30, "Extract delivery/handover date only when visible.", ["delivery date", "handover date"]),
            ("customer_name", "Customer Name", "STRING", True, True, 1.0, 40, "Extract customer receiving the vehicle exactly as printed.", ["customer", "name"]),
            ("booking_reference_number", "Booking Reference Number", "IDENTIFIER", False, False, 0.0, 50, "Extract linked booking/order reference only when printed.", ["booking no", "order no"]),
            ("vehicle_model", "Vehicle Model", "STRING", False, False, 0.0, 60, "Extract vehicle model exactly as printed.", ["model"]),
            ("vehicle_variant", "Vehicle Variant", "STRING", False, False, 0.0, 70, "Extract vehicle variant/trim only when printed.", ["variant", "trim"]),
            ("vehicle_color", "Vehicle Color", "STRING", False, False, 0.0, 80, "Extract vehicle colour only when printed.", ["color", "colour"]),
            ("chassis_number", "Chassis Number", "IDENTIFIER", False, False, 0.0, 90, "Extract chassis/VIN exactly as visible; never reconstruct missing characters.", ["chassis no", "vin"]),
            ("engine_number", "Engine Number", "IDENTIFIER", False, False, 0.0, 100, "Extract engine number exactly as visible; never reconstruct missing characters.", ["engine no"]),
            ("vehicle_registration_number", "Vehicle Registration Number", "IDENTIFIER", False, False, 0.0, 110, "Extract registration number only when visible.", ["registration no", "vehicle no", "regn no"]),
            ("delivered_by", "Delivered By", "STRING", False, False, 0.0, 120, "Extract sales/delivery executive name only when printed.", ["delivered by", "sales executive", "delivery executive"]),
            ("embedded_document_types", "Embedded Document Types", "JSON", False, False, 0.0, 130, "Extract only document types explicitly listed as attached/included in the supplied document; never infer unseen attachments.", ["attachments", "enclosures", "documents attached"]),
        ],
    ),
}


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str, data_type: str) -> None:
    existing = conn.execute(
        sa.text("""
            SELECT data_type FROM docintel.canonical_fields
            WHERE owner_tenant_id IS NULL AND field_key=:field_key
        """),
        {"field_key": field_key},
    ).scalar_one_or_none()
    if existing is not None:
        # Existing canonical vocabulary is authoritative and immutable. 0014 is
        # configuration-only, so reuse the deployed definition instead of
        # rejecting a historical type difference.
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


def _publish_next_profile(conn: Any, document_type_key: str, profile_name: str, fields: list[F]) -> None:
    dt_id = conn.execute(
        sa.text("""
            SELECT document_type_id
            FROM docintel.document_types
            WHERE owner_tenant_id IS NULL
              AND document_type_key=:key
              AND status='ACTIVE'
        """),
        {"key": document_type_key},
    ).scalar_one()

    version_no = conn.execute(
        sa.text("""
            SELECT COALESCE(MAX(version_no), 0) + 1
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
                :profile_name, 'DRAFT', :classification_hint,
                :actor_id, now(), now()
            ) RETURNING profile_id
        """),
        {
            "dt_id": dt_id,
            "version_no": version_no,
            "profile_name": profile_name,
            "classification_hint": document_type_key,
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

    # Published profiles are immutable as definitions. Retire the previous
    # published version, then publish this new version in the same DB transaction.
    conn.execute(
        sa.text("""
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE document_type_id=:dt_id
              AND scope_tenant_id IS NULL
              AND status='PUBLISHED'
        """),
        {"dt_id": dt_id},
    )
    conn.execute(
        sa.text("""
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED',
                published_by_actor_id=:actor_id,
                published_at_utc=now(),
                updated_at_utc=now()
            WHERE profile_id=:profile_id AND status='DRAFT'
        """),
        {"actor_id": _MIGRATION_ACTOR, "profile_id": profile_id},
    )


def upgrade() -> None:
    conn = op.get_bind()

    # Keep the stable documentTypeKey but remove the India-ambiguous label
    # "Corporate ID" (which can be confused with MCA CIN).
    conn.execute(
        sa.text("""
            UPDATE docintel.document_types
            SET display_name='Employee / Corporate ID Card', updated_at_utc=now()
            WHERE owner_tenant_id IS NULL AND document_type_key='corporate_id'
        """)
    )

    seen: set[str] = set()
    for _key, (_profile_name, fields) in _PROFILES.items():
        for field_key, display_name, data_type, *_rest in fields:
            if field_key in seen:
                continue
            seen.add(field_key)
            _ensure_canonical_field(conn, field_key, display_name, data_type)

    for key, (profile_name, fields) in _PROFILES.items():
        _publish_next_profile(conn, key, profile_name, fields)


def downgrade() -> None:
    # Do not delete historical profiles or extracted evidence. If rollback is
    # needed operationally, publish a new corrective profile version instead.
    pass
