"""Migration 0069: the Delivery Order reads the loan (delivery_order_cover schema
1.2), and a financier's loan email is a Delivery Order (product owner 2026-11-16)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from verigence.di.document_ai.schemas import get_schema
from verigence.di.document_ai.schemas.delivery_order import DELIVERY_ORDER_SCHEMA
from verigence.di.document_ai.type_definitions import GLOBAL_DOCUMENT_TYPE_DEFINITIONS


def _migration() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0069_do_loan_amount.py"
    spec = importlib.util.spec_from_file_location("mig_0069", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.no_docker
def test_the_snapshot_equals_the_schema() -> None:
    fields = _migration()._FIELDS
    assert [f[0] for f in fields] == [f.key for f in DELIVERY_ORDER_SCHEMA.fields]
    by_key = {f[0]: f for f in fields}
    for spec in DELIVERY_ORDER_SCHEMA.fields:
        assert by_key[spec.key][2] == spec.description, spec.key
        assert by_key[spec.key][3] is spec.required, spec.key
    assert get_schema("delivery_order_cover") is DELIVERY_ORDER_SCHEMA
    assert DELIVERY_ORDER_SCHEMA.schema_version == "1.2"


@pytest.mark.no_docker
def test_the_do_reads_the_loan_and_never_a_price() -> None:
    by_key = {f[0]: f for f in _migration()._FIELDS}
    assert by_key["loan_amount"][1] == "CURRENCY" and by_key["disbursement_date"][1] == "DATE"
    assert {"financier_name", "loan_amount", "disbursement_date", "disbursement_reference"} <= set(by_key)
    assert "never the vehicle price, down payment or margin money" in by_key["loan_amount"][2]
    assert not any(by_key[k][3] for k in ("financier_name", "loan_amount", "disbursement_date",
                                         "disbursement_reference"))


@pytest.mark.no_docker
def test_0069_follows_0068_reuses_the_publisher_and_writes_the_definitions() -> None:
    module = _migration()
    assert module.down_revision == "0068"
    publisher = module._publisher()
    assert publisher._TYPE_KEY == "delivery_order_cover" and publisher._FIELDS == module._FIELDS
    for key, definition in module._DEFINITIONS.items():
        assert GLOBAL_DOCUMENT_TYPE_DEFINITIONS[key] == definition


@pytest.mark.no_docker
def test_a_financiers_loan_email_is_a_delivery_order() -> None:
    defs = GLOBAL_DOCUMENT_TYPE_DEFINITIONS
    assert "financier's DO, disbursement advice or email" in defs["delivery_order_cover"]
    assert "bank_approval_letter" in defs["delivery_order_cover"]
    assert "financier's loan email is delivery_order_cover" in defs["supporting_document"]
