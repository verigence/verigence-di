"""tests/test_rules.py — Unit tests for rules/ package (Step 8).

All tests are marked no_docker — pure deterministic rule logic, no DB.

Coverage:
- normalizers: all 10 built-in rules
- validators: all 11 built-in rules
- runner._run_normalizers pipeline
- REGISTRY completeness
"""
from __future__ import annotations

import pytest

from verigence.di.rules.normalizers import (
    NORMALIZER_REGISTRY,
    NormalizerResult,
    get_normalizer,
)
from verigence.di.rules.validators import (
    VALIDATOR_REGISTRY,
    ValidatorRuleResult,
    get_validator,
)
from verigence.di.rules.runner import _run_normalizers


# ── Normalizer tests ──────────────────────────────────────────────────────────

class TestNormStripWhitespace:
    @pytest.mark.no_docker
    def test_strips_leading_trailing(self):
        fn = get_normalizer("di.norm.strip_whitespace")
        r = fn("  hello world  ", {})
        assert r.ok and r.normalized_value == "hello world"

    @pytest.mark.no_docker
    def test_collapses_internal_spaces(self):
        fn = get_normalizer("di.norm.strip_whitespace")
        r = fn("foo   bar\tbaz", {})
        assert r.ok and r.normalized_value == "foo bar baz"

    @pytest.mark.no_docker
    def test_none_passthrough(self):
        fn = get_normalizer("di.norm.strip_whitespace")
        r = fn(None, {})
        assert r.ok and r.normalized_value is None


class TestNormUppercase:
    @pytest.mark.no_docker
    def test_converts_to_upper(self):
        fn = get_normalizer("di.norm.uppercase")
        r = fn(" hello ", {})
        assert r.ok and r.normalized_value == "HELLO"

    @pytest.mark.no_docker
    def test_none_passthrough(self):
        fn = get_normalizer("di.norm.uppercase")
        r = fn(None, {})
        assert r.ok and r.normalized_value is None


class TestNormLowercase:
    @pytest.mark.no_docker
    def test_converts_to_lower(self):
        fn = get_normalizer("di.norm.lowercase")
        r = fn(" HELLO ", {})
        assert r.ok and r.normalized_value == "hello"


class TestNormRemoveNonAlphanumeric:
    @pytest.mark.no_docker
    def test_removes_punctuation(self):
        fn = get_normalizer("di.norm.remove_non_alphanumeric")
        r = fn("ID: 123-456/abc!", {})
        assert r.ok and r.normalized_value == "ID123456abc"

    @pytest.mark.no_docker
    def test_allows_extra_chars(self):
        fn = get_normalizer("di.norm.remove_non_alphanumeric")
        r = fn("ID: 123-456", {"allowed_chars": "-"})
        assert r.ok and r.normalized_value == "ID123-456"


class TestNormDateIso8601:
    @pytest.mark.no_docker
    def test_passthrough_iso(self):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn("2024-03-15", {})
        assert r.ok and r.normalized_value == "2024-03-15"

    @pytest.mark.no_docker
    def test_dmy_slash(self):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn("15/03/2024", {})
        assert r.ok and r.normalized_value == "2024-03-15"

    @pytest.mark.no_docker
    def test_dmy_dot(self):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn("15.03.2024", {})
        assert r.ok and r.normalized_value == "2024-03-15"

    @pytest.mark.no_docker
    def test_named_month(self):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn("01 Jan 2024", {})
        assert r.ok and r.normalized_value == "2024-01-01"

    @pytest.mark.no_docker
    def test_invalid_returns_not_ok(self):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn("not-a-date", {})
        assert not r.ok

    @pytest.mark.no_docker
    def test_none_passthrough(self):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn(None, {})
        assert r.ok and r.normalized_value is None


class TestNormDigitsOnly:
    @pytest.mark.no_docker
    def test_strips_non_digits(self):
        fn = get_normalizer("di.norm.digits_only")
        r = fn("(+27) 082-123-4567", {})
        assert r.ok and r.normalized_value == "27082123456" + "7"


class TestNormUnicodeNfc:
    @pytest.mark.no_docker
    def test_normalizes(self):
        fn = get_normalizer("di.norm.unicode_nfc")
        # Compose "café" from decomposed form
        decomposed = "cafe\u0301"
        r = fn(decomposed, {})
        assert r.ok and r.normalized_value == "caf\u00e9"


class TestNormTruncate:
    @pytest.mark.no_docker
    def test_truncates(self):
        fn = get_normalizer("di.norm.truncate")
        r = fn("hello world", {"max_length": 5})
        assert r.ok and r.normalized_value == "hello"

    @pytest.mark.no_docker
    def test_short_unchanged(self):
        fn = get_normalizer("di.norm.truncate")
        r = fn("hi", {"max_length": 5})
        assert r.ok and r.normalized_value == "hi"


