"""Migrations 0058/0059 and the V2 classifier's candidate definitions.

The classifier shows each candidate as ``- key: display name — definition``
(docintel.document_types.description). These tests pin the migrations'
definition snapshots (0058's, updated by 0059's) to
GLOBAL_DOCUMENT_TYPE_DEFINITIONS, the resulting DB state, the candidate line
format and the worker's loading of definitions.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.document_ai import v2_classifier
from verigence.di.document_ai.invoice_taxonomy import INVOICE_CLASSIFICATION_HINTS
from verigence.di.document_ai.type_definitions import GLOBAL_DOCUMENT_TYPE_DEFINITIONS
from verigence.di.document_ai.v2_classifier import (
    DEFINITION_MAX_CHARS,
    _candidate_line,
    _prompt,
)
from verigence.di.settings import get_settings
from verigence.di.workers.capture_v2_classifier import classifier_candidates

_LEDGER = GLOBAL_DOCUMENT_TYPE_DEFINITIONS["customer_ledger"]
_COST_SHEET = GLOBAL_DOCUMENT_TYPE_DEFINITIONS["cost_sheet"]


_MIGRATIONS = {
    "0058": "0058_document_type_definitions.py",
    "0059": "0059_form_21_and_delivery_receipt_types.py",
    "0060": "0060_booking_form_is_not_the_offer_letter.py",
    "0062": "0062_transaction_regularization_form_is_supporting.py",
    "0064": "0064_gate_pass_is_not_a_delivery_receipt.py",
    "0065": "0065_money_receipt_is_the_dealerships.py",
}


def _migration(revision: str = "0058") -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / _MIGRATIONS[revision]
    spec = importlib.util.spec_from_file_location(f"mig_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.no_docker
def test_migration_definition_snapshot_equals_the_constant() -> None:
    # What the rows hold after head: 0058's definitions, then 0059's and 0060's over them.
    snapshot = {**_migration("0058")._DEFINITIONS, **_migration("0059")._DEFINITIONS,
                **_migration("0060")._DEFINITIONS, **_migration("0062")._DEFINITIONS,
                **_migration("0064")._DEFINITIONS, **_migration("0065")._DEFINITIONS}
    assert list(snapshot) == list(GLOBAL_DOCUMENT_TYPE_DEFINITIONS)
    assert snapshot == GLOBAL_DOCUMENT_TYPE_DEFINITIONS


@pytest.mark.no_docker
def test_0059_adds_the_two_types_and_rewrites_only_supporting_document() -> None:
    old, new = _migration("0058")._DEFINITIONS, _migration("0059")._DEFINITIONS
    assert set(new) == {"form_21", "delivery_receipt", "supporting_document"}
    assert "form_21" not in old and "delivery_receipt" not in old
    assert new["supporting_document"] != old["supporting_document"]
    assert {key for key, _, _ in _migration("0059")._NEW_DOCUMENT_TYPES} == {"form_21", "delivery_receipt"}


@pytest.mark.no_docker
@pytest.mark.parametrize("key", sorted(GLOBAL_DOCUMENT_TYPE_DEFINITIONS))
def test_each_definition_is_one_short_untruncated_line(key: str) -> None:
    definition = GLOBAL_DOCUMENT_TYPE_DEFINITIONS[key]
    assert definition == " ".join(definition.split())
    assert len(definition.split()) <= 65
    assert len(definition) <= DEFINITION_MAX_CHARS


@pytest.mark.no_docker
def test_neighbour_definitions_say_how_they_differ() -> None:
    defs = GLOBAL_DOCUMENT_TYPE_DEFINITIONS
    assert "customer_ledger" in defs["cost_sheet"] and "payments" in defs["cost_sheet"]
    for title in ("Account Statement", "Cost Sheet", "NDC", "Offer Letter / Payment Details"):
        assert title in _LEDGER.replace("Account(s)", "Account")
    # 2026-11-03: Shivnath's Offer Letter prints a booking amount and was filed as booking_form.
    assert "Offer Letter / Payment Details" in defs["booking_form"] and "customer_ledger" in defs["booking_form"]
    for receipt in ("payment_receipt", "dealer_receipt"):
        assert "New Vehicle Delivery Receipt" in defs[receipt]
    for invoice in ("customer_invoice_dms", "tax_invoice_tally", "tax_invoice_dms",
                    "tax_invoice", "customer_invoice_dms_v2", "wholesale_invoice"):
        assert "Form 21" in defs[invoice]
    # 2026-11-11: an insurer's premium receipt was classified dealer_receipt and counted as a payment
    # to the dealership. A money receipt is the dealership's own; another party's is supporting.
    for receipt in ("payment_receipt", "dealer_receipt"):
        assert "the vehicle dealership issues" in defs[receipt]
        assert "insurance company's premium receipt" in defs[receipt] and "supporting_document" in defs[receipt]
    assert "insurer's premium receipt" in defs["supporting_document"]
    for page in ("Form 21", "New Vehicle Delivery Receipt", "email", "covering letter"):
        assert page in defs["supporting_document"]
    # ... and sends those two to their own types when they are candidates.
    assert "is form_21" in defs["supporting_document"]
    assert "is delivery_receipt" in defs["supporting_document"]
    # 2026-11-05: the dealers' Transaction Regularization Form was classified cost_sheet.
    assert "Transaction Regularization Form" in defs["cost_sheet"] and "supporting_document" in defs["cost_sheet"]
    assert "Transaction Regularization Form" in defs["supporting_document"]
    assert "Rule 53" in defs["credit_note"]
    # The two new types say how they differ from what they were filed as.
    assert "Rule 47" in defs["form_21"] and "no prices" in defs["form_21"]
    assert "Sale(s) Certificate" in defs["form_21"]
    for unlike in ("no amount", "not a money receipt", "delivery order (DO)", "gate pass"):
        assert unlike in defs["delivery_receipt"]
    # 2026-11-11: Utkal's gate pass (a checklist the customer signs for the vehicle) was classified
    # delivery_receipt on 64 pages; a page titled Gate Pass is the gate pass, said from both sides.
    assert "titled Gate Pass is gate_pass, never delivery_receipt" in defs["gate_pass"]
    assert "customer signs" in defs["gate_pass"] and "chassis" in defs["gate_pass"]
    assert "titled Gate Pass is the gate pass (gate_pass)" in defs["delivery_receipt"]


@pytest.mark.no_docker
def test_candidate_line_appends_the_definition_after_a_dash() -> None:
    assert _candidate_line("customer_ledger", "Customer Ledger", _LEDGER) == (
        f"- customer_ledger: Customer Ledger — {_LEDGER}"
    )
    # whitespace (a definition edited with line breaks) is one line in the prompt
    assert _candidate_line("cost_sheet", "Cost Sheet", "A bare\n  quotation. ") == (
        "- cost_sheet: Cost Sheet — A bare quotation."
    )
    assert len(_candidate_line("x", "X", "w " * 2000)) <= len("- x: X — ") + DEFINITION_MAX_CHARS


@pytest.mark.no_docker
def test_candidate_line_without_a_definition_is_unchanged() -> None:
    assert _candidate_line("pan_card", "PAN Card") == "- pan_card: PAN Card"
    assert _candidate_line("pan_card", "PAN Card", None) == "- pan_card: PAN Card"
    assert _candidate_line("pan_card", "PAN Card", "  ") == "- pan_card: PAN Card"
    hint = INVOICE_CLASSIFICATION_HINTS["customer_invoice_dms"]
    assert _candidate_line("customer_invoice_dms", "Customer Invoice (DMS)") == (
        f"- customer_invoice_dms: Customer Invoice (DMS). Invoice discriminator: {hint}."
    )


@pytest.mark.no_docker
def test_invoice_candidate_keeps_its_discriminator_after_the_definition() -> None:
    definition = GLOBAL_DOCUMENT_TYPE_DEFINITIONS["customer_invoice_dms"]
    hint = INVOICE_CLASSIFICATION_HINTS["customer_invoice_dms"]
    assert _candidate_line("customer_invoice_dms", "Customer Invoice (DMS)", definition) == (
        f"- customer_invoice_dms: Customer Invoice (DMS) — {definition} "
        f"Invoice discriminator: {hint}."
    )
    assert _candidate_line("credit_note", "Credit Note", "A GST credit note") == (
        "- credit_note: Credit Note — A GST credit note. Invoice discriminator: "
        f"{INVOICE_CLASSIFICATION_HINTS['credit_note']}."
    )


@pytest.mark.no_docker
def test_prompt_lists_definitions_and_keeps_its_json_contract() -> None:
    candidates = [("cost_sheet", "Cost Sheet"), ("customer_ledger", "Customer Ledger"),
                  ("pan_card", "PAN Card")]
    prompt = _prompt(candidates, {"cost_sheet": _COST_SHEET, "customer_ledger": _LEDGER})
    assert f"- cost_sheet: Cost Sheet — {_COST_SHEET}\n" in prompt
    assert f"- customer_ledger: Customer Ledger — {_LEDGER}\n" in prompt
    assert "- pan_card: PAN Card\n- UNKNOWN: none of the candidates" in prompt
    assert "not by its printed title alone" in prompt
    assert prompt.endswith(
        'Return ONLY JSON in this form: '
        '{"documentTypeKey":"<candidate key or UNKNOWN>","confidence":<0-100 integer>}. '
        "Use confidence below 90 when the visible evidence is ambiguous."
    )


@pytest.mark.no_docker
def test_prompt_without_definitions_is_as_before() -> None:
    candidates = [("pan_card", "PAN Card"), ("aadhaar", "Aadhaar Card")]
    plain = _prompt(candidates)
    assert plain == _prompt(candidates, {}) == _prompt(candidates, {"pan_card": None})
    assert "definition" not in plain
    assert "Candidates:\n- pan_card: PAN Card\n- aadhaar: Aadhaar Card\n- UNKNOWN" in plain


@pytest.mark.no_docker
def test_worker_loads_candidates_in_order_with_their_definitions() -> None:
    rows: list[dict[str, Any]] = [
        {"document_type_key": "customer_ledger", "display_name": "Customer Ledger",
         "description": _LEDGER},
        {"document_type_key": "pan_card", "display_name": "PAN Card", "description": None},
        {"document_type_key": "customer_ledger", "display_name": "Customer Ledger",
         "description": "a later row"},
    ]
    candidates, definitions = classifier_candidates(rows)
    assert candidates[:2] == [("customer_ledger", "Customer Ledger"), ("pan_card", "PAN Card")]
    assert definitions == {"customer_ledger": _LEDGER, "pan_card": None}


class _Response:
    status_code = 200

    def json(self) -> dict[str, Any]:
        return {
            "candidates": [{"content": {"parts": [{"text": '{"documentTypeKey": "customer_ledger", '
                                                           '"confidence": 96}'}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 12},
        }


class _Client:
    body: dict[str, Any] = {}

    async def post(self, url: str, **kwargs: Any) -> _Response:
        type(self).body = kwargs["json"]
        return _Response()


@pytest.mark.no_docker
@pytest.mark.asyncio
async def test_classifier_sends_the_definitions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "docai_mock", False)

    async def client() -> _Client:
        return _Client()

    monkeypatch.setattr(v2_classifier, "_gemini_client", client)
    result = await v2_classifier.classify_document_v2(
        document_bytes=b"not-a-pdf", mime_type="application/octet-stream",
        candidates=[("cost_sheet", "Cost Sheet"), ("customer_ledger", "Customer Ledger")],
        definitions={"cost_sheet": _COST_SHEET, "customer_ledger": _LEDGER},
    )
    assert result.document_type_key == "customer_ledger"
    sent = _Client.body["contents"][0]["parts"][1]["text"]
    assert f"- customer_ledger: Customer Ledger — {_LEDGER}" in sent


@pytest.mark.asyncio
async def test_global_rows_carry_the_definitions(db_session: AsyncSession) -> None:
    rows = dict((await db_session.execute(text(
        "SELECT document_type_key, description FROM docintel.document_types "
        "WHERE owner_tenant_id IS NULL AND document_type_key = ANY(:keys)"
    ), {"keys": list(GLOBAL_DOCUMENT_TYPE_DEFINITIONS)})).all())
    assert {"customer_ledger", "cost_sheet", "supporting_document", "credit_note",
            "form_21", "delivery_receipt"} <= rows.keys()
    for key, description in rows.items():
        assert description == GLOBAL_DOCUMENT_TYPE_DEFINITIONS[key], key

    placeholder = (await db_session.execute(text(
        "SELECT count(*) FROM docintel.document_types "
        "WHERE owner_tenant_id IS NULL AND description = 'Schema V2 Wave-1 document type'"
    ))).scalar_one()
    assert placeholder == 0
