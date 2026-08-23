from verigence.di.document_ai.uc03_booking_profile import (
    UC03_BOOKING_NON_PUBLISHED_FIELDS,
    filter_uc03_booking_result,
    supported_uc03_booking_fields,
)


def test_booking_form_publishes_only_reconciled_supported_fields() -> None:
    supported = supported_uc03_booking_fields("booking_form")
    assert supported == {
        "customer_name",
        "customer_phone",
        "vehicle_model",
        "vehicle_variant",
        "vehicle_color",
    }
    assert "ex_showroom_price" not in supported
    assert "booking_amount_paid" not in supported


def test_pan_card_supported_profile_includes_pan_identity() -> None:
    assert supported_uc03_booking_fields("pan_card") == {"pan_number", "pan_name"}


def test_filter_preserves_machine_envelope_without_publishing_provisional_fields() -> None:
    extraction = {
        "customer_name": {"value": "A Customer", "confidence": "high"},
        "vehicle_model": {"value": "Model X", "confidence": "medium"},
        "ex_showroom_price": {"value": 1000000, "confidence": "high"},
        "booking_amount_paid": {"value": 50000, "confidence": "high"},
    }
    filtered = filter_uc03_booking_result("booking_form", extraction)
    assert filtered == {
        "customer_name": extraction["customer_name"],
        "vehicle_model": extraction["vehicle_model"],
    }
    assert "ex_showroom_price" in UC03_BOOKING_NON_PUBLISHED_FIELDS["booking_form"]


def test_unknown_document_type_is_disabled_for_uc03_booking() -> None:
    assert supported_uc03_booking_fields("unknown") == frozenset()
    assert filter_uc03_booking_result("unknown", {"some": "value"}) == {}
