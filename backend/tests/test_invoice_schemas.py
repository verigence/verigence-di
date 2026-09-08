"""tests/test_invoice_schemas.py — schema registry sanity for the invoice domain.

All tests are no_docker — pure Python, no DB.

Covers the three document types added in migration 0009:
  invoice                   (superset: tax / retail / accessories / EW)
  dealer_accounts_statement
  rto_tax_receipt
"""
from __future__ import annotations

import pytest

from verigence.di.document_ai.schemas import SCHEMA_REGISTRY, get_schema
from verigence.di.document_ai.schemas.base import SchemaDefinition

pytestmark = pytest.mark.no_docker

_NEW_KEYS = ("invoice", "dealer_accounts_statement", "rto_tax_receipt")
_FIELD_TYPES = {"string", "number", "date", "datetime", "boolean", "array"}


@pytest.mark.parametrize("key", _NEW_KEYS)
def test_schema_registered_and_resolvable(key: str) -> None:
    assert key in SCHEMA_REGISTRY
    schema = get_schema(key)
    assert isinstance(schema, SchemaDefinition)
    assert schema.document_type_key == key
    assert schema.display_name
    assert schema.schema_version
    assert schema.system_prompt


@pytest.mark.parametrize("key", _NEW_KEYS)
def test_field_keys_unique_and_typed(key: str) -> None:
    schema = SCHEMA_REGISTRY[key]
    keys = [f.key for f in schema.fields]
    assert len(keys) == len(set(keys)), f"duplicate field keys in {key}"
    for field in schema.fields:
        assert field.field_type in _FIELD_TYPES, f"{key}.{field.key}: {field.field_type}"
        if field.enum:
            assert field.field_type == "string"


def test_invoice_is_a_superset() -> None:
    schema = SCHEMA_REGISTRY["invoice"]
    keys = {f.key for f in schema.fields}
    # classifier + identity
    assert {"invoice_kind", "invoice_number", "invoice_date", "invoice_total_amount"} <= keys
    # vehicle tax / retail invoice pricing
    assert {"ex_showroom_price", "discount_amount", "oem_discount_amount", "taxable_amount"} <= keys
    # GST break-up
    assert {"cgst_amount", "sgst_amount", "igst_amount", "total_tax_amount", "tcs_amount"} <= keys
    # accessories invoice
    assert "line_items" in keys
    # extended-warranty invoice
    assert {"ew_plan_name", "ew_coverage_years", "ew_provider_name"} <= keys

    invoice_kind = next(f for f in schema.fields if f.key == "invoice_kind")
    assert invoice_kind.required
    assert invoice_kind.enum is not None
    assert {"tax_invoice", "retail_invoice", "accessories_invoice",
            "extended_warranty_invoice"} <= set(invoice_kind.enum)


def test_accounts_statement_carries_offer_lines() -> None:
    keys = {f.key for f in SCHEMA_REGISTRY["dealer_accounts_statement"].fields}
    assert {"ex_showroom_price", "consumer_offer_amount", "corporate_offer_amount",
            "exchange_claim_amount", "cash_discount_amount",
            "net_receivable_amount"} <= keys
    assert "payment_lines" in keys


def test_rto_receipt_carries_fee_lines() -> None:
    keys = {f.key for f in SCHEMA_REGISTRY["rto_tax_receipt"].fields}
    assert {"receipt_number", "fee_lines", "rto_total_amount", "chassis_number"} <= keys


@pytest.mark.parametrize("key", _NEW_KEYS)
def test_required_fields_present(key: str) -> None:
    required = {f.key for f in SCHEMA_REGISTRY[key].fields if f.required}
    assert required, f"{key} declares no required fields"
    assert "invoice_number" in required or "receipt_number" in required or key == "dealer_accounts_statement"
