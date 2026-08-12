"""domain/scoring.py — Confidence scoring formula for Verigence DI.

Implements the deterministic weighted-mean confidence score defined in
DI_ARCHITECTURE_v2.1.md §10 and DI_CONFIGURATION_MODEL_v2.0.md §5.

Rules:
- Only enabled score_included=True fields participate.
- Only found_status=FOUND is treated as present.
- NOT_FOUND / AMBIGUOUS / ERROR are treated as missing.
- Expected missing scored field contributes confidence=0 with its weight.
- Non-expected missing scored field is excluded from numerator AND denominator.
- Result is rounded to 2 decimal places.
- Default threshold: confidence > 90.00 => OPTIONAL, <= 90.00 => MANDATORY.
- Threshold is configurable: per-tenant DB value overrides system-wide default.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from verigence.di.domain.enums import FoundStatus, HumanVerificationStatus

DEFAULT_VERIFICATION_THRESHOLD = Decimal("90.00")


@dataclass(frozen=True)
class ScoredField:
    """Input to the confidence scoring formula."""
    field_key: str
    found_status: FoundStatus
    field_confidence: Decimal | None  # 0-100, None when not found
    score_weight: Decimal
    expected: bool  # whether this field is expected in the profile


@dataclass(frozen=True)
class ConfidenceResult:
    """Output of calculate_confidence_score()."""
    confidence_score: Decimal        # 0.00 – 100.00, 2 dp
    human_verification_status: HumanVerificationStatus
    verification_threshold_applied: Decimal  # always 90.00 in Phase 1
    participating_field_count: int
    total_weight: Decimal


def calculate_confidence_score(
    fields: list[ScoredField],
    threshold: Decimal | None = None,
) -> ConfidenceResult:
    """Calculate document-level confidence score from scored field results.

    Args:
        fields: Scored field inputs.
        threshold: Verification threshold to apply. If None, uses
                   DEFAULT_VERIFICATION_THRESHOLD (90.00).

    Raises ValueError if no fields produce a positive total weight
    (indicates a misconfigured published profile — should be caught at
    profile publication time, not here).
    """
    effective_threshold = threshold if threshold is not None else DEFAULT_VERIFICATION_THRESHOLD
    numerator = Decimal("0")
    denominator = Decimal("0")
    participating = 0

    for f in fields:
        if f.found_status == FoundStatus.FOUND and f.field_confidence is not None:
            # Present field: contributes normalized confidence × weight
            clamped = max(Decimal("0"), min(Decimal("100"), f.field_confidence))
            numerator += clamped * f.score_weight
            denominator += f.score_weight
            participating += 1
        elif f.expected:
            # Expected but missing: contributes 0 × weight (full penalty)
            denominator += f.score_weight
            participating += 1
        # Non-expected missing: excluded from both numerator and denominator

    if denominator == 0:
        raise ValueError(
            "Confidence scoring denominator is zero — "
            "the published Extraction Profile has no scoreable fields. "
            "This should have been caught at profile publication."
        )

    raw = numerator / denominator
    score = Decimal(str(raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    hvs = (
        HumanVerificationStatus.OPTIONAL
        if score > effective_threshold
        else HumanVerificationStatus.MANDATORY
    )

    return ConfidenceResult(
        confidence_score=score,
        human_verification_status=hvs,
        verification_threshold_applied=effective_threshold,
        participating_field_count=participating,
        total_weight=denominator,
    )
