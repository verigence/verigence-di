"""document_ai/schemas/rto_tax_receipt.py — RTO Tax / Fee Receipt schema.

document_type_key : rto_tax_receipt
display_name      : RTO Tax Receipt
DB category       : PRINTABLE
schema_version    : 1.0

Characteristics: a government Regional Transport Office receipt — registration
fee, motor-vehicle tax, hypothecation-addition fee, permit fee, etc., issued
via the state VAHAN / Parivahan / OnlinePermitFee portals ("GOVERNMENT OF
<state> — Motor Vehicles Department", "E-FEE RECEIPT"). A short fee table and
a grand total. Source of truth for the registration / road-tax / permit
component of the on-road price.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

RTO_TAX_RECEIPT_SCHEMA = SchemaDefinition(
    document_type_key="rto_tax_receipt",
    display_name="RTO Tax Receipt",
    schema_version="1.0",
    fields=[
        FieldSpec(key="receipt_number",       field_type="string", required=True,  description="Receipt / application number (e.g. 'OR34D26080000754/OR26081316431192')"),
        FieldSpec(key="receipt_date",         field_type="date",   required=True,  description="Receipt date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="rto_office",            field_type="string", required=False, description="Issuing RTO office (e.g. 'JAJPUR RTO', 'RTO KATAKA')"),
        FieldSpec(key="state",                field_type="string", required=False, description="State (e.g. 'Odisha')"),
        FieldSpec(key="receipt_type",         field_type="string", required=False, description="What the receipt is for (e.g. 'Fresh Permit', 'New Registration', 'MV Tax')"),
        FieldSpec(key="transaction_id",       field_type="string", required=False, description="Portal transaction id"),
        FieldSpec(key="bank_reference",       field_type="string", required=False, description="Bank reference / payment reference number"),
        FieldSpec(key="payment_mode",         field_type="string", required=False, description="Payment mode (e.g. 'ONLINE-PAYMENT')"),

        FieldSpec(key="owner_name",           field_type="string", required=True,  description="Vehicle owner / applicant name"),
        FieldSpec(key="vehicle_number",       field_type="string", required=False, description="Registration number, or 'NEW' if not yet assigned"),
        FieldSpec(key="chassis_number",       field_type="string", required=False, description="Chassis number — extract exactly as printed"),
        FieldSpec(key="registration_date",    field_type="date",   required=False, description="Registration date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="vehicle_class",        field_type="string", required=False, description="Vehicle class (e.g. 'Goods Carrier', 'LMV')"),
        FieldSpec(key="financer_name",        field_type="string", required=False, description="Financer / hypothecation bank named on the receipt"),
        FieldSpec(key="sale_amount",          field_type="number", required=False, description="Sale amount printed on the receipt, if any", normalization="indian_currency"),
        FieldSpec(key="tax_paid_upto",        field_type="date",   required=False, description="Tax validity date ('Tax Paid Upto')", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="fitness_validity",     field_type="date",   required=False, description="Fitness validity date, if printed", normalization="date_dd_mm_yyyy"),

        FieldSpec(
            key="fee_lines",
            field_type="array",
            required=True,
            description=(
                "Array of fee rows from the table. One object per row with keys: "
                "particular (e.g. 'New Registration (RTO Side)', 'Hypothecation "
                "Addition', 'MV Tax', 'Automation and Technology Fee', 'Permit "
                "Application', 'Surcharge Fee'), amount, penalty, total. Money as "
                "plain numbers."
            ),
        ),
        FieldSpec(key="total_penalty_amount", field_type="number", required=False, description="Total fine / penalty across all rows", normalization="indian_currency"),
        FieldSpec(key="rto_total_amount",     field_type="number", required=True,  description="Grand total of the receipt", normalization="indian_currency"),
        FieldSpec(key="amount_in_words",      field_type="string", required=False, description="Grand total in words"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "Regional Transport Office (RTO) tax and fee receipts issued via the "
        "state VAHAN / Parivahan / OnlinePermitFee portals.\n"
        "You will be shown an RTO receipt with a short fee table and a grand "
        "total.\n\n"
        "Extract each field listed below from the document.\n"
        "Output ONLY valid JSON. For each field use this exact structure:\n"
        '  "<field_key>": {"value": <extracted value or null>, "confidence": "high"|"medium"|"low"}\n\n'
        "Confidence rules:\n"
        '  "high"   — value is clearly printed and unambiguous\n'
        '  "medium" — value is partially legible or inferred\n'
        '  "low"    — value is absent or unclear\n\n'
        "If a field is not found, return: "
        '{"value": null, "confidence": "low"}'
    ),
    prompt_notes=[
        "fee_lines: one object per row of the fee table. Keys: particular, "
        "amount, penalty, total. Include every row.",
        "rto_total_amount is the 'GRAND TOTAL' figure.",
        "vehicle_number: if the receipt shows 'NEW' (registration not yet "
        "assigned), return the string 'NEW'.",
        "chassis_number: extract exactly as printed — it links this receipt to "
        "the vehicle journey.",
        "Some bundles contain the same receipt twice (Office Copy + Customer "
        "Copy). Extract from the clearer copy; the totals are identical.",
    ],
)
