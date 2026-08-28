"""Tests for deterministic normalization and validation rules.

Tests every built-in rule implementation plus registry completeness.
No Docker required — all rules are pure functions.
"""
from __future__ import annotations

import pytest

from verigence.di.rules.normalizers import NORMALIZER_REGISTRY, get_normalizer
from verigence.di.rules.validators import VALIDATOR_REGISTRY, get_validator


# ── Normalizers ───────────────────────────────────────────────────────────────

class TestStripWhitespace:
    @pytest.mark.no_docker
    def test_collapses_whitespace(self):
        fn = get_normalizer("di.norm.strip_whitespace")
        assert fn is not None
        r = fn("  hello   world  ", {})
        assert r.ok and r.normalized_value == "hello world"

    @pytest.mark.no_docker
    def test_none_passthrough(self):
        fn = get_normalizer("di.norm.strip_whitespace")
        assert fn is not None
        r = fn(None, {})
        assert r.ok and r.normalized_value is None


class TestUppercase:
    @pytest.mark.no_docker
    def test_upper(self):
        fn = get_normalizer("di.norm.uppercase")
        assert fn("abc def", {}).normalized_value == "ABC DEF"


class TestLowercase:
    @pytest.mark.no_docker
    def test_lower(self):
        fn = get_normalizer("di.norm.lowercase")
        assert fn("ABC DEF", {}).normalized_value == "abc def"


class TestRemoveNonAlphanumeric:
    @pytest.mark.no_docker
    def test_default(self):
        fn = get_normalizer("di.norm.remove_non_alphanumeric")
        r = fn("ABC-123 / xyz", {})
        assert r.normalized_value == "ABC123xyz"

    @pytest.mark.no_docker
    def test_allowed_chars(self):
        fn = get_normalizer("di.norm.remove_non_alphanumeric")
        r = fn("ABC-123 / xyz", {"allowed_chars": "-"})
        assert r.normalized_value == "ABC-123xyz"


class TestDateISO8601:
    @pytest.mark.no_docker
    @pytest.mark.parametrize("raw,expected", [
        ("01/02/2024", "2024-02-01"),
        ("31-12-2023", "2023-12-31"),
        ("2024-06-15", "2024-06-15"),
        ("01 Jan 2024", "2024-01-01"),
        ("1 january 2024", "2024-01-01"),
    ])
    def test_indian_dates(self, raw, expected):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn(raw, {})
        assert r.ok and r.normalized_value == expected

    @pytest.mark.no_docker
    def test_us_date(self):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn("12/31/2023", {"locale": "us"})
        assert r.ok and r.normalized_value == "2023-12-31"

    @pytest.mark.no_docker
    def test_invalid_date(self):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn("not-a-date", {})
        assert not r.ok and r.normalized_value is None

    @pytest.mark.no_docker
    def test_out_of_range(self):
        fn = get_normalizer("di.norm.date_iso8601")
        r = fn("99/99/2024", {})
        assert not r.ok


class TestDigitsOnly:
    @pytest.mark.no_docker
    def test_digits(self):
        fn = get_normalizer("di.norm.digits_only")
        r = fn("+91 98765-43210", {})
        assert r.normalized_value == "919876543210"


class TestUnicodeNFC:
    @pytest.mark.no_docker
    def test_nfc(self):
        fn = get_normalizer("di.norm.unicode_nfc")
        # e + combining acute → precomposed é
        r = fn("e\u0301", {})
        assert r.normalized_value == "é"


class TestTruncate:
    @pytest.mark.no_docker
    def test_truncate(self):
        fn = get_normalizer("di.norm.truncate")
        r = fn("abcdefgh", {"max_length": 5})
        assert r.normalized_value == "abcde"


class TestRegexExtract:
    @pytest.mark.no_docker
    def test_capture_group(self):
        fn = get_normalizer("di.norm.regex_extract")
        r = fn("ID: 1234567890123 end", {"pattern": r"(\d{13})"})
        assert r.ok and r.normalized_value == "1234567890123"

    @pytest.mark.no_docker
    def test_no_match(self):
        fn = get_normalizer("di.norm.regex_extract")
        r = fn("no digits", {"pattern": r"(\d+)"})
        assert not r.ok

    @pytest.mark.no_docker
    def test_missing_pattern(self):
        fn = get_normalizer("di.norm.regex_extract")
        r = fn("value", {})
        assert not r.ok

    @pytest.mark.no_docker
    def test_invalid_pattern(self):
        fn = get_normalizer("di.norm.regex_extract")
        r = fn("value", {"pattern": "[invalid"})
        assert not r.ok


class TestReplace:
    @pytest.mark.no_docker
    def test_replace(self):
        fn = get_normalizer("di.norm.replace")
        r = fn("hello-world", {"find": "-", "replacement": " "})
        assert r.normalized_value == "hello world"


# ── Validators ────────────────────────────────────────────────────────────────

class TestRegexValidator:
    @pytest.mark.no_docker
    def test_pass(self):
        fn = get_validator("di.val.regex")
        r = fn("ABCDE1234F", None, {"pattern": r"^[A-Z]{5}\d{4}[A-Z]$"})
        assert r.result == "PASS"

    @pytest.mark.no_docker
    def test_fail(self):
        fn = get_validator("di.val.regex")
        r = fn("BAD", None, {"pattern": r"^[A-Z]{5}\d{4}[A-Z]$"})
        assert r.result == "FAIL"

    @pytest.mark.no_docker
    def test_skip_none(self):
        fn = get_validator("di.val.regex")
        r = fn(None, None, {"pattern": r".*"})
        assert r.result == "SKIP"


