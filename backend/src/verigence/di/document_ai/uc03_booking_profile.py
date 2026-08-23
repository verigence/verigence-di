"""UC03 Booking extraction publication boundary.

This module is intentionally narrower than the general DI document schemas. UC03
may consume only source mappings reconciled as SUPPORTED in
UC03_EXTRACTION_SOURCE_MAPPING_v0.1.md. PROVISIONAL and TBD fields remain
outside the published UC03 profile until business/DI reconciliation changes the
mapping artifact.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Canonical DI document type -> fields allowed into the UC03 Booking proposal
# stream. The Audit Core remains authoritative for accept/correct and typed-domain
# persistence; DI preserves the machine value, confidence and source.
UC03_BOOKING_SUPPORTED_FIELDS: dict[str, frozenset[str]] = {
    "booking_form": frozenset(
        {
            "customer_name",
            "customer_phone",
            "vehicle_model",
            "vehicle_variant",
            "vehicle_color",
        }
    ),
    "pan_card": frozenset({"pan_number", "pan_name"}),
}

# Explicitly document fields present in the broad Booking Form schema that UC03
# must not publish merely because DI can technically extract them.
UC03_BOOKING_NON_PUBLISHED_FIELDS: dict[str, frozenset[str]] = {
    "booking_form": frozenset(
        {
            "customer_email",
            "customer_address",
            "sales_person",
            "ex_showroom_price",
            "insurance_amount",
            "road_tax_registration",
            "accessories_cost",
            "other_charges",
            "total_price",
            "booking_amount_paid",
            "balance_amount",
            "mode_of_payment",
            "payment_reference_no",
            "expected_delivery",
        }
    ),
}


def supported_uc03_booking_fields(document_type_key: str) -> frozenset[str]:
    """Return the reconciled UC03 Booking allow-list for a DI document type."""
    return UC03_BOOKING_SUPPORTED_FIELDS.get(document_type_key.strip().lower(), frozenset())


def filter_uc03_booking_result(
    document_type_key: str,
    extracted_fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter an extraction result to fields allowed in the UC03 Booking profile.

    Values are returned unchanged so the caller retains the original machine
    confidence/value envelope. This function only applies the publication
    boundary; it never changes confidence, normalizes a human correction, or
    chooses source precedence.
    """
    allowed = supported_uc03_booking_fields(document_type_key)
    return {key: value for key, value in extracted_fields.items() if key in allowed}
