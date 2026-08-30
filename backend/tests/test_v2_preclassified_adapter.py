from __future__ import annotations

from decimal import Decimal

import pytest

from verigence.di.document_ai.adapter import (
    AIInvocationResult,
    DocumentAIAdapter,
    ExtractionField,
)
from verigence.di.document_ai.v2_preclassified_adapter import V2PreclassifiedAdapter
from verigence.di.domain.enums import AICapability


class _Delegate(DocumentAIAdapter):
    def __init__(self) -> None:
        self.classify_calls = 0
        self.extract_calls = 0

    @property
    def adapter_key(self) -> str:
        return "delegate-test"

    async def classify(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        candidate_type_keys: list[str],
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        del artifact_bytes, mime_type, candidate_type_keys, hint, correlation_id
        self.classify_calls += 1
        raise AssertionError("V2 reuse wrapper must not call delegate.classify()")

    async def extract(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        fields: list[ExtractionField],
        correlation_id: str | None = None,
        physical_form_type: str = "PRINTABLE",
        document_type_key: str | None = None,
    ) -> AIInvocationResult:
        del artifact_bytes, mime_type, fields, correlation_id, physical_form_type, document_type_key
        self.extract_calls += 1
        return AIInvocationResult(
            capability=AICapability.VISION_EXTRACTION,
            adapter_key=self.adapter_key,
            provider_request_id="extract-1",
            results=[],
            usage_metrics={"api_calls": 1},
        )


@pytest.mark.asyncio
async def test_v2_preclassified_adapter_reuses_classification_without_provider_call() -> None:
    delegate = _Delegate()
    adapter = V2PreclassifiedAdapter(
        delegate,
        document_type_key="pan_card",
        confidence=Decimal("97.00"),
    )

    result = await adapter.classify(
        artifact_bytes=b"ignored",
        mime_type="image/jpeg",
        candidate_type_keys=["aadhaar", "pan_card"],
        hint="pan_card",
    )

    assert delegate.classify_calls == 0
    assert result.provider_request_id is None
    assert result.usage_metrics["api_calls"] == 0
    assert len(result.results) == 1
    candidate = result.results[0]
    assert candidate.document_type_key == "pan_card"
    assert candidate.confidence == Decimal("97.00")
    assert candidate.method == "V2_CAPTURE_CLASSIFICATION_REUSE"


@pytest.mark.asyncio
async def test_v2_preclassified_adapter_delegates_extraction_unchanged() -> None:
    delegate = _Delegate()
    adapter = V2PreclassifiedAdapter(
        delegate,
        document_type_key="booking_form",
        confidence=Decimal("96.00"),
    )

    result = await adapter.extract(
        artifact_bytes=b"doc",
        mime_type="application/pdf",
        fields=[ExtractionField(field_key="customer_name")],
        document_type_key="booking_form",
    )

    assert delegate.extract_calls == 1
    assert result.provider_request_id == "extract-1"


@pytest.mark.asyncio
async def test_v2_preclassified_adapter_rejects_type_outside_processing_candidates() -> None:
    delegate = _Delegate()
    adapter = V2PreclassifiedAdapter(
        delegate,
        document_type_key="pan_card",
        confidence=Decimal("97.00"),
    )

    result = await adapter.classify(
        artifact_bytes=b"ignored",
        mime_type="image/jpeg",
        candidate_type_keys=["aadhaar"],
    )

    assert delegate.classify_calls == 0
    assert result.results == []
