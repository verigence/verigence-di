# UC03 — Booking & Delivery Audit — DI Pointer

**Unified UC03 branch:** `planning/uc-003-booking-delivery-audit`  
**Original frozen baseline:** `dev@c97b3f3e5f8577160c88af1080496808189206fb`

The canonical UC03 cross-module design/execution set is maintained in:

`verigence-audit-core / planning/uc-003-booking-delivery-audit / docs/uc-003-booking-delivery-audit/`

Canonical Audit Core documents include:

- `UC03_SOLUTION_DESIGN_v1.1.md`
- `UC03_WORKFLOW_STATE_EVENT_CATALOG_v1.1.md`
- `UC03_RULE_FLAG_CATALOG_v1.0.md`
- `UC03_DOCUMENT_123_FIELD_MATRIX_v1.0.md`
- `UC03_RECONCILIATION_DECISIONS_v1.0.md`
- `UC03_IMPLEMENTATION_DESIGN_v0.1.md`
- `UC03_IMPLEMENTATION_HANDOFF_v1.1.md` — current single-branch sequential execution contract.

## Single-branch execution rule

DI implementation continues on this existing UC03 branch. Do not create a separate Booking, Delivery, Audit, extraction or `work/uc-003-*` branch.

DI participates only when the active sequential checkpoint needs DI work:

```text
C0 Foundation / Project Context    no DI runtime change expected
C1 Booking                         Booking extraction/profile work
C2 Delivery                        Delivery extraction/profile work
C3 Audit / Review / Hardening      provenance/contract hardening only if required
```

## DI working artifacts

- [`UC03_EXTRACTION_SOURCE_MAPPING_v0.1.md`](./UC03_EXTRACTION_SOURCE_MAPPING_v0.1.md) — maps all 57 source fields marked Extracted to candidate evidence sources and classifies each mapping as `SUPPORTED`, `PROVISIONAL`, or `TBD`.
- [`UC03_V2_FAST_BOOKING_SEQUENCE_2026-08-30.md`](./UC03_V2_FAST_BOOKING_SEQUENCE_2026-08-30.md) — freezes the V2 Booking performance sequence: classification is the Step-1 hard gate, extraction starts immediately in a bounded V2 pool, and V1 APIs/adapters remain unchanged.

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

DI does not own:

- Project operational selection/authorization;
- Booking/Delivery business status;
- per-stage Audit State or Audit Status;
- Booking/Delivery workflow progression;
- audit-rule outcome;
- VIN business reconciliation result;
- Audit Flag review/resolution.

## Frozen DI direction

- Delivery business status is `STARTED -> IN_PROGRESS -> COMPLETED`; no Delivery Closed state exists.
- Web/Android communicates with Audit Core, never DI directly.
- Audit Core uses DI for evidence/document processing.
- Extraction is asynchronous and surfaced through Audit Core aggregate processing state.
- Extracted values are proposals with provenance, never silent overwrites.
- Requirement/evidence linkage retains Journey + stage + `requirementKey` semantics.
- The provisional document catalogue retains all 29 numbered source requirements pending UAT reconciliation.
- Source precedence is explicit; processing order is not precedence.
- Aadhaar is not added to extraction/raw-retention by assumption.
- VIN/chassis business reconciliation belongs to Audit Core Rule Engine.
- Only `SUPPORTED` or explicitly reconciled `PROVISIONAL` mappings may become production profiles; unresolved `TBD` stays disabled.

## Immediate implementation gate

C0 requires no DI runtime work unless a real contract dependency is discovered. DI implementation begins with the C1 Booking extraction slice after C0 is formally closed.