class TestNormRegexExtract:
    @pytest.mark.no_docker
    def test_extracts_capture_group(self):
        fn = get_normalizer("di.norm.regex_extract")
        r = fn("ID: 8001015009087", {"pattern": r"(\d{13})"})
        assert r.ok and r.normalized_value == "8001015009087"

    @pytest.mark.no_docker
    def test_no_match_returns_not_ok(self):
        fn = get_normalizer("di.norm.regex_extract")
        r = fn("no digits here", {"pattern": r"(\d{13})"})
        assert not r.ok

    @pytest.mark.no_docker
    def test_missing_pattern_param_returns_not_ok(self):
        fn = get_normalizer("di.norm.regex_extract")
        r = fn("hello", {})
        assert not r.ok


class TestNormReplace:
    @pytest.mark.no_docker
    def test_replaces_literal(self):
        fn = get_normalizer("di.norm.replace")
        r = fn("hello world", {"find": " ", "replacement": "_"})
        assert r.ok and r.normalized_value == "hello_world"


# ── Normalizer pipeline ───────────────────────────────────────────────────────

class TestNormPipeline:
    @pytest.mark.no_docker
    def test_chained_normalizers(self):
        """strip → uppercase pipeline."""
        configs = [
            {"implementation_key": "di.norm.strip_whitespace", "parameters": {}},
            {"implementation_key": "di.norm.uppercase", "parameters": {}},
        ]
        result = _run_normalizers("  hello  ", configs)
        assert result.ok and result.normalized_value == "HELLO"

    @pytest.mark.no_docker
    def test_empty_configs_passthrough(self):
        result = _run_normalizers("hello", [])
        assert result.ok and result.normalized_value == "hello"

    @pytest.mark.no_docker
    def test_pipeline_stops_on_fail(self):
        """date_iso8601 fails → pipeline returns not ok."""
        configs = [
            {"implementation_key": "di.norm.date_iso8601", "parameters": {}},
            {"implementation_key": "di.norm.uppercase", "parameters": {}},
        ]
        result = _run_normalizers("not-a-date", configs)
        assert not result.ok

    @pytest.mark.no_docker
    def test_none_propagates_through_pipeline(self):
        configs = [
            {"implementation_key": "di.norm.strip_whitespace", "parameters": {}},
            {"implementation_key": "di.norm.uppercase", "parameters": {}},
        ]
        result = _run_normalizers(None, configs)
        assert result.ok and result.normalized_value is None


# ── Validator tests ───────────────────────────────────────────────────────────

class TestValRequired:
    @pytest.mark.no_docker
    def test_fails_on_none(self):
        fn = get_validator("di.val.required")
        r = fn(None, None, {})
        assert r.result == "FAIL"

    @pytest.mark.no_docker
    def test_fails_on_empty_string(self):
        fn = get_validator("di.val.required")
        r = fn("", None, {})
        assert r.result == "FAIL"

    @pytest.mark.no_docker
    def test_passes_on_value(self):
        fn = get_validator("di.val.required")
        r = fn("hello", None, {})
        assert r.result == "PASS"


class TestValMinLength:
    @pytest.mark.no_docker
    def test_fails_when_too_short(self):
        fn = get_validator("di.val.min_length")
        r = fn("hi", None, {"min_length": 5})
        assert r.result == "FAIL"

    @pytest.mark.no_docker
    def test_passes_at_minimum(self):
        fn = get_validator("di.val.min_length")
        r = fn("hello", None, {"min_length": 5})
        assert r.result == "PASS"


class TestValMaxLength:
    @pytest.mark.no_docker
    def test_fails_when_too_long(self):
        fn = get_validator("di.val.max_length")
        r = fn("hello world", None, {"max_length": 5})
        assert r.result == "FAIL"

    @pytest.mark.no_docker
    def test_passes_within_limit(self):
        fn = get_validator("di.val.max_length")
        r = fn("hello", None, {"max_length": 5})
        assert r.result == "PASS"


class TestValRegexMatch:
    @pytest.mark.no_docker
    def test_passes_valid_pattern(self):
        fn = get_validator("di.val.regex_match")
        r = fn("8001015009087", None, {"pattern": r"\d{13}"})
        assert r.result == "PASS"

    @pytest.mark.no_docker
    def test_fails_no_match(self):
        fn = get_validator("di.val.regex_match")
        r = fn("abc", None, {"pattern": r"\d{13}"})
        assert r.result == "FAIL"


