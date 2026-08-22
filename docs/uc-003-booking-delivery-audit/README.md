# UC03 — Booking & Delivery Audit — DI Planning Pointer

**Planning branch:** `planning/uc-003-booking-delivery-audit`  
**Frozen baseline:** `dev@c97b3f3e5f8577160c88af1080496808189206fb`

The canonical UC03 cross-module design set is maintained in:

`verigence-audit-core / planning/uc-003-booking-delivery-audit / docs/uc-003-booking-delivery-audit/`

Canonical Audit Core documents include:

- `UC03_SOLUTION_DESIGN_v1.1.md`
- `UC03_WORKFLOW_STATE_EVENT_CATALOG_v1.1.md`
- `UC03_RULE_FLAG_CATALOG_v1.0.md`
- `UC03_DOCUMENT_123_FIELD_MATRIX_v1.0.md`
- `UC03_RECONCILIATION_DECISIONS_v1.0.md`

## DI working artifact

- [`UC03_EXTRACTION_SOURCE_MAPPING_v0.1.md`](./UC03_EXTRACTION_SOURCE_MAPPING_v0.1.md) — maps all 57 source fields marked Extracted to candidate evidence sources and classifies each mapping as `SUPPORTED`, `PROVISIONAL`, or `TBD`.

A `TBD` field is not authorized for a production extraction profile until its source is reconciled.

## DI responsibility

DI owns document/evidence intelligence:

- document processing state;
- quality/readability processing where supported;
- classification;
- extraction;
- canonical extracted facts;
- confidence;
- extraction correction/provenance under the approved DI contract.

DI does **not** own:

- Booking/Delivery business status;
- per-stage Audit State or Audit Status;
- Booking/Delivery workflow progression;
- audit-rule outcome;
- VIN business reconciliation result;
- audit flag review/resolution.

## Current UC03 direction

- Delivery business status is `STARTED -> IN_PROGRESS -> COMPLETED`; no Delivery Closed state exists.
- Web/Android communicates with Audit Core as the workflow boundary.
- Audit Core uses DI for evidence/document processing.
- Extraction is asynchronous; Audit Core exposes an aggregate processing read model for Web/Android polling.
- Extracted values are proposals with provenance; they are not silent overwrites.
- The current document catalogue retains all 29 numbered source requirements provisionally pending UAT reconciliation against the source's 26-document wording.
- Source precedence must be explicit where two documents can supply the same field; processing order is not precedence.
- Aadhaar is not added to the 57-field extraction profile by assumption; any future Aadhaar extraction requires explicit privacy/security approval.
- VIN/chassis reconciliation logic is owned by Audit Core Rule Engine; DI supplies source-specific identifier facts only.

No DI production implementation is authorized by these planning documents.
