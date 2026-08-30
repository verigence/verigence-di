from verigence.di.document_ai.uc03_booking_profile import (
    UC03_BOOKING_NON_PUBLISHED_FIELDS,
    filter_uc03_booking_result,
    is_commercial_field,
    supported_uc03_booking_fields,
)


def test_booking_form_keeps_reconciled_non_commercial_profile() -> None:
    supported = supported_uc03_booking_fields("booking_form")
    assert supported == {
        "booking_date",
        "customer_phone",
        "vehicle_model",
        "vehicle_variant",
        "vehicle_color",
        "sku_code",
    }
    assert "customer_name" not in supported
    assert "customer_name" in UC03_BOOKING_NON_PUBLISHED_FIELDS["booking_form"]


def test_booking_form_publishes_commercial_and_sku_facts_without_name_authority() -> None:
    extraction = {
        "booking_date": {"value": "2026-08-24", "confidence": "high"},
        "customer_name": {"value": "A Customer", "confidence": "high"},
        "vehicle_model": {"value": "Model X", "confidence": "medium"},
        "vehicle_variant": {"value": "AX7 L", "confidence": "medium"},
        "sku_code": {"value": "XUV700-AX7L-R", "confidence": "high"},
        "ex_showroom_price": {"value": 1000000, "confidence": "high"},
        "insurance_amount": {"value": 50000, "confidence": "high"},
        "road_tax_registration": {"value": 80000, "confidence": "high"},
        "accessories_cost": {"value": 15000, "confidence": "medium"},
        "other_charges": {"value": 5000, "confidence": "medium"},
        "total_price": {"value": 1150000, "confidence": "high"},
        "booking_amount_paid": {"value": 50000, "confidence": "high"},
        "balance_amount": {"value": 1100000, "confidence": "high"},
        "mode_of_payment": {"value": "CARD", "confidence": "high"},
        "payment_reference_no": {"value": "PAY123", "confidence": "high"},
    }
    filtered = filter_uc03_booking_result("booking_form", extraction)
    assert "customer_name" not in filtered
    assert filtered["booking_date"] == extraction["booking_date"]
    assert filtered["vehicle_model"] == extraction["vehicle_model"]
    assert filtered["vehicle_variant"] == extraction["vehicle_variant"]
    assert filtered["sku_code"] == extraction["sku_code"]
    for field_key in (
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
    ):
        assert filtered[field_key] == extraction[field_key]


def test_commercial_facts_are_published_from_any_document_type() -> None:
    extraction = {
        "invoice_value": {"value": 1200000, "confidence": "high"},
        "dealer_discount_amount": {"value": 25000, "confidence": "medium"},
        "emi_amount": {"value": 22000, "confidence": "medium"},
        "customer_name": {"value": "Do not publish", "confidence": "high"},
        "unrelated_reference": {"value": "ABC", "confidence": "high"},
    }
    filtered = filter_uc03_booking_result("future_commercial_document", extraction)
    assert filtered == {
        "invoice_value": extraction["invoice_value"],
        "dealer_discount_amount": extraction["dealer_discount_amount"],
        "emi_amount": extraction["emi_amount"],
    }


def test_commercial_semantic_key_detection_is_broad_but_not_arbitrary() -> None:
    assert is_commercial_field("total_price")
    assert is_commercial_field("road_tax_registration")
    assert is_commercial_field("mode_of_payment")
    assert is_commercial_field("invoice_value")
    assert is_commercial_field("grand_total")
    assert not is_commercial_field("customer_address")
    assert not is_commercial_field("vehicle_model")
    assert not is_commercial_field("sku_code")


def test_pan_card_supported_profile_includes_pan_identity() -> None:
    assert supported_uc03_booking_fields("pan_card") == {"pan_number", "pan_name"}


def test_aadhaar_supported_profile_publishes_printed_name_only() -> None:
    assert supported_uc03_booking_fields("aadhaar") == {"aadhaar_name"}
    extraction = {
        "aadhaar_name": {"value": "A Customer", "confidence": "high"},
        "aadhaar_number": {"value": "XXXX XXXX 1234", "confidence": "high"},
        "aadhaar_address": {"value": "Address", "confidence": "medium"},
    }
    assert filter_uc03_booking_result("aadhaar", extraction) == {
        "aadhaar_name": extraction["aadhaar_name"],
    }


def test_unknown_document_type_keeps_only_commercial_facts() -> None:
    assert supported_uc03_booking_fields("unknown") == frozenset()
    extraction = {
        "some": "value",
        "net_total": {"value": 12345, "confidence": "medium"},
    }
    assert filter_uc03_booking_result("unknown", extraction) == {
        "net_total": extraction["net_total"]
    }
