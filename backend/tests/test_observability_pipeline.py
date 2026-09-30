"""tests/test_observability_pipeline.py

Error classification, retry decisions, log levels/fields and persisted
failure-text safety across the DI processing pipeline:

- provider failure codes and retryability survive from the adapter to the job;
- Gemini parse failures / safety blocks get their own codes;
- Capture V2 classification failures carry status/retryability, and a corrupt
  upload or a missing type configuration is not retried;
- failure events carry ``error_category`` and durations at the right level;
- persisted failure details never contain exception text;
- the job context reaches logs emitted below the worker;
- the heartbeat survives a failing queue-depth query.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import structlog

from verigence.di.document_ai import gemini_adapter, v2_classifier
from verigence.di.document_ai.adapter import (
    AIInvocationResult,
    ClassificationCandidate,
    DocumentAIAdapter,
    DocumentAIProviderError,
    ExtractionField,
    SafeDocumentAIAdapter,
)
from verigence.di.document_ai.gemini_cost import GeminiUsage, usage_from_response
from verigence.di.domain.enums import AICapability
from verigence.di.rules import runner as rules_runner
from verigence.di.rules.normalizers import NormalizerResult
from verigence.di.runtime_errors import (
    BUSINESS,
    CONFIGURATION,
    DEPENDENCY,
    TECHNICAL,
    failure_category,
    technical_failure,
)
from verigence.di.scheduler import beat
from verigence.di.settings import get_settings
from verigence.di.workers import capture_v2_classifier, heartbeat, job_runner, processor

pytestmark = pytest.mark.no_docker

SECRET = "customer-secret-value s3://bucket/tenant/key.pdf"


class _Log:
    """Records (level, event, fields); bind() merges fields like structlog."""

    def __init__(self, bound: dict[str, Any] | None = None, events: list[Any] | None = None) -> None:
        self._bound = bound or {}
        self.events: list[tuple[str, str, dict[str, Any]]] = events if events is not None else []

    def bind(self, **kwargs: Any) -> _Log:
        return _Log({**self._bound, **kwargs}, self.events)

    def __getattr__(self, level: str):  # type: ignore[no-untyped-def]
        def record(event: str, **kwargs: Any) -> None:
            self.events.append((level, event, {**self._bound, **kwargs}))
        return record

    def find(self, event: str) -> list[tuple[str, dict[str, Any]]]:
        return [(level, fields) for level, name, fields in self.events if name == event]


async def _no_sleep(_: float) -> None:
    return None


# ── categories ────────────────────────────────────────────────────────────────

def test_failure_categories() -> None:
    assert failure_category("CLASSIFICATION_AMBIGUOUS") == BUSINESS
    assert failure_category("INVALID_FILE_CONTENT") == BUSINESS
    assert failure_category("DOCUMENT_AI_CONTENT_BLOCKED") == BUSINESS
    assert failure_category("EXTRACTION_PROFILE_EMPTY") == CONFIGURATION
    assert failure_category("DOCUMENT_TYPE_NOT_FOUND") == CONFIGURATION
    assert failure_category("DOCUMENT_AI_RATE_LIMITED") == DEPENDENCY
    assert failure_category("STORAGE_READ_ERROR") == DEPENDENCY
    assert failure_category("WORKER_INTERNAL_ERROR") == TECHNICAL
    assert failure_category(None) == TECHNICAL


def test_provider_status_mapping_keeps_retryability() -> None:
    rejected = technical_failure(gemini_adapter.GeminiApiError(400, "bad"), operation="extraction_provider")
    assert (rejected.code, rejected.retryable) == ("DOCUMENT_AI_REQUEST_REJECTED", False)
    limited = technical_failure(gemini_adapter.GeminiApiError(429, "slow"), operation="extraction_provider")
    assert (limited.code, limited.retryable) == ("DOCUMENT_AI_RATE_LIMITED", True)
    timeout = technical_failure(httpx.ReadTimeout("t"), operation="extraction_provider")
    assert (timeout.code, timeout.retryable) == ("DOCUMENT_AI_UNAVAILABLE", True)


# ── Gemini extraction adapter ────────────────────────────────────────────────

def _gemini(monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]], behaviour: Any) -> _Log:
    async def fake_call(**kwargs: Any) -> tuple[str, int, int, int]:
        calls.append(kwargs)
        return await behaviour(len(calls), kwargs)

    log = _Log()
    monkeypatch.setattr(gemini_adapter, "_call_gemini_instrumented", fake_call)
    monkeypatch.setattr(gemini_adapter.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(gemini_adapter, "logger", log)
    return log


async def _extract_safely() -> Any:
    adapter = SafeDocumentAIAdapter(gemini_adapter.GeminiDocumentAIAdapter("AQ.test"))
    return await adapter.extract(b"pdf", "application/pdf", [ExtractionField(field_key="customer_name")],
                                 correlation_id="corr-x", document_type_key="booking_form")


@pytest.mark.asyncio
async def test_rejected_request_is_not_retried_and_keeps_its_code(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def reject(_n: int, _kw: dict[str, Any]) -> tuple[str, int, int, int]:
        raise gemini_adapter.GeminiApiError(400, SECRET)

    log = _gemini(monkeypatch, calls, reject)
    with pytest.raises(DocumentAIProviderError) as caught:
        await _extract_safely()
    assert (caught.value.technical_code, caught.value.retryable) == ("DOCUMENT_AI_REQUEST_REJECTED", False)
    assert len(calls) == 1
    assert SECRET not in str(caught.value)
    [(level, fields)] = log.find("gemini_api_error")
    assert level == "error" and fields["will_retry"] is False and fields["http_status"] == 400


@pytest.mark.asyncio
async def test_unavailable_is_warning_while_retrying_then_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def unavailable(_n: int, _kw: dict[str, Any]) -> tuple[str, int, int, int]:
        raise gemini_adapter.GeminiApiError(503, "busy")

    log = _gemini(monkeypatch, calls, unavailable)
    with pytest.raises(DocumentAIProviderError) as caught:
        await _extract_safely()
    assert (caught.value.technical_code, caught.value.retryable) == ("DOCUMENT_AI_UNAVAILABLE", True)
    assert [level for level, _ in log.find("gemini_api_error")] == ["warning", "error"]
    assert all("duration_ms" in fields and "total_duration_ms" in fields
               for _, fields in log.find("gemini_api_error"))


@pytest.mark.asyncio
async def test_unparseable_output_becomes_response_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def garbage(_n: int, kwargs: dict[str, Any]) -> tuple[str, int, int, int]:
        kwargs["on_usage"](GeminiUsage(finish_reason="STOP"))
        return "not json at all", 200, 10, 5

    log = _gemini(monkeypatch, calls, garbage)
    with pytest.raises(DocumentAIProviderError) as caught:
        await _extract_safely()
    assert (caught.value.technical_code, caught.value.retryable) == ("DOCUMENT_AI_RESPONSE_INVALID", True)
    assert len(calls) == 2
    levels = [level for level, _ in log.find("gemini_parse_failure")]
    assert levels == ["warning", "error"]
    assert log.find("gemini_parse_failure")[0][1]["finish_reason"] == "STOP"


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload


class _Client:
    response: _Response

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def post(self, url: str, **kwargs: object) -> _Response:
        del url, kwargs
        return type(self).response


@pytest.mark.asyncio
async def test_safety_block_is_its_own_non_retryable_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _Client.response = _Response(200, {"promptFeedback": {"blockReason": "SAFETY"},
                                       "usageMetadata": {"promptTokenCount": 900}})
    monkeypatch.setattr(gemini_adapter.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(gemini_adapter.asyncio, "sleep", _no_sleep)
    log = _Log()
    monkeypatch.setattr(gemini_adapter, "logger", log)

    with pytest.raises(DocumentAIProviderError) as caught:
        await _extract_safely()

    assert (caught.value.technical_code, caught.value.retryable) == ("DOCUMENT_AI_CONTENT_BLOCKED", False)
    [(level, fields)] = log.find("gemini_content_blocked")
    assert fields["block_reason"] == "SAFETY"
    assert not log.find("gemini_retry")


@pytest.mark.asyncio
async def test_gemini_response_logs_usage_finish_and_response_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    payload = {
        "responseId": "gemini-resp-123",
        "modelVersion": "gemini-3-flash-preview",
        "candidates": [{"finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 60, "thoughtsTokenCount": 40,
                          "cachedContentTokenCount": 700, "totalTokenCount": 1100},
    }

    async def ok(_n: int, kwargs: dict[str, Any]) -> tuple[str, int, int, int]:
        kwargs["on_usage"](usage_from_response(payload))
        return '{"customer_name": {"value": "A", "confidence": "high"}}', 200, 1000, 60

    log = _gemini(monkeypatch, calls, ok)
    result = await _extract_safely()

    assert result.provider_request_id == "gemini-resp-123"
    assert result.adapter_key == "gemini_3_flash_preview_v1"
    [(level, fields)] = log.find("gemini_response")
    assert level == "info"
    assert fields["finish_reason"] == "STOP"
    assert fields["provider_request_id"] == "gemini-resp-123"
    assert (fields["total_tokens"], fields["cached_tokens"], fields["thoughts_tokens"]) == (1100, 700, 40)
    assert "duration_ms" in fields and "total_duration_ms" in fields
    assert result.usage_metrics["cached_tokens"] == 700


# ── Job runner: provider codes, scores, safe persisted detail ────────────────

class _ClassifyAdapter(DocumentAIAdapter):
    def __init__(self, *, error: BaseException | None = None, confidence: str = "95") -> None:
        self._error = error
        self._confidence = confidence

    @property
    def adapter_key(self) -> str:
        return "test_adapter"

    async def classify(self, artifact_bytes: bytes, mime_type: str, candidate_type_keys: list[str],
                       hint: str | None = None, correlation_id: str | None = None) -> AIInvocationResult:
        if self._error is not None:
            raise self._error
        return AIInvocationResult(
            capability=AICapability.CLASSIFICATION, adapter_key=self.adapter_key, provider_request_id="p",
            results=[ClassificationCandidate("pan_card", Decimal(self._confidence), "TEST", {}),
                     ClassificationCandidate("aadhaar", Decimal("12.5"), "TEST", {})],
            usage_metrics={},
        )

    async def extract(self, artifact_bytes: bytes, mime_type: str, fields: list[ExtractionField],
                      correlation_id: str | None = None, physical_form_type: str = "PRINTABLE",
                      document_type_key: str | None = None) -> AIInvocationResult:
        raise AssertionError("not reached")


def _runner_harness(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, list[dict[str, Any]], _Log]:
    session = AsyncMock()
    invocations: list[dict[str, Any]] = []

    async def update_invocation(_s: Any, _t: str, _i: uuid.UUID, outcome: str, **kwargs: Any) -> None:
        invocations.append({"outcome": outcome, **kwargs})

    candidates = [{"document_type_id": uuid.uuid4(), "document_type_key": "pan_card", "profile_id": uuid.uuid4()},
                  {"document_type_id": uuid.uuid4(), "document_type_key": "aadhaar", "profile_id": uuid.uuid4()}]
    monkeypatch.setattr(job_runner, "_get_tenant_settings",
                        AsyncMock(return_value={"classification_acceptance_score": Decimal("90")}))
    monkeypatch.setattr(job_runner, "_get_document_hint_key", AsyncMock(return_value=None))
    monkeypatch.setattr(job_runner, "_form_candidate_set", AsyncMock(return_value=candidates))
    monkeypatch.setattr(job_runner, "_get_document_subject_id", AsyncMock(return_value=None))
    monkeypatch.setattr(job_runner, "_load_original_artifact",
                        AsyncMock(return_value=(b"pdf", "application/pdf")))
    monkeypatch.setattr(job_runner, "_insert_invocation", AsyncMock())
    monkeypatch.setattr(job_runner, "_update_invocation", update_invocation)
    log = _Log()
    monkeypatch.setattr(job_runner, "logger", log)
    return session, invocations, log


async def _run(session: AsyncMock, adapter: DocumentAIAdapter) -> job_runner.JobRunResult:
    return await job_runner.run_processing_job(
        session=session, tenant_id="t1", document_id=uuid.uuid4(), processing_job_id=uuid.uuid4(),
        job_type="INITIAL", correlation_id="corr-1", ai_adapter=adapter,
    )


def _persisted_run_failure(session: AsyncMock) -> dict[str, Any]:
    for call in session.execute.call_args_list:
        if "run_status = 'FAILED'" in str(call.args[0]):
            params: dict[str, Any] = call.args[1]
            return params
    raise AssertionError("processing run was not failed")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(429, "DOCUMENT_AI_RATE_LIMITED", True), (503, "DOCUMENT_AI_UNAVAILABLE", True),
     (400, "DOCUMENT_AI_REQUEST_REJECTED", False)],
)
async def test_provider_code_and_retryability_reach_the_job(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, retryable: bool,
) -> None:
    session, invocations, _ = _runner_harness(monkeypatch)
    raw = gemini_adapter.GeminiApiError(status, SECRET)
    safe = SafeDocumentAIAdapter(_ClassifyAdapter(error=raw))

    result = await _run(session, safe)

    assert (result.error_code, result.retryable) == (code, retryable)
    assert invocations[-1]["outcome"] == "FAILED"
    assert SECRET not in invocations[-1]["error_detail"]
    assert _persisted_run_failure(session)["error_class"] == ("RETRYABLE" if retryable else "NON_RETRYABLE")


@pytest.mark.asyncio
async def test_ambiguous_classification_logs_the_real_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, log = _runner_harness(monkeypatch)

    result = await _run(session, _ClassifyAdapter(confidence="42.00"))

    assert result.error_code == "CLASSIFICATION_AMBIGUOUS" and result.retryable is False
    [(level, fields)] = log.find("classification_failed")
    assert fields["scores"] == [("pan_card", "42.00"), ("aadhaar", "12.5")]
    assert fields["error_category"] == BUSINESS


@pytest.mark.asyncio
async def test_unexpected_worker_error_persists_only_the_exception_type(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, log = _runner_harness(monkeypatch)
    monkeypatch.setattr(job_runner, "_execute_steps", AsyncMock(side_effect=KeyError(SECRET)))

    result = await _run(session, _ClassifyAdapter())

    params = _persisted_run_failure(session)
    assert params["error_code"] == "WORKER_INTERNAL_ERROR"
    assert "KeyError" in params["error_detail"] and SECRET not in params["error_detail"]
    assert result.error_detail is not None and SECRET not in result.error_detail
    [(level, fields)] = log.find("processing_run_unexpected_error")
    assert level == "error" and fields["exception_type"] == "KeyError"


class _BrokenStorage:
    async def get_stream(self, key: str) -> Any:
        raise RuntimeError(f"NoSuchKey: {SECRET}")
        yield b""  # pragma: no cover


@pytest.mark.asyncio
async def test_storage_read_failure_detail_has_no_bucket_or_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import verigence.di.storage.adapter as storage_adapter

    monkeypatch.setattr(storage_adapter, "get_storage_adapter", lambda: _BrokenStorage())
    log = _Log()
    monkeypatch.setattr(job_runner, "logger", log)
    session = AsyncMock()
    row = MagicMock()
    row.one_or_none.return_value = ("tenant/doc/original.pdf", "application/pdf", "s1")
    session.execute = AsyncMock(return_value=row)

    with pytest.raises(job_runner.RetryableError) as caught:
        await job_runner._load_original_artifact(session, "t1", uuid.uuid4())

    assert caught.value.code == "STORAGE_READ_ERROR"
    assert SECRET not in caught.value.detail and "RuntimeError" in caught.value.detail
    [(level, fields)] = log.find("artifact_download_failed")
    assert "duration_ms" in fields


def test_normalizer_exception_text_is_not_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(_value: Any, _params: Any) -> NormalizerResult:
        raise ValueError(SECRET)

    monkeypatch.setattr(rules_runner, "get_normalizer", lambda _key: explode)
    result = rules_runner._run_normalizers("raw", [{"implementation_key": "boom"}])
    assert result.ok is False
    assert result.message is not None and SECRET not in result.message and "ValueError" in result.message


@pytest.mark.asyncio
async def test_validator_exception_text_is_not_persisted(monkeypatch: pytest.MonkeyPatch) -> None:
    field_id = uuid.uuid4()

    def explode(*_args: Any) -> Any:
        raise ValueError(SECRET)

    monkeypatch.setattr(rules_runner, "_load_normalizer_configs", AsyncMock(return_value={}))
    monkeypatch.setattr(rules_runner, "_load_validator_configs", AsyncMock(return_value={
        field_id: [{"rule_key": "r1", "implementation_key": "boom", "parameters": {}, "severity": "ERROR"}],
    }))
    monkeypatch.setattr(rules_runner, "get_validator", lambda _key: explode)
    session = AsyncMock()

    await rules_runner.normalize_and_validate(
        session=session, tenant_id="t1", document_id=uuid.uuid4(), processing_run_id=uuid.uuid4(),
        profile_id=uuid.uuid4(),
        extracted_fields=[rules_runner.ExtractedFieldInput(uuid.uuid4(), field_id, uuid.uuid4(), "raw", "FOUND")],
    )

    messages = [call.args[1].get("message") for call in session.execute.call_args_list
                if "validation_results" in str(call.args[0])]
    assert messages and all(SECRET not in str(m) and "ValueError" in str(m) for m in messages)


# ── Processor: levels, durations, per-job context ─────────────────────────────

def _session_factory() -> MagicMock:
    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session = AsyncMock()
    session.begin = MagicMock(return_value=begin_cm)
    outer = AsyncMock()
    outer.__aenter__ = AsyncMock(return_value=session)
    outer.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=outer)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "retryable", "level"),
    [("CLASSIFICATION_AMBIGUOUS", False, "info"), ("EXTRACTION_PROFILE_EMPTY", False, "warning"),
     ("DOCUMENT_AI_UNAVAILABLE", True, "error"), ("WORKER_INTERNAL_ERROR", True, "error")],
)
async def test_terminal_failure_level_follows_the_category(
    monkeypatch: pytest.MonkeyPatch, code: str, retryable: bool, level: str,
) -> None:
    monkeypatch.setattr(processor, "fail_job", AsyncMock())
    monkeypatch.setattr(processor, "insert_backout_job", AsyncMock())
    log = _Log()
    await processor._handle_failure(
        session_factory=_session_factory(), tenant_id="t1", job_id=uuid.uuid4(), document_id=uuid.uuid4(),
        correlation_id="c", processing_run_id=None, error_code=code, error_detail=None, retryable=retryable,
        attempt_no=2, is_capture_v2=False, job_log=log, duration_ms=12.5,
    )
    [(logged_level, fields)] = log.find("job_failed_backout")
    assert logged_level == level
    assert fields["error_category"] == failure_category(code) and fields["duration_ms"] == 12.5


@pytest.mark.asyncio
async def test_job_context_reaches_logs_below_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(**_: Any) -> job_runner.JobRunResult:
        seen.update(structlog.contextvars.get_contextvars())
        return job_runner.JobRunResult(success=True, processing_run_id=uuid.uuid4(),
                                       confidence_score=Decimal("95"), human_verification_status="OPTIONAL")

    monkeypatch.setattr(processor, "run_processing_job", fake_run)
    monkeypatch.setattr(processor, "complete_job", AsyncMock())
    job_id = uuid.uuid4()
    log = _Log()
    outcome = await processor._execute_claimed_job(
        session_factory=_session_factory(),
        job={"tenant_id": "t1", "processing_job_id": job_id, "document_id": uuid.uuid4(),
             "correlation_id": "audit-core-corr", "job_type": "INITIAL", "attempt_no": 1},
        ai_adapter=_ClassifyAdapter(), log=log,
    )

    assert outcome == "completed"
    assert seen["processing_job_id"] == str(job_id)
    assert seen["attempt_no"] == 1 and seen["correlation_id"] == "audit-core-corr"
    assert "processing_job_id" not in structlog.contextvars.get_contextvars()
    [(_, claimed)] = log.find("job_claimed")
    assert claimed["attempt_no"] == 1


def test_notify_received_is_debug() -> None:
    source = inspect.getsource(processor._NotifyWorker._open_notify_conn)
    assert 'logger.debug(\n                "notify_received"' in source


# ── Capture V2 classification ────────────────────────────────────────────────

class _V2Client:
    response: Any

    async def post(self, url: str, **kwargs: Any) -> Any:
        del url, kwargs
        if isinstance(type(self).response, BaseException):
            raise type(self).response
        return type(self).response


async def _classify_v2(monkeypatch: pytest.MonkeyPatch, response: Any, *, document: bytes = b"x",
                       mime: str = "application/octet-stream") -> Any:
    monkeypatch.setattr(get_settings(), "docai_mock", False)
    _V2Client.response = response

    async def client() -> _V2Client:
        return _V2Client()

    monkeypatch.setattr(v2_classifier, "_gemini_client", client)
    return await v2_classifier.classify_document_v2(
        document_bytes=document, mime_type=mime, candidates=[("pan_card", "PAN Card")],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(429, "DOCUMENT_AI_RATE_LIMITED", True), (503, "DOCUMENT_AI_UNAVAILABLE", True),
     (400, "DOCUMENT_AI_REQUEST_REJECTED", False)],
)
async def test_v2_http_failures_carry_status_and_retryability(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, retryable: bool,
) -> None:
    with pytest.raises(v2_classifier.V2ClassificationError) as caught:
        await _classify_v2(monkeypatch, _Response(status, {}))
    assert caught.value.status_code == status
    failure = technical_failure(caught.value, operation="capture_v2_classification")
    assert (failure.code, failure.retryable) == (code, retryable)


@pytest.mark.asyncio
async def test_v2_transport_error_is_retryable_provider_unavailability(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(v2_classifier.V2ClassificationError) as caught:
        await _classify_v2(monkeypatch, httpx.ConnectTimeout("t"))
    assert (caught.value.technical_code, caught.value.retryable) == ("DOCUMENT_AI_UNAVAILABLE", True)


@pytest.mark.asyncio
@pytest.mark.parametrize("document", [b"%PDF-1.4 truncated garbage", b""])
async def test_v2_corrupt_pdf_is_a_non_retryable_business_failure(
    monkeypatch: pytest.MonkeyPatch, document: bytes,
) -> None:
    with pytest.raises(v2_classifier.V2ClassificationError) as caught:
        await _classify_v2(monkeypatch, _Response(200, {}), document=document, mime="application/pdf")
    failure = technical_failure(caught.value, operation="capture_v2_classification")
    assert (failure.code, failure.retryable, failure.category) == ("INVALID_FILE_CONTENT", False, BUSINESS)


@pytest.mark.asyncio
async def test_v2_bad_payload_and_blocked_content(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = {"candidates": [{"content": {"parts": [{"text": "nope"}]}, "finishReason": "STOP"}]}
    with pytest.raises(v2_classifier.V2ClassificationError) as caught:
        await _classify_v2(monkeypatch, _Response(200, bad))
    assert (caught.value.technical_code, caught.value.retryable) == ("DOCUMENT_AI_RESPONSE_INVALID", True)

    blocked = {"candidates": [{"finishReason": "SAFETY"}]}
    with pytest.raises(v2_classifier.V2ClassificationError) as caught:
        await _classify_v2(monkeypatch, _Response(200, blocked))
    assert (caught.value.technical_code, caught.value.retryable) == ("DOCUMENT_AI_CONTENT_BLOCKED", False)


@pytest.mark.asyncio
async def test_v2_call_logs_usage_status_latency_and_response_id(monkeypatch: pytest.MonkeyPatch) -> None:
    log = _Log()
    monkeypatch.setattr(v2_classifier, "_logger", log)
    payload = {
        "responseId": "resp-v2",
        "candidates": [{"content": {"parts": [{"text": '{"documentTypeKey": "pan_card", "confidence": 97}'}]},
                        "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 700, "candidatesTokenCount": 12, "thoughtsTokenCount": 3,
                          "totalTokenCount": 715},
    }
    result = await _classify_v2(monkeypatch, _Response(200, payload))

    assert result.provider_request_id == "resp-v2"
    [(level, fields)] = log.find("gemini_classification_usage")
    assert level == "info"
    assert fields["http_status"] == 200 and fields["finish_reason"] == "STOP"
    assert (fields["prompt_tokens"], fields["response_tokens"], fields["thoughts_tokens"]) == (700, 12, 3)
    assert "duration_ms" in fields and fields["gemini_model"]
    assert not any(key in fields for key in ("prompt", "text", "raw_response"))


class _TenantSession:
    def __init__(self) -> None:
        self.session = AsyncMock()

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *args: object) -> None:
        del args


def _capture_fail_harness(monkeypatch: pytest.MonkeyPatch) -> tuple[_TenantSession, _Log]:
    holder = _TenantSession()
    monkeypatch.setattr(capture_v2_classifier, "tenant_session", lambda _tenant: holder)
    log = _Log()
    monkeypatch.setattr(capture_v2_classifier, "logger", log)
    return holder, log


def _executed_sql(holder: _TenantSession) -> list[tuple[str, dict[str, Any]]]:
    return [(str(call.args[0]), call.args[1]) for call in holder.session.execute.call_args_list]


@pytest.mark.asyncio
async def test_non_retryable_classification_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    holder, log = _capture_fail_harness(monkeypatch)
    failure = technical_failure(
        v2_classifier.V2ClassificationError("x", technical_code="INVALID_FILE_CONTENT", retryable=False),
        operation="capture_v2_classification",
    )
    await capture_v2_classifier.CaptureV2ClassificationWorker()._fail_job(
        tenant_id="t1", job_id=uuid.uuid4(), document_id=uuid.uuid4(), attempt_no=1,
        correlation_id="c", failure=failure, duration_ms=3.0,
    )
    sql = _executed_sql(holder)
    assert not any("job_status='PENDING'" in statement for statement, _ in sql)
    assert any("state='FAILED'" in statement and params["code"] == "INVALID_FILE_CONTENT"
               for statement, params in sql)
    [(level, fields)] = log.find("capture_v2_classification_failed")
    assert level == "info" and fields["error_category"] == BUSINESS


@pytest.mark.asyncio
async def test_retryable_classification_failure_backs_off_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """An outage waits five minutes for one more attempt rather than
    failing the page after one quick retry; the second failure is final."""
    failure = technical_failure(
        v2_classifier.V2ClassificationError("x", technical_code="DOCUMENT_AI_UNAVAILABLE", retryable=True),
        operation="capture_v2_classification",
    )
    for attempt_no, delay in enumerate((300,), start=1):
        holder, log = _capture_fail_harness(monkeypatch)
        await capture_v2_classifier.CaptureV2ClassificationWorker()._fail_job(
            tenant_id="t1", job_id=uuid.uuid4(), document_id=uuid.uuid4(), attempt_no=attempt_no,
            correlation_id="c", failure=failure,
        )
        [(_, params)] = [(s, p) for s, p in _executed_sql(holder) if "job_status='PENDING'" in s]
        assert (params["due"] - params["now"]).total_seconds() == delay
        assert params["attempt_step"] == 1
        [(level, fields)] = log.find("capture_v2_classification_retry")
        assert level == "warning" and fields["retry_in_seconds"] == delay and fields["attempt_counted"] is True

    holder, log = _capture_fail_harness(monkeypatch)
    await capture_v2_classifier.CaptureV2ClassificationWorker()._fail_job(
        tenant_id="t1", job_id=uuid.uuid4(), document_id=uuid.uuid4(),
        attempt_no=capture_v2_classifier.CLASSIFICATION_MAX_ATTEMPTS, correlation_id="c", failure=failure,
    )
    assert not any("job_status='PENDING'" in statement for statement, _ in _executed_sql(holder))
    assert any(params.get("code") == "CLASSIFICATION_FAILED" for _, params in _executed_sql(holder))
    assert log.find("capture_v2_classification_failed")[0][0] == "error"


@pytest.mark.asyncio
async def test_a_quota_hit_is_waited_out_without_spending_the_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load is never a failure (2026-09-30): a 429 puts the job back in the
    queue five minutes or so later at the same attempt number, however many
    times, until the job has waited on the quota for six hours; after that
    it counts like any other retryable failure."""
    from datetime import UTC, datetime, timedelta

    failure = technical_failure(
        v2_classifier.V2ClassificationError("x", technical_code="DOCUMENT_AI_RATE_LIMITED", retryable=True),
        operation="capture_v2_classification",
    )
    holder, log = _capture_fail_harness(monkeypatch)
    holder.session.execute.return_value.scalar_one_or_none = MagicMock(
        return_value=datetime.now(UTC) - timedelta(hours=1))
    await capture_v2_classifier.CaptureV2ClassificationWorker()._fail_job(
        tenant_id="t1", job_id=uuid.uuid4(), document_id=uuid.uuid4(),
        attempt_no=capture_v2_classifier.CLASSIFICATION_MAX_ATTEMPTS, correlation_id="c", failure=failure,
    )
    [(_, params)] = [(s, p) for s, p in _executed_sql(holder) if "job_status='PENDING'" in s]
    assert params["attempt_step"] == 0
    assert 300 <= (params["due"] - params["now"]).total_seconds() <= 360
    [(level, fields)] = log.find("capture_v2_classification_retry")
    assert level == "warning" and fields["attempt_counted"] is False

    holder, log = _capture_fail_harness(monkeypatch)
    holder.session.execute.return_value.scalar_one_or_none = MagicMock(
        return_value=datetime.now(UTC) - timedelta(hours=7))
    await capture_v2_classifier.CaptureV2ClassificationWorker()._fail_job(
        tenant_id="t1", job_id=uuid.uuid4(), document_id=uuid.uuid4(),
        attempt_no=capture_v2_classifier.CLASSIFICATION_MAX_ATTEMPTS, correlation_id="c", failure=failure,
    )
    assert not any("job_status='PENDING'" in statement for statement, _ in _executed_sql(holder))
    assert any(params.get("code") == "CLASSIFICATION_FAILED" for _, params in _executed_sql(holder))


