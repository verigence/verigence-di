# UC03 DI Identity and Booking Date Amendment

**Date:** 2026-08-25  
**Status:** Implementation baseline  
**Scope:** DI publication boundary for UC03 Booking

## 1. Legal Name sources

UC03 distinguishes the Process Coordinator's initial Entered Name from evidence-derived Legal Name.

DI does not own or overwrite either customer field. DI only publishes source facts and preserves machine provenance. Audit Core decides whether an extracted value is accepted or corrected and owns typed customer persistence.

The identity-authoritative Legal Name sources currently supported by UC03 are:

| Document | DI document type | DI field | UC03 meaning |
| --- | --- | --- | --- |
| PAN | `pan_card` | `pan_name` | Legal Name proposal |
| Aadhaar | `aadhaar` | `aadhaar_name` | Legal Name proposal |

`aadhaar_name` is the full name exactly as printed on the Aadhaar evidence. `pan_name` is the corresponding PAN identity-name field.

## 2. Booking Form customer name

The broad Booking Form extraction schema continues to extract `customer_name` because it is a valid source-document fact. However, it is **not** published into the UC03 Booking proposal stream as an identity-authoritative customer name.

Rationale:

- the PC-entered name must remain immutable audit input;
- a Booking Form is not the approved identity source for Legal Name;
- PAN/Aadhaar may later prove a materially different Legal Name;
- DI must not silently cause one source to overwrite another.

The Booking Form `customer_name` remains available in the document/extraction result for evidence comparison and review.

## 3. Actual Booking Date

The existing Booking Form schema defines:

- field: `booking_date`
- type: date
- meaning: Booking date explicitly visible on the form
- normalization: `date_dd_mm_yyyy`

UC03 now publishes this field into the Booking proposal stream. Audit Core maps the accepted/corrected value to the existing `bookings.booking_date`, whose business label is **Actual Booking Date**.

DI must not infer a missing Booking date from upload time, document metadata, Journey creation time, or any other timestamp.

## 4. Audit Captured At

DI does not create or publish Audit Captured At. Audit Core owns this timestamp using the immutable Journey creation timestamp (`journeys.created_at_utc`).

This separation allows a Booking performed at a satellite outlet on one day to be uploaded and audited on a later day without altering the real-world Booking date.

## 5. Publication rules

The UC03 Booking proposal boundary now follows these rules:

1. `pan_name` -> publish as identity evidence for Legal Name.
2. `aadhaar_name` -> publish as identity evidence for Legal Name.
3. `booking_form.customer_name` -> do not publish as identity-authoritative proposal; keep as document fact.
4. `booking_form.booking_date` -> publish as Actual Booking Date proposal.
5. DI never chooses between PAN and Aadhaar when names differ.
6. DI never overwrites an accepted/corrected value or an operational value in Audit Core.
7. All machine values, confidence and source provenance remain unchanged at the DI boundary.

## 6. Conflict ownership

If PAN and Aadhaar produce different validated names, DI publishes both source facts independently. Audit Core owns comparison, Legal Name status and conflict/audit handling.

No fuzzy identity merge or silent source precedence is introduced in DI by this amendment.
