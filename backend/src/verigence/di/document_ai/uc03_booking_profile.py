"""UC03 Booking extraction publication boundary.

Part 1 is evidence-led: Booking Docket, PAN-or-Aadhaar KYC and one-or-more
Booking Payment Receipts. DI publishes source facts only. Audit Core owns human
accept/correct, Product Master reconciliation, payment persistence and Flags.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UC03_BOOKING_SUPPORTED_FIELDS: dict[str, frozenset[str]] = {
    "booking_form": frozenset(
        {
            "customer_phone",
            "vehicle_model",
            "vehicle_variant",
            "vehicle_color",
            "booking_reference_number",
            "booking_date",
        }
    ),
    "booking_docket": frozenset(
        {
            "customer_phone",
            "vehicle_model",
            "vehicle_variant",
            "vehicle_color",
            "booking_reference_number",
            "booking_date",
        }
    ),
    "pan_card": frozenset({"pan_number", "pan_name"}),
    "pan": frozenset({"pan_number", "pan_name"}),
    # Aadhaar number is deliberately not published into the UC03 Booking stream.
    "aadhaar": frozenset({"aadhaar_name"}),
    "dealer_receipt": frozenset(
        {
            "receipt_number",
            "receipt_date",
            "amount_paid",
            "payment_mode",
            "payment_reference_no",
        }
    ),
}

# Explicitly document broad Booking Form fields that Part 1 does not publish.
# customer_name is retained as a document fact but KYC is the identity source for
# legal-name review. Payment facts come from each dealer_receipt, not the Docket.
UC03_BOOKING_NON_PUBLISHED_FIELDS: dict[str, frozenset[str]] = {
    "booking_form": frozenset(
        {
            "customer_name",
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
    "booking_docket": frozenset(
        {
            "customer_name",
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
    """Return the owner-approved UC03 Booking publication allow-list."""
    return UC03_BOOKING_SUPPORTED_FIELDS.get(document_type_key.strip().lower(), frozenset())


def filter_uc03_booking_result(
    document_type_key: str,
    extracted_fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only Part-1 facts allowed into the UC03 Booking proposal stream."""
    allowed = supported_uc03_booking_fields(document_type_key)
    return {key: value for key, value in extracted_fields.items() if key in allowed}