def test_capture_v2_unknown_is_info_and_missing_type_is_configuration() -> None:
    source = inspect.getsource(capture_v2_classifier.CaptureV2ClassificationWorker._classify)
    unknown = source.index('"capture_v2_classification_unknown"')
    assert source.rindex("log.info(", 0, unknown) > source.rindex("log.warning(", 0, unknown)
    type_lookup = source[source.index("type_row = ("):source.index("if type_row is None:")]
    assert ").mappings().one_or_none()" in type_lookup
    assert 'CodedError("DOCUMENT_TYPE_NOT_FOUND", retryable=False)' in source
    failure = technical_failure(
        capture_v2_classifier.CodedError("DOCUMENT_TYPE_NOT_FOUND", retryable=False),
        operation="capture_v2_classification",
    )
    assert (failure.code, failure.retryable, failure.category) == ("DOCUMENT_TYPE_NOT_FOUND", False, CONFIGURATION)


# ── Scheduler: correlation reuse, report once, safe errors ────────────────────

@pytest.mark.asyncio
async def test_eod_retry_reuses_the_original_correlation_id() -> None:
    session = AsyncMock()
    select_result = MagicMock()
    select_result.all.return_value = [(uuid.uuid4(), "audit-core-corr"), (uuid.uuid4(), None)]
    session.execute = AsyncMock(side_effect=[select_result, MagicMock(), MagicMock()])

    await beat._insert_eod_retry_jobs(session, "t1", beat.datetime.now(beat.UTC))

    first, second = (call.args[1]["corr"] for call in session.execute.call_args_list[1:])
    assert first == "audit-core-corr"
    assert second.startswith("eod.")