class TestValNumericRange:
    @pytest.mark.no_docker
    def test_passes_in_range(self):
        fn = get_validator("di.val.numeric_range")
        r = fn("50", None, {"min_value": 0, "max_value": 100})
        assert r.result == "PASS"

    @pytest.mark.no_docker
    def test_fails_below_min(self):
        fn = get_validator("di.val.numeric_range")
        r = fn("-1", None, {"min_value": 0})
        assert r.result == "FAIL"

    @pytest.mark.no_docker
    def test_fails_above_max(self):
        fn = get_validator("di.val.numeric_range")
        r = fn("101", None, {"max_value": 100})
        assert r.result == "FAIL"


class TestValDateNotFuture:
    @pytest.mark.no_docker
    def test_fails_future_date(self):
        fn = get_validator("di.val.date_not_future")
        r = fn("2099-01-01", None, {})
        assert r.result == "FAIL"

    @pytest.mark.no_docker
    def test_passes_past_date(self):
        fn = get_validator("di.val.date_not_future")
        r = fn("2000-01-01", None, {})
        assert r.result == "PASS"


class TestValDateNotExpired:
    @pytest.mark.no_docker
    def test_fails_past_date(self):
        fn = get_validator("di.val.date_not_expired")
        r = fn("2000-01-01", None, {})
        assert r.result == "FAIL"

    @pytest.mark.no_docker
    def test_passes_future_date(self):
        fn = get_validator("di.val.date_not_expired")
        r = fn("2099-12-31", None, {})
        assert r.result == "PASS"


class TestValAllowedValues:
    @pytest.mark.no_docker
    def test_passes_valid_value(self):
        fn = get_validator("di.val.allowed_values")
        r = fn("ZAF", None, {"allowed_values": ["ZAF", "GBR", "USA"]})
        assert r.result == "PASS"

    @pytest.mark.no_docker
    def test_case_insensitive_by_default(self):
        fn = get_validator("di.val.allowed_values")
        r = fn("zaf", None, {"allowed_values": ["ZAF"]})
        assert r.result == "PASS"

    @pytest.mark.no_docker
    def test_fails_unknown_value(self):
        fn = get_validator("di.val.allowed_values")
        r = fn("XYZ", None, {"allowed_values": ["ZAF"]})
        assert r.result == "FAIL"


class TestValLuhn:
    @pytest.mark.no_docker
    def test_valid_luhn(self):
        fn = get_validator("di.val.luhn")
        # Classic test number
        r = fn("4532015112830366", None, {})
        assert r.result == "PASS"

    @pytest.mark.no_docker
    def test_invalid_luhn(self):
        fn = get_validator("di.val.luhn")
        r = fn("1234567890123456", None, {})
        assert r.result == "FAIL"


class TestValSaIdNumber:
    @pytest.mark.no_docker
    def test_valid_sa_id(self):
        fn = get_validator("di.val.sa_id_number")
        # Verified SA ID (from public test datasets)
        r = fn("8001015009087", None, {})
        assert r.result == "PASS"

    @pytest.mark.no_docker
    def test_wrong_length(self):
        fn = get_validator("di.val.sa_id_number")
        r = fn("123456789012", None, {})  # 12 digits
        assert r.result == "FAIL"

    @pytest.mark.no_docker
    def test_bad_checksum(self):
        fn = get_validator("di.val.sa_id_number")
        r = fn("8001015009080", None, {})  # last digit changed
        assert r.result == "FAIL"


class TestValIban:
    @pytest.mark.no_docker
    def test_valid_iban(self):
        fn = get_validator("di.val.iban")
        # DE example IBAN (well-known test value)
        r = fn("DE89370400440532013000", None, {})
        assert r.result == "PASS"

    @pytest.mark.no_docker
    def test_invalid_iban(self):
        fn = get_validator("di.val.iban")
        r = fn("DE00370400440532013000", None, {})  # bad check digits
        assert r.result == "FAIL"


# ── Registry completeness ─────────────────────────────────────────────────────

class TestRegistryCompleteness:
    @pytest.mark.no_docker
    def test_all_normalizer_keys_resolve(self):
        for key in NORMALIZER_REGISTRY:
            assert get_normalizer(key) is not None, f"{key} is None in registry"

    @pytest.mark.no_docker
    def test_all_validator_keys_resolve(self):
        for key in VALIDATOR_REGISTRY:
            assert get_validator(key) is not None, f"{key} is None in registry"

    @pytest.mark.no_docker
    def test_normalizer_count(self):
        assert len(NORMALIZER_REGISTRY) == 10

    @pytest.mark.no_docker
    def test_validator_count(self):
        assert len(VALIDATOR_REGISTRY) == 11
