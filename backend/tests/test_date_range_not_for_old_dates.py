"""date_plausible_range is not run on dates that are years old by nature
(product owner 2026-10-29, calibration)."""
from __future__ import annotations

import pytest

from verigence.di.rules.runner import NOT_RECENT_DATE_FIELDS, applies_to_field

pytestmark = pytest.mark.no_docker


@pytest.mark.parametrize("field_key", sorted(NOT_RECENT_DATE_FIELDS))
def test_old_by_nature_dates_skip_the_recent_date_range(field_key):
    assert not applies_to_field("date_plausible_range", field_key)


@pytest.mark.parametrize("field_key", ["invoice_date", "receipt_date", "booking_date", "policy_start_date"])
def test_transaction_dates_keep_it(field_key):
    assert applies_to_field("date_plausible_range", field_key)


def test_other_rules_on_old_dates_still_run():
    assert applies_to_field("date_not_future", "date_of_birth")
    assert applies_to_field("date_plausible_range", None)