class TestLengthValidator:
    @pytest.mark.no_docker
    def test_exact(self):
        fn = get_validator("di.val.length")
        assert fn("12345", None, {"exact": 5}).result == "PASS"
        assert fn("1234", None, {"exact": 5}).result == "FAIL"

    @pytest.mark.no_docker
    def test_range(self):
        fn = get_validator("di.val.length")
        assert fn("abc", None, {"min": 2, "max": 5}).result == "PASS"
        assert fn("a", None, {"min": 2}).result == "FAIL"
        assert fn("abcdef", None, {"max": 5}).result == "FAIL"


class TestNumericRangeValidator:
    @pytest.mark.no_docker
    def test_pass(self):
        fn = get_validator("di.val.numeric_range")
        assert fn(50, None, {"min": 0, "max": 100}).result == "PASS"

    @pytest.mark.no_docker
    def test_below_min(self):
        fn = get_validator("di.val.numeric_range")
        assert fn(-1, None, {"min": 0}).result == "FAIL"

    @pytest.mark.no_docker
    def test_above_max(self):
        fn = get_validator("di.val.numeric_range")
        assert fn(101, None, {"max": 100}).result == "FAIL"

    @pytest.mark.no_docker
    def test_not_numeric(self):
        fn = get_validator("di.val.numeric_range")
        assert fn("abc", None, {}).result == "ERROR"


class TestAllowedValuesValidator:
    @pytest.mark.no_docker
    def test_allowed(self):
        fn = get_validator("di.val.allowed_values")
        assert fn("ACTIVE", None, {"allowed": ["ACTIVE", "INACTIVE"]}).result == "PASS"

    @pytest.mark.no_docker
    def test_disallowed(self):
        fn = get_validator("di.val.allowed_values")
        assert fn("UNKNOWN", None, {"allowed": ["ACTIVE"]}).result == "FAIL"


class TestRequiredValidator:
    @pytest.mark.no_docker
    def test_present(self):
        fn = get_validator("di.val.required")
        assert fn("value", None, {}).result == "PASS"

    @pytest.mark.no_docker
    def test_none(self):
        fn = get_validator("di.val.required")
        assert fn(None, None, {}).result == "FAIL"

    @pytest.mark.no_docker
    def test_empty(self):
        fn = get_validator("di.val.required")
        assert fn("", None, {}).result == "FAIL"


class TestDateRangeValidator:
    @pytest.mark.no_docker
    def test_valid(self):
        fn = get_validator("di.val.date_range")
        assert fn("2024-01-01", None, {}).result == "PASS"

    @pytest.mark.no_docker
    def test_invalid(self):
        fn = get_validator("di.val.date_range")
        assert fn("2024-13-01", None, {}).result == "FAIL"


class TestCrossFieldCompareValidator:
    @pytest.mark.no_docker
    def test_equal(self):
        fn = get_validator("di.val.cross_field_compare")
        r = fn("ABC", None, {"other_value": "ABC", "operator": "eq"})
        assert r.result == "PASS"

    @pytest.mark.no_docker
    def test_not_equal(self):
        fn = get_validator("di.val.cross_field_compare")
        r = fn("ABC", None, {"other_value": "XYZ", "operator": "eq"})
        assert r.result == "FAIL"


class TestLuhnValidator:
    @pytest.mark.no_docker
    def test_valid_luhn(self):
        fn = get_validator("di.val.luhn")
        assert fn("79927398713", None, {}).result == "PASS"

    @pytest.mark.no_docker
    def test_invalid_luhn(self):
        fn = get_validator("di.val.luhn")
        assert fn("79927398714", None, {}).result == "FAIL"


class TestEmailValidator:
    @pytest.mark.no_docker
    def test_valid_email(self):
        fn = get_validator("di.val.email")
        assert fn("user@example.com", None, {}).result == "PASS"

    @pytest.mark.no_docker
    def test_invalid_email(self):
        fn = get_validator("di.val.email")
        assert fn("not-an-email", None, {}).result == "FAIL"


class TestPhoneValidator:
    @pytest.mark.no_docker
    def test_valid_india(self):
        fn = get_validator("di.val.phone")
        assert fn("9876543210", None, {"country": "IN"}).result == "PASS"

    @pytest.mark.no_docker
    def test_invalid_india(self):
        fn = get_validator("di.val.phone")
        assert fn("12345", None, {"country": "IN"}).result == "FAIL"


class TestGSTINValidator:
    @pytest.mark.no_docker
    def test_valid_format(self):
        fn = get_validator("di.val.gstin")
        assert fn("27AAPFU0939F1ZV", None, {}).result == "PASS"

    @pytest.mark.no_docker
    def test_invalid_format(self):
        fn = get_validator("di.val.gstin")
        assert fn("BADGSTIN", None, {}).result == "FAIL"


class TestIBANValidator:
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
        assert len(NORMALIZER_REGISTRY) == 12

    @pytest.mark.no_docker
    def test_validator_count(self):
        assert len(VALIDATOR_REGISTRY) == 11
