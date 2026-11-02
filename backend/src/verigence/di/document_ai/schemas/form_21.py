"""document_ai/schemas/form_21.py — Form 21 (Sale Certificate).

The RTO sale certificate a dealer issues for registering a new vehicle
("FORM 21 {See Rule 47(a) and (d)} SALE CERTIFICATE", sometimes headed only
"SALES CERTIFICATE"): it certifies the vehicle was delivered to the buyer on a
date and gives the buyer, any financier and the vehicle's particulars. It
prints the invoice number but no prices, so with no type of its own it was
read as a vehicle invoice (customer_invoice_dms / wholesale_invoice).

Keys are exactly the migration 0059 published profile's and reuse the names
the invoice and ledger schemas give the same facts (buyer_name, vin_number,
financed_by, ...). No amount is extracted: the certificate bills nothing.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

FORM_21_SCHEMA = SchemaDefinition(
    document_type_key="form_21",
    display_name="Form 21 (Sale Certificate)",
    schema_version="1.0",
    fields=[
        FieldSpec("certificate_number", "string", False,
                  "The certificate's own serial number exactly as printed, only when it prints one; never the invoice number."),
        FieldSpec("invoice_number", "string", False,
                  "Invoice number printed on the certificate (Invoice No. / Bill No.), exactly as printed."),
        FieldSpec("sale_date", "date", False,
                  "Date of sale: the date the certificate says the vehicle was delivered to the buyer "
                  "(\"has been delivered by me to ... on <date>\", Date of Sale / Delivery).",
                  normalization="date_dd_mm_yyyy"),
        FieldSpec("buyer_name", "string", True,
                  "Name of the buyer exactly as printed; not the son/wife/daughter of name."),
        FieldSpec("buyer_address", "string", False,
                  "Buyer's address exactly as printed (the permanent address when both are printed)."),
        FieldSpec("dealer_name", "string", False,
                  "Dealer issuing the certificate (letterhead or signatory), exactly as printed."),
        FieldSpec("vin_number", "string", True,
                  "Chassis number / VIN (Chassis No.) exactly as printed; never correct or complete characters."),
        FieldSpec("engine_number", "string", False,
                  "Engine number (or motor number) exactly as printed; never correct or complete characters."),
        FieldSpec("vehicle_make", "string", False, "Maker's name exactly as printed."),
        FieldSpec("vehicle_model", "string", False,
                  "Vehicle model / brand name exactly as printed (after \"Certified that\" or against Model)."),
        FieldSpec("vehicle_color", "string", False, "Colour of the body exactly as printed."),
        FieldSpec("vehicle_manufacture_month_year", "string", False,
                  "Month and year of manufacture exactly as printed, e.g. 09/2026."),
        FieldSpec("financed_by", "string", False,
                  "Financier the vehicle is held under hire-purchase / lease / hypothecation with, exactly as printed."),
    ],
    system_prompt=(
        "You extract data from an Indian Form 21 Sale Certificate (\"FORM 21, See Rule 47(a) and (d)\") that a "
        "vehicle dealer issues for the registration of a new vehicle. Read only what is printed or written on it. "
        "Chassis and engine numbers are identifiers: copy them character for character and never repair or "
        "complete them. The certificate carries no prices; never return an amount.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "buyer_name is the person or company the vehicle was delivered to, not the dealer or the financier.",
        "invoice_number is the invoice the certificate refers to; certificate_number only when the certificate prints a number of its own.",
        "sale_date is the date of sale / delivery the certificate certifies, not the date it was signed when both are printed.",
        "Leave financed_by out when the hire-purchase / lease / hypothecation line is blank, struck through or says NA, Nil or Cash.",
        "If a field is not printed or is unclear, leave it out.",
    ],
)
