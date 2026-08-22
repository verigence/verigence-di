# UC03 — Booking & Delivery Audit — DI Planning Pointer

**Planning branch:** `planning/uc-003-booking-delivery-audit`  
**Frozen baseline:** `dev@c97b3f3e5f8577160c88af1080496808189206fb`

The canonical UC03 design set is maintained in:

`verigence-audit-core / planning/uc-003-booking-delivery-audit / docs/uc-003-booking-delivery-audit/`

Current canonical documents:

- `UC03_SOLUTION_DESIGN_v1.1.md`
- `UC03_WORKFLOW_STATE_EVENT_CATALOG_v1.1.md`
- `UC03_RULE_FLAG_CATALOG_v1.0.md`
- `UC03_DOCUMENT_123_FIELD_MATRIX_v1.0.md`

DI is a controlled supporting module for UC03.

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
- The current document catalogue is provisional: source prose says 26 while the numbered applicability diagram contains 29 entries.
- The 123-field matrix identifies 57 extracted fields; exact field-to-document extraction profiles and precedence still require DI review.
- VIN/chassis reconciliation logic is owned by Audit Core Rule Engine; DI supplies evidence/facts only.

No DI production implementation is authorized by this planning pointer.