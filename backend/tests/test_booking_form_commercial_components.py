from verigence.di.document_ai.schemas.booking_form import BOOKING_FORM_SCHEMA


EXPECTED_COMMERCIAL_COMPONENT_FIELDS = {
    "sales_discount_amount",
    "buffer_discount_amount",
    "exchange_discount_amount",
    "corporate_discount_amount",
    "loyalty_discount_amount",
    "inhouse_insurance_discount_amount",
    "mr_discount_amount",
    "oem_referral_discount_amount",
    "other_discount_amount",
    "free_accessory_discount_amount",
    "essential_kit_amount",
    "genuine_accessories_amount",
    "non_genuine_accessories_amount",
    "fastag_amount",
    "extended_warranty_amount",
    "green_tax_amount",
    "service_package_amount",
}


def test_booking_form_v15_requests_all_detailed_commercial_components() -> None:
    assert BOOKING_FORM_SCHEMA.schema_version == "1.5"
    field_keys = {field.key for field in BOOKING_FORM_SCHEMA.fields}
    assert EXPECTED_COMMERCIAL_COMPONENT_FIELDS <= field_keys


def test_booking_form_keeps_aggregate_fields_for_exact_document_totals() -> None:
    field_keys = {field.key for field in BOOKING_FORM_SCHEMA.fields}
    assert {"discount_amount", "accessories_cost", "other_charges"} <= field_keys


def test_component_fields_are_optional_and_never_required_inference() -> None:
    fields = {field.key: field for field in BOOKING_FORM_SCHEMA.fields}
    assert all(not fields[key].required for key in EXPECTED_COMMERCIAL_COMPONENT_FIELDS)