@pytest.mark.asyncio
async def test_nightly_reuses_the_original_correlation_id() -> None:
    from verigence.di.repositories.processing_jobs import insert_nightly_reprocessing_jobs

    session = AsyncMock()
    select_result = MagicMock()
    select_result.mappings.return_value.all.return_value = [
        {"tenant_id": "t1", "document_id": uuid.uuid4(), "last_attempt_no": 2,
         "original_correlation_id": "audit-core-corr"},
    ]
    session.execute = AsyncMock(side_effect=[select_result, MagicMock()])

    await insert_nightly_reprocessing_jobs(session)

    select_params = session.execute.call_args_list[0].args[1]
    assert "CLASSIFICATION_AMBIGUOUS" in select_params["non_reprocessable_codes"]
    assert "recent_cutoff" in select_params
    assert session.execute.call_args_list[1].args[1]["corr"] == "audit-core-corr"


@pytest.mark.asyncio
async def test_nightly_run_is_performed_and_reported_once(monkeypatch: pytest.MonkeyPatch) -> None:
    claims = iter([True, False, False])
    monkeypatch.setattr(beat, "claim_scheduler_run", AsyncMock(side_effect=lambda *_a, **_k: next(claims)))
    monkeypatch.setattr(beat, "complete_scheduler_run", AsyncMock())
    insert = AsyncMock(return_value=7)
    monkeypatch.setattr(beat, "insert_nightly_reprocessing_jobs", insert)
    report = AsyncMock()
    monkeypatch.setattr(beat, "_report_nightly_reprocess_run", report)

    now = beat.datetime.now(beat.UTC)
    for _ in range(3):
        await beat._run_nightly_reprocess(_session_factory(), now, log=_Log())

    insert.assert_awaited_once()
    report.assert_awaited_once()
    assert report.call_args.kwargs["queued_count"] == 7


