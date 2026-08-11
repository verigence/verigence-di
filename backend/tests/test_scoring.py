"""tests/test_scoring.py — Pure unit tests for the confidence scoring formula.

These tests have NO external dependencies (no DB, no Docker, no network).
Mark the module so pytest does not trigger the pg_container session fixture.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.no_docker  # prevents session-scoped pg_container from running

from verigence.di.domain.enums import FoundStatus, HumanVerificationStatus
from verigence.di.domain.scoring import ScoredField, calculate_confidence_score


def _field(key: str, found: FoundStatus, conf: float | None, weight: float,
           expected: bool = True) -> ScoredField:
    return ScoredField(
        field_key=key,
        found_status=found,
        field_confidence=Decimal(str(conf)) if conf is not None else None,
        score_weight=Decimal(str(weight)),
        expected=expected,
    )


def test_all_fields_found_above_threshold() -> None:
    fields = [
        _field("name", FoundStatus.FOUND, 95.0, 1.0),
        _field("dob", FoundStatus.FOUND, 92.0, 1.0),
    ]
    result = calculate_confidence_score(fields)
    assert result.confidence_score == Decimal("93.50")
    assert result.human_verification_status == HumanVerificationStatus.OPTIONAL


def test_score_exactly_90_is_mandatory() -> None:
    fields = [_field("id", FoundStatus.FOUND, 90.0, 1.0)]
    result = calculate_confidence_score(fields)
    assert result.confidence_score == Decimal("90.00")
    assert result.human_verification_status == HumanVerificationStatus.MANDATORY


def test_score_above_90_is_optional() -> None:
    fields = [_field("id", FoundStatus.FOUND, 90.01, 1.0)]
    result = calculate_confidence_score(fields)
    assert result.human_verification_status == HumanVerificationStatus.OPTIONAL


def test_expected_missing_contributes_zero() -> None:
    """Expected field NOT_FOUND → confidence 0, weight still counted."""
    fields = [
        _field("name", FoundStatus.FOUND, 100.0, 1.0),
        _field("dob", FoundStatus.NOT_FOUND, None, 1.0, expected=True),
    ]
    result = calculate_confidence_score(fields)
    # (100 * 1 + 0 * 1) / 2 = 50.00
    assert result.confidence_score == Decimal("50.00")
    assert result.human_verification_status == HumanVerificationStatus.MANDATORY


def test_non_expected_missing_excluded_from_denominator() -> None:
    """Non-expected NOT_FOUND → excluded from numerator AND denominator."""
    fields = [
        _field("name", FoundStatus.FOUND, 80.0, 1.0),
        _field("optional_field", FoundStatus.NOT_FOUND, None, 1.0, expected=False),
    ]
    result = calculate_confidence_score(fields)
    # Only name participates: 80/1 = 80.00
    assert result.confidence_score == Decimal("80.00")


def test_zero_denominator_raises() -> None:
    """All fields non-expected and missing → denominator = 0 → ValueError."""
    fields = [
        _field("x", FoundStatus.NOT_FOUND, None, 1.0, expected=False),
    ]
    with pytest.raises(ValueError, match="denominator is zero"):
        calculate_confidence_score(fields)


def test_verification_threshold_always_90() -> None:
    fields = [_field("f", FoundStatus.FOUND, 50.0, 1.0)]
    result = calculate_confidence_score(fields)
    assert result.verification_threshold_applied == Decimal("90.00")
