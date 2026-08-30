# UC03 DI Identity and Booking Date Amendment

**Date:** 2026-08-25  
**Updated:** 2026-08-30  
**Status:** Implementation baseline  
**Scope:** DI publication boundary for UC03 Booking

## 1. Customer-name model

UC03 intentionally keeps the Process Coordinator's entered customer name and every document-extracted customer name as separate facts.

DI does not own or overwrite the PC-entered customer name. Audit Core stores that operational value separately and keeps it immutable after Journey creation. DI publishes document-extracted names with their original source/provenance so they can be compared visibly.

The identity-authoritative Legal Name sources currently supported by UC03 are:

| Document | DI document type | DI field | UC03 meaning |
| --- | --- | --- | --- |
| PAN | `pan_card` | `pan_name` | Identity-authoritative Legal Name proposal |
| Aadhaar | `aadhaar` | `aadhaar_name` | Identity-authoritative Legal Name proposal |

`aadhaar_name` is the full name exactly as printed on the Aadhaar evidence. `pan_name` is the corresponding PAN identity-name field.

## 2. Booking Form customer name

The Booking Form extraction schema extracts `customer_name`, and UC03 now publishes it into the Booking evidence/review stream.

This does **not** make the Booking Form name an identity-authoritative Legal Name source. It remains a genuine source-document fact that is retained for comparison with:

- the PC-entered customer name; and
- PAN/Aadhaar identity names when those documents are available.

Audit Core source precedence remains PAN/Aadhaar first for Legal Name. Booking Form `customer_name` must never overwrite the immutable PC-entered name or a PAN/Aadhaar-derived Legal Name.

The same publication correction applies to Booking Form `customer_email`: because it is already extracted and is useful to UC03 review, it is published instead of being silently filtered out.

## 3. Actual Booking Date

The existing Booking Form schema defines:

- field: `booking_date`
- type: date
- meaning: Booking date explicitly visible on the form
- normalization: `date_dd_mm_yyyy`

UC03 publishes this field into the Booking proposal stream. Audit Core maps the accepted/corrected value to the existing `bookings.booking_date`, whose business label is **Actual Booking Date**.

DI must not infer a missing Booking date from upload time, document metadata, Journey creation time, or any other timestamp.

## 4. Audit Captured At

DI does not create or publish Audit Captured At. Audit Core owns this timestamp using the immutable Journey creation timestamp (`journeys.created_at_utc`).

This separation allows a Booking performed at a satellite outlet on one day to be uploaded and audited on a later day without altering the real-world Booking date.

## 5. Publication rules

The UC03 Booking proposal/evidence boundary follows these rules:

1. `pan_name` -> publish as identity-authoritative evidence for Legal Name.
2. `aadhaar_name` -> publish as identity-authoritative evidence for Legal Name.
3. `booking_form.customer_name` -> publish as genuine Booking-document evidence for comparison, but not as an identity-authoritative Legal Name source.
4. `booking_form.customer_email` -> publish as Booking-document evidence.
5. `booking_form.booking_date` -> publish as Actual Booking Date proposal.
6. DI never chooses between PAN and Aadhaar when names differ.
7. DI never overwrites an accepted/corrected value or an operational value in Audit Core.
8. All machine values, confidence and source provenance remain unchanged at the DI boundary.

## 6. Conflict ownership

If the PC-entered name, Booking Form name, PAN name or Aadhaar name differ, all source values remain available. Audit Core owns comparison, Legal Name status and conflict/audit handling.

PAN/Aadhaar remain the authoritative identity sources. A Booking Form name mismatch is audit evidence; it is not permission to replace either the PC-entered name or verified Legal Name.

No fuzzy identity merge or silent source overwrite is introduced in DI by this amendment.
