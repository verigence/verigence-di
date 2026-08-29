from __future__ import annotations

from verigence.di.document_ai.schemas import get_schema
from verigence.di.rules.normalizers import get_normalizer
from verigence.di.rules.runner import _run_normalizers
from verigence.di.rules.schema_v2_validators import get_schema_v2_validator


def test_structured_literal_parser_accepts_json_array() -> None:
    fn = get_normalizer("di.norm.structured_literal_parse")
    assert fn is not None

    result = fn('[{"head":"Dent","amount":1250.0,"is_handwritten":false}]', {"container": "array"})

    assert result.ok is True
    assert result.normalized_value == [
        {"head": "Dent", "amount": 1250.0, "is_handwritten": False}
    ]


def test_structured_literal_parser_accepts_legacy_python_repr() -> None:
    fn = get_normalizer("di.norm.structured_literal_parse")
    assert fn is not None

    result = fn("[{'name': 'Body', 'score_as_printed': None, 'is_blank': True}]", {"container": "array"})

    assert result.ok is True
    assert result.normalized_value == [
        {"name": "Body", "score_as_printed": None, "is_blank": True}
    ]


def test_runner_keeps_final_structured_value_typed() -> None:
    result = _run_normalizers(
        "['A', 'B']",
        [
            {
                "implementation_key": "di.norm.structured_literal_parse",
                "parameters": {"container": "array"},
            }
        ],
    )

    assert result.ok is True
    assert result.normalized_value == ["A", "B"]
    assert isinstance(result.normalized_value, list)


def test_structured_literal_parser_rejects_wrong_container() -> None:
    fn = get_normalizer("di.norm.structured_literal_parse")
    assert fn is not None

    result = fn('{"head":"Dent"}', {"container": "array"})

    assert result.ok is False
    assert result.normalized_value is None


def test_scalar_literal_parser_keeps_number_boolean_and_integer_typed() -> None:
    fn = get_normalizer("di.norm.scalar_literal_parse")
    assert fn is not None

    number = fn("1250.50", {"type": "number"})
    integer = fn("12.0", {"type": "integer"})
    boolean = fn("True", {"type": "boolean"})

    assert number.ok is True and number.normalized_value == 1250.5
    assert integer.ok is True and integer.normalized_value == 12
    assert boolean.ok is True and boolean.normalized_value is True


def test_scalar_literal_parser_does_not_silently_coerce_currency_text() -> None:
    fn = get_normalizer("di.norm.scalar_literal_parse")
    assert fn is not None

    result = fn("₹1,25,000", {"type": "number"})

    assert result.ok is False
    assert result.normalized_value is None


def test_structured_shape_validator_accepts_typed_valuation_rows() -> None:
    fn = get_schema_v2_validator("di.val.structured_shape")
    assert fn is not None

    result = fn(
        [{"head": "Dent", "amount": 1250.0, "is_handwritten": False}],
        None,
        {
            "container": "array",
            "item_type": "object",
            "properties": {
                "head": ["string", "null"],
                "amount": ["number", "null"],
                "is_handwritten": "boolean",
            },
            "required_keys": ["head", "amount", "is_handwritten"],
            "allow_extra_keys": False,
            "severity": "ERROR",
        },
    )

    assert result.result == "PASS"
    assert result.details == {"row_count": 1}


def test_structured_shape_validator_surfaces_bad_row_without_dropping_it() -> None:
    fn = get_schema_v2_validator("di.val.structured_shape")
    assert fn is not None

    result = fn(
        [
            {"head": "Dent", "amount": "not-a-number"},
            {"head": None, "amount": 500, "is_handwritten": True, "unexpected": 1},
        ],
        None,
        {
            "container": "array",
            "item_type": "object",
            "properties": {
                "head": ["string", "null"],
                "amount": ["number", "null"],
                "is_handwritten": "boolean",
            },
            "required_keys": ["head", "amount", "is_handwritten"],
            "allow_extra_keys": False,
            "severity": "ERROR",
        },
    )

    assert result.result == "FAIL"
    assert result.details is not None
    assert result.details["row_count"] == 2
    assert "$[0].amount" in result.details["error_paths"]
    assert "$[0].is_handwritten" in result.details["error_paths"]
    assert "$[1].unexpected" in result.details["error_paths"]


def test_structured_shape_validator_accepts_string_array() -> None:
    fn = get_schema_v2_validator("di.val.structured_shape")
    assert fn is not None

    result = fn(
        ["Submit invoice", "Provide insurance copy"],
        None,
        {"container": "array", "item_type": "string", "severity": "ERROR"},
    )

    assert result.result == "PASS"


def test_wave_1_schemas_are_registered() -> None:
    assert get_schema("gst_certificate").schema_version == "2.0"
    assert get_schema("corporate_id").schema_version == "2.0"
    assert get_schema("bank_approval_letter").schema_version == "2.0"
    assert get_schema("valuation_report").schema_version == "2.0"


def test_reference_or_derived_categories_are_not_gemini_targets() -> None:
    valuation_keys = {field.key for field in get_schema("valuation_report").fields}
    bank_keys = {field.key for field in get_schema("bank_approval_letter").fields}

    assert "valuation_platform" not in valuation_keys
    assert "financier_type" not in bank_keys
    assert "platform_name_as_printed" in valuation_keys
    assert "financier_name" in bank_keys
