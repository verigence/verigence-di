"""UC03 Booking extraction publication boundary.

UC03 keeps an explicit allow-list for non-commercial Booking facts, but commercial
facts are an explicit cross-document exception: when DI has extracted a field
whose semantic key is commercial, that machine fact remains available to the
audit-consumption stream regardless of document type. Audit Core remains the
business-logic owner and decides how (or whether) the fact is used.

Customer identity intentionally preserves multiple sources. The PC-entered name is
owned by Audit Core and is never overwritten by DI. Booking-form ``customer_name``
is published as a source-document fact for visible comparison, while PAN/Aadhaar
names are the identity-authoritative sources used by Audit Core for Legal Name.
Identity relationship fields are publication-only evidence facts. PAN and Aadhaar
use source-specific keys so two different printed relationships cannot be
accidentally merged into one resolved attribute.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Canonical DI document type -> non-commercial fields allowed into the UC03
# Booking proposal/review stream. Commercial fields are handled separately below
# so a price/amount/payment fact is not silently lost just because it came from a
# different document type.
UC03_BOOKING_SUPPORTED_FIELDS: dict[str, frozenset[str]] = {
    "booking_form": frozenset(
        {
            "booking_date",
            "customer_name",
            "customer_phone",
            "customer_email",
            "vehicle_model",
            "vehicle_variant",
            "vehicle_color",
            "sku_code",
            "registration_by",
            "registration_type",
            "insurance_by",
            "exchange_applicable",
            "expected_delivery",
            "expected_delivery_date",
        }
    ),
    "pan_card": frozenset(
        {
            "pan_number",
            "pan_name",
            "pan_father_name",
            "pan_relationship_type",
            "pan_relationship_name",
        }
    ),
    "aadhaar": frozenset(
        {
            "aadhaar_name",
            "aadhaar_relationship_type",
            "aadhaar_relationship_name",
        }
    ),
}

# Commercial semantics are intentionally based on canonical field keys rather
# than document type. This lets future document schemas publish extracted money
# and payment facts without requiring a UC03 code change for every document.
_COMMERCIAL_EXACT_FIELDS = frozenset(
    {
        "total",
        "subtotal",
        "grand_total",
        "net_total",
        "gross_total",
        "taxable_value",
        "assessable_value",
        "exchange_value",
        "invoice_value",
        "on_road_value",
        "on_road_price",
        "ex_showroom_price",
    }
)
_COMMERCIAL_FIELD_MARKERS = frozenset(
    {
        "amount",
        "price",
        "cost",
        "charge",
        "charges",
        "tax",
        "discount",
        "fee",
        "fees",
        "premium",
        "payment",
        "balance",
        "finance",
        "loan",
        "emi",
        "margin",
        "rate",
        "subsidy",
        "scheme",
        "commercial",
        "invoice",
    }
)

# Broad Booking Form fields that remain intentionally outside the UC03
# proposal/review stream. customer_name is deliberately NOT listed here: it is
# retained as document evidence, but Audit Core source precedence prevents it
# from replacing the immutable PC-entered name or PAN/Aadhaar Legal Name.
UC03_BOOKING_NON_PUBLISHED_FIELDS: dict[str, frozenset[str]] = {
    "booking_form": frozenset(
        {
            "customer_address",
            "sales_person",
        }
    ),
}


def supported_uc03_booking_fields(document_type_key: str) -> frozenset[str]:
    """Return the reconciled non-commercial UC03 Booking allow-list."""
    return UC03_BOOKING_SUPPORTED_FIELDS.get(document_type_key.strip().lower(), frozenset())


def is_commercial_field(field_key: str) -> bool:
    """Return True when a canonical extraction key represents a commercial fact."""
    normalized = field_key.strip().lower()
    if normalized in _COMMERCIAL_EXACT_FIELDS:
        return True
    tokens = {token for token in normalized.replace("-", "_").split("_") if token}
    return bool(tokens & _COMMERCIAL_FIELD_MARKERS)


def filter_uc03_booking_result(
    document_type_key: str,
    extracted_fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter an extraction result to fields available to UC03 Booking/Audit.

    Non-commercial facts follow the reconciled document allow-list. Commercial
    facts are preserved across document types. Values are returned unchanged so
    confidence, raw value and source envelopes remain owned by DI.
    """
    allowed = supported_uc03_booking_fields(document_type_key)
    return {
        key: value
        for key, value in extracted_fields.items()
        if key in allowed or is_commercial_field(key)
    }
