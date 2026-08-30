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
        "registration_by",
        "registration_type",
        "insurance_by",
        "exchange_applicable",
        "expected_delivery",
        "expected_delivery_date",
    }
    assert "customer_name" not in supported
    assert "customer_name" in UC03_BOOKING_NON_PUBLISHED_FIELDS["booking_form"]


def test_booking_form_publishes_completed_commercial_fields_without_name_authority() -> None:
    extraction = {
        "booking_date": {"value": "2026-08-24", "confidence": "high"},
        "customer_name": {"value": "A Customer", "confidence": "high"},
        "vehicle_model": {"value": "Model X", "confidence": "medium"},
        "vehicle_variant": {"value": "AX7 L", "confidence": "medium"},
        "sku_code": {"value": "XUV700-AX7L-R", "confidence": "high"},
        "registration_by": {"value": "Dealer", "confidence": "high"},
        "registration_type": {"value": "INDIVIDUAL", "confidence": "high"},
        "insurance_by": {"value": "Dealer", "confidence": "high"},
        "exchange_applicable": {"value": True, "confidence": "high"},
        "expected_delivery": {"value": "2 weeks", "confidence": "medium"},
        "expected_delivery_date": {"value": "2026-09-10", "confidence": "high"},
        "exchange_value": {"value": 300000, "confidence": "medium"},
        "ex_showroom_price": {"value": 1000000, "confidence": "high"},
        "insurance_amount": {"value": 50000, "confidence": "high"},
        "registration_charges": {"value": 20000, "confidence": "high"},
        "road_tax_amount": {"value": 60000, "confidence": "high"},
        "road_tax_registration": {"value": 80000, "confidence": "high"},
        "tcs_amount": {"value": 10000, "confidence": "high"},
        "rsa_amount": {"value": 2500, "confidence": "high"},
        "additional_warranty_amount": {"value": 12000, "confidence": "high"},
        "accessories_cost": {"value": 15000, "confidence": "medium"},
        "other_charges": {"value": 5000, "confidence": "medium"},
        "discount_amount": {"value": 25000, "confidence": "high"},
        "bonus_amount": {"value": 10000, "confidence": "medium"},
        "total_price": {"value": 1150000, "confidence": "high"},
        "net_amount": {"value": 1115000, "confidence": "high"},
        "booking_amount_paid": {"value": 50000, "confidence": "high"},
        "balance_amount": {"value": 1065000, "confidence": "high"},
        "mode_of_payment": {"value": "CARD", "confidence": "high"},
        "payment_reference_no": {"value": "PAY123", "confidence": "high"},
    }
    filtered = filter_uc03_booking_result("booking_form", extraction)
    assert "customer_name" not in filtered
    for field_key, value in extraction.items():
        if field_key != "customer_name":
            assert filtered[field_key] == value


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
    assert is_commercial_field("registration_charges")
    assert is_commercial_field("road_tax_amount")
    assert is_commercial_field("tcs_amount")
    assert is_commercial_field("rsa_amount")
    assert is_commercial_field("additional_warranty_amount")
    assert is_commercial_field("discount_amount")
    assert is_commercial_field("bonus_amount")
    assert is_commercial_field("net_amount")
    assert is_commercial_field("exchange_value")
    assert is_commercial_field("mode_of_payment")
    assert is_commercial_field("invoice_value")
    assert is_commercial_field("grand_total")
    assert not is_commercial_field("customer_address")
    assert not is_commercial_field("vehicle_model")
    assert not is_commercial_field("sku_code")
    assert not is_commercial_field("expected_delivery_date")


def test_pan_card_supported_profile_keeps_relationship_evidence_source_specific() -> None:
    assert supported_uc03_booking_fields("pan_card") == {
        "pan_number",
        "pan_name",
        "pan_father_name",
        "pan_relationship_type",
        "pan_relationship_name",
    }


def test_aadhaar_supported_profile_keeps_relationship_evidence_source_specific() -> None:
    assert supported_uc03_booking_fields("aadhaar") == {
        "aadhaar_name",
        "aadhaar_relationship_type",
        "aadhaar_relationship_name",
    }
    extraction = {
        "aadhaar_name": {"value": "A Customer", "confidence": "high"},
        "aadhaar_number": {"value": "XXXX XXXX 1234", "confidence": "high"},
        "aadhaar_address": {"value": "Address", "confidence": "medium"},
        "aadhaar_relationship_type": {"value": "W/O", "confidence": "high"},
        "aadhaar_relationship_name": {"value": "Related Person", "confidence": "high"},
    }
    assert filter_uc03_booking_result("aadhaar", extraction) == {
        "aadhaar_name": extraction["aadhaar_name"],
        "aadhaar_relationship_type": extraction["aadhaar_relationship_type"],
        "aadhaar_relationship_name": extraction["aadhaar_relationship_name"],
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
