"""Utkal's "Final Vehicle Accounts Statement" is read row by row (2026-11-04).

Live: 57 NDC copies on 46 bookings came back with their printed totals (Total
Cost, Total Receipt) and none of their rows, Utkal's two-column form above all,
and a forced re-read returned the same. The reader is now told how that form is
laid out and that a form whose rows carry amounts never returns totals only."""
from __future__ import annotations

import pytest

from verigence.di.document_ai.schemas import get_schema

pytestmark = pytest.mark.no_docker


def _notes() -> str:
    return " ".join(get_schema("customer_ledger").prompt_notes)


def test_the_two_column_vehicle_accounts_statement_is_described() -> None:
    notes = _notes()
    assert "Final Vehicle Accounts Statement" in notes
    assert "'Vehicle a/c details'" in notes and "'Payment a/c details'" in notes
    assert "'FINANCE D/O'" in notes and "'MR NO'" in notes
    assert "total_cost is the amount against Total Cost" in notes


def test_a_form_with_row_amounts_never_returns_totals_only() -> None:
    assert "never return only the totals of a form whose rows have amounts" in _notes()


def test_the_older_rules_stay() -> None:
    notes = _notes()
    assert "Do not put those summary rows" in notes and "OFFER LETTER / PAYMENT DETAILS" in notes
