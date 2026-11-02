"""document_ai/schemas/delivery_receipt.py — Vehicle Delivery Receipt.

The customer's acknowledgement of taking delivery of the new vehicle (a New
Vehicle Delivery Receipt or delivery note): the vehicle handed over, when and
to whom, and any financier. It carries no amount by nature, so with no type of
its own it was read as a money receipt (payment_receipt / dealer_receipt) with
no amount.

Keys are exactly the migration 0059 published profile's and reuse the names
other schemas give the same facts (customer_name, vin_number, financed_by,
...). No amount is extracted.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

DELIVERY_RECEIPT_SCHEMA = SchemaDefinition(
    document_type_key="delivery_receipt",
    display_name="Vehicle Delivery Receipt",
    schema_version="1.0",
    fields=[
        FieldSpec("receipt_number", "string", False,
                  "The delivery receipt / delivery note's own number exactly as printed."),
        FieldSpec("delivery_date", "date", False,
                  "Date the customer took delivery of the vehicle, as printed.",
                  normalization="date_dd_mm_yyyy"),
        FieldSpec("customer_name", "string", True,
                  "Customer taking delivery of the vehicle, exactly as printed."),
        FieldSpec("vehicle_model", "string", False, "Vehicle model exactly as printed."),
        FieldSpec("vin_number", "string", True,
                  "Chassis number / VIN exactly as printed; never correct or complete characters."),
        FieldSpec("engine_number", "string", False,
                  "Engine number exactly as printed; never correct or complete characters."),
        FieldSpec("financed_by", "string", False,
                  "Financier / hypothecation printed on the receipt, exactly as printed."),
    ],
    system_prompt=(
        "You extract data from an Indian automobile dealer's New Vehicle Delivery Receipt or delivery note: the "
        "customer's acknowledgement of taking delivery of the vehicle. Read only what is printed or written on it. "
        "Chassis and engine numbers are identifiers: copy them character for character and never repair or "
        "complete them. The receipt records the vehicle handed over, not a payment; never return an amount.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "customer_name is the person or company taking delivery, not the dealer, the sales executive or the financier.",
        "receipt_number is the receipt's own number, not a booking, invoice or money-receipt number printed on it.",
        "delivery_date is the date of delivery, not the invoice or booking date.",
        "Leave financed_by out when it is blank or says NA, Nil or Cash.",
        "If a field is not printed or is unclear, leave it out.",
    ],
)
