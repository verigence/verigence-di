"""tests/test_reconciliation.py — Unit tests for D17 reconciliation rules.

All tests are no_docker — pure Python logic, no DB.

Coverage:
  R1 AMOUNT_MATCH — pass, fail, skipped
  R2 UTR_SUFFIX_MATCH — pass, fail, skipped (leading zeros stripped)
  R3 DATE_PROXIMITY — pass within 3 days, fail beyond 3 days, skipped
  R4 NAME_MATCH — pass ≥80%, fail <80%, skipped (no name)
  R5 TOTAL_CHECK — pass ±1, fail >1
  R6 DATE_SEQUENCE — pass (delivery after receipt), fail (delivery before)
  R7 DUPLICATE_DETECTION — pass unique, fail duplicate, skipped (<2 receipts)
  run_reconciliation — RECONCILED / DISCREPANCY / INSUFFICIENT_DATA summary
  AnalyseRequest validation — at_least_one, max 50
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_docker


# ── Helpers ────────────────────────────────────────────────────────────────────

def _receipt(amount=1000.0, date="2024-01-15", rtgs="395659",
             payee_name="Rajan Kumar") -> dict:
    return {
        "amount": amount,
        "payment_date": date,
        "rtgs_reference": rtgs,
        "payee_name": payee_name,
    }


def _booking(total=1000.0) -> dict:
    return {"total_price": total}


def _bank(utr="KKBK0007395659", date="2024-01-16") -> dict:
    return {"utr_number": utr, "transaction_date": date}


def _delivery(date="2024-01-20") -> dict:
    return {"delivery_date": date}


# ── R1 AMOUNT_MATCH ────────────────────────────────────────────────────────────

class TestR1AmountMatch:
    def _run(self, receipts, bookings):
        from verigence.di.application.reconciliation import _r1_amount_match
        return _r1_amount_match(receipts, bookings)

    def test_pass_exact(self):
        f = self._run([_receipt(1000.0)], [_booking(1000.0)])
        assert f.result == "PASS"

    def test_pass_within_1(self):
        f = self._run([_receipt(999.5)], [_booking(1000.0)])
        assert f.result == "PASS"

    def test_fail_exceeds_tolerance(self):
        f = self._run([_receipt(900.0)], [_booking(1000.0)])
        assert f.result == "FAIL"

    def test_multiple_receipts_summed(self):
        f = self._run([_receipt(600.0), _receipt(400.0)], [_booking(1000.0)])
        assert f.result == "PASS"

    def test_skipped_no_receipts(self):
        f = self._run([], [_booking(1000.0)])
        assert f.result == "SKIPPED"

    def test_skipped_no_bookings(self):
        f = self._run([_receipt(1000.0)], [])
        assert f.result == "SKIPPED"

    def test_skipped_none_amounts(self):
        f = self._run([{"amount": None}], [_booking(1000.0)])
        assert f.result == "SKIPPED"


# ── R2 UTR_SUFFIX_MATCH ───────────────────────────────────────────────────────

class TestR2UtrSuffixMatch:
    def _run(self, receipts, bank_statements):
        from verigence.di.application.reconciliation import _r2_utr_suffix_match
        return _r2_utr_suffix_match(receipts, bank_statements)

    def test_pass_exact_suffix(self):
        f = self._run([_receipt(rtgs="395659")], [_bank(utr="KKBK0007395659")])
        assert f.result == "PASS"

    def test_pass_strip_leading_zeros(self):
        f = self._run([_receipt(rtgs="0395659")], [_bank(utr="KKBK0007395659")])
        assert f.result == "PASS"

    def test_fail_no_match(self):
        f = self._run([_receipt(rtgs="999999")], [_bank(utr="KKBK0007395659")])
        assert f.result == "FAIL"

    def test_skipped_no_receipts(self):
        f = self._run([], [_bank()])
        assert f.result == "SKIPPED"

    def test_skipped_no_bank(self):
        f = self._run([_receipt()], [])
        assert f.result == "SKIPPED"


# ── R3 DATE_PROXIMITY ─────────────────────────────────────────────────────────

class TestR3DateProximity:
    def _run(self, receipts, bank):
        from verigence.di.application.reconciliation import _r3_date_proximity
        return _r3_date_proximity(receipts, bank)

    def test_pass_same_day(self):
        f = self._run([_receipt(date="2024-01-15")], [_bank(date="2024-01-15")])
        assert f.result == "PASS"

    def test_pass_3_days_apart(self):
        f = self._run([_receipt(date="2024-01-12")], [_bank(date="2024-01-15")])
        assert f.result == "PASS"

    def test_fail_4_days_apart(self):
        f = self._run([_receipt(date="2024-01-11")], [_bank(date="2024-01-15")])
        assert f.result == "FAIL"

    def test_skipped_no_receipt_date(self):
        f = self._run([{"amount": 100}], [_bank()])
        assert f.result == "SKIPPED"

    def test_skipped_no_bank_date(self):
        f = self._run([_receipt()], [{"utr_number": "ABC"}])
        assert f.result == "SKIPPED"


# ── R4 NAME_MATCH ─────────────────────────────────────────────────────────────

class TestR4NameMatch:
    def _run(self, receipts, subject_name):
        from verigence.di.application.reconciliation import _r4_name_match
        return _r4_name_match(receipts, subject_name)

    def test_pass_exact(self):
        f = self._run([_receipt(payee_name="Rajan Kumar")], "Rajan Kumar")
        assert f.result == "PASS"

    def test_pass_fuzzy_above_80(self):
        # "Rajan Kumar" vs "Rajan Kumaar" — close enough
        f = self._run([_receipt(payee_name="Rajan Kumaar")], "Rajan Kumar")
        assert f.result == "PASS"

    def test_fail_low_similarity(self):
        f = self._run([_receipt(payee_name="John Doe")], "Rajan Kumar")
        assert f.result == "FAIL"

    def test_skipped_no_subject_name(self):
        f = self._run([_receipt()], None)
        assert f.result == "SKIPPED"

    def test_skipped_no_payee_name(self):
        f = self._run([{"amount": 100}], "Rajan Kumar")
        assert f.result == "SKIPPED"


# ── R5 TOTAL_CHECK ────────────────────────────────────────────────────────────

class TestR5TotalCheck:
    def _run(self, receipts, bookings):
        from verigence.di.application.reconciliation import _r5_total_check_impl
        return _r5_total_check_impl(receipts, bookings)

    def test_pass_exact(self):
        f = self._run([_receipt(1000.0)], [_booking(1000.0)])
        assert f.result == "PASS"
        assert f.rule_key == "R5_TOTAL_CHECK"

    def test_pass_within_1(self):
        f = self._run([_receipt(1000.50)], [_booking(1001.0)])
        assert f.result == "PASS"

    def test_fail(self):
        f = self._run([_receipt(500.0)], [_booking(1000.0)])
        assert f.result == "FAIL"


# ── R6 DATE_SEQUENCE ──────────────────────────────────────────────────────────

class TestR6DateSequence:
    def _run(self, receipts, delivery_orders):
        from verigence.di.application.reconciliation import _r6_date_sequence
        return _r6_date_sequence(receipts, delivery_orders)

    def test_pass_delivery_after(self):
        f = self._run([_receipt(date="2024-01-15")], [_delivery("2024-01-20")])
        assert f.result == "PASS"

    def test_pass_same_day(self):
        f = self._run([_receipt(date="2024-01-15")], [_delivery("2024-01-15")])
        assert f.result == "PASS"

    def test_fail_delivery_before(self):
        f = self._run([_receipt(date="2024-01-15")], [_delivery("2024-01-10")])
        assert f.result == "FAIL"

    def test_skipped_no_receipts(self):
        f = self._run([], [_delivery()])
        assert f.result == "SKIPPED"

    def test_skipped_no_delivery(self):
        f = self._run([_receipt()], [])
        assert f.result == "SKIPPED"


# ── R7 DUPLICATE_DETECTION ────────────────────────────────────────────────────

class TestR7DuplicateDetection:
    def _run(self, receipts):
        from verigence.di.application.reconciliation import _r7_duplicate_detection
        return _r7_duplicate_detection(receipts)

    def test_pass_unique(self):
        f = self._run([_receipt(1000.0), _receipt(500.0)])
        assert f.result == "PASS"

    def test_fail_duplicate(self):
        f = self._run([_receipt(1000.0), _receipt(1000.0)])
        assert f.result == "FAIL"

    def test_skipped_single_receipt(self):
        f = self._run([_receipt()])
        assert f.result == "SKIPPED"

    def test_skipped_no_receipts(self):
        f = self._run([])
        assert f.result == "SKIPPED"


# ── run_reconciliation — summary verdicts ─────────────────────────────────────

class TestRunReconciliation:
    def test_reconciled_all_pass(self):
        from verigence.di.application.reconciliation import run_reconciliation

        docs = [
            {"document_type_key": "dealer_receipt",
             "indexed_fields": _receipt(1000.0)},
            {"document_type_key": "booking_form",
             "indexed_fields": _booking(1000.0)},
        ]
        result = run_reconciliation(documents=docs, subject_display_name="Rajan Kumar")
        # R1 and R5 should PASS; others SKIPPED (no bank/delivery); summary = RECONCILED
        assert result.summary == "RECONCILED"
        assert result.analysed_documents == 2

    def test_discrepancy_when_any_fail(self):
        from verigence.di.application.reconciliation import run_reconciliation

        docs = [
            {"document_type_key": "dealer_receipt",
             "indexed_fields": _receipt(500.0)},   # mismatch
            {"document_type_key": "booking_form",
             "indexed_fields": _booking(1000.0)},
        ]
        result = run_reconciliation(documents=docs)
        assert result.summary == "DISCREPANCY"

    def test_insufficient_data_all_skipped(self):
        from verigence.di.application.reconciliation import run_reconciliation

        # Documents with no extractable fields
        docs = [
            {"document_type_key": "unknown_type", "indexed_fields": {}},
        ]
        result = run_reconciliation(documents=docs)
        assert result.summary == "INSUFFICIENT_DATA"

    def test_findings_list_length(self):
        from verigence.di.application.reconciliation import run_reconciliation

        result = run_reconciliation(documents=[], subject_display_name=None)
        # All 7 rules should be present
        assert len(result.findings) == 7

    def test_analysed_documents_count(self):
        from verigence.di.application.reconciliation import run_reconciliation

        docs = [
            {"document_type_key": "dealer_receipt", "indexed_fields": {}},
            {"document_type_key": "booking_form", "indexed_fields": {}},
            {"document_type_key": "bank_statement_extract", "indexed_fields": {}},
        ]
        result = run_reconciliation(documents=docs)
        assert result.analysed_documents == 3


# ── AnalyseRequest validation ─────────────────────────────────────────────────

class TestAnalyseRequest:
    def test_empty_list_rejected(self):
        from pydantic import ValidationError

        from verigence.di.api.v1.analyse import AnalyseRequest

        with pytest.raises(ValidationError):
            AnalyseRequest(document_ids=[])

    def test_too_many_rejected(self):
        from pydantic import ValidationError

        from verigence.di.api.v1.analyse import AnalyseRequest

        with pytest.raises(ValidationError):
            AnalyseRequest(document_ids=["x"] * 51)

    def test_valid_single(self):
        from verigence.di.api.v1.analyse import AnalyseRequest

        req = AnalyseRequest(document_ids=["abc"])
        assert len(req.document_ids) == 1

    def test_valid_50(self):
        from verigence.di.api.v1.analyse import AnalyseRequest

        req = AnalyseRequest(document_ids=["x"] * 50)
        assert len(req.document_ids) == 50
