"""document_ai/adapter.py — Provider-neutral DocumentAIAdapter interface.

The Processing Worker only calls DocumentAIAdapter.classify() and
DocumentAIAdapter.extract(). The concrete provider implementation
(Google Document AI, Tesseract, mock) is injected at runtime.

Every provider adapter MUST normalise its confidence to 0-100.
A provider that cannot provide a documented deterministic normalisation
is not eligible for production configuration (DI_LLD_v2.1.md §3).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from verigence.di.domain.enums import AICapability, FoundStatus


@dataclass(frozen=True)
class ClassificationCandidate:
    document_type_key: str
    confidence: Decimal          # 0-100, normalised by adapter
    method: str                  # e.g. "GOOGLE_DOCAI_CLASSIFIER"
    raw_provider_response: dict  # type: ignore[type-arg]  # kept for lineage


@dataclass(frozen=True)
class ExtractionField:
    """Schema for one field sent to the AI provider."""
    field_key: str
    aliases: list[str] = field(default_factory=list)
    instruction: str | None = None


@dataclass(frozen=True)
class FieldResult:
    """Result for one extracted field, returned by the AI provider."""
    field_key: str
    found_status: FoundStatus
    raw_value: str | None
    normalized_value: object | None     # post-normalization (set by rules layer)
    confidence: Decimal | None          # 0-100, normalised
    page_no: int | None
    evidence_region: dict | None        # type: ignore[type-arg]  # bounding box etc.
    provider_raw: dict                  # type: ignore[type-arg]  # full provider payload


@dataclass
class AIInvocationResult:
    """Envelope returned by classify() or extract()."""
    capability: AICapability
    adapter_key: str
    provider_request_id: str | None
    results: list[ClassificationCandidate] | list[FieldResult]
    usage_metrics: dict                 # type: ignore[type-arg]  # tokens, pages etc.
    error_code: str | None = None
    error_detail: str | None = None


class DocumentAIAdapter(abc.ABC):
    """Abstract provider-neutral AI adapter."""

    @property
    @abc.abstractmethod
    def adapter_key(self) -> str:
        """Stable identifier for this adapter (e.g. 'google_docai_v1')."""

    @abc.abstractmethod
    async def classify(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        candidate_type_keys: list[str],
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        """Classify a document. Returns ClassificationCandidate list."""

    @abc.abstractmethod
    async def extract(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        fields: list[ExtractionField],
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        """Extract configured fields. Returns FieldResult list."""


# ── Mock adapter — used locally and in CI ─────────────────────────────────────
class MockDocumentAIAdapter(DocumentAIAdapter):
    """Deterministic mock adapter for local development and CI.

    Returns high-confidence results so documents reach CONFIRMED state
    in the local Docker Compose environment without real API calls.
    """

    @property
    def adapter_key(self) -> str:
        return "mock_v1"

    async def classify(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        candidate_type_keys: list[str],
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        import uuid
        chosen = hint or (candidate_type_keys[0] if candidate_type_keys else "UNKNOWN")
        return AIInvocationResult(
            capability=AICapability.CLASSIFICATION,
            adapter_key=self.adapter_key,
            provider_request_id=str(uuid.uuid4()),
            results=[
                ClassificationCandidate(
                    document_type_key=chosen,
                    confidence=Decimal("95.00"),
                    method="MOCK",
                    raw_provider_response={},
                )
            ],
            usage_metrics={"pages": 1},
        )

    async def extract(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        fields: list[ExtractionField],
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        import uuid
        results = [
            FieldResult(
                field_key=f.field_key,
                found_status=FoundStatus.FOUND,
                raw_value=f"mock_value_for_{f.field_key}",
                normalized_value=f"mock_value_for_{f.field_key}",
                confidence=Decimal("92.00"),
                page_no=1,
                evidence_region=None,
                provider_raw={},
            )
            for f in fields
        ]
        return AIInvocationResult(
            capability=AICapability.VISION_EXTRACTION,
            adapter_key=self.adapter_key,
            provider_request_id=str(uuid.uuid4()),
            results=results,
            usage_metrics={"pages": 1, "fields": len(fields)},
        )


def get_document_ai_adapter() -> DocumentAIAdapter:
    """FastAPI / worker dependency — returns configured adapter."""
    from verigence.di.settings import get_settings
    s = get_settings()
    if s.docai_mock:
        return MockDocumentAIAdapter()
    # Google Document AI implementation will be wired here in Step 9
    raise NotImplementedError(
        "Google Document AI adapter not yet implemented. "
        "Set DI_DOCAI_MOCK=true for local development."
    )
