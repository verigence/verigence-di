"""document_ai/schemas/booking_form.py — Booking Form schema.

document_type_key : booking_form
display_name      : Booking Form
DB category       : HANDWRITTEN
schema_version    : 1.0

Characteristics: handwritten or printed, variable dealer layouts
(Mahindra-style tabular, Hyundai-style price breakdown), often phone
photos that are skewed or low-contrast.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

BOOKING_FORM_SCHEMA = SchemaDefinition(
    document_type_key="booking_form",
    display_name="Booking Form",
    schema_version="1.1",
    fields=[
        FieldSpec(key="dealer_name",             field_type="string",  required=True,  description="Name of the dealership"),
        FieldSpec(key="dealer_branch",            field_type="string",  required=False, description="Branch or location of the dealer"),
        FieldSpec(key="booking_reference_number", field_type="string",  required=True,  description="Booking reference or order number"),
        FieldSpec(key="booking_date",             field_type="date",    required=True,  description="Date the booking was made", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="customer_name",            field_type="string",  required=True,  description="Full name of the customer"),
        FieldSpec(key="customer_phone",           field_type="string",  required=True,  description="Customer contact phone number", normalization="phone_e164"),
        FieldSpec(key="customer_email",           field_type="string",  required=False, description="Customer email address"),
        FieldSpec(key="customer_address",         field_type="string",  required=False, description="Customer residential or postal address"),
        FieldSpec(key="vehicle_model",            field_type="string",  required=True,  description="Vehicle model name (e.g. Scorpio N, Creta)"),
        FieldSpec(key="vehicle_variant",          field_type="string",  required=True,  description="Vehicle variant or trim level (e.g. Z8S, SX+)"),
        FieldSpec(key="vehicle_color",            field_type="string",  required=True,  description="Preferred or booked vehicle colour"),
        FieldSpec(key="sales_person",             field_type="string",  required=False, description="Name of the sales executive"),
        FieldSpec(key="ex_showroom_price",        field_type="number",  required=False, description="Ex-showroom price of the vehicle", normalization="indian_currency"),
        FieldSpec(key="insurance_amount",         field_type="number",  required=False, description="Insurance component of the total price", normalization="indian_currency"),
        FieldSpec(key="road_tax_registration",    field_type="number",  required=False, description="Road tax and registration charges", normalization="indian_currency"),
        FieldSpec(key="accessories_cost",         field_type="number",  required=False, description="Cost of accessories added", normalization="indian_currency"),
        FieldSpec(key="other_charges",            field_type="number",  required=False, description="Any other charges listed", normalization="indian_currency"),
        FieldSpec(key="total_price",              field_type="number",  required=True,  description="Grand total on-road price", normalization="indian_currency"),
        FieldSpec(key="booking_amount_paid",      field_type="number",  required=True,  description="Amount paid as booking advance", normalization="indian_currency"),
        FieldSpec(key="balance_amount",           field_type="number",  required=False, description="Remaining balance due at delivery", normalization="indian_currency"),
        FieldSpec(
            key="mode_of_payment",
            field_type="string",
            required=False,
            description="Payment mode used for the booking amount",
            enum=["cash", "cheque", "demand_draft", "neft_rtgs", "payorder"],
        ),
        FieldSpec(key="payment_reference_no",     field_type="string",  required=False, description="Cheque number, DD number, or NEFT/RTGS reference"),
        FieldSpec(key="expected_delivery",        field_type="string",  required=False, description="Expected delivery date or timeframe"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "automotive dealership booking forms.\n"
        "You will be shown a booking form — it may be handwritten, printed, or a "
        "phone photograph of a physical form. The layout varies by dealer.\n\n"
        "Extract each field listed below from the document.\n"
        "Output ONLY valid JSON. For each field use this exact structure:\n"
        '  "<field_key>": {"value": <extracted value or null>, "confidence": "high"|"medium"|"low"}\n\n'
        "Confidence rules:\n"
        '  "high"   — value is clearly legible and unambiguous\n'
        '  "medium" — value is partially legible or inferred from context\n'
        '  "low"    — value is illegible, guessed, or absent\n\n'
        "If a field is not found or is illegible, return: "
        '{"value": null, "confidence": "low"}\n'
        "Never guess a numeric value you cannot read clearly."
    ),
    prompt_notes=[
        "Handwritten values override printed placeholder text — do not confuse "
        "a printed field-label with a filled-in value.",
        "Currency values may use Indian numbering with commas (e.g. '8,58,600') — "
        "normalize to a plain integer (858600) in the value field.",
        "total_price: use the grand total row if explicitly labelled; otherwise sum "
        "all visible charge rows minus any deductions. Note computed values in a "
        "separate '_extraction_notes' key in your response.",
        "If the form is skewed, rotated, or partially obscured, still extract what "
        "is legible and mark affected fields as medium or low confidence.",
    ],
)
