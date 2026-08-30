"""V2-only adapter wrapper that reuses an accepted capture classification.

Document Capture V2 performs a real byte-based classification before Step 1 may
complete.  The normal DI processing pipeline still expects to call
``DocumentAIAdapter.classify()`` before extraction.  This wrapper satisfies that
existing contract locally from the accepted V2 result and delegates extraction
unchanged to the configured provider adapter.

The legacy adapter interface and all V1 adapter implementations remain untouched.
"""
from __future__ import annotations

from decimal import Decimal

from verigence.di.document_ai.adapter import (
    AIInvocationResult,
    ClassificationCandidate,
    DocumentAIAdapter,
    ExtractionField,
)
from verigence.di.domain.enums import AICapability


class V2PreclassifiedAdapter(DocumentAIAdapter):
    """Reuse one already-accepted V2 classification, delegate extraction as-is."""

    def __init__(
        self,
        delegate: DocumentAIAdapter,
        *,
        document_type_key: str,
        confidence: Decimal,
    ) -> None:
        self._delegate = delegate
        self._document_type_key = document_type_key
        self._confidence = confidence

    @property
    def adapter_key(self) -> str:
        # Keep the configured adapter identity in processor lineage.  The
        # ClassificationCandidate.method below makes the V2 reuse explicit.
        return self._delegate.adapter_key

    async def classify(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        candidate_type_keys: list[str],
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        del artifact_bytes, mime_type, hint, correlation_id
        if self._document_type_key not in candidate_type_keys:
            # Returning no candidate lets the unchanged processing pipeline raise
            # its normal CLASSIFICATION_AMBIGUOUS/configuration failure instead of
            # silently accepting a type whose published profile is unavailable.
            results: list[ClassificationCandidate] = []
        else:
            results = [
                ClassificationCandidate(
                    document_type_key=self._document_type_key,
                    confidence=self._confidence,
                    method="V2_CAPTURE_CLASSIFICATION_REUSE",
                    raw_provider_response={
                        "reusedAcceptedV2Classification": True,
                        "documentTypeKey": self._document_type_key,
                    },
                )
            ]
        return AIInvocationResult(
            capability=AICapability.CLASSIFICATION,
            adapter_key=self.adapter_key,
            provider_request_id=None,
            results=results,
            usage_metrics={"api_calls": 0, "reused_v2_classification": True},
        )

    async def extract(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        fields: list[ExtractionField],
        correlation_id: str | None = None,
        physical_form_type: str = "PRINTABLE",
        document_type_key: str | None = None,
    ) -> AIInvocationResult:
        return await self._delegate.extract(
            artifact_bytes=artifact_bytes,
            mime_type=mime_type,
            fields=fields,
            correlation_id=correlation_id,
            physical_form_type=physical_form_type,
            document_type_key=document_type_key,
        )
