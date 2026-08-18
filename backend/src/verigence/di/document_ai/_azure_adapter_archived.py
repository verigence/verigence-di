"""document_ai/azure_adapter.py — Azure Document Intelligence adapter stub.

D13: Azure Document Intelligence replaces Google Document AI.
D18: ALL documents processed regardless of physical_form_type.

Model routing (D13 + D18):
  GOVT_ID                                          → prebuilt-idDocument
  PRINTABLE bank_statement/loan_statement/ledger   → prebuilt-bankStatement
  PRINTABLE salary_slip                            → prebuilt-payStub
  PRINTABLE insurance/utility/booking/dealer_rcpt  → prebuilt-invoice
  PRINTABLE (other)                                → prebuilt-layout
  HANDWRITTEN                                      → prebuilt-read
  ADDITIONAL                                       → prebuilt-read
  upi_screenshot (any form type)                   → prebuilt-read

TODO (Step 9): implement extract() using azure-ai-documentintelligence SDK.
              This stub raises NotImplementedError so CI stays green while
              DI_DOCAI_MOCK=true.  Only instantiated when DI_DOCAI_MOCK=false.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from verigence.di.document_ai.adapter import (
    AIInvocationResult,
    ClassificationCandidate,
    DocumentAIAdapter,
    ExtractionField,
)
from verigence.di.domain.enums import AICapability

# Model routing tables (D13 + D18)
_PRINTABLE_BANK_TYPES = {"bank_statement", "loan_statement", "customer_ledger"}
_PRINTABLE_INVOICE_TYPES = {
    "insurance_cover", "utility_bill", "booking_docket", "dealer_receipt",
}
_PRINTABLE_PAY_STUB_TYPES = {"salary_slip"}
_READ_DOC_TYPES = {"upi_screenshot"}   # override regardless of form_type


def _select_model(physical_form_type: str, document_type_key: str | None) -> str:
    """Return the Azure prebuilt model ID for a given form type + doc type key."""
    dtk = document_type_key or ""

    # upi_screenshot always uses prebuilt-read regardless of form type
    if dtk in _READ_DOC_TYPES:
        return "prebuilt-read"

    if physical_form_type == "GOVT_ID":
        return "prebuilt-idDocument"

    if physical_form_type == "PRINTABLE":
        if dtk in _PRINTABLE_BANK_TYPES:
            return "prebuilt-bankStatement"
        if dtk in _PRINTABLE_PAY_STUB_TYPES:
            return "prebuilt-payStub"
        if dtk in _PRINTABLE_INVOICE_TYPES:
            return "prebuilt-invoice"
        return "prebuilt-layout"

    # HANDWRITTEN and ADDITIONAL both use prebuilt-read (D18)
    return "prebuilt-read"


class AzureDocumentAIAdapter(DocumentAIAdapter):
    """Azure Document Intelligence adapter.

    Requires:
      endpoint: https://<resource>.cognitiveservices.azure.com/
      api_key:  API key from Azure portal → Keys and Endpoint

    Step 9 implementation: replace the NotImplementedError bodies with real
    azure-ai-documentintelligence SDK calls.
    """

    def __init__(self, endpoint: str, api_key: str) -> None:
        self._endpoint = endpoint
        self._api_key = api_key

    @property
    def adapter_key(self) -> str:
        return "azure_document_intelligence_v1"

    async def classify(
        self,
        artifact_bytes: bytes,
        mime_type: str,
        candidate_type_keys: list[str],
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> AIInvocationResult:
        """Pass-through classification — hint key accepted at confidence 100 (D13).

        No Azure API call is made for classification.
        """
        chosen = hint or (candidate_type_keys[0] if candidate_type_keys else "UNKNOWN")
        return AIInvocationResult(
            capability=AICapability.CLASSIFICATION,
            adapter_key=self.adapter_key,
            provider_request_id=str(uuid.uuid4()),
            results=[
                ClassificationCandidate(
                    document_type_key=chosen,
                    confidence=Decimal("100.00"),
                    method="AZURE_HINT_PASSTHROUGH",
                    raw_provider_response={"hint": hint},
                )
            ],
            usage_metrics={"pages": 0, "api_calls": 0},
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
        """Extract fields via Azure Document Intelligence.

        TODO (Step 9): implement using azure-ai-documentintelligence SDK.
        model = _select_model(physical_form_type, document_type_key)
        """
        model = _select_model(physical_form_type, document_type_key)
        raise NotImplementedError(
            f"AzureDocumentAIAdapter.extract() not yet implemented (Step 9). "
            f"Would use model: {model}. "
            f"Set DI_DOCAI_MOCK=true for local development."
        )
