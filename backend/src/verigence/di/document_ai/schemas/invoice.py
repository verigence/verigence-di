"""document_ai/schemas/invoice.py — Vehicle sale Invoice (superset) schema.

document_type_key : invoice
display_name      : Invoice
DB category       : PRINTABLE
schema_version    : 1.0

ONE superset schema for every dealer-issued invoice on a vehicle journey. The
document classifier cannot reliably tell a vehicle Tax Invoice from a Retail
Invoice, an Accessories Invoice or an Extended-Warranty Invoice — the layouts
overlap — so all of them are classified as ``invoice`` and extracted against
this schema. ``invoice_kind`` is classified *inside* the extraction, and each
sub-type's fields are optional: an accessories invoice fills ``line_items`` and
``invoice_total_amount``; a tax/retail invoice fills ``ex_showroom_price`` /
``discount_amount`` / the GST block; an EW invoice fills the ``ew_*`` fields.

Downstream (Audit Core) routes each extracted invoice to the right canonical
component by ``invoice_kind`` + the fields that are populated, with the
invoice-first source precedence reconciling multiple invoices for one journey.

Not covered here (own schemas): dealer_accounts_statement, rto_tax_receipt,
insurance_cover, dealer_receipt, bank_statement_extract.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

INVOICE_SCHEMA = SchemaDefinition(
    document_type_key="invoice",
    display_name="Invoice",
    schema_version="1.0",
    fields=[
        # ── classification ─────────────────────────────────────────────────
        FieldSpec(
            key="invoice_kind",
            field_type="string",
            required=True,
            description="Which kind of invoice this document is",
            enum=[
                "tax_invoice",
                "retail_invoice",
                "accessories_invoice",
                "extended_warranty_invoice",
                "proforma_invoice",
                "supplementary_invoice",
                "other",
            ],
        ),

        # ── invoice identity ───────────────────────────────────────────────
        FieldSpec(key="invoice_number",       field_type="string", required=True,  description="Invoice number / GST invoice number (e.g. 'INV27B000387', 'E7A01/0127/26-27', 'C1R27B00000406')"),
        FieldSpec(key="invoice_date",         field_type="date",   required=True,  description="Invoice date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="irn_number",           field_type="string", required=False, description="Invoice Reference Number (IRN) of the e-invoice, if printed"),
        FieldSpec(key="irn_date",             field_type="date",   required=False, description="IRN acknowledgement date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="reference_number",     field_type="string", required=False, description="Internal reference / bill number (e.g. 'IN-24023654')"),
        FieldSpec(key="process_type",         field_type="string", required=False, description="Process / document label as printed (e.g. 'Sales Invoice', 'Counter Sales')"),
        FieldSpec(key="sale_type",            field_type="string", required=False, description="Sale type (e.g. 'Within State', 'Inter State')"),
        FieldSpec(key="pay_mode",             field_type="string", required=False, description="Payment mode on the invoice (e.g. 'Credit', 'Cash')"),

        # ── seller (dealer) ───────────────────────────────────────────────
        FieldSpec(key="dealer_name",          field_type="string", required=True,  description="Name of the dealership issuing the invoice"),
        FieldSpec(key="dealer_gstin",         field_type="string", required=True,  description="Dealer GSTIN (15-character GST registration number)"),
        FieldSpec(key="dealer_pan",           field_type="string", required=False, description="Dealer PAN"),
        FieldSpec(key="dealer_address",       field_type="string", required=False, description="Dealer registered address as printed"),
        FieldSpec(key="dealer_state_code",    field_type="string", required=False, description="Dealer GST state code (e.g. '21' for Odisha)"),
        FieldSpec(key="dealer_branch",        field_type="string", required=False, description="Dealer branch / outlet name"),
        FieldSpec(key="sales_executive",      field_type="string", required=False, description="Sales / parts executive name on the invoice"),

        # ── buyer (customer) ─────────────────────────────────────────────
        FieldSpec(key="customer_name",        field_type="string", required=True,  description="Full name of the customer / buyer"),
        FieldSpec(key="customer_code",        field_type="string", required=False, description="Dealer/DMS customer code (e.g. 'R270561262', 'C2026063448')"),
        FieldSpec(key="customer_gstin",       field_type="string", required=False, description="Customer GSTIN if registered; else 'Unregistered'"),
        FieldSpec(key="customer_pan",         field_type="string", required=False, description="Customer PAN"),
        FieldSpec(key="customer_aadhaar",     field_type="string", required=False, description="Customer Aadhaar as printed (often masked, e.g. 'XXXXXXXX4792')"),
        FieldSpec(key="customer_phone",       field_type="string", required=False, description="Customer phone number", normalization="phone_e164"),
        FieldSpec(key="customer_address",     field_type="string", required=False, description="Customer billing address"),
        FieldSpec(key="place_of_supply",      field_type="string", required=False, description="Place of supply (state) as printed"),

        # ── booking linkage ─────────────────────────────────────────────
        FieldSpec(key="booking_number",       field_type="string", required=False, description="Dealer booking / order number referenced (e.g. 'B-12947340')"),
        FieldSpec(key="booking_date",         field_type="date",   required=False, description="Booking date referenced", normalization="date_dd_mm_yyyy"),

        # ── vehicle ─────────────────────────────────────────────────────
        FieldSpec(key="vehicle_model",        field_type="string", required=False, description="Vehicle model / product description (e.g. 'BOL MAXX PUP HD 1.7L LX', 'EXTER 1.2AMT Kappa HX 6'). Null for a pure accessories invoice with no vehicle line."),
        FieldSpec(key="vehicle_variant",      field_type="string", required=False, description="Vehicle variant / trim if separately printed"),
        FieldSpec(key="vehicle_colour",       field_type="string", required=False, description="Vehicle colour"),
        FieldSpec(key="model_group",          field_type="string", required=False, description="Model group as printed on parts invoices (e.g. 'PICK UP')"),
        FieldSpec(key="hsn_sac_code",         field_type="string", required=False, description="HSN/SAC code of the main line (e.g. '87042100', '87032291')"),
        FieldSpec(key="quantity",             field_type="number", required=False, description="Quantity of the main line (normally 1 for a vehicle)"),
        FieldSpec(key="vin",                  field_type="string", required=False, description="VIN — extract exactly as printed"),
        FieldSpec(key="chassis_number",       field_type="string", required=False, description="Chassis number — extract exactly as printed (may equal the VIN). Links the invoice to the vehicle journey."),
        FieldSpec(key="engine_number",        field_type="string", required=False, description="Engine number"),
        FieldSpec(key="key_number",           field_type="string", required=False, description="Key number"),
        FieldSpec(key="fuel_type",            field_type="string", required=False, description="Fuel type (e.g. 'DIESEL', 'PETROL')"),
        FieldSpec(key="emission_norm",        field_type="string", required=False, description="Emission norm (e.g. 'BS VI')"),

        # ── vehicle pricing (tax_invoice / retail_invoice) ──────────────
        FieldSpec(key="ex_showroom_price",    field_type="number", required=False, description="Vehicle selling price / rate BEFORE discount ('Selling Price', 'Rate', 'Price of One', 'Ex-showroom')", normalization="indian_currency"),
        FieldSpec(key="discount_amount",      field_type="number", required=False, description="Total discount on the invoice ('Discount', 'Discount On (Scheme)'), as a positive number", normalization="indian_currency"),
        FieldSpec(key="oem_discount_amount",  field_type="number", required=False, description="OEM/manufacturer discount line shown separately ('OEM Discount'), as a positive number", normalization="indian_currency"),
        FieldSpec(key="taxable_amount",       field_type="number", required=False, description="Taxable value after discount ('Taxable Amount', 'Net Selling Price')", normalization="indian_currency"),

        # ── accessories invoice line items ─────────────────────────────
        FieldSpec(
            key="line_items",
            field_type="array",
            required=False,
            description=(
                "For an accessories/parts invoice: array of line-item objects, "
                "one per row, with keys: part_number, part_description, hsn, "
                "quantity, uom, rate, discount, taxable_value, cgst_rate, "
                "cgst_amount, sgst_rate, sgst_amount, line_total. Money as plain "
                "numbers. Null for a vehicle invoice."
            ),
        ),
        FieldSpec(key="total_items",          field_type="number", required=False, description="Total number of distinct items (accessories invoice)"),
        FieldSpec(key="total_quantity",       field_type="number", required=False, description="Total quantity across all lines (accessories invoice)"),

        # ── extended warranty invoice ─────────────────────────────────
        FieldSpec(key="ew_provider_name",     field_type="string", required=False, description="Extended-warranty provider / programme (e.g. 'Mahindra Shield', 'Hyundai Wonder Warranty')"),
        FieldSpec(key="ew_plan_name",         field_type="string", required=False, description="Extended-warranty plan / package name"),
        FieldSpec(key="ew_coverage_years",    field_type="string", required=False, description="Additional years covered, as printed (e.g. '4th year', '4th & 5th year')"),
        FieldSpec(key="ew_coverage_km_limit", field_type="number", required=False, description="Kilometre limit of the extended cover"),
        FieldSpec(key="ew_coverage_start_date", field_type="date", required=False, description="Extended cover start date", normalization="date_dd_mm_yyyy"),
        FieldSpec(key="ew_coverage_end_date", field_type="date",   required=False, description="Extended cover end date", normalization="date_dd_mm_yyyy"),

        # ── amounts / GST break-up ────────────────────────────────────
        FieldSpec(key="subtotal_taxable",     field_type="number", required=False, description="Sub-total of taxable value across all lines (accessories invoice)", normalization="indian_currency"),
        FieldSpec(key="total_discount_amount", field_type="number", required=False, description="Total discount across all lines, positive (accessories invoice)", normalization="indian_currency"),
        FieldSpec(key="other_charges",        field_type="number", required=False, description="Other charges line, if any", normalization="indian_currency"),
        FieldSpec(key="cgst_rate",            field_type="number", required=False, description="CGST rate percent (e.g. 9)"),
        FieldSpec(key="cgst_amount",          field_type="number", required=False, description="CGST amount (total)", normalization="indian_currency"),
        FieldSpec(key="sgst_rate",            field_type="number", required=False, description="SGST/UGST rate percent (e.g. 9)"),
        FieldSpec(key="sgst_amount",          field_type="number", required=False, description="SGST/UGST amount (total)", normalization="indian_currency"),
        FieldSpec(key="igst_rate",            field_type="number", required=False, description="IGST rate percent (inter-state supply)"),
        FieldSpec(key="igst_amount",          field_type="number", required=False, description="IGST amount (total)", normalization="indian_currency"),
        FieldSpec(key="cess_amount",          field_type="number", required=False, description="GST compensation cess amount, if any", normalization="indian_currency"),
        FieldSpec(key="total_tax_amount",     field_type="number", required=False, description="Total tax amount (CGST + SGST, or IGST, plus cess)", normalization="indian_currency"),
        FieldSpec(key="tcs_amount",           field_type="number", required=False, description="TCS amount; 'N/A' or blank means 0", normalization="indian_currency"),
        FieldSpec(key="round_off_amount",     field_type="number", required=False, description="Round-off adjustment, signed (e.g. -0.29)", normalization="indian_currency"),
        FieldSpec(key="invoice_total_amount", field_type="number", required=True,  description="Grand total / total amount payable on this invoice (after round-off)", normalization="indian_currency"),
        FieldSpec(key="amount_in_words",      field_type="string", required=False, description="Total amount written in words"),

        # ── finance ──────────────────────────────────────────────────
        FieldSpec(key="hypothecation_bank",   field_type="string", required=False, description="Bank / financier the vehicle is hypothecated to (e.g. 'KOTAK MAHINDRA BANK LTD')"),
        FieldSpec(key="financier_branch",     field_type="string", required=False, description="Financier branch name"),
        FieldSpec(key="reverse_charge",       field_type="boolean", required=False, description="Whether tax is payable on reverse charge (usually 'No')"),
    ],
    system_prompt=(
        "You are a document data extraction assistant specialising in Indian "
        "automotive dealer invoices for the sale of a motor vehicle and its "
        "add-ons.\n"
        "You will be shown ONE invoice. It may be a vehicle Tax Invoice, a "
        "Retail Invoice, an Accessories/Parts Invoice, or an Extended-Warranty "
        "Invoice — printed or a PDF/scan, layout varies by OEM and DMS.\n\n"
        "First decide which kind of invoice it is and set invoice_kind. Then "
        "extract each field listed below. Only some fields apply to any one "
        "invoice — return null + low confidence for fields that are not on the "
        "document.\n"
        "Output ONLY valid JSON. For each field use this exact structure:\n"
        '  "<field_key>": {"value": <extracted value or null>, "confidence": "high"|"medium"|"low"}\n'
        "For line_items, value is a JSON array of objects.\n\n"
        "Confidence rules:\n"
        '  "high"   — value is clearly printed and unambiguous\n'
        '  "medium" — value is partially legible or inferred from an adjacent total\n'
        '  "low"    — value is absent or unclear\n\n'
        "If a field is not found, return: "
        '{"value": null, "confidence": "low"}\n'
        "Never guess a numeric value you cannot read clearly."
    ),
    prompt_notes=[
        "invoice_kind: 'tax_invoice' = full GST tax invoice for the vehicle "
        "(HSN 8703/8704, 'TAX INVOICE', Rule 46). 'retail_invoice' = short "
        "'Retail Invoice' with a numbered PARTICULARS list (Price of One / "
        "Discount / Net Selling Price / CGST / SGST / TOTAL / GRAND TOTAL). "
        "'accessories_invoice' = parts invoice with a multi-row part table. "
        "'extended_warranty_invoice' = invoice for a warranty plan. "
        "'proforma_invoice' = marked proforma / quotation. Use 'other' only if "
        "none fit.",
        "ex_showroom_price is the vehicle price BEFORE discount ('Selling "
        "Price', 'Rate', 'Price of One'). Do NOT put the post-discount 'Taxable "
        "Amount' / 'Net Selling Price' here.",
        "discount_amount and oem_discount_amount: always POSITIVE numbers even "
        "if printed as '-16,949.00' or in a 'less' column. If the invoice shows "
        "one discount, use discount_amount; if it also shows a separate 'OEM "
        "Discount', capture both.",
        "line_items (accessories invoice): one object per part row, keys "
        "part_number, part_description, hsn, quantity, uom, rate, discount, "
        "taxable_value, cgst_rate, cgst_amount, sgst_rate, sgst_amount, "
        "line_total. discount defaults to 0.",
        "GST: intra-state → cgst_* and sgst_*; inter-state → igst_*. Rates are "
        "percentages (9, 14, 18) — number only. total_tax_amount is their sum.",
        "invoice_total_amount is the final 'Grand Total' after round-off.",
        "vin and chassis_number: extract EXACTLY as printed, character for "
        "character. They are frequently identical.",
        "tcs_amount: 'N/A', 'NIL' or blank → return 0 with medium confidence.",
        "All money fields: normalise Indian-formatted numbers ('8,19,100.00') "
        "to a plain number (819100). Keep paise if printed (978500.29).",
    ],
)
