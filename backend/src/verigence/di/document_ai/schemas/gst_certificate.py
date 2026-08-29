"""Schema V2 extraction schema for Indian GST Registration Certificates.

Field vocabulary follows the frozen 18-document schema package.  These are
provider-facing extraction keys; the extraction profile maps them onto the
stable DI canonical vocabulary.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

GST_CERTIFICATE_SCHEMA = SchemaDefinition(
    document_type_key="gst_certificate",
    display_name="GST Certificate",
    schema_version="2.0",
    fields=[
        FieldSpec("gstin", "string", False, "GSTIN exactly as printed."),
        FieldSpec("legal_name", "string", False, "Legal name of the registered person/entity."),
        FieldSpec("trade_name", "string", False, "Trade name, if printed."),
        FieldSpec("constitution_of_business", "string", False, "Constitution of business exactly as printed."),
        FieldSpec("address_principal_place", "string", False, "Full address of the principal place of business."),
        FieldSpec("state", "string", False, "State for the principal place of business."),
        FieldSpec("pincode", "string", False, "PIN code for the principal place of business."),
        FieldSpec("type_of_registration", "string", False, "Registration type such as Regular, Composition, Casual Taxable Person, SEZ, or the exact printed value."),
        FieldSpec("date_of_liability", "string", False, "Date of liability exactly as printed; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("period_of_validity_from", "string", False, "Validity start date exactly as printed; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("period_of_validity_to", "string", False, "Validity end date exactly as printed. It may state Not Applicable; do not invent a date."),
        FieldSpec("date_of_issue", "string", False, "Certificate issue date exactly as printed; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("jurisdiction_state", "string", False, "State jurisdiction exactly as printed."),
        FieldSpec("jurisdiction_centre", "string", False, "Centre jurisdiction exactly as printed."),
        FieldSpec("authorised_signatory_names", "array", False, "JSON array of authorised signatory names. Every array item must be a string; return [] only when the document clearly has no names."),
        FieldSpec("cancellation_or_suspension_text", "string", False, "Verbatim text if the certificate mentions cancellation or suspension; otherwise null."),
        FieldSpec("has_digital_signature", "boolean", False, "Three-state observation: true when a digital signature is clearly present, false when clearly absent, null when unreadable/uncertain."),
    ],
    system_prompt=(
        "You extract evidence from Indian GST Registration Certificates. "
        "Read only what is visible in the supplied document. Preserve printed wording "
        "for names, registration type and jurisdiction. Never infer a value from general "
        "GST knowledge. Evidence-presence observations are three-state: true, false, or null."
    ),
    prompt_notes=[
        "Do not treat the GSTIN as a vehicle/customer identifier; it identifies the registered organisation/person.",
        "For period_of_validity_to, preserve text such as 'Not Applicable' rather than converting it to a guessed date.",
        "authorised_signatory_names must be a JSON array of strings, not a comma-separated string.",
        "Use null, not false, when the document is cropped, unreadable, or ambiguous.",
    ],
)
