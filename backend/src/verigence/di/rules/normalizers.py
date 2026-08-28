"""rules/normalizers.py — Deterministic field normalization rule implementations.

Each rule is a callable registered in NORMALIZER_REGISTRY keyed by
implementation_key (matches normalization_rule_catalog.implementation_key).

Contract (DI_LLD_v2.2 §Processing Worker step 11):
- Input  : raw_value_text (str | None), profile-level parameters (dict)
- Output : NormalizerResult with normalized_value (JSON-serialisable) or None
- Rules MUST be deterministic — no AI, no network calls.
- Rules MUST NOT raise; return NormalizerResult with ok=False on failure.
"""
from __future__ import annotations

import ast
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class NormalizerResult:
    ok: bool
    normalized_value: Any          # JSON-serialisable; None means "could not normalize"
    message: str | None = None


# ── Type alias ────────────────────────────────────────────────────────────────
NormalizerFn = Callable[[str | None, dict[str, Any]], NormalizerResult]


# ── Rule implementations ──────────────────────────────────────────────────────

def _norm_strip_whitespace(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Trim leading/trailing whitespace and collapse internal runs to single space."""
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)
    value = re.sub(r"\s+", " ", raw.strip())
    return NormalizerResult(ok=True, normalized_value=value)


def _norm_uppercase(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Convert value to uppercase."""
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)
    return NormalizerResult(ok=True, normalized_value=raw.strip().upper())


def _norm_lowercase(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Convert value to lowercase."""
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)
    return NormalizerResult(ok=True, normalized_value=raw.strip().lower())


def _norm_remove_non_alphanumeric(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Remove all characters that are not alphanumeric or the allowed_chars param."""
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)
    allowed_extra: str = params.get("allowed_chars", "")
    pattern = rf"[^\w{re.escape(allowed_extra)}]"
    value = re.sub(pattern, "", raw, flags=re.UNICODE)
    return NormalizerResult(ok=True, normalized_value=value)


def _norm_date_iso8601(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Parse common date formats and return ISO-8601 YYYY-MM-DD.

    Supported input formats (configurable via ``formats`` param):
    - DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    - MM/DD/YYYY (when locale=us in params)
    - YYYY-MM-DD (passthrough)
    - DD Mon YYYY  (e.g. 01 Jan 2024)
    """
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)

    cleaned = raw.strip()
    locale: str = params.get("locale", "iso")

    # Month name mapping
    _months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    # Try YYYY-MM-DD passthrough
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", cleaned)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _make_date_result(y, mo, d, raw)

    # Try DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    m = re.fullmatch(r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})", cleaned)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if locale == "us":
            mo, d = a, b
        else:
            d, mo = a, b
        return _make_date_result(y, mo, d, raw)

    # Try DD Mon YYYY
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", cleaned)
    if m:
        d = int(m.group(1))
        mon_str = m.group(2)[:3].lower()
        month_number = _months.get(mon_str)
        y = int(m.group(3))
        if month_number is not None:
            return _make_date_result(y, month_number, d, raw)

    return NormalizerResult(
        ok=False,
        normalized_value=None,
        message=f"Cannot parse {raw!r} as a date",
    )


def _make_date_result(y: int, mo: int, d: int, raw: str) -> NormalizerResult:
    if 1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2200:
        return NormalizerResult(ok=True, normalized_value=f"{y:04d}-{mo:02d}-{d:02d}")
    return NormalizerResult(
        ok=False,
        normalized_value=None,
        message=f"Date values out of range in {raw!r}",
    )


def _norm_digits_only(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Strip all non-digit characters, returning a digit-only string."""
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)
    value = re.sub(r"\D", "", raw)
    return NormalizerResult(ok=True, normalized_value=value)


def _norm_unicode_nfc(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Apply Unicode NFC normalization (composed form)."""
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)
    return NormalizerResult(ok=True, normalized_value=unicodedata.normalize("NFC", raw))


def _norm_truncate(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Truncate string to max_length characters."""
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)
    max_len: int = int(params.get("max_length", 255))
    return NormalizerResult(ok=True, normalized_value=raw[:max_len])


def _norm_regex_extract(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Extract the first capture group from ``pattern`` param.

    Example: pattern=r'(\\d{13})' on an ID number with surrounding text.
    """
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)
    pattern: str = params.get("pattern", "")
    if not pattern:
        return NormalizerResult(
            ok=False, normalized_value=None,
            message="regex_extract: 'pattern' parameter is required",
        )
    try:
        m = re.search(pattern, raw)
        if m:
            value = m.group(1) if m.lastindex else m.group(0)
            return NormalizerResult(ok=True, normalized_value=value)
        return NormalizerResult(
            ok=False, normalized_value=None,
            message=f"Pattern {pattern!r} did not match {raw!r}",
        )
    except re.error as exc:
        return NormalizerResult(
            ok=False, normalized_value=None,
            message=f"Invalid regex pattern: {exc}",
        )


def _norm_replace(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Replace all occurrences of ``find`` with ``replacement`` (literal strings)."""
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)
    find: str = params.get("find", "")
    replacement: str = params.get("replacement", "")
    return NormalizerResult(ok=True, normalized_value=raw.replace(find, replacement))


