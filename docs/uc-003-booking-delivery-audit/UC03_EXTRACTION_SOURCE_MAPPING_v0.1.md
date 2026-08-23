# Verigence UC03 — DI Extraction Source Mapping

**Document ID:** `VUC03-DI-001`  
**Version:** `0.1`  
**Status:** WORKING / PROVISIONAL EXTRACTION RECONCILIATION  
**Date:** 2026-08-22  
**Canonical parent:** `verigence-audit-core / VUC03-SD-002`  
**Field inventory:** `VUC03-FM-001 / UC03_DOCUMENT_123_FIELD_MATRIX_v1.0.md`

---

## 1. Purpose

This document maps the **57 fields marked `Extracted`** in the supplied UC03 123-field inventory to the best-supported source-document direction available from the supplied PC process, SPR process and provisional document catalogue.

It deliberately distinguishes confirmed source support from inference.

Classification:

```text
SUPPORTED    relationship is directly supported by supplied process/document descriptions
PROVISIONAL  reasonable mapping for design, but exact DI profile/source precedence needs confirmation
TBD          current source material does not support a reliable source mapping
```

A `TBD` row is **not authorized for production extraction configuration** until reconciled.

---

## 2. Cross-module rule

DI owns extraction, classification, confidence and machine provenance.

DI does not decide:

- whether Booking/Delivery may progress;
- whether a variance is a breach;
- whether VIN/chassis values match under business policy;
- whether an audit flag is resolved.

Audit Core owns those decisions.

Extracted values are proposals. They do not silently overwrite a human-entered or previously accepted business value.

---

## 3. Source precedence direction

Where only one source is listed, that document is the current preferred candidate.

Where multiple sources are listed:

1. DI extracts each provenance-bearing fact independently where configured;
2. Audit Core/implementation design defines precedence or reconciliation;
3. disagreement may become an audit-rule input;
4. “last document processed wins” is prohibited as an implicit policy.

---

## 4. Complete 57-field mapping

