"""document_ai/schemas/booking_form.py — India booking-form extraction schema.

Extraction-only policy:
- extract only values explicitly visible in the supplied evidence;
- never calculate, infer, back-solve, or manufacture missing commercial values;
- caller supplies document_type_key; this schema performs no classification.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

BOOKING_FORM_SCHEMA = SchemaDefinition(
    document_type_key="booking_form",
    display_name="Booking Form",
    schema_version="1.2",
    fields=[
        FieldSpec(key="dealer_name", field_type="string", required=True, description="Name of the dealership exactly as visible"),
        FieldSpec(key="dealer_branch", field_type="string", required=False, description="Dealer branch/outlet/location exactly as visible"),
        FieldSpec(key="booking_reference_number", field_type="string", required=True, description="Booking, order, enquiry, or reference number printed/written on the form"),
        FieldSpec(key="booking_date", field_type="date", required=True, description="Booking date explicitly visible on the form", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="customer_name", field_type="string", required=True, description="Full customer name exactly as visible"),
        FieldSpec(key="customer_phone", field_type="string", required=True, description="Customer contact/mobile number exactly as visible", normalization="phone_e164"),
        FieldSpec(key="customer_email", field_type="string", required=False, description="Customer email address if explicitly visible"),
        FieldSpec(key="customer_address", field_type="string", required=False, description="Customer residential/postal address if explicitly visible"),
        FieldSpec(key="vehicle_model", field_type="string", required=True, description="Booked vehicle model exactly as visible"),
        FieldSpec(key="vehicle_variant", field_type="string", required=True, description="Booked vehicle variant/trim exactly as visible"),
        FieldSpec(key="vehicle_color", field_type="string", required=True, description="Booked/preferred vehicle colour exactly as visible"),
        FieldSpec(key="sales_person", field_type="string", required=False, description="Sales executive/consultant name if explicitly visible"),
        FieldSpec(key="ex_showroom_price", field_type="number", required=False, description="Ex-showroom price only when explicitly printed/written", normalization="indian_currency"),
        FieldSpec(key="insurance_amount", field_type="number", required=False, description="Insurance charge only when explicitly printed/written", normalization="indian_currency"),
        FieldSpec(key="road_tax_registration", field_type="number", required=False, description="Road-tax/registration charge only when explicitly printed/written", normalization="indian_currency"),
        FieldSpec(key="accessories_cost", field_type="number", required=False, description="Accessories charge only when explicitly printed/written", normalization="indian_currency"),
        FieldSpec(key="other_charges", field_type="number", required=False, description="Other charge only when explicitly printed/written", normalization="indian_currency"),
        FieldSpec(key="total_price", field_type="number", required=True, description="Grand total/on-road price only when explicitly shown; never calculate a missing total", normalization="indian_currency"),
        FieldSpec(key="booking_amount_paid", field_type="number", required=True, description="Booking advance/amount paid only when explicitly shown", normalization="indian_currency"),
        FieldSpec(key="balance_amount", field_type="number", required=False, description="Balance amount only when explicitly shown; never calculate it", normalization="indian_currency"),
        FieldSpec(key="mode_of_payment", field_type="string", required=False, description="Payment mode exactly as printed, including UPI/card/cash/cheque/NEFT/RTGS/DD/pay order when applicable"),
        FieldSpec(key="payment_reference_no", field_type="string", required=False, description="Cheque/DD/NEFT/RTGS/UPI/card/reference number only when explicitly visible"),
        FieldSpec(key="expected_delivery", field_type="string", required=False, description="Expected delivery date/timeframe exactly as stated"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian automotive dealership booking forms.\n"
        "The document may be handwritten, printed, scanned, or photographed.\n\n"
        "AUDIT EVIDENCE RULES:\n"
        "- Extract only information explicitly visible in the supplied document.\n"
        "- Never calculate, infer, back-solve, or manufacture a missing value.\n"
        "- Never use general knowledge to fill a blank.\n"
        "- If a value is absent, obscured, or uncertain, return null with low confidence.\n"
        "- Handwritten filled values take precedence over blank printed placeholders.\n\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Currency values may use Indian numbering (for example 8,58,600); normalize only the formatting of a value that is actually visible.",
        "total_price must be extracted only from an explicitly shown grand-total/on-road-total value. Do not sum component charges.",
        "balance_amount must be extracted only when explicitly shown. Do not subtract booking amount from total price.",
        "Preserve identifiers exactly as visible; do not repair ambiguous digits or letters.",
    ],
)
