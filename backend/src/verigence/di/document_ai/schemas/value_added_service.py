"""document_ai/schemas/value_added_service.py — Other Value Added Service document.

Evidence of a value-added service sold with the vehicle (e.g. extended care
package, anti-rust coating, service plan) that has no more specific type.
Keys are exactly the migration 0046 published profile's.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

VALUE_ADDED_SERVICE_SCHEMA = SchemaDefinition(
    document_type_key="value_added_service_document",
    display_name="Other Value Added Service Document",
    schema_version="1.0",
    fields=[
        FieldSpec("document_title", "string", True,
                  "The document's visible title or service name, e.g. 'Shield Plus Certificate', 'Anti-Rust Coating Invoice'."),
        FieldSpec("issuing_entity", "string", False, "Organisation issuing the document (dealer, OEM or provider)."),
        FieldSpec("reference_number", "string", False,
                  "Primary certificate / policy / invoice / document number, exactly as printed."),
        FieldSpec("document_date", "date", False, "Primary issue / document date.", normalization="date_dd_mm_yyyy"),
        FieldSpec("subject_name", "string", False, "Customer or vehicle owner the service is for."),
        FieldSpec("service_amount", "number", False,
                  "Price / amount charged for the service (grand total if itemised).", normalization="indian_currency"),
    ],
    system_prompt=(
        "You extract data from a value-added service document issued with a new vehicle in India (service "
        "package certificate, protection plan, coating or similar). Extract only what is printed.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "document_title is the service/document name as printed, not a generic word such as 'Invoice' alone when a service name is shown.",
        "service_amount is the amount charged for this service; ignore unrelated vehicle prices.",
        "If a field is not printed or is unclear, return null with low confidence.",
    ],
)
