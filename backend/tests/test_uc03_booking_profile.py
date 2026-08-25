from verigence.di.document_ai.uc03_booking_profile import (
    UC03_BOOKING_NON_PUBLISHED_FIELDS,
    filter_uc03_booking_result,
    supported_uc03_booking_fields,
)


def test_booking_form_publishes_actual_booking_date_but_not_identity_name() -> None:
    supported = supported_uc03_booking_fields("booking_form")
    assert supported == {
        "booking_date",
        "customer_phone",
        "vehicle_model",
        "vehicle_variant",
        "vehicle_color",
    }
    assert "customer_name" not in supported
    assert "customer_name" in UC03_BOOKING_NON_PUBLISHED_FIELDS["booking_form"]
    assert "ex_showroom_price" not in supported
    assert "booking_amount_paid" not in supported


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


def test_filter_preserves_machine_envelope_and_keeps_booking_name_non_authoritative() -> None:
    extraction = {
        "booking_date": {"value": "2026-08-24", "confidence": "high"},
        "customer_name": {"value": "A Customer", "confidence": "high"},
        "vehicle_model": {"value": "Model X", "confidence": "medium"},
        "ex_showroom_price": {"value": 1000000, "confidence": "high"},
        "booking_amount_paid": {"value": 50000, "confidence": "high"},
    }
    filtered = filter_uc03_booking_result("booking_form", extraction)
    assert filtered == {
        "booking_date": extraction["booking_date"],
        "vehicle_model": extraction["vehicle_model"],
    }
    assert "customer_name" in UC03_BOOKING_NON_PUBLISHED_FIELDS["booking_form"]
    assert "ex_showroom_price" in UC03_BOOKING_NON_PUBLISHED_FIELDS["booking_form"]


def test_unknown_document_type_is_disabled_for_uc03_booking() -> None:
    assert supported_uc03_booking_fields("unknown") == frozenset()
    assert filter_uc03_booking_result("unknown", {"some": "value"}) == {}