def _parse_literal(raw: str) -> tuple[bool, Any, str | None]:
    try:
        return True, json.loads(raw), None
    except (json.JSONDecodeError, TypeError):
        try:
            return True, ast.literal_eval(raw), None
        except (ValueError, SyntaxError) as exc:
            return False, None, str(exc)


def _norm_scalar_literal_parse(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Parse provider text back into a typed number/integer/boolean scalar.

    Gemini emits valid JSON values, but the current provider-neutral adapter stores
    ``raw_value_text`` as text.  This rule converts that text back to the expected
    scalar *without* forgiving currency symbols, percentages, words, or mixed
    strings.  A model that ignored the requested JSON scalar type therefore causes
    deterministic normalization failure and review instead of silent coercion.
    """
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)

    expected = str(params.get("type", "")).lower()
    if expected not in {"number", "integer", "boolean"}:
        return NormalizerResult(
            ok=False,
            normalized_value=None,
            message="scalar_literal_parse requires type=number|integer|boolean",
        )

    ok, parsed, error = _parse_literal(raw.strip())
    if not ok:
        return NormalizerResult(
            ok=False,
            normalized_value=None,
            message=f"Cannot parse typed scalar: {error}",
        )

    if expected == "boolean":
        if isinstance(parsed, bool):
            return NormalizerResult(ok=True, normalized_value=parsed)
        return NormalizerResult(
            ok=False,
            normalized_value=None,
            message=f"Expected boolean scalar, got {type(parsed).__name__}",
        )

    if isinstance(parsed, bool) or not isinstance(parsed, (int, float)):
        return NormalizerResult(
            ok=False,
            normalized_value=None,
            message=f"Expected numeric scalar, got {type(parsed).__name__}",
        )

    if expected == "integer":
        if isinstance(parsed, int):
            return NormalizerResult(ok=True, normalized_value=parsed)
        if isinstance(parsed, float) and parsed.is_integer():
            return NormalizerResult(ok=True, normalized_value=int(parsed))
        return NormalizerResult(
            ok=False,
            normalized_value=None,
            message=f"Expected integer scalar, got non-integral value {parsed!r}",
        )

    return NormalizerResult(ok=True, normalized_value=parsed)


def _norm_structured_literal_parse(
    raw: str | None,
    params: dict[str, Any],
) -> NormalizerResult:
    """Parse an extracted JSON/collection literal into a real JSON value.

    Existing provider-neutral FieldResult stores ``raw_value_text`` as text.  Gemini
    currently stringifies array/object values before they reach the rules layer;
    Python's representation is therefore possible for older adapter output.  This
    normalizer accepts strict JSON first and falls back to ``ast.literal_eval`` for
    that backwards-compatible representation.  The result must be JSON-serialisable
    and, when ``container`` is supplied, must match the requested top-level shape.

    This rule only parses.  Typed row validation is performed by a separate
    deterministic validator so malformed rows are visible as review conditions.
    """
    if raw is None:
        return NormalizerResult(ok=True, normalized_value=None)

    ok, parsed, error = _parse_literal(raw)
    if not ok:
        return NormalizerResult(
            ok=False,
            normalized_value=None,
            message=f"Cannot parse structured value: {error}",
        )

    container = params.get("container")
    if container == "array" and not isinstance(parsed, list):
        return NormalizerResult(
            ok=False,
            normalized_value=None,
            message=f"Expected structured array, got {type(parsed).__name__}",
        )
    if container == "object" and not isinstance(parsed, dict):
        return NormalizerResult(
            ok=False,
            normalized_value=None,
            message=f"Expected structured object, got {type(parsed).__name__}",
        )

    try:
        json.dumps(parsed)
    except (TypeError, ValueError) as exc:
        return NormalizerResult(
            ok=False,
            normalized_value=None,
            message=f"Structured value is not JSON-serialisable: {exc}",
        )

    return NormalizerResult(ok=True, normalized_value=parsed)


# ── Public registry: implementation_key → function ───────────────────────────
# Keys must match normalization_rule_catalog.implementation_key in the DB.

NORMALIZER_REGISTRY: dict[str, NormalizerFn] = {
    "di.norm.strip_whitespace":         _norm_strip_whitespace,
    "di.norm.uppercase":                _norm_uppercase,
    "di.norm.lowercase":                _norm_lowercase,
    "di.norm.remove_non_alphanumeric":  _norm_remove_non_alphanumeric,
    "di.norm.date_iso8601":             _norm_date_iso8601,
    "di.norm.digits_only":              _norm_digits_only,
    "di.norm.unicode_nfc":              _norm_unicode_nfc,
    "di.norm.truncate":                 _norm_truncate,
    "di.norm.regex_extract":            _norm_regex_extract,
    "di.norm.replace":                  _norm_replace,
    "di.norm.scalar_literal_parse":     _norm_scalar_literal_parse,
    "di.norm.structured_literal_parse": _norm_structured_literal_parse,
}


def get_normalizer(implementation_key: str) -> NormalizerFn | None:
    """Return the normalizer function for the given implementation_key, or None."""
    return NORMALIZER_REGISTRY.get(implementation_key)
