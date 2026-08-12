"""rules/validators.py — Deterministic field and document validation rule implementations.

Each rule is a callable registered in VALIDATOR_REGISTRY keyed by
implementation_key (matches validation_rule_catalog.implementation_key).

Contract (DI_LLD_v2.2 §Processing Worker step 12):
- FIELD rules receive: normalized_value (Any), raw_value_text (str | None), parameters (dict)
- Result: ValidatorRuleResult — result in PASS|FAIL|WARNING|SKIP|ERROR, severity INFO|WARNING|ERROR
- Rules MUST be deterministic — no AI, no network calls.
- Rules MUST NOT raise; return result=ERROR on unexpected failures.

result_scope (per validation_rule_catalog.result_scope):
  FIELD      — operates on a single extracted field value
  DOCUMENT   — operates on the whole document (all field values together)
  CROSS_FIELD — operates on two or more specific named fields
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Callable


@dataclass
class ValidatorRuleResult:
    rule_key: str
    result: str         # PASS | FAIL | WARNING | SKIP | ERROR
    severity: str       # INFO | WARNING | ERROR  (from profile_field_validators.severity)
    message: str | None = None
    details: dict[str, Any] | None = None


# ── Type alias ────────────────────────────────────────────────────────────────
ValidatorFn = Callable[
    [Any, str | None, dict[str, Any]],  # (normalized_value, raw_value_text, params)
    ValidatorRuleResult,
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make(rule_key: str, result: str, severity: str,
          msg: str | None = None, details: dict | None = None) -> ValidatorRuleResult:
    return ValidatorRuleResult(
        rule_key=rule_key, result=result, severity=severity,
        message=msg, details=details,
    )


# ── Rule implementations ──────────────────────────────────────────────────────

def _val_required(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.required",
) -> ValidatorRuleResult:
    """Fail when the normalized value is None, empty string, or empty collection."""
    severity = params.get("severity", "ERROR")
    empty = value is None or value == "" or value == [] or value == {}
    if empty:
        return _make(rule_key, "FAIL", severity, "Field is required but no value was found")
    return _make(rule_key, "PASS", severity)


def _val_min_length(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.min_length",
) -> ValidatorRuleResult:
    """Fail when string length is below min_length."""
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No value to check length")
    min_len: int = int(params.get("min_length", 1))
    length = len(str(value))
    if length < min_len:
        return _make(rule_key, "FAIL", severity,
                     f"Value length {length} is below minimum {min_len}",
                     {"length": length, "min_length": min_len})
    return _make(rule_key, "PASS", severity, details={"length": length})


def _val_max_length(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.max_length",
) -> ValidatorRuleResult:
    """Fail when string length exceeds max_length."""
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No value to check length")
    max_len: int = int(params.get("max_length", 255))
    length = len(str(value))
    if length > max_len:
        return _make(rule_key, "FAIL", severity,
                     f"Value length {length} exceeds maximum {max_len}",
                     {"length": length, "max_length": max_len})
    return _make(rule_key, "PASS", severity, details={"length": length})


def _val_regex_match(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.regex_match",
) -> ValidatorRuleResult:
    """Fail when the value does not match the required ``pattern``."""
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No value to match pattern")
    pattern: str = params.get("pattern", "")
    if not pattern:
        return _make(rule_key, "ERROR", "ERROR", "regex_match: 'pattern' parameter is required")
    try:
        if re.fullmatch(pattern, str(value)):
            return _make(rule_key, "PASS", severity)
        return _make(rule_key, "FAIL", severity,
                     f"Value {str(value)!r} does not match pattern {pattern!r}",
                     {"pattern": pattern})
    except re.error as exc:
        return _make(rule_key, "ERROR", "ERROR", f"Invalid regex pattern: {exc}")


def _val_numeric_range(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.numeric_range",
) -> ValidatorRuleResult:
    """Fail when numeric value is outside [min_value, max_value]."""
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No value to range-check")
    try:
        num = float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return _make(rule_key, "FAIL", severity,
                     f"Cannot parse {value!r} as a number")
    min_val = params.get("min_value")
    max_val = params.get("max_value")
    if min_val is not None and num < float(min_val):
        return _make(rule_key, "FAIL", severity,
                     f"Value {num} is below minimum {min_val}",
                     {"value": num, "min_value": float(min_val)})
    if max_val is not None and num > float(max_val):
        return _make(rule_key, "FAIL", severity,
                     f"Value {num} exceeds maximum {max_val}",
                     {"value": num, "max_value": float(max_val)})
    return _make(rule_key, "PASS", severity, details={"value": num})


def _val_date_not_future(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.date_not_future",
) -> ValidatorRuleResult:
    """Fail when an ISO-8601 date is in the future (after today UTC)."""
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No date value to check")
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        return _make(rule_key, "FAIL", severity,
                     f"Cannot parse {value!r} as ISO-8601 date")
    today = datetime.now(UTC).date()
    if d > today:
        return _make(rule_key, "FAIL", severity,
                     f"Date {d} is in the future",
                     {"date": str(d), "today": str(today)})
    return _make(rule_key, "PASS", severity)


def _val_date_not_expired(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.date_not_expired",
) -> ValidatorRuleResult:
    """Fail when an ISO-8601 expiry date is in the past (before today UTC).

    Useful for: passport/ID expiry checks.
    """
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No expiry date value to check")
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        return _make(rule_key, "FAIL", severity,
                     f"Cannot parse {value!r} as ISO-8601 date")
    today = datetime.now(UTC).date()
    if d < today:
        return _make(rule_key, "FAIL", severity,
                     f"Expiry date {d} is in the past (document expired)",
                     {"expiry_date": str(d), "today": str(today)})
    return _make(rule_key, "PASS", severity)


def _val_allowed_values(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.allowed_values",
) -> ValidatorRuleResult:
    """Fail when value is not in the ``allowed_values`` list (case-insensitive by default)."""
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No value to check")
    allowed: list = params.get("allowed_values", [])
    if not allowed:
        return _make(rule_key, "ERROR", "ERROR", "allowed_values: 'allowed_values' parameter is required")
    case_sensitive: bool = params.get("case_sensitive", False)
    candidate = str(value) if case_sensitive else str(value).upper()
    allowed_norm = allowed if case_sensitive else [str(v).upper() for v in allowed]
    if candidate in allowed_norm:
        return _make(rule_key, "PASS", severity)
    return _make(rule_key, "FAIL", severity,
                 f"Value {str(value)!r} is not in the allowed set",
                 {"allowed_values": allowed})


def _val_luhn(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.luhn",
) -> ValidatorRuleResult:
    """Validate a numeric string passes the Luhn check (credit card / ID numbers)."""
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No value to Luhn-check")
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return _make(rule_key, "FAIL", severity, "No digits found in value for Luhn check")
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    if total % 10 == 0:
        return _make(rule_key, "PASS", severity)
    return _make(rule_key, "FAIL", severity,
                 f"Value {digits!r} failed Luhn check")


def _val_sa_id_number(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.sa_id_number",
) -> ValidatorRuleResult:
    """Validate a South African 13-digit ID number (format + Luhn).

    Format: YYMMDD GGGG C A Z
    YY=birth year, MM=01-12, DD=01-31, GGGG=gender (0000-4999 female, 5000-9999 male),
    C=citizenship (0=SA, 1=permanent resident), A=race digit (legacy, any),
    Z=Luhn check digit.
    """
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No value to validate as SA ID number")
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 13:
        return _make(rule_key, "FAIL", severity,
                     f"SA ID number must be 13 digits, got {len(digits)}",
                     {"digits": digits})
    # Basic date validity: YYMMDD
    mm, dd = int(digits[2:4]), int(digits[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return _make(rule_key, "FAIL", severity,
                     f"SA ID number date portion {digits[:6]} is invalid")
    # Luhn check (reuse _val_luhn logic)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    if total % 10 != 0:
        return _make(rule_key, "FAIL", severity,
                     f"SA ID number {digits!r} failed Luhn check")
    return _make(rule_key, "PASS", severity)


def _val_iban(
    value: Any, raw: str | None, params: dict[str, Any],
    rule_key: str = "di.val.iban",
) -> ValidatorRuleResult:
    """Basic IBAN format and modulo-97 check."""
    severity = params.get("severity", "ERROR")
    if value is None:
        return _make(rule_key, "SKIP", severity, "No value to validate as IBAN")
    # Strip spaces
    iban = re.sub(r"\s", "", str(value)).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return _make(rule_key, "FAIL", severity, f"IBAN {iban!r} has invalid format")
    # Rearrange: move first 4 chars to end
    rearranged = iban[4:] + iban[:4]
    # Convert letters to digits: A=10, B=11, …
    numeric_str = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    if int(numeric_str) % 97 == 1:
        return _make(rule_key, "PASS", severity)
    return _make(rule_key, "FAIL", severity, f"IBAN {iban!r} failed modulo-97 check")


# ── Public registry: implementation_key → function ───────────────────────────
# Keys must match validation_rule_catalog.implementation_key in the DB.

VALIDATOR_REGISTRY: dict[str, ValidatorFn] = {
    "di.val.required":          lambda v, r, p: _val_required(v, r, p, "di.val.required"),
    "di.val.min_length":        lambda v, r, p: _val_min_length(v, r, p, "di.val.min_length"),
    "di.val.max_length":        lambda v, r, p: _val_max_length(v, r, p, "di.val.max_length"),
    "di.val.regex_match":       lambda v, r, p: _val_regex_match(v, r, p, "di.val.regex_match"),
    "di.val.numeric_range":     lambda v, r, p: _val_numeric_range(v, r, p, "di.val.numeric_range"),
    "di.val.date_not_future":   lambda v, r, p: _val_date_not_future(v, r, p, "di.val.date_not_future"),
    "di.val.date_not_expired":  lambda v, r, p: _val_date_not_expired(v, r, p, "di.val.date_not_expired"),
    "di.val.allowed_values":    lambda v, r, p: _val_allowed_values(v, r, p, "di.val.allowed_values"),
    "di.val.luhn":              lambda v, r, p: _val_luhn(v, r, p, "di.val.luhn"),
    "di.val.sa_id_number":      lambda v, r, p: _val_sa_id_number(v, r, p, "di.val.sa_id_number"),
    "di.val.iban":              lambda v, r, p: _val_iban(v, r, p, "di.val.iban"),
}


def get_validator(implementation_key: str) -> ValidatorFn | None:
    """Return the validator function for the given implementation_key, or None."""
    return VALIDATOR_REGISTRY.get(implementation_key)
