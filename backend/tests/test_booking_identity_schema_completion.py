from verigence.di.document_ai.schemas.aadhaar import AADHAAR_SCHEMA
from verigence.di.document_ai.schemas.booking_form import BOOKING_FORM_SCHEMA
from verigence.di.document_ai.schemas.pan_card import PAN_CARD_SCHEMA


def _field_map(schema):
    return {field.key: field for field in schema.fields}


def test_booking_form_v14_contains_verified_gap_fields_and_legacy_compatibility() -> None:
    assert BOOKING_FORM_SCHEMA.schema_version == "1.4"
    fields = _field_map(BOOKING_FORM_SCHEMA)
    expected = {
        "registration_by",
        "registration_type",
        "insurance_by",
        "exchange_applicable",
        "exchange_value",
        "registration_charges",
        "road_tax_amount",
        "road_tax_registration",
        "tcs_amount",
        "rsa_amount",
        "additional_warranty_amount",
        "discount_amount",
        "bonus_amount",
        "net_amount",
        "expected_delivery",
        "expected_delivery_date",
    }
    assert expected <= fields.keys()
    assert fields["exchange_applicable"].field_type == "boolean"
    assert fields["expected_delivery"].field_type == "string"
    assert fields["expected_delivery_date"].field_type == "date"
    assert fields["registration_charges"].field_type == "number"
    assert fields["road_tax_amount"].field_type == "number"
    assert fields["road_tax_registration"].field_type == "number"


def test_pan_relationship_fields_are_source_specific_and_explicit_only() -> None:
    assert PAN_CARD_SCHEMA.schema_version == "1.1"
    fields = _field_map(PAN_CARD_SCHEMA)
    assert {
        "pan_father_name",
        "pan_relationship_type",
        "pan_relationship_name",
    } <= fields.keys()
    assert fields["pan_relationship_type"].enum == ["W/O", "S/O", "D/O"]
    assert "relationship_type" not in fields
    assert "relationship_name" not in fields


def test_aadhaar_relationship_fields_are_source_specific_and_explicit_only() -> None:
    assert AADHAAR_SCHEMA.schema_version == "1.1"
    fields = _field_map(AADHAAR_SCHEMA)
    assert {
        "aadhaar_relationship_type",
        "aadhaar_relationship_name",
    } <= fields.keys()
    assert fields["aadhaar_relationship_type"].enum == ["W/O", "S/O", "D/O"]
    assert "relationship_type" not in fields
    assert "relationship_name" not in fields