@pytest.mark.asyncio
async def test_nightly_failure_reports_a_safe_summary_once(monkeypatch: pytest.MonkeyPatch) -> None:
    failure_claims = iter([True, False])

    async def claim(_session: Any, **kwargs: Any) -> bool:
        if kwargs["run_name"] == beat._NIGHTLY_FAILURE_REPORT_RUN_NAME:
            return next(failure_claims)
        return True

    monkeypatch.setattr(beat, "claim_scheduler_run", claim)
    monkeypatch.setattr(beat, "insert_nightly_reprocessing_jobs", AsyncMock(side_effect=RuntimeError(SECRET)))
    report = AsyncMock()
    monkeypatch.setattr(beat, "_report_nightly_reprocess_run", report)
    log = _Log()

    now = beat.datetime.now(beat.UTC)
    for _ in range(2):
        await beat._run_nightly_reprocess(_session_factory(), now, log=log)

    report.assert_awaited_once()
    error = report.call_args.kwargs["error"]
    assert SECRET not in error and "RuntimeError" in error
    [(level, fields), _] = log.find("nightly_reprocess_failed")
    assert level == "error" and fields["exception_type"] == "RuntimeError"
    assert "error" not in fields


def test_scheduler_failure_events_use_safe_exception_context() -> None:
    source = inspect.getsource(beat)
    assert "error=str(exc)" not in source


