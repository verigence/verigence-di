"""Schema V2 extraction schema for vehicle-finance approval/sanction letters."""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

BANK_APPROVAL_LETTER_SCHEMA = SchemaDefinition(
    document_type_key="bank_approval_letter",
    display_name="Bank Approval Letter",
    schema_version="2.0",
    fields=[
        FieldSpec("financier_name", "string", False, "Financier name exactly as printed."),
        FieldSpec("financier_type", "string", False, "Financier category: BANK, NBFC, CAPTIVE_FINANCE, COOPERATIVE, OTHER."),
        FieldSpec("branch", "string", False, "Financier branch exactly as printed."),
        FieldSpec("sanction_letter_number", "string", False, "Sanction/approval letter number exactly as printed."),
        FieldSpec("sanction_date", "string", False, "Sanction date; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("offer_valid_until", "string", False, "Offer/sanction validity end date; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("applicant_name", "string", False, "Primary applicant name exactly as printed."),
        FieldSpec("applicant_pan", "string", False, "Primary applicant PAN exactly as printed."),
        FieldSpec("co_applicant_name", "string", False, "Co-applicant name exactly as printed, if present."),
        FieldSpec("guarantor_name", "string", False, "Guarantor name exactly as printed, if present."),
        FieldSpec("loan_account_or_application_number", "string", False, "Loan account/application/reference number exactly as printed."),
        FieldSpec("chassis_number", "string", False, "Vehicle chassis/VIN stated in the approval, if present."),
        FieldSpec("make_model_variant", "string", False, "Vehicle make/model/variant text exactly as printed."),
        FieldSpec("ex_showroom_considered", "number", False, "Ex-showroom amount considered by the financier."),
        FieldSpec("on_road_price_considered", "number", False, "On-road price considered by the financier."),
        FieldSpec("insurance_considered", "number", False, "Insurance amount considered by the financier."),
        FieldSpec("accessories_considered", "number", False, "Accessories amount considered by the financier."),
        FieldSpec("invoice_or_proforma_value_referenced", "number", False, "Invoice or proforma value referenced in the approval."),
        FieldSpec("proforma_reference_number", "string", False, "Proforma/invoice reference number exactly as printed."),
        FieldSpec("sanctioned_amount", "number", False, "Loan amount sanctioned/approved."),
        FieldSpec("ltv_percent_stated", "number", False, "Loan-to-value percentage stated on the approval."),
        FieldSpec("margin_money_required", "number", False, "Margin money/down-payment requirement stated by the financier."),
        FieldSpec("tenure_months", "number", False, "Loan tenure in months as stated."),
        FieldSpec("interest_rate", "number", False, "Interest rate as stated; return the numeric percentage when explicit."),
        FieldSpec("rate_type", "string", False, "Interest-rate type exactly as stated, e.g. fixed/floating."),
        FieldSpec("emi_amount", "number", False, "EMI amount stated on the approval."),
        FieldSpec("processing_fee", "number", False, "Processing fee stated on the approval."),
        FieldSpec("insurance_funded", "boolean", False, "Three-state observation of whether insurance is explicitly funded by the loan."),
        FieldSpec("subvention_scheme_referenced", "string", False, "Subvention scheme/code referenced, if any."),
        FieldSpec("subvention_borne_by_stated", "string", False, "Party stated to bear subvention: OEM, DEALER, FINANCIER, SHARED, NOT_STATED."),
        FieldSpec("subvention_amount", "number", False, "Subvention amount stated, if any."),
        FieldSpec("dealer_payout_amount", "number", False, "Dealer payout amount stated, if any."),
        FieldSpec("disbursement_in_favour_of", "string", False, "Beneficiary in whose favour disbursement is stated."),
        FieldSpec("disbursement_mode", "string", False, "Disbursement mode exactly as stated."),
        FieldSpec("disbursement_date", "string", False, "Disbursement date when explicitly stated; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("conditions_precedent", "array", False, "JSON array of condition-precedent clauses/requirements. Every item must be a string and no printed clause may be silently dropped."),
        FieldSpec("signature_present", "boolean", False, "Three-state observation of authorising signature presence."),
    ],
    system_prompt=(
        "You extract facts from vehicle-finance approval or sanction letters for audit. "
        "Separate what the financier states from what may be true elsewhere in the deal. "
        "Amounts are document-stated evidence, not reference/master values."
    ),
    prompt_notes=[
        "Do not infer financing terms that are not printed.",
        "conditions_precedent must be a JSON array of strings preserving every visible clause; do not summarize multiple clauses into one item.",
        "signature_present and insurance_funded are true/false/null observations; use null when unclear.",
        "A chassis number in this document refers to the financed subject/new vehicle unless an explicit profile role override says otherwise.",
    ],
)
