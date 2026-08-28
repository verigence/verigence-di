"""Schema V2 extraction schema for corporate/employment eligibility evidence.

The frozen source package intentionally treats multiple corporate proof formats
as one business evidence type.  evidence_format records the observed physical
format while the remaining keys capture only values actually stated on it.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

CORPORATE_ID_SCHEMA = SchemaDefinition(
    document_type_key="corporate_id",
    display_name="Corporate ID",
    schema_version="2.0",
    fields=[
        FieldSpec("evidence_format", "string", False, "Observed evidence format: PHOTO_ID_CARD, EMPLOYMENT_LETTER, SALARY_SLIP, BUSINESS_CARD, EMAIL_PRINTOUT, HR_CERTIFICATE, OFFER_LETTER, OTHER."),
        FieldSpec("employer_name", "string", False, "Employer/organisation name exactly as printed."),
        FieldSpec("employer_address", "string", False, "Employer address exactly as printed."),
        FieldSpec("employer_gstin_printed", "string", False, "Employer GSTIN exactly as printed, if present."),
        FieldSpec("employee_name", "string", False, "Employee/customer name exactly as printed."),
        FieldSpec("employee_code", "string", False, "Employee code or staff identifier exactly as printed."),
        FieldSpec("designation", "string", False, "Designation/job title exactly as printed."),
        FieldSpec("department", "string", False, "Department exactly as printed."),
        FieldSpec("date_of_joining", "string", False, "Date of joining exactly as printed; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("id_valid_from", "string", False, "ID/evidence validity start date if stated; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("id_valid_until", "string", False, "ID/evidence validity end date if stated; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("document_date", "string", False, "Document date exactly as printed; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("salary_slip_month", "string", False, "Salary-slip month/period exactly as printed."),
        FieldSpec("corporate_scheme_code_referenced", "string", False, "Corporate scheme/code referenced on the evidence, if any."),
        FieldSpec("photo_present", "boolean", False, "Three-state observation: true when a person photo is clearly present, false when clearly absent, null when uncertain."),
        FieldSpec("employer_logo_present", "boolean", False, "Three-state observation: true when an employer logo is clearly present, false when clearly absent, null when uncertain."),
        FieldSpec("issuing_authority_signature_present", "boolean", False, "Three-state observation of issuing-authority signature presence."),
        FieldSpec("is_photocopy", "boolean", False, "Three-state observation: true when clearly a photocopy, false when clearly original/print, null when uncertain."),
    ],
    system_prompt=(
        "You extract corporate/employment evidence used for dealership audit. "
        "The document may be an employee ID card, employment letter, salary slip, "
        "business card, email printout, HR certificate, offer letter, or another "
        "corporate proof. Extract only what the evidence itself states."
    ),
    prompt_notes=[
        "Do not invent employer details from logos, email domains, or general knowledge when the text is not readable.",
        "Return the physical evidence category in evidence_format using the listed vocabulary when clear; use OTHER only when a real but different format is evident.",
        "Presence observations are true/false/null. Use null for cropped, unreadable or ambiguous evidence.",
    ],
)
