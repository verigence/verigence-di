"""document_ai/schemas/no_dues_certificate.py — No Dues Certificate (loan closure).

Financier's certificate that a vehicle loan is fully repaid -- typically for
the customer's old (exchange) vehicle before it can be transferred. Keys are
exactly the migration 0046 published profile's.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

NO_DUES_CERTIFICATE_SCHEMA = SchemaDefinition(
    document_type_key="no_dues_certificate",
    display_name="No Dues Certificate",
    schema_version="1.0",
    fields=[
        FieldSpec("financer_name", "string", True, "Bank / NBFC / financier issuing the certificate."),
        FieldSpec("borrower_name", "string", True, "Borrower / customer name exactly as printed."),
        FieldSpec("loan_account_number", "string", True,
                  "Loan account / agreement / reference number exactly as printed."),
        FieldSpec("vehicle_registration_number", "string", False,
                  "Registration number of the financed vehicle, if printed."),
        FieldSpec("certificate_date", "date", False, "Date the certificate was issued.",
                  normalization="date_dd_mm_yyyy"),
        FieldSpec("closure_date", "date", False,
                  "Date the loan was closed / fully repaid, when stated separately from the certificate date.",
                  normalization="date_dd_mm_yyyy"),
    ],
    system_prompt=(
        "You extract data from an Indian vehicle-loan No Dues / No Objection / loan closure certificate issued "
        "by a bank or NBFC. Extract only what is printed; account numbers are identifiers, copy them exactly.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "financer_name is the issuing lender (letterhead / signatory organisation), not the dealer or RTO.",
        "Keep a masked loan account number masked; never complete hidden digits.",
        "Return closure_date only when the certificate states a closure/repayment date; do not copy the certificate date into it.",
        "If a field is not printed or is unclear, return null with low confidence.",
    ],
)
