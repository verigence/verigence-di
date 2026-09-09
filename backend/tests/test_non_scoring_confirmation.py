"""tests/test_non_scoring_confirmation.py — Pure unit tests for
_non_scoring_confirmation_values (job_runner.py).

Regression coverage for a live bug: document types whose extraction profile
has no score_included fields (gate_pass, rto_challan, tax_invoice_tally) were
confirmed with confidence_score=None / verification_threshold_applied=None,
which violates docintel's ck_documents_confirmation_invariants CHECK
constraint (both must be NOT NULL whenever confirmation_status='CONFIRMED').
The CONFIRMED UPDATE raised CheckViolationError, poisoning the worker's
transaction and leaving affected documents stuck retrying forever -- seen
live via Railway logs.

No DB/Docker dependency: this exercises the pure value-selection function
directly against the constraint's own logic, restated below.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from verigence.di.domain.enums import HumanVerificationStatus
from verigence.di.workers.job_runner import _non_scoring_confirmation_values

pytestmark = pytest.mark.no_docker


def _assert_satisfies_confirmation_invariant(
    confidence_score: Decimal | None,
    threshold_applied: Decimal | None,
    hvs: HumanVerificationStatus,
) -> None:
    """Restates ck_documents_confirmation_invariants' CONFIRMED-branch checks."""
    assert confidence_score is not None
    assert threshold_applied is not None
    expected_hvs = (
        HumanVerificationStatus.OPTIONAL
        if confidence_score > threshold_applied
        else HumanVerificationStatus.MANDATORY
    )
    assert hvs == expected_hvs


def test_ordinary_non_scoring_document_is_optional_at_full_confidence() -> None:
    """The common case (no deterministic rule failures): nothing to score,
    so record full confidence -- never needs review."""
    confidence_score, threshold_applied, hvs = _non_scoring_confirmation_values(
        Decimal("90.00"), deterministic_rules_force_review=False,
    )
    assert confidence_score == Decimal("100")
    assert threshold_applied == Decimal("90.00")
    assert hvs == HumanVerificationStatus.OPTIONAL
    _assert_satisfies_confirmation_invariant(confidence_score, threshold_applied, hvs)


def test_neither_value_is_none_regardless_of_branch() -> None:
    """The exact defect this function replaces: both values must always be
    NOT NULL whenever the document is about to be CONFIRMED."""
    for force_review in (True, False):
        confidence_score, threshold_applied, _hvs = _non_scoring_confirmation_values(
            Decimal("90.00"), deterministic_rules_force_review=force_review,
        )
        assert confidence_score is not None
        assert threshold_applied is not None


def test_deterministic_rule_failure_forces_mandatory_and_stays_consistent() -> None:
    """A normalization/validation failure elsewhere in the document still
    forces mandatory review even though there is nothing to score. Naively
    keeping confidence_score=100 here (as the ordinary case does) while
    forcing human_verification_status=MANDATORY would itself violate the
    constraint, since 100 > 90 derives OPTIONAL -- confidence must instead
    be recorded at-or-below the threshold so the derivation lines up."""
    confidence_score, threshold_applied, hvs = _non_scoring_confirmation_values(
        Decimal("90.00"), deterministic_rules_force_review=True,
    )
    assert hvs == HumanVerificationStatus.MANDATORY
    assert confidence_score <= threshold_applied
    _assert_satisfies_confirmation_invariant(confidence_score, threshold_applied, hvs)


def test_respects_a_tenant_specific_threshold() -> None:
    """effective_threshold varies per tenant (tenant override or global
    default) -- the returned threshold_applied must track whatever the
    caller passes in, not a hardcoded value."""
    confidence_score, threshold_applied, hvs = _non_scoring_confirmation_values(
        Decimal("75.50"), deterministic_rules_force_review=False,
    )
    assert threshold_applied == Decimal("75.50")
    _assert_satisfies_confirmation_invariant(confidence_score, threshold_applied, hvs)
