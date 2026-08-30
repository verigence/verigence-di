"""UC03 Booking extraction publication boundary.

UC03 does not filter extracted fields by an application allow-list. If a field was
produced by the active DI extraction schema, the field is published unchanged to
the Booking/Audit consumption stream. Audit Core owns review, source precedence and
business projection; DI must not silently suppress an extracted fact.

The legacy helper names below are retained only for compatibility with older
callers. They no longer participate in publication decisions.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Legacy compatibility symbols. UC03 no longer has a supported/non-published field
# list: schema output itself defines the publication surface.
UC03_BOOKING_SUPPORTED_FIELDS: dict[str, frozenset[str]] = {}
UC03_BOOKING_NON_PUBLISHED_FIELDS: dict[str, frozenset[str]] = {}

# Retained for callers/tests that classify commercial semantics. Publication no
# longer depends on this classification.
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


def supported_uc03_booking_fields(document_type_key: str) -> frozenset[str]:
    """Legacy compatibility helper; UC03 publication is no longer allow-listed."""
    del document_type_key
    return frozenset()


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
    """Publish every field returned by the active DI extraction schema unchanged.

    There is deliberately no UC03 application allow-list and no non-published set.
    Review/source-of-truth/business ownership decisions belong to Audit Core.
    """
    del document_type_key
    return dict(extracted_fields)
