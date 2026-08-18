"""application/reconciliation.py — Seven deterministic reconciliation rules (D17).

Called by POST /v1/tenants/{tenantId}/analyse (D15).

The engine is pure Python — it receives pre-loaded indexed_field dicts
from document_search_index and returns a findings list + summary verdict.

Rule keys (D17):
  R1 AMOUNT_MATCH        — dealer receipt amounts == booking docket total
  R2 UTR_SUFFIX_MATCH    — RTGS ref on receipt is suffix of UTR in bank statement
  R3 DATE_PROXIMITY      — payment date within ±3 days of bank statement date
  R4 NAME_MATCH          — payee/payer name fuzzy-matches subject display_name (≥80%)
  R5 TOTAL_CHECK         — all receipts sum to booking total ±₹1
  R6 DATE_SEQUENCE       — delivery order date is after latest receipt date
  R7 DUPLICATE_DETECTION — no two receipts share amount + date + RTGS ref

Summary verdicts:
  RECONCILED          — all applicable rules PASS
  DISCREPANCY         — one or more applicable rules FAIL
  INSUFFICIENT_DATA   — no applicable rule could be evaluated (all SKIPPED)
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

# ── Domain types ──────────────────────────────────────────────────────────────

@dataclass
class Finding:
    rule_key: str
    result: str   # "PASS" | "FAIL" | "SKIPPED"
    detail: str


@dataclass
class ReconciliationResult:
    findings: list[Finding]
    summary: str              # "RECONCILED" | "DISCREPANCY" | "INSUFFICIENT_DATA"
    analysed_documents: int


# ── Helper utilities ──────────────────────────────────────────────────────────

def _to_float(value: Any) -> float | None:
    """Parse a numeric field value to float. Returns None on any error."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _to_date(value: Any) -> date | None:
    """Parse ISO date string (YYYY-MM-DD) or datetime to a date. Returns None on error."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def _strip_zeros(s: str) -> str:
    return s.lstrip("0") or "0"


def _fuzzy_ratio(a: str, b: str) -> float:
    """0.0–1.0 similarity using SequenceMatcher."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ── Rule implementations ──────────────────────────────────────────────────────

def _r1_amount_match(
    receipts: list[dict[str, Any]],
    bookings: list[dict[str, Any]],
) -> Finding:
    """R1: Sum of dealer receipt amounts == booking docket total."""
    receipt_amounts = [_to_float(r.get("amount") or r.get("total_amount")) for r in receipts]
    booking_totals  = [_to_float(b.get("total_price") or b.get("booking_total") or b.get("amount")) for b in bookings]

    if not any(a is not None for a in receipt_amounts):
        return Finding("R1_AMOUNT_MATCH", "SKIPPED", "No receipt amount fields found")
    if not any(t is not None for t in booking_totals):
        return Finding("R1_AMOUNT_MATCH", "SKIPPED", "No booking total fields found")

    receipt_sum   = sum(a for a in receipt_amounts if a is not None)
    booking_total = sum(t for t in booking_totals  if t is not None)

    if abs(receipt_sum - booking_total) <= 1.0:
        return Finding("R1_AMOUNT_MATCH", "PASS",
                       f"Receipt sum {receipt_sum} matches booking total {booking_total}")
    return Finding("R1_AMOUNT_MATCH", "FAIL",
                   f"Receipt sum {receipt_sum} ≠ booking total {booking_total}")


def _r2_utr_suffix_match(
    receipts: list[dict[str, Any]],
    bank_statements: list[dict[str, Any]],
) -> Finding:
    """R2: RTGS reference on receipt is a suffix of the UTR in bank statement."""
    rtgs_refs = [
        str(r.get("rtgs_reference") or r.get("utr_number") or "").strip()
        for r in receipts
    ]
    rtgs_refs = [r for r in rtgs_refs if r]

    utrs = [
        str(b.get("utr_number") or b.get("transaction_id") or "").strip()
        for b in bank_statements
    ]
    utrs = [u for u in utrs if u]

    if not rtgs_refs:
        return Finding("R2_UTR_SUFFIX_MATCH", "SKIPPED", "No RTGS reference found on receipts")
    if not utrs:
        return Finding("R2_UTR_SUFFIX_MATCH", "SKIPPED", "No UTR found in bank statements")

    for rtgs in rtgs_refs:
        stripped = _strip_zeros(rtgs)
        for utr in utrs:
            if utr.endswith(stripped):
                return Finding("R2_UTR_SUFFIX_MATCH", "PASS",
                               f"UTR {utr!r} ends with RTGS ref {rtgs!r}")
    return Finding("R2_UTR_SUFFIX_MATCH", "FAIL",
                   f"No UTR {utrs} ends with any RTGS ref {rtgs_refs}")


