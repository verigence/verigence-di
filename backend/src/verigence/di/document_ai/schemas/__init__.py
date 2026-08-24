"""document_ai/schemas/__init__.py — Document Schema Registry.

Central registry: maps document_type_key → SchemaDefinition.

D20: Adding a new document type requires:
  1. Create document_ai/schemas/<new_type_key>.py with a SchemaDefinition
  2. Import and register it here in SCHEMA_REGISTRY
  3. Add a seed row to document_types in the next migration
  No other code changes required.

Every key in SCHEMA_REGISTRY must correspond to an existing row in
docintel.document_types (global seed or tenant-owned).
"""
from __future__ import annotations

from verigence.di.document_ai.schemas._fallback import FALLBACK_SCHEMA
from verigence.di.document_ai.schemas.aadhaar import AADHAAR_SCHEMA
from verigence.di.document_ai.schemas.bank_statement import BANK_STATEMENT_SCHEMA
from verigence.di.document_ai.schemas.base import SchemaDefinition
from verigence.di.document_ai.schemas.booking_form import BOOKING_FORM_SCHEMA
from verigence.di.document_ai.schemas.dealer_receipt import DEALER_RECEIPT_SCHEMA
from verigence.di.document_ai.schemas.delivery_order import DELIVERY_ORDER_SCHEMA
from verigence.di.document_ai.schemas.insurance_cover import INSURANCE_COVER_SCHEMA
from verigence.di.document_ai.schemas.pan_card import PAN_CARD_SCHEMA
from verigence.di.document_ai.schemas.upi_screenshot import UPI_SCREENSHOT_SCHEMA
from verigence.di.document_ai.schemas.upi_transaction import UPI_TRANSACTION_SCHEMA

__all__ = [
    "SCHEMA_REGISTRY",
    "FALLBACK_SCHEMA",
    "SchemaDefinition",
    "get_schema",
]

# Keys must match document_types.document_type_key in the DB exactly.
SCHEMA_REGISTRY: dict[str, SchemaDefinition] = {
    "booking_form":           BOOKING_FORM_SCHEMA,
    "dealer_receipt":         DEALER_RECEIPT_SCHEMA,
    "bank_statement_extract": BANK_STATEMENT_SCHEMA,
    "upi_transaction":        UPI_TRANSACTION_SCHEMA,
    "delivery_order_cover":   DELIVERY_ORDER_SCHEMA,
    "upi_screenshot":         UPI_SCREENSHOT_SCHEMA,
    "insurance_cover":        INSURANCE_COVER_SCHEMA,
    "pan_card":               PAN_CARD_SCHEMA,
    "aadhaar":                AADHAAR_SCHEMA,
}


def get_schema(document_type_key: str) -> SchemaDefinition:
    """Return the registered schema, or the generic fallback for unknown keys."""
    return SCHEMA_REGISTRY.get(document_type_key, FALLBACK_SCHEMA)
