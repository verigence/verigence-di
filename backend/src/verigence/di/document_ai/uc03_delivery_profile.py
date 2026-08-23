"""UC03 Delivery extraction publication boundary.

Only mappings classified SUPPORTED in UC03_EXTRACTION_SOURCE_MAPPING_v0.1.md
are eligible for the C2 Delivery proposal stream. PROVISIONAL/TBD mappings,
including VIN/chassis source precedence and Aadhaar extraction, remain excluded.
DI publishes source facts and provenance; Audit Core owns business reconciliation.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UC03_DELIVERY_SUPPORTED_FIELDS: dict[str, frozenset[str]] = {
    "payment_receipt": frozenset({"amount", "receipt_date", "utr_no"}),
    "payment_receipts_tally": frozenset({"amount", "receipt_date", "utr_no"}),
    "bank_transfer_receipt": frozenset({"amount", "receipt_date", "utr_no"}),
    "delivery_order": frozenset({"amount", "bank_name"}),
    "bank_approval_letter": frozenset({"amount", "bank_name"}),
}

# These fields may exist in broad document schemas, but the UC03 source mapping
# does not authorize them for the C2 publication boundary yet.
UC03_DELIVERY_NON_PUBLISHED_FIELDS: dict[str, frozenset[str]] = {
    "tax_invoice_dms": frozenset({"vin", "chassis_number"}),
    "customer_id": frozenset({"aadhaar_number"}),
    "aadhaar": frozenset({"aadhaar_number"}),
}


def supported_uc03_delivery_fields(document_type_key: str) -> frozenset[str]:
    """Return the reconciled C2 allow-list for a DI document type."""
    return UC03_DELIVERY_SUPPORTED_FIELDS.get(
        document_type_key.strip().lower(), frozenset()
    )


def filter_uc03_delivery_result(
    document_type_key: str,
    extracted_fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Filter machine output without changing the value/provenance envelope."""
    allowed = supported_uc03_delivery_fields(document_type_key)
    return {key: value for key, value in extracted_fields.items() if key in allowed}
