"""document_ai/schemas/debit_note.py — dealer debit-note extraction schema.

A debit note is raised by the dealer against the customer for amounts the dealer
collects and pays on the customer's behalf — typically the insurance premium and
the RTO / registration charges. The audit layer reconciles the debit-note
amounts against the insurance cover note and the RTO challan.

Extraction is evidence-only. Preserve each printed amount independently; never
calculate a missing total.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

DEBIT_NOTE_SCHEMA = SchemaDefinition(
    document_type_key="debit_note",
    display_name="Debit Note",
    schema_version="1.0",
    fields=[
        FieldSpec("dealer_name", "string", False, "Issuing dealership/company name exactly as printed"),
        FieldSpec("dealer_gstin", "string", False, "Issuer GSTIN exactly as printed"),
        FieldSpec("debit_note_number", "string", False, "Debit note number/reference exactly as printed"),
        FieldSpec("debit_note_date", "date", False, "Debit note date exactly as printed", normalization="date_dd_mm_yyyy"),
        FieldSpec("customer_name", "string", True, "Customer/party name the debit note is raised against, exactly as printed"),
        FieldSpec("against_invoice_number", "string", False, "Invoice/reference the debit note is raised against, if printed"),
        FieldSpec("booking_reference_number", "string", False, "Booking/order/deal reference printed on the note, if any"),
        FieldSpec("insurance_amount", "number", False, "Amount charged for insurance premium only when explicitly shown as an insurance line", normalization="indian_currency"),
        FieldSpec("rto_amount", "number", False, "Amount charged for RTO / registration / road tax only when explicitly shown as such a line", normalization="indian_currency"),
        FieldSpec("other_charges", "number", False, "Any other charge line only when explicitly printed and not insurance or RTO", normalization="indian_currency"),
        FieldSpec("total_amount", "number", False, "Debit note total only when explicitly printed as a total; never sum the lines yourself", normalization="indian_currency"),
        FieldSpec("particulars", "string", False, "Narration/particulars/reason text exactly as printed"),
        FieldSpec("line_items", "array", False, "JSON array of visible lines. For each line preserve particulars_raw and extract only explicitly printed hsn_sac, quantity, rate and amount"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian automobile-dealership debit notes.\n"
        "Extract only values explicitly visible in the supplied document.\n"
        "- Never calculate, infer, or manufacture a missing total.\n"
        "- Populate insurance_amount / rto_amount only when a line explicitly identifies that charge; do not infer from the amount.\n"
        "- Keep separately printed charges separate.\n\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Currency values may use Indian numbering (for example 8,58,600); normalize only the formatting of a value that is actually visible.",
        "If the note shows only a single lump amount with no charge-type breakdown, return total_amount and leave insurance_amount / rto_amount null.",
    ],
)
