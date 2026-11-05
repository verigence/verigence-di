"""document_ai/schemas/cost_sheet.py — Cost Sheet (price quotation).

The dealer's itemised on-road price quotation for a customer. Keys are
exactly the published profile's (0046, then 0061); amounts are the quoted
figures, used as quote-side evidence beside the booking form and invoices.

1.1 (2026-11-05): every priced row (``line_items``) and the title printed at the
top (``document_title``). The four headline figures left the sheet's other rows
-- TCS, extended warranty, RSA, FASTag, handling, others -- unread, so the
on-road total could never be checked against its rows (product owner: "the
cost sheet should add up"); and the title tells a dealer's account statement
filed as a cost sheet before the classifier knew the difference.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

COST_SHEET_SCHEMA = SchemaDefinition(
    document_type_key="cost_sheet",
    display_name="Cost Sheet",
    schema_version="1.1",
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
        FieldSpec("document_title", "string", False,
                  "Title printed at the top of the page, verbatim (for example Quotation, Cost Sheet, "
                  "Quotation cum Proforma Invoice, Vehicle Account Statement)."),
        FieldSpec("line_items", "array", False,
                  "JSON array of every priced row of the sheet in printed order, each as particulars_raw "
                  "(the row's label verbatim), amount (as printed) and deduction (true when the row is "
                  "subtracted: a discount, offer, scheme or Less row); never the total, on-road, net or "
                  "grand-total rows."),
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
        "line_items lists every row that carries an amount - ex-showroom, TCS, insurance, registration/RTO, "
        "extended warranty, accessories, FASTag, RSA, handling, others and each discount - exactly as printed, "
        "one row per printed row, never added together; a row without an amount is left out. The total / "
        "on-road / net amount row goes only to total_on_road_price.",
        "CHECK YOUR READING AGAINST THE SHEET'S OWN TOTAL before you answer: the line_items amounts, less the "
        "deduction rows, should add up to the printed on-road / grand total. When they do not, look at the page "
        "again for a row you missed, a row read twice or a digit misread, and correct those rows. Never change or "
        "compute the printed total to make them agree: if the rows as written still do not add up, return them as "
        "written.",
        "If a field is not printed or is unclear, return null with low confidence.",
    ],
)
