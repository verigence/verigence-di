# Generalized Invoice Intelligence — 2026-08-30

Status: **Implemented on feature branch; reconciliation rules and TL/PM views are NOT part of this increment.**

## Objective

Preserve all existing UC03/UC04 document requirement keys while making DI capable of classifying and extracting commercial evidence from multiple invoice forms without creating one bespoke platform path for every dealer/system/invoice combination.

## Non-negotiable constraints

1. Existing document types and schemas must not be lost or rewritten unnecessarily.
2. Existing UC03/UC04 requirement keys remain stable.
3. No PC journey or TL/PM view design is changed here.
4. No reconciliation rule is implemented here; this increment only produces normalized, provenance-backed invoice facts for later rules.
5. Gemini call budget stays at the existing topology: one V2 classification call and, for accepted processable documents, one extraction call. No extra Gemini call is introduced for invoice subtype/source/purpose classification.
6. Commercial amounts are preserved exactly as printed, including decimal paise and signed round-off. No tolerance, recomputation, or rounding is applied by DI.
7. DI never infers a master SKU. An explicit printed SKU can be extracted; master resolution remains Audit Core responsibility.

## Pre-change backup / rollback

The repo-local backup is under:

`backup/pre-generalized-invoice-2026-08-30/`

Base `dev` commit before the change:

`6563a9e9d73108bc2141bcbf21a197e36ce8f441`

The backup records the full schema directory blob SHAs and verbatim copies of the schema registry/base and V2 classifier. Preferred rollback is a Git revert of the implementation PR. Migration downgrade retires only the profiles published by migration 0022, re-enables any previous global profile, disables invoice processing introduced by 0022, and deactivates the generic fallback for existing tenants. Historical extraction evidence is never deleted.

## Classification model

A document may still satisfy an existing business requirement such as:

- `customer_invoice_dms`
- `tax_invoice_tally`
- `accessory_invoice_dms`
- `accessory_invoice_tally`
- `ew_invoice`
- `rsa_invoice`
- `wholesale_invoice`

DI adds one internal fallback:

- `invoice_generic` — clearly an invoice, but a more specific configured invoice candidate cannot be established reliably.

The fallback is added inside the V2 classifier only when invoice candidates are already present. It is not a new mandatory/optional journey requirement slot.

The classifier remains one Gemini call. Candidate descriptions explicitly distinguish the business purpose of the invoiced goods/service from the printed heading. Example: a document titled `Tax Invoice` can still be a vehicle, accessory, EW, RSA, or another invoice.

## Extraction model

All invoice schemas are produced from one common schema factory.

### Common invoice envelope

- `invoice_purpose`
- `invoice_nature`
- `source_system`
- `issuer_role`
- invoice number/date
- seller name/GSTIN/address
- buyer name/customer ID/GSTIN/address
- financier/hypothecation when printed
- gross amount before discount
- invoice discount
- taxable amount
- CGST/SGST/IGST rate and amount
- cess
- TCS
- signed round-off
- grand total
- amount in words
- narration
- `line_items[]`

### Invoice semantic dimensions

`invoice_purpose` values:

- `VEHICLE_SALE`
- `VEHICLE_WHOLESALE`
- `ACCESSORY`
- `EXTENDED_WARRANTY`
- `RSA`
- `SERVICE`
- `OTHER`
- `UNKNOWN`

`invoice_nature` values:

- `TAX_INVOICE`
- `RETAIL_INVOICE`
- `PROFORMA_INVOICE`
- `CREDIT_NOTE`
- `DEBIT_NOTE`
- `OTHER`
- `UNKNOWN`

`source_system` values:

- `DMS`
- `TALLY`
- `DEALER_GENERATED`
- `OEM`
- `THIRD_PARTY`
- `UNKNOWN`

`issuer_role` values:

- `DEALER`
- `OEM`
- `ACCESSORY_VENDOR`
- `SERVICE_PROVIDER`
- `INSURER`
- `OTHER`
- `UNKNOWN`

Unknown is intentionally valid. DI must not fabricate a source system simply to complete the structure.

### Purpose-specific extensions

Vehicle-sale/wholesale invoices additionally extract raw vehicle description, explicit SKU when printed, raw model/variant, VIN/chassis/engine, key number, colour, registration and HSN.

EW/RSA invoices additionally extract plan/service name, coverage dates/duration and linked vehicle identifiers when printed.

Accessory and generic invoices use common line items plus lightweight vehicle linkage fields rather than carrying the full vehicle-sale schema.

## Commercial semantics

Neutral field names are intentional. For example, an invoice value called `Price of One` or `Taxable Value` is not automatically called `ex_showroom_price`. DI only extracts `ex_showroom` when a future document-specific field explicitly says so. This prevents the audit layer from comparing semantically different numbers under the same label.

`line_items` retain raw descriptions and only printed item code, HSN/SAC, quantity, unit rate, gross, discount, taxable, tax and net values. Separate lines are never merged into a synthetic line item.

## Gemini-call optimization

Existing V2 topology is preserved:

1. First-page V2 classification — one Gemini call.
2. Accepted invoice with published profile — one schema-driven extraction call.

Invoice purpose/source/nature/issuer are extracted during step 2. There is no third call for invoice sub-classification.

No multi-page retry was introduced in this increment. If first-page classification is ambiguous, the existing UNKNOWN/low-confidence behavior remains rather than silently spending another provider call.

## Activation / journey isolation

Migration 0022 publishes non-scoring extraction profiles for the existing invoice keys and `invoice_generic`. Existing invoice document types introduced by migration 0016 change from evidence-only to processable evidence. The new profile fields are deliberately `score_included=false` and `expected=false`, so this increment does not add a new PC verification/completion gate.

No Booking/Delivery requirement profile is changed. No new mandatory or optional document is shown to the PC. No other document schema is modified.

## Explicitly deferred

- DMS vs Tally vs dealer invoice reconciliation rules
- vehicle invoice vs master price reconciliation
- accessory/EW/RSA hidden-discount rules
- invoice-to-booking and invoice-to-delivery SKU confirmation rules
- TL/PM Deal Integrity UI
- thresholds/tolerances (none are introduced here)

These will consume the normalized facts later and should be implemented as deterministic Audit Core rules with DI evidence provenance.