def _r3_date_proximity(
    receipts: list[dict[str, Any]],
    bank_statements: list[dict[str, Any]],
) -> Finding:
    """R3: Payment date on receipt is within ±3 days of bank statement transaction date."""
    parsed_receipt_dates = [
        _to_date(r.get("payment_date") or r.get("date")) for r in receipts
    ]
    receipt_dates: list[date] = [d for d in parsed_receipt_dates if d is not None]

    parsed_bank_dates = [
        _to_date(b.get("transaction_date") or b.get("date")) for b in bank_statements
    ]
    bank_dates: list[date] = [d for d in parsed_bank_dates if d is not None]

    if not receipt_dates:
        return Finding("R3_DATE_PROXIMITY", "SKIPPED", "No receipt payment date found")
    if not bank_dates:
        return Finding("R3_DATE_PROXIMITY", "SKIPPED", "No bank statement transaction date found")

    for rd in receipt_dates:
        for bd in bank_dates:
            delta = abs((rd - bd).days)
            if delta <= 3:
                return Finding("R3_DATE_PROXIMITY", "PASS",
                               f"Receipt date {rd} within {delta} days of bank date {bd}")

    closest = min(abs((rd - bd).days) for rd in receipt_dates for bd in bank_dates)
    return Finding("R3_DATE_PROXIMITY", "FAIL",
                   f"Closest date gap is {closest} days (threshold: 3)")


def _r4_name_match(
    receipts: list[dict[str, Any]],
    subject_display_name: str | None,
) -> Finding:
    """R4: Payee/payer name on receipt fuzzy-matches subject display_name (≥80%)."""
    if not subject_display_name:
        return Finding("R4_NAME_MATCH", "SKIPPED", "Subject display name not available")

    names = [
        str(r.get("payee_name") or r.get("payer_name") or r.get("customer_name") or "").strip()
        for r in receipts
    ]
    names = [n for n in names if n]

    if not names:
        return Finding("R4_NAME_MATCH", "SKIPPED", "No payee/payer name found on receipts")

    best = max(_fuzzy_ratio(n, subject_display_name) for n in names)
    if best >= 0.8:
        return Finding("R4_NAME_MATCH", "PASS",
                       f"Best name similarity {best:.0%} ≥ 80% threshold")
    return Finding("R4_NAME_MATCH", "FAIL",
                   f"Best name similarity {best:.0%} < 80% threshold")


def _r6_date_sequence(
    receipts: list[dict[str, Any]],
    delivery_orders: list[dict[str, Any]],
) -> Finding:
    """R6: Delivery order date is after the latest receipt date."""
    parsed_receipt_dates = [
        _to_date(r.get("payment_date") or r.get("date")) for r in receipts
    ]
    receipt_dates: list[date] = [d for d in parsed_receipt_dates if d is not None]

    parsed_delivery_dates = [
        _to_date(d.get("delivery_date") or d.get("date")) for d in delivery_orders
    ]
    delivery_dates: list[date] = [d for d in parsed_delivery_dates if d is not None]

    if not receipt_dates:
        return Finding("R6_DATE_SEQUENCE", "SKIPPED", "No receipt dates found")
    if not delivery_dates:
        return Finding("R6_DATE_SEQUENCE", "SKIPPED", "No delivery order dates found")

    latest_receipt   = max(receipt_dates)
    earliest_delivery = min(delivery_dates)

    if earliest_delivery >= latest_receipt:
        return Finding("R6_DATE_SEQUENCE", "PASS",
                       f"Delivery date {earliest_delivery} ≥ latest receipt date {latest_receipt}")
    return Finding("R6_DATE_SEQUENCE", "FAIL",
                   f"Delivery date {earliest_delivery} precedes latest receipt date {latest_receipt}")


