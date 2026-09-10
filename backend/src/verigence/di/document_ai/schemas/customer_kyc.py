"""document_ai/schemas/customer_kyc.py — Customer identity/KYC evidence schema.

customer_kyc was registered as a document type in migration 0016 but never got
a dedicated extraction schema, silently falling back to FALLBACK_SCHEMA's
generic prompt. Unlike PAN/Aadhaar (each their own specific, already-schema'd
document type), "Customer KYC" in this dealership's process is a looser bucket
covering whichever identity/address proof format a customer actually hands
over -- so, like corporate_id.py's employment-evidence schema, this treats
multiple physical formats as one business evidence type with an
evidence_format discriminator, rather than forcing a single rigid shape.

This is NOT the right home for a dealer-issued declaration ABOUT the customer
(GST status declaration, no-dues certificate, etc.) -- those are their own
document types (see gst_declaration.py). customer_kyc is specifically the
customer's OWN identity/address evidence.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

CUSTOMER_KYC_SCHEMA = SchemaDefinition(
    document_type_key="customer_kyc",
    display_name="Customer KYC",
    schema_version="1.0",
    fields=[
        FieldSpec("evidence_format", "string", False, "Observed evidence format: PAN_CARD, AADHAAR, VOTER_ID, PASSPORT, DRIVING_LICENSE, KYC_FORM, OTHER."),
        FieldSpec("customer_name", "string", True, "Customer name exactly as printed."),
        FieldSpec("relation_name", "string", False, "Father's/husband's/guardian's name if printed (commonly labelled S/O, W/O, D/O, or C/O)."),
        FieldSpec("id_type", "string", False, "Type of identity document if this is a printed ID (e.g. PAN, Aadhaar, Voter ID, Passport, Driving Licence)."),
        FieldSpec("id_number", "string", False, "Identity/document number exactly as printed."),
        FieldSpec("date_of_birth", "date", False, "Date of birth if printed.", normalization="date_dd_mm_yyyy"),
        FieldSpec("address", "string", False, "Full address exactly as printed."),
        FieldSpec("pin_code", "string", False, "PIN/postal code exactly as printed."),
        FieldSpec("phone_number", "string", False, "Phone number exactly as printed."),
        FieldSpec("document_date", "date", False, "Date the KYC form/declaration itself was signed or issued, if printed.", normalization="date_dd_mm_yyyy"),
        FieldSpec("photo_present", "boolean", False, "Three-state observation: true when a person photo is clearly present, false when clearly absent, null when uncertain."),
        FieldSpec("signature_present", "boolean", False, "Three-state observation of the customer's signature presence."),
        FieldSpec("is_photocopy", "boolean", False, "Three-state observation: true when clearly a photocopy/scan of an original ID, false when clearly an original print/form, null when uncertain."),
    ],
    system_prompt=(
        "You extract customer identity/KYC evidence used for dealership audit. The document may be a printed "
        "identity card (PAN, Aadhaar, Voter ID, Passport, Driving Licence) or a dealer-provided KYC form the "
        "customer filled in. Extract only what the evidence itself states.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Do not invent an id_type from context alone -- only report it when the document text or a recognizable official layout confirms it.",
        "Return the physical evidence category in evidence_format using the listed vocabulary when clear; use OTHER only when a real but different format is evident.",
        "This is customer identity evidence, not a dealer-issued declaration about the customer's GST status, dues, or account -- if the document is such a declaration rather than identity/address evidence, extract only customer_name and address and leave identity-specific fields null.",
        "Presence observations are true/false/null. Use null for cropped, unreadable or ambiguous evidence.",
    ],
)