| # | Field | Stage | Candidate source document(s) | Confidence | Notes |
|---:|---|---|---|---|---|
| 2 | Customer Name | Booking | Booking Docket | SUPPORTED | PC process states customer name is extracted from Booking documents. |
| 3 | Customer Number | Booking | Booking Docket | SUPPORTED | Booking Docket/customer details are the current primary source direction. |
| 5 | Alternate No | Booking | Booking Docket / Customer KYC | PROVISIONAL | Source inventory requires extraction but process does not name exact document. |
| 6 | Mail ID | Booking | Booking Docket / Customer KYC | PROVISIONAL | Exact source not explicitly stated. |
| 7 | Pan | Booking | Customer KYC — PAN | SUPPORTED | KYC explicitly feeds PAN. |
| 8 | GST No | Booking | GST Certificate | SUPPORTED | Corporate/GST requirement explicitly tied to GST certificate. |
| 9 | SC Name | Booking | Booking Docket / dealer booking file | PROVISIONAL | PC process lists SC Name among Booking capture/output; exact printed source not explicit. |
| 10 | SC Number | Booking | Booking Docket / dealer booking file | PROVISIONAL | Same as SC Name. |
| 11 | Pincode | Booking | Address Proof / Booking Docket | PROVISIONAL | KYC/address material supports address; exact precedence is not explicit. |
| 20 | Model | Booking | Booking Docket | SUPPORTED | Process states model is extracted from Booking Docket. |
| 21 | Fuel Type | Booking | Booking Docket / vehicle description source | PROVISIONAL | Exact source not explicitly named. |
| 22 | Variant | Booking | Booking Docket | SUPPORTED | Process states variant is extracted from Booking Docket. |
| 23 | Color | Booking | Booking Docket | SUPPORTED | Process states colour is extracted during Booking document read. |
| 27 | Vin Number/Chasis Number | Booking | Booking Docket / later Tax Invoice DMS | PROVISIONAL | Source mentions chassis extraction but authoritative 8-vs-17 reconciliation remains unresolved. DI must preserve source values separately. |
| 28 | DMS Customer Name | Booking | Booking Docket / DMS-origin document | PROVISIONAL | Legacy field name implies DMS source, but supplied source does not name exact document contract. |
| 29 | DMS Invoice Number | Booking | Tax Invoice — DMS when available / DMS-origin document | PROVISIONAL | Booking-stage availability timing requires confirmation. |
| 35 | Ex Showroom | Booking | Booking Docket / Cost Sheet / Tax Invoice DMS | PROVISIONAL | Commercial value exists in dealer documents; final precedence required. |
| 36 | Registration Type (amount) | Booking | Booking Docket / registration pricing evidence | PROVISIONAL | SPR says registration amount can be populated from registration type; may become master/system rather than DI extraction in final ownership review. |
| 38 | Essential Kit | Booking | Booking Docket / Cost Sheet | PROVISIONAL | Commercial component source not explicitly isolated. |
| 39 | Ceramic Coating | Booking | Booking Docket / Cost Sheet | PROVISIONAL | Same commercial-source issue. |
| 40 | Maintenance Package | Booking | Booking Docket / Cost Sheet | PROVISIONAL | Same commercial-source issue. |
| 41 | Genuine Accessory | Booking | Booking Docket / Cost Sheet / Accessory Invoice | PROVISIONAL | Delivery accessory invoice may be stronger evidence later. |
| 42 | Non Genuine with OEM | Booking | Booking Docket / Cost Sheet / Accessory Invoice | PROVISIONAL | Exact source unsupported. |
| 43 | Non Genuine | Booking | Booking Docket / Cost Sheet / Accessory Invoice | PROVISIONAL | Exact source unsupported. |
| 44 | Insurance | Booking | Booking Docket / Insurance Cover Note | PROVISIONAL | Booking value may be proposal; Delivery policy document later provides stronger evidence. |
| 46 | RSA | Booking | RSA invoice / Booking Docket / Cost Sheet | TBD | SPR mentions RSA invoice in Delivery document set, while provisional 29-document catalogue does not yet carry it as a dedicated requirement. Must reconcile document catalogue first. |
| 47 | TCS | Booking | Booking Docket / Cost Sheet / Tax Invoice | PROVISIONAL | Tax/commercial source direction only; exact precedence not defined. |
| 48 | EW (Extended Warranty) | Booking | EW invoice / Booking Docket / Cost Sheet | TBD | SPR mentions EW Invoice but provisional catalogue does not yet include a dedicated EW requirement. |
| 50 | Service Package | Booking | Booking Docket / Cost Sheet / service-package evidence | TBD | No explicit canonical document in current provisional catalogue. |
| 56 | Sales Discount | Booking | Booking Docket / Cost Sheet / supporting discount document | PROVISIONAL | Source states discounts come from documents and variance requires support. |
| 57 | Buffer Discount | Booking | Booking Docket / Cost Sheet / supporting discount document | PROVISIONAL | Exact support document varies. |
| 60 | Inhouse Insurance Discount | Booking | Booking Docket / Cost Sheet / Insurance evidence | PROVISIONAL | Requires commercial-source precedence. |
| 61 | MR Discount | Booking | Booking Docket / Cost Sheet / supporting discount evidence | PROVISIONAL | Exact source not isolated. |
| 62 | OEM Referral | Booking | Booking Docket / supporting program evidence | PROVISIONAL | Source field label can overlap deal classification; exact source requires review. |
| 63 | Other Discount | Booking | Booking Docket / Cost Sheet / supporting discount evidence | PROVISIONAL | Requires supporting-doc rule configuration. |
| 64 | Scrap Exchange | Booking | Trade-in valuation / Booking Docket | PROVISIONAL | Exchange documents are applicable, but exact source for amount/category is not stated. |
| 65 | Sambandh Scheme | Booking | Booking Docket / scheme-support evidence | TBD | Scheme-specific source is not named in supplied material. |
| 66 | Upward Sales | Booking | Booking Docket / scheme-support evidence | TBD | Exact business/document definition not present in supplied material. |
| 67 | Pro Pack Trims | Booking | Booking Docket / Cost Sheet / accessory evidence | PROVISIONAL | Exact source not isolated. |
| 68 | Non Pro Pack Trims | Booking | Booking Docket / Cost Sheet / accessory evidence | PROVISIONAL | Exact source not isolated. |
| 69 | Self Insurance Discount | Booking | Booking Docket / Cost Sheet / insurance evidence | PROVISIONAL | Exact source/precedence requires review. |
| 70 | Navratri Booking Bonus | Booking | Booking Docket / campaign-support evidence | TBD | Campaign-specific proof is not defined in source. |
| 71 | 2 to 4 Consumer offer | Booking | Booking Docket / campaign-support evidence | TBD | Offer-specific proof is not defined in source. |
| 74 | Amount of Old Vehicle | Booking | Trade-in valuation document | SUPPORTED | Trade-in valuation is explicitly a conditional document requirement. |
| 75 | Trade-in Vehicle Registration No. | Booking | Trade-in RC / RC-Transfer-Authorization document | SUPPORTED | Exchange RC/ownership documents are explicit source material. |
| 76 | Trade-in Car Model | Booking | Trade-in valuation / RC | SUPPORTED | Trade-in documents explicitly include RC and valuation. |
| 80 | Trade-in Vehicle Model Year | Booking | Trade-in RC / valuation | SUPPORTED | Vehicle year is expected from trade-in evidence; exact precedence can be configured. |
| 82 | Actual Discount | Booking | Booking Docket / Cost Sheet / supporting discount evidence | PROVISIONAL | Actual vs standard variance is source-backed; exact document precedence is not. |
| 86 | Name of Firm | Booking | GST Certificate / Corporate ID / Purchase Order | SUPPORTED | Corporate documents are explicit conditional requirements. |
| 88 | Actual | Booking | Purchase Order / corporate-support evidence / Cost Sheet | PROVISIONAL | Field context is corporate discount; exact primary source needs business mapping. |
| 98 | Amount | Both | Payment receipt / Payment Receipts — Tally | SUPPORTED | Receipt amounts are document-backed. |
| 101 | Receipt Date | Both | Payment receipt / Payment Receipts — Tally | SUPPORTED | Receipt date is document-backed. |
| 104 | Receipt Date | Both | Payment receipt / Payment Receipts — Tally | SUPPORTED | Second receipt-detail block; same evidence family. |
| 105 | Amount | Both | Payment receipt / Payment Receipts — Tally | SUPPORTED | Receipt amount. |
| 106 | UTR No | Both | bank transfer receipt / payment evidence | SUPPORTED | Delivery process explicitly calls for UTR for transfers. |
| 113 | Amount | Both | Delivery Order / Bank approval letter | SUPPORTED | DO/finance evidence is explicit for financed deals. |
| 114 | Bank Name | Both | Delivery Order / Bank approval letter | SUPPORTED | Bank is captured for DO/finance verification. |