# ── Heartbeat ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heartbeat_survives_a_failing_queue_depth_query(monkeypatch: pytest.MonkeyPatch) -> None:
    log = _Log()
    monkeypatch.setattr(heartbeat, "logger", log)

    def broken_factory() -> Any:
        raise ConnectionError("db down")

    stats = [heartbeat.WorkerStats(cycles=5, processed=3, failed=1), heartbeat.WorkerStats(cycles=2)]
    stop = asyncio.Event()
    task = asyncio.create_task(heartbeat.run_heartbeat(
        stop_event=stop, session_factory=broken_factory, stats=lambda: stats,  # type: ignore[arg-type]
        fields={"worker_mode": "v2"}, interval_seconds=0.01,
    ))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1)

    beats = log.find("di_worker_heartbeat")
    assert len(beats) >= 2
    assert beats[0][1] == {"worker_mode": "v2", "cycles": 7, "processed": 3, "failed": 1}
    assert log.find("di_worker_heartbeat_queue_depth_failed")


@pytest.mark.asyncio
async def test_heartbeat_reports_queue_depth() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = [("processing", "PENDING", 4), ("classification", "RUNNING", 2)]
    session.execute = AsyncMock(return_value=result)
    depth = await heartbeat.queue_depth(session)
    assert depth == {"processing_pending": 4, "processing_running": 0,
                     "classification_pending": 0, "classification_running": 2}
