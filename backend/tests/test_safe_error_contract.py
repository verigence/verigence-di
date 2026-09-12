"""Regression tests for DI safe error/logging behavior."""
from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from verigence.di.document_ai.adapter import (
    AIInvocationResult,
    DocumentAIAdapter,
    DocumentAIProviderError,
    ExtractionField,
    SafeDocumentAIAdapter,
)
from verigence.di.domain.enums import AICapability
from verigence.di.errors import ErrorCode, error_for_http_status
from verigence.di.logging_config import _SafeEventProcessor
from verigence.di.main import CORRELATION_ID_HEADER, create_app
from verigence.di.runtime_errors import safe_exception_context, validation_problem_detail

pytestmark = pytest.mark.no_docker


class _ValidationBody(BaseModel):
    quantity: int


class _ExplodingAdapter(DocumentAIAdapter):
    @property
    def adapter_key(self) -> str:
        return "exploding-test-adapter"

    async def classify(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        candidate_type_keys: list[str],
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        del artifact_bytes, mime_type, candidate_type_keys, hint, correlation_id
        raise RuntimeError("customer-secret-classification-value")

    async def extract(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        fields: list[ExtractionField],
        correlation_id: str | None = None,
        physical_form_type: str = "PRINTABLE",
        document_type_key: str | None = None,
    ) -> AIInvocationResult:
        del (
            artifact_bytes,
            mime_type,
            fields,
            correlation_id,
            physical_form_type,
            document_type_key,
        )
        raise RuntimeError("customer-secret-extraction-value")


@pytest.mark.asyncio
async def test_unhandled_api_error_is_safe_and_correlated() -> None:
    app = create_app()

    @app.get("/__test_unhandled")
    async def _boom() -> None:
        raise RuntimeError("sensitive-customer-input-123")

    correlation_id = "safe-error-contract-001"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/__test_unhandled",
            headers={CORRELATION_ID_HEADER: correlation_id},
        )

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == ErrorCode.INTERNAL_ERROR.code
    assert body["correlationId"] == correlation_id
    assert response.headers[CORRELATION_ID_HEADER] == correlation_id
    assert "sensitive-customer-input-123" not in response.text
    assert "RuntimeError" not in response.text


@pytest.mark.asyncio
async def test_framework_404_and_405_use_stable_problem_codes() -> None:
    app = create_app()

    @app.post("/__test_method")
    async def _post_only() -> dict[str, bool]:
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        missing = await client.get(
            "/__definitely_missing",
            headers={CORRELATION_ID_HEADER: "safe-route-404"},
        )
        wrong_method = await client.get(
            "/__test_method",
            headers={CORRELATION_ID_HEADER: "safe-route-405"},
        )

    assert missing.status_code == 404
    assert missing.json()["code"] == ErrorCode.ROUTE_NOT_FOUND.code
    assert missing.json()["correlationId"] == missing.headers[CORRELATION_ID_HEADER]

    assert wrong_method.status_code == 405
    assert wrong_method.json()["code"] == ErrorCode.METHOD_NOT_ALLOWED.code
    assert wrong_method.json()["correlationId"] == wrong_method.headers[CORRELATION_ID_HEADER]


@pytest.mark.asyncio
async def test_validation_response_does_not_echo_submitted_value() -> None:
    app = create_app()

    @app.post("/__test_validation")
    async def _validate(body: _ValidationBody) -> dict[str, int]:
        return {"quantity": body.quantity}

    submitted_secret = "customer-account-secret-value"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/__test_validation",
            json={"quantity": submitted_secret},
            headers={CORRELATION_ID_HEADER: "safe-validation-001"},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == ErrorCode.INVALID_REQUEST.code
    assert body["correlationId"] == response.headers[CORRELATION_ID_HEADER]
    assert submitted_secret not in response.text
    assert body["validationIssues"][0]["field"] == "body.quantity"


def test_validation_problem_detail_never_copies_input_or_message() -> None:
    secret = "private-request-value"
    detail, issues = validation_problem_detail(
        [
            {
                "loc": ("body", "amount"),
                "type": "int_parsing",
                "input": secret,
                "msg": f"cannot parse {secret}",
            }
        ]
    )

    assert secret not in detail
    assert secret not in repr(issues)
    assert issues == [{"field": "body.amount", "type": "int_parsing"}]


def test_safe_exception_context_is_bounded_and_has_no_exception_message() -> None:
    secret = "document-value-that-must-not-be-logged"

    def _level_one() -> None:
        _level_two()

    def _level_two() -> None:
        _level_three()

    def _level_three() -> None:
        _level_four()

    def _level_four() -> None:
        _level_five()

    def _level_five() -> None:
        raise RuntimeError(secret)

    try:
        _level_one()
    except RuntimeError as exc:
        context = safe_exception_context(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError")

    assert context["exception_type"] == "RuntimeError"
    assert len(context["stack_summary"]) <= 4
    assert context["stack_truncated"] is True
    assert secret not in repr(context)


def test_structlog_processor_redacts_values_and_adds_correlation() -> None:
    processor = _SafeEventProcessor()
    secret = "raw-document-value"
    event = processor(
        None,
        "warning",
        {
            "event": "provider_failed",
            "error_code": "DOCUMENT_AI_UNAVAILABLE",
            "error": secret,
            "error_detail": secret,
            "raw_value": secret,
            "raw_response": {"value": secret},
        },
    )

    assert event["error_code"] == "DOCUMENT_AI_UNAVAILABLE"
    assert "correlation_id" in event
    assert secret not in repr(event)
    assert "error" not in event
    assert "raw_value" not in event
    assert "raw_response" not in event


@pytest.mark.asyncio
async def test_safe_document_ai_adapter_maps_raw_provider_exception() -> None:
    adapter = SafeDocumentAIAdapter(_ExplodingAdapter())

    with pytest.raises(DocumentAIProviderError) as captured:
        await adapter.extract(
            artifact_bytes=b"private document bytes",
            mime_type="application/pdf",
            fields=[ExtractionField(field_key="invoice_number")],
            correlation_id="safe-provider-001",
            document_type_key="vehicle_invoice",
        )

    exc = captured.value
    assert exc.technical_code == ErrorCode.EXTRACTION_PROVIDER_ERROR.code
    assert exc.retryable is True
    assert "customer-secret-extraction-value" not in str(exc)
    assert "customer-secret-extraction-value" not in repr(exc)


def test_framework_status_mapping_is_stable() -> None:
    assert error_for_http_status(404) is ErrorCode.ROUTE_NOT_FOUND
    assert error_for_http_status(405) is ErrorCode.METHOD_NOT_ALLOWED
    assert error_for_http_status(503) is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert error_for_http_status(500) is ErrorCode.INTERNAL_ERROR


def test_ai_invocation_result_shape_unchanged() -> None:
    """Guard the adapter boundary against accidental success-path contract drift."""
    result = AIInvocationResult(
        capability=AICapability.CLASSIFICATION,
        adapter_key="test",
        provider_request_id="provider-request-id",
        results=[],
        usage_metrics={"confidence": str(Decimal("99.0"))},
    )
    assert result.adapter_key == "test"
    assert result.error_code is None