---

## 5. Mapping summary

Current working classification:

- **SUPPORTED:** fields whose source relationship is directly evidenced by the supplied process/document descriptions.
- **PROVISIONAL:** fields where the general document family is supportable but exact primary source/precedence is not.
- **TBD:** RSA, EW, Service Package and certain scheme/campaign fields whose dedicated evidence source is not sufficiently defined in the current 29-requirement catalogue.

The exact numeric count by class is informational only; source review can move rows between classes without changing the 57-field inventory.

---

## 6. DI configuration gates before implementation

A UC03 extraction profile for a field may be published only when:

1. field has an approved canonical DI fact key;
2. one or more approved document types are mapped;
3. precedence/disagreement behavior is defined where sources overlap;
4. output type/normalisation is defined;
5. confidence threshold and low-confidence treatment are defined;
6. PII handling is approved for identity fields;
7. Audit Core accepted-value destination is defined.

`TBD` rows fail Gate 2 and cannot be silently implemented.

---

## 7. Aadhaar special handling

Aadhaar is not one of the 57 `Extracted` rows in the current workbook; it is marked PC-entered at Delivery. However, Aadhaar evidence also appears in the Booking KYC document catalogue.

UC03 therefore does not add an Aadhaar extraction profile through this mapping document.

Any future Aadhaar extraction/verification must follow the UC03 reconciliation decision:

- masked user presentation;
- no assumed raw Audit Core retention;
- explicit privacy/security approval;
- provenance retained.

---

## 8. VIN special handling

Field #27 may be extracted from one or more source documents, but DI only supplies source-specific identifier facts.

DI does **not** decide whether an 8-character and 17-character representation match.

Audit Core Rule Engine owns that algorithm/version/result.
