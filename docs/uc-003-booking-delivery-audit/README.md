# UC03 — Booking & Delivery Audit — DI Planning Pointer

**Planning branch:** `planning/uc-003-booking-delivery-audit`  
**Frozen baseline:** `dev@c97b3f3e5f8577160c88af1080496808189206fb`

The canonical UC03 cross-module Solution Design and Workflow Manager model are maintained in:

`verigence-audit-core / planning/uc-003-booking-delivery-audit / docs/uc-003-booking-delivery-audit/`

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

## UC03 direction

- Web/Android communicates with Audit Core as the workflow boundary.
- Audit Core uses DI for evidence/document processing.
- Extraction is asynchronous and may take meaningful time; Audit Core exposes a cheap aggregate processing read model for Web/Android polling.
- Extracted values are proposals and retain provenance; they are not client-side silent overwrites.
- Exact UC03 document/extraction configuration is deferred until the provisional document and 123-field matrix is reviewed.

No DI production implementation is authorized by this planning pointer.
