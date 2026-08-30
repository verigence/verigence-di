from verigence.di.document_ai.uc03_booking_profile import (
    UC03_BOOKING_NON_PUBLISHED_FIELDS,
    UC03_BOOKING_SUPPORTED_FIELDS,
    filter_uc03_booking_result,
    is_commercial_field,
    supported_uc03_booking_fields,
)


def test_uc03_has_no_application_publication_allow_list() -> None:
    assert UC03_BOOKING_SUPPORTED_FIELDS == {}
    assert UC03_BOOKING_NON_PUBLISHED_FIELDS == {}
    assert supported_uc03_booking_fields("booking_form") == frozenset()
    assert supported_uc03_booking_fields("aadhaar") == frozenset()
    assert supported_uc03_booking_fields("pan_card") == frozenset()


def test_booking_form_publishes_every_extracted_field_unchanged() -> None:
    extraction = {
        "dealer_name": {"value": "Dealer A", "confidence": "high"},
        "dealer_branch": {"value": "Branch 1", "confidence": "high"},
        "booking_reference_number": {"value": "BK123", "confidence": "high"},
        "booking_date": {"value": "2026-08-24", "confidence": "high"},
        "customer_name": {"value": "A Customer", "confidence": "high"},
        "customer_phone": {"value": "9876543210", "confidence": "high"},
        "customer_email": {"value": "a.customer@example.com", "confidence": "high"},
        "customer_address": {"value": "Booking Address", "confidence": "medium"},
        "vehicle_model": {"value": "Model X", "confidence": "medium"},
        "vehicle_variant": {"value": "AX7 L", "confidence": "medium"},
        "vehicle_color": {"value": "Red", "confidence": "high"},
        "sku_code": {"value": "XUV700-AX7L-R", "confidence": "high"},
        "sales_person": {"value": "Sales Person", "confidence": "high"},
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
    assert filter_uc03_booking_result("booking_form", extraction) == extraction


def test_aadhaar_publishes_number_address_gender_dob_and_relationship() -> None:
    extraction = {
        "aadhaar_name": {"value": "A Customer", "confidence": "high"},
        "aadhaar_number": {"value": "XXXX XXXX 1234", "confidence": "high"},
        "aadhaar_address": {"value": "Address", "confidence": "medium"},
        "date_of_birth": {"value": "1990-01-01", "confidence": "high"},
        "gender": {"value": "FEMALE", "confidence": "high"},
        "aadhaar_relationship_type": {"value": "W/O", "confidence": "high"},
        "aadhaar_relationship_name": {"value": "Related Person", "confidence": "high"},
    }
    assert filter_uc03_booking_result("aadhaar", extraction) == extraction


def test_pan_publishes_dob_and_all_extracted_identity_fields() -> None:
    extraction = {
        "pan_number": {"value": "ABCDE1234F", "confidence": "high"},
        "pan_name": {"value": "A Customer", "confidence": "high"},
        "pan_father_name": {"value": "Parent Name", "confidence": "high"},
        "pan_relationship_type": {"value": "S/O", "confidence": "high"},
        "pan_relationship_name": {"value": "Parent Name", "confidence": "high"},
        "date_of_birth": {"value": "1990-01-01", "confidence": "high"},
    }
    assert filter_uc03_booking_result("pan_card", extraction) == extraction


def test_unknown_document_type_is_not_filtered() -> None:
    extraction = {
        "some": {"value": "value", "confidence": "high"},
        "net_total": {"value": 12345, "confidence": "medium"},
    }
    assert filter_uc03_booking_result("unknown", extraction) == extraction


def test_commercial_semantic_detection_remains_available_but_does_not_gate_publication() -> None:
    assert is_commercial_field("total_price")
    assert is_commercial_field("road_tax_registration")
    assert is_commercial_field("mode_of_payment")
    assert is_commercial_field("invoice_value")
    assert not is_commercial_field("customer_address")
    assert not is_commercial_field("vehicle_model")
