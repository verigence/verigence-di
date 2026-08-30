"""UC03 Booking extraction publication boundary.

UC03 keeps a narrow allow-list for non-commercial Booking facts, but commercial
facts are an explicit cross-document exception: when DI has extracted a field
whose semantic key is commercial, that machine fact remains available to the
audit-consumption stream regardless of document type. Audit Core remains the
business-logic owner and decides how (or whether) the fact is used.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Canonical DI document type -> non-commercial fields allowed into the UC03
# Booking proposal stream. Commercial fields are handled separately below so a
# price/amount/payment fact is not silently lost just because it came from a
# different document type.
UC03_BOOKING_SUPPORTED_FIELDS: dict[str, frozenset[str]] = {
    "booking_form": frozenset(
        {
            "booking_date",
            "customer_phone",
            "vehicle_model",
            "vehicle_variant",
            "vehicle_color",
        }
    ),
    "pan_card": frozenset({"pan_number", "pan_name"}),
    "aadhaar": frozenset({"aadhaar_name"}),
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

# Explicitly document broad Booking Form fields that are still not published.
# Commercials are no longer listed here: extracted commercial facts must remain
# available to Audit Core, while identity/source-authority rules still apply.
UC03_BOOKING_NON_PUBLISHED_FIELDS: dict[str, frozenset[str]] = {
    "booking_form": frozenset(
        {
            "customer_name",
            "customer_email",
            "customer_address",
            "sales_person",
            "expected_delivery",
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
