from verigence.di.document_ai.uc03_booking_profile import (
    UC03_BOOKING_NON_PUBLISHED_FIELDS,
    filter_uc03_booking_result,
    supported_uc03_booking_fields,
)


def test_booking_docket_publishes_part1_supported_fields() -> None:
    supported = supported_uc03_booking_fields("booking_docket")
    assert supported == {
        "customer_phone",
        "vehicle_model",
        "vehicle_variant",
        "vehicle_color",
        "booking_reference_number",
        "booking_date",
    }
    assert "customer_name" not in supported
    assert "booking_amount_paid" not in supported


def test_booking_form_alias_has_same_part1_boundary() -> None:
    assert supported_uc03_booking_fields("booking_form") == supported_uc03_booking_fields(
        "booking_docket"
    )


def test_pan_card_supported_profile_includes_pan_identity() -> None:
    assert supported_uc03_booking_fields("pan_card") == {"pan_number", "pan_name"}


def test_aadhaar_publishes_name_but_not_identifier() -> None:
    assert supported_uc03_booking_fields("aadhaar") == {"aadhaar_name"}


def test_dealer_receipt_publishes_distinct_receipt_and_transaction_references() -> None:
    assert supported_uc03_booking_fields("dealer_receipt") == {
        "receipt_number",
        "receipt_date",
        "amount_paid",
        "payment_mode",
        "payment_reference_no",
    }


def test_filter_preserves_machine_envelope_without_publishing_docket_customer_name() -> None:
    extraction = {
        "customer_name": {"value": "A Customer", "confidence": "high"},
        "vehicle_model": {"value": "Model X", "confidence": "medium"},
        "booking_date": {"value": "2026-08-25", "confidence": "high"},
        "booking_amount_paid": {"value": 50000, "confidence": "high"},
    }
    filtered = filter_uc03_booking_result("booking_docket", extraction)
    assert filtered == {
        "vehicle_model": extraction["vehicle_model"],
        "booking_date": extraction["booking_date"],
    }
    assert "customer_name" in UC03_BOOKING_NON_PUBLISHED_FIELDS["booking_docket"]


def test_unknown_document_type_is_disabled_for_uc03_booking() -> None:
    assert supported_uc03_booking_fields("unknown") == frozenset()
    assert filter_uc03_booking_result("unknown", {"some": "value"}) == {}
