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
from verigence.di.document_ai.schemas.bank_approval_letter import BANK_APPROVAL_LETTER_SCHEMA
from verigence.di.document_ai.schemas.bank_statement import BANK_STATEMENT_SCHEMA
from verigence.di.document_ai.schemas.base import SchemaDefinition
from verigence.di.document_ai.schemas.booking_form import BOOKING_FORM_SCHEMA
from verigence.di.document_ai.schemas.corporate_id import CORPORATE_ID_SCHEMA
from verigence.di.document_ai.schemas.customer_ledger import CUSTOMER_LEDGER_SCHEMA
from verigence.di.document_ai.schemas.dealer_receipt import DEALER_RECEIPT_SCHEMA
from verigence.di.document_ai.schemas.debit_note import DEBIT_NOTE_SCHEMA
from verigence.di.document_ai.schemas.delivery_order import DELIVERY_ORDER_SCHEMA
from verigence.di.document_ai.schemas.gate_pass import GATE_PASS_SCHEMA
from verigence.di.document_ai.schemas.gst_certificate import GST_CERTIFICATE_SCHEMA
from verigence.di.document_ai.schemas.insurance_cover import INSURANCE_COVER_SCHEMA
from verigence.di.document_ai.schemas.invoice import (
    ACCESSORY_INVOICE_DMS_SCHEMA,
    ACCESSORY_INVOICE_TALLY_SCHEMA,
    CUSTOMER_INVOICE_DMS_SCHEMA,
    EW_INVOICE_SCHEMA,
    GENERIC_INVOICE_SCHEMA,
    RSA_INVOICE_SCHEMA,
    TAX_INVOICE_TALLY_SCHEMA,
    WHOLESALE_INVOICE_SCHEMA,
)
from verigence.di.document_ai.schemas.pan_card import PAN_CARD_SCHEMA
from verigence.di.document_ai.schemas.purchase_order import PURCHASE_ORDER_SCHEMA
from verigence.di.document_ai.schemas.rto_challan import RTO_CHALLAN_SCHEMA
from verigence.di.document_ai.schemas.upi_screenshot import UPI_SCREENSHOT_SCHEMA
from verigence.di.document_ai.schemas.upi_transaction import UPI_TRANSACTION_SCHEMA
from verigence.di.document_ai.schemas.valuation_report import VALUATION_REPORT_SCHEMA

__all__ = [
    "SCHEMA_REGISTRY",
    "FALLBACK_SCHEMA",
    "SchemaDefinition",
    "get_schema",
]

# Keys must match document_types.document_type_key in the DB exactly.
SCHEMA_REGISTRY: dict[str, SchemaDefinition] = {
    "booking_form": BOOKING_FORM_SCHEMA,
    "dealer_receipt": DEALER_RECEIPT_SCHEMA,
    "bank_statement_extract": BANK_STATEMENT_SCHEMA,
    "upi_transaction": UPI_TRANSACTION_SCHEMA,
    "delivery_order_cover": DELIVERY_ORDER_SCHEMA,
    "upi_screenshot": UPI_SCREENSHOT_SCHEMA,
    "insurance_cover": INSURANCE_COVER_SCHEMA,
    "pan_card": PAN_CARD_SCHEMA,
    "aadhaar": AADHAAR_SCHEMA,
    "gate_pass": GATE_PASS_SCHEMA,
    # Schema V2 Wave 1. The DB migration/profile publication is deliberately
    # separate so registry code can be reviewed and tested before activation.
    "gst_certificate": GST_CERTIFICATE_SCHEMA,
    "corporate_id": CORPORATE_ID_SCHEMA,
    "bank_approval_letter": BANK_APPROVAL_LETTER_SCHEMA,
    "valuation_report": VALUATION_REPORT_SCHEMA,
    "customer_ledger": CUSTOMER_LEDGER_SCHEMA,
    "debit_note": DEBIT_NOTE_SCHEMA,
    "purchase_order": PURCHASE_ORDER_SCHEMA,
    # Generalized invoice intelligence. Existing business requirement keys remain
    # stable; all are backed by one common invoice evidence superset with only
    # genuinely service-specific additions.
    "wholesale_invoice": WHOLESALE_INVOICE_SCHEMA,
    "customer_invoice_dms": CUSTOMER_INVOICE_DMS_SCHEMA,
    "tax_invoice_tally": TAX_INVOICE_TALLY_SCHEMA,
    "accessory_invoice_dms": ACCESSORY_INVOICE_DMS_SCHEMA,
    "accessory_invoice_tally": ACCESSORY_INVOICE_TALLY_SCHEMA,
    "ew_invoice": EW_INVOICE_SCHEMA,
    "rsa_invoice": RSA_INVOICE_SCHEMA,
    "invoice_generic": GENERIC_INVOICE_SCHEMA,
    "rto_challan": RTO_CHALLAN_SCHEMA,
}


def get_schema(document_type_key: str) -> SchemaDefinition:
    """Return the registered schema, or the generic fallback for unknown keys."""
    return SCHEMA_REGISTRY.get(document_type_key, FALLBACK_SCHEMA)
