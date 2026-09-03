"""Generalized invoice extraction schemas.

Existing business document keys remain stable. Every invoice key gets one lossless common
commercial + vehicle evidence superset, with only genuinely service-specific fields added
where needed. This lets DI classify conservatively as a generic invoice without dropping
useful vehicle or commercial facts.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

_INVOICE_PURPOSES = [
    "VEHICLE_SALE",
    "VEHICLE_WHOLESALE",
    "ACCESSORY",
    "EXTENDED_WARRANTY",
    "RSA",
    "SERVICE",
    "OTHER",
    "UNKNOWN",
]
_INVOICE_NATURES = [
    "TAX_INVOICE",
    "RETAIL_INVOICE",
    "PROFORMA_INVOICE",
    "CREDIT_NOTE",
    "DEBIT_NOTE",
    "OTHER",
    "UNKNOWN",
]
_SOURCE_SYSTEMS = [
    "DMS",
    "TALLY",
    "DEALER_GENERATED",
    "OEM",
    "THIRD_PARTY",
    "UNKNOWN",
]
_ISSUER_ROLES = [
    "DEALER",
    "OEM",
    "ACCESSORY_VENDOR",
    "SERVICE_PROVIDER",
    "INSURER",
    "OTHER",
    "UNKNOWN",
]
_BUYER_GSTIN_STATUSES = [
    "REGISTERED",
    "UNREGISTERED",
    "NOT_STATED",
    "UNKNOWN",
]


def _common_fields() -> list[FieldSpec]:
    return [
        FieldSpec(
            "invoice_purpose",
            "string",
            True,
            "Business purpose of this invoice based on visible content.",
            enum=_INVOICE_PURPOSES,
        ),
        FieldSpec(
            "invoice_nature",
            "string",
            True,
            "Legal/business nature explicitly stated or reliably evidenced by the document.",
            enum=_INVOICE_NATURES,
        ),
        FieldSpec(
            "invoice_heading_as_printed",
            "string",
            False,
            "Invoice heading/title exactly as printed, for example TAX INVOICE or Retail Invoice.",
        ),
        FieldSpec(
            "source_system",
            "string",
            True,
            "Source/system only when visible or reliably evidenced; otherwise UNKNOWN.",
            enum=_SOURCE_SYSTEMS,
        ),
        FieldSpec(
            "issuer_role",
            "string",
            True,
            "Role of the invoice issuer based on the visible seller/issuer context.",
            enum=_ISSUER_ROLES,
        ),
        FieldSpec(
            "invoice_number",
            "string",
            False,
            "Invoice/reference number exactly as printed.",
        ),
        FieldSpec(
            "invoice_date",
            "string",
            False,
            "Invoice date exactly as printed; normalize to YYYY-MM-DD when unambiguous.",
            normalization="date_dd_mm_yyyy",
        ),
        FieldSpec(
            "seller_name",
            "string",
            False,
            "Seller/issuer legal or trade name exactly as printed.",
        ),
        FieldSpec("seller_gstin", "string", False, "Seller GSTIN exactly as printed."),
        FieldSpec(
            "seller_address",
            "string",
            False,
            "Seller/issuer address exactly as printed.",
        ),
        FieldSpec("buyer_name", "string", False, "Buyer/customer name exactly as printed."),
        FieldSpec(
            "buyer_customer_id",
            "string",
            False,
            "Buyer/customer ID only when explicitly printed.",
        ),
        FieldSpec("buyer_gstin", "string", False, "Buyer/customer GSTIN exactly as printed; null when the document says unregistered."),
        FieldSpec(
            "buyer_gstin_status",
            "string",
            False,
            "Buyer GST registration status only from explicit document evidence; do not infer from a missing GSTIN.",
            enum=_BUYER_GSTIN_STATUSES,
        ),
        FieldSpec(
            "buyer_address",
            "string",
            False,
            "Buyer/customer address exactly as printed.",
        ),
        FieldSpec(
            "financed_by",
            "string",
            False,
            "Financier/hypothecation/loan institution exactly as printed.",
        ),
        FieldSpec(
            "gross_amount_before_discount",
            "number",
            False,
            "Gross/base amount before invoice-level discount only when explicitly stated.",
        ),
        FieldSpec(
            "invoice_discount_amount",
            "number",
            False,
            "Invoice-level discount amount exactly as stated; do not calculate it.",
        ),
        FieldSpec(
            "taxable_amount",
            "number",
            False,
            "Taxable/net selling value exactly as stated; do not derive it from other amounts.",
        ),
        FieldSpec("cgst_rate", "number", False, "CGST rate percentage when explicitly printed."),
        FieldSpec("cgst_amount", "number", False, "CGST amount exactly as printed."),
        FieldSpec("sgst_rate", "number", False, "SGST rate percentage when explicitly printed."),
        FieldSpec("sgst_amount", "number", False, "SGST amount exactly as printed."),
        FieldSpec("igst_rate", "number", False, "IGST rate percentage when explicitly printed."),
        FieldSpec("igst_amount", "number", False, "IGST amount exactly as printed."),
        FieldSpec(
            "cess_amount",
            "number",
            False,
            "GST compensation cess or other cess amount only when explicitly printed.",
        ),
        FieldSpec(
            "tcs_amount",
            "number",
            False,
            "TCS amount only when explicitly printed; return null for N/A.",
        ),
        FieldSpec(
            "round_off_amount",
            "number",
            False,
            "Signed round-off amount exactly as printed; preserve negative values and paise.",
        ),
        FieldSpec(
            "grand_total_amount",
            "number",
            False,
            "Final invoice/grand total exactly as printed; do not recompute taxes or rounding.",
        ),
        FieldSpec(
            "amount_in_words",
            "string",
            False,
            "Invoice amount-in-words text exactly as printed.",
        ),
        FieldSpec("narration", "string", False, "Narration/remarks exactly as printed, if present."),
        FieldSpec(
            "line_items",
            "array",
            False,
            (
                "JSON array of visible invoice line items. For each item preserve "
                "description_raw and extract only explicitly printed item_code, hsn_sac, "
                "quantity, unit_rate, gross_amount, discount_amount, taxable_amount, "
                "tax_rate, tax_amount and net_amount."
            ),
        ),
    ]


def _vehicle_fields() -> list[FieldSpec]:
    return [
        FieldSpec(
            "vehicle_description_raw",
            "string",
            False,
            "Complete vehicle description exactly as printed when present on any invoice.",
        ),
        FieldSpec(
            "sku_code",
            "string",
            False,
            "Explicit SKU/product/model code only when printed; never infer it.",
        ),
        FieldSpec(
            "model_name_raw",
            "string",
            False,
            "Vehicle model text exactly as printed; do not map to a master.",
        ),
        FieldSpec(
            "variant_raw",
            "string",
            False,
            "Vehicle variant/trim text exactly as printed; do not map to a master.",
        ),
        FieldSpec(
            "vin_number",
            "string",
            False,
            "VIN exactly as printed; never reconstruct missing characters.",
        ),
        FieldSpec("chassis_number", "string", False, "Chassis number exactly as printed."),
        FieldSpec("engine_number", "string", False, "Engine number exactly as printed."),
        FieldSpec(
            "key_number",
            "string",
            False,
            "Vehicle key number only when explicitly printed.",
        ),
        FieldSpec("vehicle_color", "string", False, "Vehicle colour exactly as printed."),
        FieldSpec(
            "vehicle_registration_number",
            "string",
            False,
            "Vehicle registration number only when printed.",
        ),
        FieldSpec("vehicle_hsn_code", "string", False, "Vehicle HSN code exactly as printed."),
    ]


def _service_fields() -> list[FieldSpec]:
    return [
        FieldSpec("plan_name", "string", False, "Plan/product/service name exactly as printed."),
        FieldSpec(
            "coverage_start_date",
            "string",
            False,
            "Coverage/service start date only when explicitly printed.",
            normalization="date_dd_mm_yyyy",
        ),
        FieldSpec(
            "coverage_end_date",
            "string",
            False,
            "Coverage/service end date only when explicitly printed.",
            normalization="date_dd_mm_yyyy",
        ),
        FieldSpec(
            "tenure_months",
            "number",
            False,
            "Coverage/service tenure in months only when explicitly printed.",
        ),
    ]


def _build_schema(
    *,
    document_type_key: str,
    display_name: str,
    expected_purpose: str | None,
    expected_source: str | None,
    extension: str,
) -> SchemaDefinition:
    # Every invoice gets the same lossless commercial + vehicle evidence superset.
    # Specific invoice keys remain classification/context hints, not extraction ceilings.
    fields = _common_fields() + _vehicle_fields()
    if extension == "service":
        fields += _service_fields()

    notes = [
        "Extract one invoice in one pass; do not request or assume a second classification pass.",
        (
            "Do not equate an invoice heading with its business purpose. Preserve "
            "invoice_heading_as_printed, and determine invoice_nature and invoice_purpose "
            "separately from visible evidence."
        ),
        (
            "Vehicle identifiers prove vehicle-related content; they do not prove the source "
            "system. Keep source_system UNKNOWN unless the document visibly or reliably "
            "identifies DMS, Tally, dealer-generated, OEM, or third-party origin."
        ),
        (
            "If the buyer GST section explicitly says Unregistered, set buyer_gstin to null "
            "and buyer_gstin_status to UNREGISTERED. Do not store 'Unregistered' as a GSTIN."
        ),
        (
            "Never calculate missing monetary values. Preserve each printed source amount "
            "independently so reconciliation can happen later."
        ),
        (
            "Preserve decimal precision exactly, including paise and signed round-off values; "
            "do not round extracted commercial evidence."
        ),
        (
            "Do not call a base/taxable value ex-showroom unless the document explicitly "
            "labels it ex-showroom; this schema intentionally uses neutral commercial names."
        ),
        (
            "For line_items return a JSON array; do not merge separate printed items into one "
            "synthetic item."
        ),
    ]
    if expected_purpose:
        notes.append(
            f"This requirement normally represents {expected_purpose}; if visible content "
            "contradicts that, extract the observed invoice_purpose rather than forcing it."
        )
    if expected_source:
        notes.append(
            f"This requirement normally comes from {expected_source}; return another source "
            f"or UNKNOWN when the visible document does not support {expected_source}."
        )

    return SchemaDefinition(
        document_type_key=document_type_key,
        display_name=display_name,
        schema_version="1.0",
        fields=fields,
        system_prompt=(
            "You extract structured commercial evidence from automobile-dealership invoices "
            "for audit. Preserve what the document states, including source differences and "
            "rounding, so a separate deterministic audit layer can reconcile documents later. "
            "Never infer a master SKU, invent a commercial amount, or hide a disagreement "
            "between printed values."
        ),
        prompt_notes=notes,
    )


WHOLESALE_INVOICE_SCHEMA = _build_schema(
    document_type_key="wholesale_invoice",
    display_name="Wholesale Invoice",
    expected_purpose="VEHICLE_WHOLESALE",
    expected_source="OEM",
    extension="vehicle",
)
CUSTOMER_INVOICE_DMS_SCHEMA = _build_schema(
    document_type_key="customer_invoice_dms",
    display_name="Customer Invoice (DMS)",
    expected_purpose="VEHICLE_SALE",
    expected_source="DMS",
    extension="vehicle",
)
TAX_INVOICE_TALLY_SCHEMA = _build_schema(
    document_type_key="tax_invoice_tally",
    display_name="Tax Invoice (Tally)",
    expected_purpose="VEHICLE_SALE",
    expected_source="TALLY",
    extension="vehicle",
)
ACCESSORY_INVOICE_DMS_SCHEMA = _build_schema(
    document_type_key="accessory_invoice_dms",
    display_name="Accessory Invoice / Challan (DMS)",
    expected_purpose="ACCESSORY",
    expected_source="DMS",
    extension="generic",
)
ACCESSORY_INVOICE_TALLY_SCHEMA = _build_schema(
    document_type_key="accessory_invoice_tally",
    display_name="Accessory Invoice (Tally)",
    expected_purpose="ACCESSORY",
    expected_source="TALLY",
    extension="generic",
)
EW_INVOICE_SCHEMA = _build_schema(
    document_type_key="ew_invoice",
    display_name="Extended Warranty Invoice",
    expected_purpose="EXTENDED_WARRANTY",
    expected_source=None,
    extension="service",
)
RSA_INVOICE_SCHEMA = _build_schema(
    document_type_key="rsa_invoice",
    display_name="RSA Invoice",
    expected_purpose="RSA",
    expected_source=None,
    extension="service",
)
GENERIC_INVOICE_SCHEMA = _build_schema(
    document_type_key="invoice_generic",
    display_name="Other Invoice",
    expected_purpose=None,
    expected_source=None,
    extension="generic",
)
