from __future__ import annotations

from verigence.di.document_ai.invoice_taxonomy import (
    GENERIC_INVOICE_TYPE_KEY,
    INVOICE_DOCUMENT_TYPE_KEYS,
)
from verigence.di.document_ai.schemas import get_schema
from verigence.di.document_ai.schemas.booking_form import BOOKING_FORM_SCHEMA
from verigence.di.document_ai.v2_classifier import _prompt, _with_invoice_fallback


def _field_map(document_type_key: str) -> dict[str, object]:
    schema = get_schema(document_type_key)
    return {field.key: field for field in schema.fields}


def test_existing_non_invoice_schema_is_unchanged() -> None:
    assert get_schema("booking_form") is BOOKING_FORM_SCHEMA


def test_all_invoice_document_keys_have_matching_registered_schema() -> None:
    for document_type_key in INVOICE_DOCUMENT_TYPE_KEYS:
        schema = get_schema(document_type_key)
        assert schema.document_type_key == document_type_key
        assert schema.display_name != "Generic Document"
        assert "invoice_purpose" in _field_map(document_type_key)
        assert "line_items" in _field_map(document_type_key)


def test_every_invoice_has_common_vehicle_and_audit_evidence_superset() -> None:
    expected = {
        "invoice_heading_as_printed",
        "invoice_number",
        "invoice_date",
        "buyer_gstin",
        "buyer_gstin_status",
        "financed_by",
        "grand_total_amount",
        "vehicle_description_raw",
        "sku_code",
        "model_name_raw",
        "variant_raw",
        "vin_number",
        "chassis_number",
        "engine_number",
        "key_number",
        "vehicle_color",
        "vehicle_registration_number",
        "vehicle_hsn_code",
    }
    for document_type_key in INVOICE_DOCUMENT_TYPE_KEYS:
        assert expected <= _field_map(document_type_key).keys()


def test_generic_invoice_preserves_vehicle_fields_without_subtype_reclassification() -> None:
    fields = _field_map(GENERIC_INVOICE_TYPE_KEY)
    for key in (
        "model_name_raw",
        "variant_raw",
        "vin_number",
        "chassis_number",
        "engine_number",
        "key_number",
        "vehicle_color",
        "vehicle_hsn_code",
    ):
        assert key in fields


def test_vehicle_invoice_has_vehicle_identity_but_no_master_inference_field() -> None:
    fields = _field_map("customer_invoice_dms")
    assert "vehicle_description_raw" in fields
    assert "sku_code" in fields
    assert "vin_number" in fields
    assert "chassis_number" in fields
    assert "engine_number" in fields
    assert "ex_showroom_price" not in fields


def test_buyer_gstin_status_is_explicit_and_does_not_replace_gstin() -> None:
    fields = _field_map(GENERIC_INVOICE_TYPE_KEY)
    assert fields["buyer_gstin_status"].enum == [
        "REGISTERED",
        "UNREGISTERED",
        "NOT_STATED",
        "UNKNOWN",
    ]
    assert "null when the document says unregistered" in fields["buyer_gstin"].description


def test_invoice_amount_fields_preserve_decimal_source_precision() -> None:
    fields = _field_map("tax_invoice_tally")
    for key in (
        "gross_amount_before_discount",
        "invoice_discount_amount",
        "taxable_amount",
        "cgst_amount",
        "sgst_amount",
        "round_off_amount",
        "grand_total_amount",
    ):
        field = fields[key]
        assert field.field_type == "number"
        assert field.normalization is None


def test_classifier_adds_one_generic_invoice_fallback_only_for_invoice_candidates() -> None:
    invoice_candidates = [
        ("customer_invoice_dms", "Customer Invoice (DMS)"),
        ("tax_invoice_tally", "Tax Invoice (Tally)"),
    ]
    expanded = _with_invoice_fallback(invoice_candidates)
    assert expanded[:-1] == invoice_candidates
    assert expanded[-1] == (GENERIC_INVOICE_TYPE_KEY, "Other Invoice")
    assert _with_invoice_fallback(expanded) == expanded

    non_invoice = [("pan_card", "PAN Card")]
    assert _with_invoice_fallback(non_invoice) == non_invoice


def test_classifier_prompt_differentiates_invoice_purpose_in_same_call() -> None:
    prompt = _prompt(
        [
            ("customer_invoice_dms", "Customer Invoice (DMS)"),
            ("accessory_invoice_tally", "Accessory Invoice (Tally)"),
            (GENERIC_INVOICE_TYPE_KEY, "Other Invoice"),
        ]
    )
    assert "goods/service being invoiced" in prompt
    assert "invoice_generic" in prompt
    assert "separate invoice subtype pass" in prompt
