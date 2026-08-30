"""Generalized invoice taxonomy used by V2 classification and extraction.

The business requirement keys remain stable. This module adds a semantic layer so
invoice purpose, legal nature, source system, and issuer role are not encoded as
one ever-growing document-type name.
"""
from __future__ import annotations

from collections.abc import Iterable

GENERIC_INVOICE_TYPE_KEY = "invoice_generic"

INVOICE_SPECIFIC_DOCUMENT_TYPE_KEYS = frozenset(
    {
        "wholesale_invoice",
        "customer_invoice_dms",
        "tax_invoice_tally",
        "accessory_invoice_dms",
        "accessory_invoice_tally",
        "ew_invoice",
        "rsa_invoice",
    }
)
INVOICE_DOCUMENT_TYPE_KEYS = INVOICE_SPECIFIC_DOCUMENT_TYPE_KEYS | {
    GENERIC_INVOICE_TYPE_KEY
}

INVOICE_CLASSIFICATION_HINTS: dict[str, str] = {
    "wholesale_invoice": (
        "invoice for wholesale/OEM-to-dealer vehicle supply; not the retail customer "
        "vehicle-sale invoice"
    ),
    "customer_invoice_dms": (
        "customer retail invoice for the actual vehicle sale from DMS; normally includes "
        "vehicle identity such as VIN/chassis/engine and customer-sale values"
    ),
    "tax_invoice_tally": (
        "GST/tax invoice for the actual vehicle sale from Tally/accounting output; normally "
        "shows taxable value and GST breakup"
    ),
    "accessory_invoice_dms": (
        "DMS invoice or challan whose primary goods are vehicle accessories/parts, not the "
        "vehicle itself"
    ),
    "accessory_invoice_tally": (
        "Tally/accounting invoice whose primary goods are vehicle accessories/parts, not "
        "the vehicle itself"
    ),
    "ew_invoice": "invoice specifically for extended-warranty coverage",
    "rsa_invoice": "invoice specifically for roadside-assistance (RSA) coverage/service",
    GENERIC_INVOICE_TYPE_KEY: (
        "fallback only: the document is clearly an invoice, but none of the more specific "
        "invoice candidates can be established reliably from the visible document"
    ),
}


def expand_v2_candidate_keys(candidate_keys: Iterable[str], *, phase: str) -> list[str]:
    """Deduplicate candidates and add one generic invoice fallback for Delivery only.

    The fallback is intentionally not a requirement slot. It prevents genuinely new or
    dealer-generated invoice formats from being discarded as UNKNOWN while preserving
    all existing UC03/UC04 requirement keys and matching behaviour.
    """
    expanded = list(dict.fromkeys(key.strip() for key in candidate_keys if key.strip()))
    if (
        phase == "DELIVERY"
        and GENERIC_INVOICE_TYPE_KEY not in expanded
        and any(key in INVOICE_SPECIFIC_DOCUMENT_TYPE_KEYS for key in expanded)
    ):
        expanded.append(GENERIC_INVOICE_TYPE_KEY)
    return expanded
