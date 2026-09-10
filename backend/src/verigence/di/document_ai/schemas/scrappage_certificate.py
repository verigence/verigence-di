"""document_ai/schemas/scrappage_certificate.py — Vehicle Scrappage Certificate
of Deposit extraction schema.

Under India's Vehicle Scrappage Policy, an RVSF (Registered Vehicle Scrapping
Facility) issues a "Certificate of Deposit" (CD) when an old vehicle is
scrapped, entitling the holder to a one-time registration-fee waiver, motor
vehicle tax concession, and OEM discount on a new vehicle purchase. The CD is
also tradable on a national portal (DigiELV and similar): the original owner
can sell it to someone else's new-vehicle purchase, producing a "Transfer
Certificate of Deposit" that records the sale (from/to holder, trade date,
trade number) instead of the original scrapping transaction.

This is the "Scrappage Documents" evidence Audit Core's own Booking checkpoint
rules have referenced since migration 0033 but could never verify --
``uc03_booking_confirmation_rules.py`` cross-checks the Booking Form's own
``scrappage_discount_amount`` against a required document, but no document
type existed for that evidence until now (see verigence-audit-core's own
BK_SCRAPPAGE_DOCUMENT_UNCLASSIFIED finding, which fires unconditionally for
lack of anywhere to verify against).

One schema covers both physical forms (identical vehicle-details table on
both; the certificate_variant discriminator plus a handful of variant-only
fields tell them apart), the same evidence_format-style pattern already used
by customer_kyc.py and corporate_id.py for "one business evidence type, more
than one physical layout."
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

SCRAPPAGE_CERTIFICATE_SCHEMA = SchemaDefinition(
    document_type_key="scrappage_certificate_of_deposit",
    display_name="Scrappage Certificate of Deposit",
    schema_version="1.0",
    fields=[
        FieldSpec("certificate_variant", "string", True, "ORIGINAL when this is a plain Certificate of Deposit issued directly by the scrapping facility, TRANSFERRED when it is titled 'Transfer Certificate of Deposit' and records a sale of the certificate.", enum=["ORIGINAL", "TRANSFERRED"]),
        FieldSpec("certificate_number", "string", True, "The Certificate/CD number exactly as printed (commonly labelled 'Certificate No' or 'COD...')."),
        FieldSpec("old_vehicle_registration_number", "string", True, "Registration number of the OLD (scrapped) vehicle this certificate is for -- never the new vehicle being purchased."),
        FieldSpec("old_vehicle_make", "string", False, "Old vehicle's Make/Maker exactly as printed."),
        FieldSpec("old_vehicle_model", "string", False, "Old vehicle's Model exactly as printed."),
        FieldSpec("old_vehicle_category", "string", False, "Old vehicle's Category/Class exactly as printed (e.g. LMV)."),
        FieldSpec("old_vehicle_type", "string", False, "Old vehicle's Vehicle Type exactly as printed (e.g. Transport, Non-Transport)."),
        FieldSpec("old_vehicle_fuel_type", "string", False, "Old vehicle's Fuel Type exactly as printed."),
        FieldSpec("old_vehicle_cubic_capacity", "number", False, "Old vehicle's Cubic Capacity exactly as printed."),
        FieldSpec("old_vehicle_seating_capacity", "number", False, "Old vehicle's Seating Capacity exactly as printed."),
        FieldSpec("old_vehicle_year_of_manufacturing", "string", False, "Old vehicle's Year of Manufacturing exactly as printed (format varies, e.g. '09-1996' or '1996' -- preserve as printed, do not reformat)."),
        FieldSpec("old_vehicle_unladen_weight_kg", "number", False, "Old vehicle's Unladen Weight in kg exactly as printed."),
        FieldSpec("old_vehicle_number_of_cylinders", "number", False, "Old vehicle's Number of Cylinders exactly as printed."),
        FieldSpec("old_vehicle_gross_vehicle_weight_kg", "number", False, "Old vehicle's Registered Gross Vehicle Weight in kg exactly as printed."),
        FieldSpec("old_vehicle_wheelbase_mm", "number", False, "Old vehicle's Wheelbase in mm exactly as printed."),
        FieldSpec("original_owner_name", "string", False, "Name the certificate was originally issued to / scrapped in the name of (on a Transfer certificate, this is the 'from' party)."),
        FieldSpec("current_holder_name", "string", True, "Name the certificate currently belongs to: on an ORIGINAL certificate, same as original_owner_name; on a TRANSFERRED certificate, the 'transferred to' party -- whoever is claiming the benefit on the new purchase."),
        FieldSpec("current_holder_mobile", "string", False, "Current holder's mobile number exactly as printed (may be partially masked)."),
        FieldSpec("current_holder_pan", "string", False, "Current holder's PAN exactly as printed (may be partially masked)."),
        FieldSpec("trade_date", "date", False, "Date the certificate was traded/transferred, only present on a TRANSFERRED certificate.", normalization="date_dd_mm_yyyy"),
        FieldSpec("trade_number", "string", False, "Trade/transaction number, only present on a TRANSFERRED certificate."),
        FieldSpec("certificate_issue_date", "date", False, "Date the certificate itself was issued.", normalization="date_dd_mm_yyyy"),
        FieldSpec("certificate_valid_until_date", "date", False, "Date the certificate is valid until.", normalization="date_dd_mm_yyyy"),
        FieldSpec("scrapping_facility_name", "string", False, "Name of the RVSF (Registered Vehicle Scrapping Facility) that issued the certificate, only present on an ORIGINAL certificate."),
        FieldSpec("rvsf_registration_number", "string", False, "The RVSF's own registration/certification number (commonly labelled 'RVSF No'), only present on an ORIGINAL certificate."),
        FieldSpec("state_of_scrapping", "string", False, "State/UT where the vehicle was scrapped, only present on an ORIGINAL certificate."),
    ],
    system_prompt=(
        "You extract data from an Indian Vehicle Scrappage Certificate of Deposit (CD) or Transfer Certificate "
        "of Deposit, issued under India's Vehicle Scrappage Policy (RVSF / DigiELV / VAHAN ecosystem). "
        "Return only values explicitly printed on the document.\n"
        "Return ONLY valid JSON using the requested field structure."
    ),
    prompt_notes=[
        "Set certificate_variant to TRANSFERRED only when the document is titled 'Transfer Certificate of Deposit' or otherwise explicitly records a trade between two named parties; otherwise ORIGINAL.",
        "old_vehicle_registration_number is the SCRAPPED vehicle's registration -- this document never mentions the new vehicle being purchased.",
        "On a TRANSFERRED certificate, current_holder_name/mobile/pan are the party the certificate was traded TO; original_owner_name is the party it was traded FROM.",
        "On an ORIGINAL certificate, current_holder_name is whoever the certificate is issued/valid in the name of; leave trade_date, trade_number, and current_holder_mobile/pan null unless actually printed.",
        "Preserve old_vehicle_year_of_manufacturing exactly as printed; do not reformat or infer a missing month.",
        "Leave any field null when not clearly legible or not printed -- never infer a value from context or general knowledge.",
    ],
)
