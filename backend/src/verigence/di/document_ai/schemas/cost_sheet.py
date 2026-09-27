"""document_ai/schemas/cost_sheet.py — Cost Sheet (price quotation).

The dealer's itemised on-road price quotation for a customer. Keys are
exactly the migration 0046 published profile's; amounts are the quoted
figures, used as quote-side evidence beside the booking form and invoices.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

COST_SHEET_SCHEMA = SchemaDefinition(
    document_type_key="cost_sheet",
    display_name="Cost Sheet",
    schema_version="1.0",
    fields=[
        FieldSpec("customer_name", "string", True, "Customer name exactly as printed/written."),
        FieldSpec("vehicle_model", "string", True, "Vehicle model and variant exactly as printed."),
        FieldSpec("ex_showroom_price", "number", True, "Ex-showroom price.", normalization="indian_currency"),
        FieldSpec("rto_amount", "number", False,
                  "RTO / registration / road-tax amount (the total of the registration charges if itemised).",
                  normalization="indian_currency"),
        FieldSpec("insurance_amount", "number", False, "Insurance amount.", normalization="indian_currency"),
        FieldSpec("accessories_amount", "number", False,
                  "Accessories amount (the accessories total if itemised).", normalization="indian_currency"),
        FieldSpec("discount_amount", "number", False,
                  "Total discount / bonus / offer amount deducted, as a positive number.",
                  normalization="indian_currency"),
        FieldSpec("total_on_road_price", "number", True,
                  "Total on-road price / grand total payable.", normalization="indian_currency"),
        FieldSpec("cost_sheet_date", "date", False, "Date of the cost sheet.", normalization="date_dd_mm_yyyy"),
    ],
    system_prompt=(
        "You extract data from an Indian automobile dealership cost sheet (on-road price quotation), printed "
        "or handwritten on a printed format. Extract only amounts that are shown; never add up, compute or "
        "estimate a figure the sheet does not state.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "When several variants or price options are listed, extract the one marked as selected/quoted for this customer; if none is marked, return null for the amounts.",
        "discount_amount is a deduction: return it as a positive number even if printed with a minus sign.",
        "total_on_road_price is the final payable figure after discounts when the sheet shows one; otherwise the on-road total.",
        "Normalize Indian currency formatting (e.g. 12,45,000) only for a clearly visible amount.",
        "If a field is not printed or is unclear, return null with low confidence.",
    ],
)
