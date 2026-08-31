"""document_ai/schemas/booking_form.py — India booking-form extraction schema.

Extraction-only policy:
- extract only values explicitly visible in the supplied evidence;
- never calculate, infer, back-solve, or manufacture missing commercial values;
- preserve distinct printed commercial components instead of folding them into
  broader buckets;
- caller supplies document_type_key; this schema performs no classification.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

BOOKING_FORM_SCHEMA = SchemaDefinition(
    document_type_key="booking_form",
    display_name="Booking Form",
    schema_version="1.5",
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
        FieldSpec(key="sku_code", field_type="string", required=False, description="Vehicle/product/SKU code only when explicitly printed or written on the Booking Form; never infer it from model, variant, price, or general knowledge"),
        FieldSpec(key="sales_person", field_type="string", required=False, description="Sales executive/consultant name if explicitly visible"),
        FieldSpec(key="registration_by", field_type="string", required=False, description="Person, party, dealer, customer, or agency shown as responsible for registration; return the text exactly as visible and do not infer responsibility"),
        FieldSpec(key="registration_type", field_type="string", required=False, description="Registration type/category exactly as explicitly printed or written; do not infer from customer or vehicle details"),
        FieldSpec(key="insurance_by", field_type="string", required=False, description="Person, party, dealer, customer, insurer, or agency shown as arranging/providing insurance; return the text exactly as visible and do not infer responsibility"),
        FieldSpec(key="exchange_applicable", field_type="boolean", required=False, description="Whether exchange/trade-in is explicitly marked Yes/No on the form; return null when there is no explicit selection and never infer from an exchange value"),
        FieldSpec(key="exchange_value", field_type="number", required=False, description="Exchange/trade-in value only when explicitly printed/written", normalization="indian_currency"),
        FieldSpec(key="ex_showroom_price", field_type="number", required=False, description="Ex-showroom price only when explicitly printed/written", normalization="indian_currency"),
        FieldSpec(key="insurance_amount", field_type="number", required=False, description="Insurance charge only when explicitly printed/written", normalization="indian_currency"),
        FieldSpec(key="registration_charges", field_type="number", required=False, description="Registration charges only when shown as a distinct amount; do not derive them from a combined road-tax/registration amount", normalization="indian_currency"),
        FieldSpec(key="road_tax_amount", field_type="number", required=False, description="Road tax amount only when shown as a distinct amount; do not derive it from a combined road-tax/registration amount", normalization="indian_currency"),
        FieldSpec(key="road_tax_registration", field_type="number", required=False, description="Legacy combined road-tax/registration charge only when the document itself presents a combined amount; do not sum separate registration and road-tax values", normalization="indian_currency"),
        FieldSpec(key="tcs_amount", field_type="number", required=False, description="Tax Collected at Source (TCS) amount only when explicitly shown", normalization="indian_currency"),
        FieldSpec(key="rsa_amount", field_type="number", required=False, description="Roadside Assistance (RSA) amount only when explicitly shown", normalization="indian_currency"),
        FieldSpec(key="additional_warranty_amount", field_type="number", required=False, description="Additional warranty amount only when explicitly shown", normalization="indian_currency"),
        FieldSpec(key="extended_warranty_amount", field_type="number", required=False, description="Extended Warranty/EW amount only when explicitly shown as a separate charge", normalization="indian_currency"),
        FieldSpec(key="accessories_cost", field_type="number", required=False, description="Total/combined accessories charge only when explicitly printed/written", normalization="indian_currency"),
        FieldSpec(key="essential_kit_amount", field_type="number", required=False, description="Essential Kit/accessory kit amount only when explicitly shown as a separate line", normalization="indian_currency"),
        FieldSpec(key="genuine_accessories_amount", field_type="number", required=False, description="Genuine accessories amount only when explicitly shown as a separate line", normalization="indian_currency"),
        FieldSpec(key="non_genuine_accessories_amount", field_type="number", required=False, description="Non-genuine/non-OEM accessories amount only when explicitly shown as a separate line", normalization="indian_currency"),
        FieldSpec(key="fastag_amount", field_type="number", required=False, description="FASTag/Fast Tag charge only when explicitly shown", normalization="indian_currency"),
        FieldSpec(key="green_tax_amount", field_type="number", required=False, description="Green tax/green cess amount only when explicitly shown", normalization="indian_currency"),
        FieldSpec(key="service_package_amount", field_type="number", required=False, description="Service package/service plan/maintenance package amount only when explicitly shown", normalization="indian_currency"),
        FieldSpec(key="other_charges", field_type="number", required=False, description="Other charge only when explicitly printed/written; do not include separately labelled TCS, RSA, warranty, FASTag, green tax, service package, registration, road tax, insurance, accessories, discount, or bonus amounts", normalization="indian_currency"),
        FieldSpec(key="discount_amount", field_type="number", required=False, description="Total/lump-sum discount or scheme amount only when explicitly shown; do not calculate it and do not allocate it across discount types", normalization="indian_currency"),
        FieldSpec(key="sales_discount_amount", field_type="number", required=False, description="Sales discount amount only when explicitly labelled/shown", normalization="indian_currency"),
        FieldSpec(key="buffer_discount_amount", field_type="number", required=False, description="Buffer discount amount only when explicitly labelled/shown", normalization="indian_currency"),
        FieldSpec(key="exchange_discount_amount", field_type="number", required=False, description="Exchange discount/benefit amount only when explicitly labelled/shown; keep separate from exchange vehicle value", normalization="indian_currency"),
        FieldSpec(key="corporate_discount_amount", field_type="number", required=False, description="Corporate discount/benefit amount only when explicitly labelled/shown", normalization="indian_currency"),
        FieldSpec(key="loyalty_discount_amount", field_type="number", required=False, description="Loyalty discount/benefit amount only when explicitly labelled/shown", normalization="indian_currency"),
        FieldSpec(key="inhouse_insurance_discount_amount", field_type="number", required=False, description="In-house insurance discount/benefit amount only when explicitly labelled/shown", normalization="indian_currency"),
        FieldSpec(key="mr_discount_amount", field_type="number", required=False, description="MR discount/benefit amount only when the document explicitly uses the MR label", normalization="indian_currency"),
        FieldSpec(key="oem_referral_discount_amount", field_type="number", required=False, description="OEM referral discount/benefit amount only when explicitly labelled/shown", normalization="indian_currency"),
        FieldSpec(key="other_discount_amount", field_type="number", required=False, description="Other specifically labelled discount amount only when explicitly shown; do not use this for an unlabelled total discount", normalization="indian_currency"),
        FieldSpec(key="free_accessory_discount_amount", field_type="number", required=False, description="Free accessory/accessory benefit discount amount only when explicitly shown as a monetary value", normalization="indian_currency"),
        FieldSpec(key="bonus_amount", field_type="number", required=False, description="Bonus amount only when explicitly shown", normalization="indian_currency"),
        FieldSpec(key="total_price", field_type="number", required=True, description="Grand total/on-road price only when explicitly shown; never calculate a missing total", normalization="indian_currency"),
        FieldSpec(key="net_amount", field_type="number", required=False, description="Net amount/net deal only when explicitly shown; never calculate it from total, discounts, bonus, or payments", normalization="indian_currency"),
        FieldSpec(key="booking_amount_paid", field_type="number", required=True, description="Booking advance/amount paid only when explicitly shown", normalization="indian_currency"),
        FieldSpec(key="balance_amount", field_type="number", required=False, description="Balance amount only when explicitly shown; never calculate it", normalization="indian_currency"),
        FieldSpec(key="mode_of_payment", field_type="string", required=False, description="Payment mode exactly as printed, including UPI/card/cash/cheque/NEFT/RTGS/DD/pay order when applicable"),
        FieldSpec(key="payment_reference_no", field_type="string", required=False, description="Cheque/DD/NEFT/RTGS/UPI/card/reference number only when explicitly visible"),
        FieldSpec(key="expected_delivery", field_type="string", required=False, description="Legacy raw expected-delivery value/timeframe exactly as stated, including an exact date when that is what the document shows"),
        FieldSpec(key="expected_delivery_date", field_type="date", required=False, description="Complete expected delivery calendar date only when explicitly stated; return null for vague periods such as '2 weeks' or 'October'", normalization="date_dd_mm_yyyy"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian automotive dealership booking forms.\n"
        "The document may be handwritten, printed, scanned, or photographed.\n\n"
        "AUDIT EVIDENCE RULES:\n"
        "- Extract only information explicitly visible in the supplied document.\n"
        "- Never calculate, infer, back-solve, or manufacture a missing value.\n"
        "- Never use general knowledge to fill a blank.\n"
        "- If a value is absent, obscured, or uncertain, return null with low confidence.\n"
        "- Handwritten filled values take precedence over blank printed placeholders.\n"
        "- Keep separately labelled commercial components separate; do not fold one field into another.\n"
        "- Never split a lump-sum discount/scheme or total accessories amount into component values unless the document itself shows those component amounts.\n\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Currency values may use Indian numbering (for example 8,58,600); normalize only the formatting of a value that is actually visible.",
        "registration_charges and road_tax_amount are extracted only when the document shows them separately. road_tax_registration remains the backward-compatible field for an explicitly combined value; never split or sum values yourself.",
        "exchange_applicable is based only on an explicit Yes/No, checkbox, tick, or equivalent selection. The existence of exchange_value must not be used to infer it.",
        "total_price must be extracted only from an explicitly shown grand-total/on-road-total value. Do not sum component charges.",
        "net_amount, discount_amount, bonus_amount, and balance_amount must be extracted only when explicitly shown. Do not derive one from the others.",
        "discount_amount is the explicitly printed aggregate/lump-sum discount. Sales, Buffer, Exchange, Corporate, Loyalty, In-house Insurance, MR, OEM Referral, Other and Free Accessory discounts are populated independently only when the form explicitly shows their individual monetary values. Never allocate a lump-sum scheme across them.",
        "accessories_cost is the explicitly printed total/combined accessories amount. essential_kit_amount, genuine_accessories_amount and non_genuine_accessories_amount are populated only when those components are separately visible; never split a total accessories amount.",
        "FASTag, Extended Warranty/EW, Green Tax and Service Package are kept as distinct commercial components whenever the form explicitly shows them.",
        "other_charges must not absorb a separately labelled TCS, RSA, warranty, FASTag, green tax, service package, registration, road tax, insurance, accessories, discount, or bonus amount.",
        "expected_delivery is the backward-compatible raw field. expected_delivery_date is populated only when a complete calendar date is explicitly visible; never manufacture a date from a timeframe.",
        "sku_code must be extracted only when an explicit SKU/product/vehicle code is visible. Never derive it from model, variant, colour, or price.",
        "Preserve identifiers exactly as visible; do not repair ambiguous digits or letters.",
    ],
)