def _r7_duplicate_detection(receipts: list[dict[str, Any]]) -> Finding:
    """R7: No two receipts share identical amount + date + RTGS reference."""
    if len(receipts) < 2:
        return Finding("R7_DUPLICATE_DETECTION", "SKIPPED",
                       "Fewer than 2 receipts — duplicate detection not applicable")

    seen: set[tuple[Any, Any, Any]] = set()
    for r in receipts:
        amount = _to_float(r.get("amount") or r.get("total_amount"))
        date_  = _to_date(r.get("payment_date") or r.get("date"))
        rtgs   = str(r.get("rtgs_reference") or r.get("utr_number") or "").strip()
        # Skip receipts with no identity fields — all-null keys cannot be compared
        if not amount and not date_ and not rtgs:
            continue
        key    = (amount, date_, rtgs)
        if key in seen:
            return Finding("R7_DUPLICATE_DETECTION", "FAIL",
                           f"Duplicate receipt detected: amount={amount}, date={date_}, ref={rtgs!r}")
        seen.add(key)

    return Finding("R7_DUPLICATE_DETECTION", "PASS",
                   f"All {len(receipts)} receipts are unique")


# ── Public engine ─────────────────────────────────────────────────────────────

def _r5_total_check_impl(
    receipts: list[dict[str, Any]],
    bookings: list[dict[str, Any]],
) -> Finding:
    receipt_amounts = [_to_float(r.get("amount") or r.get("total_amount")) for r in receipts]
    booking_totals  = [_to_float(b.get("total_price") or b.get("booking_total") or b.get("amount")) for b in bookings]

    if not any(a is not None for a in receipt_amounts):
        return Finding("R5_TOTAL_CHECK", "SKIPPED", "No receipt amount fields found")
    if not any(t is not None for t in booking_totals):
        return Finding("R5_TOTAL_CHECK", "SKIPPED", "No booking total fields found")

    receipt_sum   = sum(a for a in receipt_amounts if a is not None)
    booking_total = sum(t for t in booking_totals  if t is not None)

    if abs(receipt_sum - booking_total) <= 1.0:
        return Finding("R5_TOTAL_CHECK", "PASS",
                       f"Receipt sum {receipt_sum} matches booking total {booking_total}")
    return Finding("R5_TOTAL_CHECK", "FAIL",
                   f"Receipt sum {receipt_sum} ≠ booking total {booking_total}")


def run_reconciliation(
    *,
    documents: list[dict[str, Any]],
    subject_display_name: str | None = None,
) -> ReconciliationResult:
    """Run all 7 reconciliation rules against the supplied document set.

    Args:
        documents: List of document dicts, each with at least:
                   - "document_type_key": str
                   - "indexed_fields": dict[str, Any]
        subject_display_name: Subject's full display name (for R4 name matching).

    Returns:
        ReconciliationResult with findings list and summary verdict.
    """
    receipts        = [d["indexed_fields"] for d in documents if d.get("document_type_key") == "dealer_receipt"]
    bookings        = [d["indexed_fields"] for d in documents if d.get("document_type_key") in ("booking_form", "booking_docket")]
    bank_statements = [d["indexed_fields"] for d in documents if d.get("document_type_key") in ("bank_statement_extract", "bank_statement")]
    delivery_orders = [d["indexed_fields"] for d in documents if d.get("document_type_key") in ("delivery_order_cover", "delivery_order")]

    findings = [
        _r1_amount_match(receipts, bookings),
        _r2_utr_suffix_match(receipts, bank_statements),
        _r3_date_proximity(receipts, bank_statements),
        _r4_name_match(receipts, subject_display_name),
        _r5_total_check_impl(receipts, bookings),
        _r6_date_sequence(receipts, delivery_orders),
        _r7_duplicate_detection(receipts),
    ]

    applicable = [f for f in findings if f.result != "SKIPPED"]
    if not applicable:
        summary = "INSUFFICIENT_DATA"
    elif any(f.result == "FAIL" for f in applicable):
        summary = "DISCREPANCY"
    else:
        summary = "RECONCILED"

    return ReconciliationResult(
        findings=findings,
        summary=summary,
        analysed_documents=len(documents),
    )
