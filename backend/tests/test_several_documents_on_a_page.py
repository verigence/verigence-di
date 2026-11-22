"""A page that carries more than one document is refused for what it is (22 Nov 2026).

Live that day: 27 pages PCs had typed as a receipt or an accessory invoice were
answered by the AI with several objects (25 of them with exactly two) and refused
as DOCUMENT_AI_RESPONSE_INVALID -- three attempts each, every time the page was
sent, and the PC read "AI reading failed. Please upload this page again". The
same page uploaded again got the same answer.

Product owner, 17 Nov: a page that carries two receipts is not accepted and is
not split. 22 Nov: such a page gets its own refusal, the PC is told to upload
each document as its own page, and it is not retried.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from verigence.di.document_ai import gemini_adapter
from verigence.di.document_ai.adapter import (
    DocumentAIProviderError,
    ExtractionField,
    SafeDocumentAIAdapter,
)
from verigence.di.document_ai.gemini_adapter import (
    GeminiResponseInvalidError,
    GeminiSeveralDocumentsError,
    _parse_response,
)
from verigence.di.document_ai.schemas import get_schema
from verigence.di.errors import ErrorCode
from verigence.di.retry_policy import DOCUMENT, failure_kind, retry_delay_seconds
from verigence.di.runtime_errors import BUSINESS, failure_category

_FIELDS = [ExtractionField(field_key=k) for k in ("receipt_number", "amount")]
CODE = "PAGE_HAS_SEVERAL_DOCUMENTS"


def _f(value: Any, page: int | None = 1) -> dict[str, Any]:
    return {"value": value, "confidence": "high", **({"pageNo": page} if page else {})}


def _receipt(number: str, amount: str, page: int | None = 1) -> dict[str, Any]:
    return {"receipt_number": _f(number, page), "amount": _f(amount, page)}


def _parse(answer: list[Any]) -> Any:
    return _parse_response(json.dumps(answer), get_schema("payment_receipt"), _FIELDS)


# ── the answer ────────────────────────────────────────────────────────────────
def test_two_receipts_on_one_page_are_refused_as_several_documents() -> None:
    with pytest.raises(GeminiSeveralDocumentsError) as caught:
        _parse([_receipt("SECRET-R-101", "50000"), _receipt("SECRET-R-102", "25000")])
    error = caught.value
    assert (error.technical_code, error.retryable, error.items, error.shared_pages) == (CODE, False, 2, [1])
    assert "SECRET" not in str(error)                      # nothing of the page in the error
    # (its shape is still logged without values: test_gemini_trailing_marks.py)
    # still a ValueError: schema authoring answers 422 for such a sample, as before
    assert isinstance(error, ValueError) and not isinstance(error, GeminiResponseInvalidError)


def test_three_documents_of_which_two_share_a_page() -> None:
    with pytest.raises(GeminiSeveralDocumentsError) as caught:
        _parse([_receipt("R-1", "1", 1), _receipt("R-2", "2", 2), _receipt("R-3", "3", 2)])
    assert (caught.value.items, caught.value.shared_pages) == (3, [2])


@pytest.mark.parametrize("answer", [
    # an object that holds nothing is not a second document
    [_receipt("R-1", "1"), {"receipt_number": _f(None), "amount": _f(None)}],
    # nothing says the two are on one page
    [_receipt("R-1", "1", None), _receipt("R-2", "2", None)],
    # not objects
    [_receipt("R-1", "1"), "R-2"],
    # pages out of order, none in common: an answer we cannot use, as before
    [_receipt("R-1", "1", 2), _receipt("R-2", "2", 1)],
])
def test_any_other_answer_of_several_items_stays_an_unusable_answer(answer: list[Any]) -> None:
    with pytest.raises(GeminiResponseInvalidError):
        _parse(answer)


def test_one_document_answered_one_object_per_page_is_still_merged() -> None:
    fields = [ExtractionField(field_key=k) for k in ("invoice_number", "grand_total_amount")]
    raw = json.dumps([
        {"invoice_number": _f("INV-1", 1), "grand_total_amount": _f("3000.00", 1)},
        {"invoice_number": _f("INV-1", 2), "grand_total_amount": _f("4746.00", 2)},
    ])
    result = {r.field_key: r.raw_value for r in _parse_response(raw, get_schema("accessory_invoice_dms"), fields)}
    assert result == {"invoice_number": "INV-1", "grand_total_amount": "4746.00"}


# ── one request, never retried ────────────────────────────────────────────────
class _Log:
    def __init__(self, bound: dict[str, Any] | None = None, events: list[Any] | None = None) -> None:
        self._bound = bound or {}
        self.events: list[tuple[str, str, dict[str, Any]]] = events if events is not None else []

    def bind(self, **kwargs: Any) -> _Log:
        return _Log({**self._bound, **kwargs}, self.events)

    def __getattr__(self, level: str):  # type: ignore[no-untyped-def]
        def record(event: str, **kwargs: Any) -> None:
            self.events.append((level, event, {**self._bound, **kwargs}))
        return record

    def find(self, event: str) -> list[dict[str, Any]]:
        return [fields for _level, name, fields in self.events if name == event]


@pytest.mark.asyncio
async def test_the_page_is_read_once_and_the_failure_is_not_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def two_receipts(**kwargs: Any) -> tuple[str, int, int, int]:
        calls.append(kwargs)
        return json.dumps([_receipt("SECRET-R-101", "50000"), _receipt("SECRET-R-102", "25000")]), 200, 900, 120

    async def no_sleep(_seconds: float) -> None:
        return None

    log = _Log()
    monkeypatch.setattr(gemini_adapter, "_call_gemini_instrumented", two_receipts)
    monkeypatch.setattr(gemini_adapter.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(gemini_adapter, "logger", log)
    adapter = SafeDocumentAIAdapter(gemini_adapter.GeminiDocumentAIAdapter("AQ.test"))

    with pytest.raises(DocumentAIProviderError) as caught:
        await adapter.extract(b"pdf", "application/pdf", _FIELDS, correlation_id="corr-x",
                              document_type_key="payment_receipt")

    assert (caught.value.technical_code, caught.value.retryable) == (CODE, False)
    assert len(calls) == 1 and not log.find("gemini_retry") and not log.find("gemini_parse_failure")
    [told] = log.find("gemini_several_documents")
    assert (told["items"], told["shared_pages"], told["error_code"]) == (2, [1], CODE)
    # nothing of the page above debug level (gemini_raw_response is debug, never written live)
    written = [event for event in log.events if event[0] != "debug"]
    assert "SECRET" not in str(caught.value) and "SECRET" not in json.dumps(written, default=str)


def test_it_is_the_document_not_the_ai_and_no_attempt_follows() -> None:
    assert failure_category(CODE) == BUSINESS
    assert failure_kind(CODE) == DOCUMENT
    for attempt in (1, 2):
        assert retry_delay_seconds(CODE, retryable=True, attempt_no=attempt) is None
    assert (ErrorCode.PAGE_HAS_SEVERAL_DOCUMENTS.code, ErrorCode.PAGE_HAS_SEVERAL_DOCUMENTS.retryable) == (CODE, False)
    # an answer we cannot use for any other reason is still tried again at 10 and 20 minutes
    assert retry_delay_seconds("DOCUMENT_AI_RESPONSE_INVALID", retryable=True, attempt_no=1) == 600
