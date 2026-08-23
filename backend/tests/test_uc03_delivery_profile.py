from verigence.di.document_ai.uc03_delivery_profile import (
    filter_uc03_delivery_result,
    supported_uc03_delivery_fields,
)


def test_payment_receipt_publishes_only_reconciled_supported_fields() -> None:
    machine = {
        "amount": {"value": "50000", "confidence": 0.99},
        "receipt_date": {"value": "2026-08-23", "confidence": 0.97},
        "utr_no": {"value": "UTR123", "confidence": 0.95},
        "payer_name": {"value": "Example", "confidence": 0.92},
    }
    result = filter_uc03_delivery_result("payment_receipt", machine)
    assert set(result) == {"amount", "receipt_date", "utr_no"}
    assert result["amount"] is machine["amount"]


def test_delivery_order_publishes_amount_and_bank_only() -> None:
    result = filter_uc03_delivery_result(
        "delivery_order",
        {
            "amount": {"value": "700000"},
            "bank_name": {"value": "Example Bank"},
            "vin": {"value": "VIN-SHOULD-NOT-PUBLISH"},
        },
    )
    assert set(result) == {"amount", "bank_name"}


def test_provisional_vin_and_aadhaar_profiles_publish_nothing() -> None:
    assert supported_uc03_delivery_fields("tax_invoice_dms") == frozenset()
    assert supported_uc03_delivery_fields("customer_id") == frozenset()
    assert supported_uc03_delivery_fields("aadhaar") == frozenset()
    assert filter_uc03_delivery_result(
        "tax_invoice_dms", {"vin": {"value": "12345678901234567"}}
    ) == {}


def test_unknown_document_type_is_closed_by_default() -> None:
    assert supported_uc03_delivery_fields("future_delivery_doc") == frozenset()
    assert filter_uc03_delivery_result(
        "future_delivery_doc", {"amount": {"value": "1"}}
    ) == {}
