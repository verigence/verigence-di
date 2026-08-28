# Schema V2 — Frozen Implementation Plan

**Status:** FROZEN FOR IMPLEMENTATION  
**Date:** 29-Aug-2026  
**Implementation branch:** `feature/schema-v2-document-extraction`  
**Database work branch:** Neon `schema-v2-sandbox` (`br-small-union-ay4fly2s`)  
**Database safety snapshot:** Neon `pre-schema-v2-20260829` (`br-falling-pond-ay4o95km`)  
**Parent database branch:** `production` (`br-frosty-star-ayknqwz6`) — MUST remain untouched during sandbox work.

## 1. Frozen source inputs

This implementation is governed by two user-supplied source files plus the decisions in this plan.

1. **Initial architecture/design document**
   - Original uploaded filename: `bafa0036-bde2-4e09-a3aa-c9c447b4e1dc.md`
   - SHA-256: `d8889eccfd5c12e270d35140baf1ce2e9e8153ab3720c827349d7d6feb9f0773`
   - Key design themes retained: classification separated from extraction; type-specific schemas; raw evidence preserved; deterministic normalization/verification; DMS as deterministic ingress; reconciliation and audit resolution distinct from extraction; effective-dated masters; immutable provenance.

2. **18-document proposed extraction-schema package**
   - Original uploaded filename: `baaebe3f-05b2-4b78-8168-d5c5154752ae.json`
   - SHA-256: `1ec12211fdb35c2dac998f8897198048e44032955a1d91cc4ecc4174b06f7724`
   - The package is a field-discovery and extraction-design input, not an instruction to create duplicate canonical fields verbatim.

If a future implementation decision conflicts with these frozen inputs or this plan, it requires an explicit design amendment before code/profile publication.

## 2. Non-negotiable architecture constraints

1. Preserve the existing DI architecture. No replacement schema engine and no parallel extraction subsystem.
2. DI owns evidence custody, classification, extraction, normalization/validation and immutable extraction lineage.
3. Audit Core owns journey/business semantics, source reconciliation, deterministic classification of business concepts, controls/findings and final audit conclusions.
4. Web should normally interact through Audit Core for journey/evidence semantics; DI must not be taught dealer-audit business logic merely to make a UI easier.
5. Existing published extraction profiles remain immutable/versioned. New versions retire previous published versions; historical facts remain traceable.
6. Keep current invoice separation such as `tax_invoice_tally` and `accessory_invoice_tally`. Do not collapse these into a generic invoice type for the audit.
7. No production/default database mutation during development. All database changes are first exercised on `schema-v2-sandbox`.

## 3. Gate 1 — semantic role model (blocking)

### 3.1 Role granularity

Role is **not only a document attribute**. A document may carry a default role, but each extracted fact must have an effective role, because one document can contain facts about multiple entities/vehicles.

Examples:
- Cost Sheet: subject/new vehicle chassis facts plus exchange-vehicle registration/make/value facts in the same extraction.
- Transfer Letter: transferor/transferee facts can have distinct party roles.
- Valuation Report: primarily exchange vehicle, but may reference the subject/new deal.

The model is therefore:

`document default role -> profile-field role override -> emitted fact effective role`

The canonical key remains the semantic field (`chassis_number`, `vehicle_registration_number`, etc.); role prevents collision. Do not proliferate duplicate canonicals such as `new_vehicle_chassis_number` and `exchange_vehicle_chassis_number` merely to represent context.

### 3.2 Initial role vocabulary

The implementation starts with a deliberately small, extensible vocabulary:

- `UNSPECIFIED`
- `SUBJECT_VEHICLE`
- `EXCHANGE_VEHICLE`
- `SUBJECT_TRANSACTION`
- `CUSTOMER`
- `PAYER`
- `TRANSFEROR`
- `TRANSFEREE`
- `ORGANISATION`

Only roles needed by an approved profile are introduced. Values are business context, not AI confidence labels.

### 3.3 Vehicle RC instance role

`VEHICLE_RC` is one document type. Whether a specific RC instance is subject/new-vehicle evidence or exchange-vehicle evidence must not be guessed from visual type alone.

Preferred source of instance role: the Audit Core evidence requirement/slot selected by the workflow/human. DI may preserve the supplied opaque role context, but must not infer trade-in semantics from document type. An unknown/ambiguous instance role routes to review rather than a dangerous journey-level join.

## 4. Canonical-field discipline

1. Reuse an existing canonical field only when business meaning is identical.
2. Never map by string similarity alone.
3. Context/role participates in semantic identity. For example, vehicle registration and GST registration are not aliases.
4. Keep canonical vocabulary stable; put document-native terminology into `extraction_instruction`/aliases.

Example:

- Canonical: `vehicle_registration_number`
- RC extraction instruction: "Extract the Regn. No. printed at the top of the RC."

This preserves vocabulary discipline without weakening Gemini extraction instructions.

## 5. Three-state evidence semantics

For evidence-presence observations:

- `true` = clearly present/affirmatively observed
- `false` = clearly absent/affirmatively not observed
- `null` = unknown, unreadable, cropped, ambiguous or cannot establish

All presence booleans in the proposed schema package must allow null, including signatures, seals, notarisation, handwritten flags, complimentary flags, QR/photo presence, hypothecation, manual alteration and similar evidence observations.

Rule-authoring standard: **never use generic truthiness** for three-state facts. Rules must explicitly distinguish TRUE, FALSE and UNKNOWN. `if not signature_present` is prohibited because it collapses `null` and `false`.

## 6. Raw evidence vs deterministic derived concepts

Gemini should extract what the document states. Where a concept can be classified reproducibly in code, keep the printed text/section and derive the category outside the model.

Candidates for deterministic derivation include, where applicable:
- `discount_type`
- `movement_type`
- charge/fee categories
- `valuation_platform`
- debit-note reason/direction classifications
- similar normalized business enums

The classification mapping/ruleset is itself auditable configuration. It must be **versioned, immutable after publication and pinned to findings/evaluations**, just like an extraction profile.

## 7. Evidence / Reference / Extract-and-Compare partition

Every candidate field is assigned one of three source classes before profile publication:

1. **EVIDENCE — must extract**: the document's statement is itself the audit subject, e.g. printed discount lines, approvals/signatures, complimentary flags, net payable as printed, exchange values as stated, manual alterations.
2. **REFERENCE — use DMS/master**: authoritative master/reference facts where reading the same value from a document adds no control value.
3. **EXTRACT_AND_COMPARE — extract both**: fields where divergence between document and system/master is itself an audit signal, e.g. ex-showroom, RTO charged, insurance charged, transaction totals.

Cost Sheet pruning is forbidden until the first draft of the discount/revenue-leakage controls exists. The final keep-list is the union of control inputs plus the evidence and compare buckets.

## 8. Structured rows and ledger handling

DI's JSON persistence can carry structured values, but nested row shape must not rely only on prompt compliance.

- Repeating arrays are post-validated with deterministic typed row models.
- A malformed row is surfaced as an extraction-quality/review condition; it is never silently dropped.
- Customer Ledger remains a document-level invocation.
- Ledger rows carry `source_page` where available.
- Extract document-stated totals and closing balance.
- Reconcile extracted row sums and running-balance continuity against stated totals.
- A reconciliation failure is initially `AMBIGUOUS_REVIEW`, not automatically `EXTRACTION_FAILED`, because it may mean either a dropped extraction row or a genuinely non-reconciling ledger — which is itself potentially an audit finding.

## 9. Lineage — implemented from Wave 1, not deferred

Every sandbox extraction used as test evidence must be traceable. Target lineage:

`Finding/Evaluation -> Audit Evidence Fact -> DI Fact/Value Version -> DI Processing Run -> Extraction Profile ID + Version -> AI Invocation -> Classification Ruleset Version (if a derived classification was used)`

DI already stores processing run, profile reference, per-field confidence, page/evidence localization and invocation linkage. Integration changes must ensure Audit Core snapshots enough identifiers/version information to defend historical findings without re-running Gemini.

## 10. Classification and splitting

### 10.1 Classification baseline

DI already persists a deterministic candidate snapshot and pins the profile chosen for the processing run. This behavior is preserved.

The current Gemini adapter's classifier implementation must be treated separately from the design specification: implementation verification is required before relying on machine classification accuracy.

### 10.2 Mixed-file splitting

Current intake treats one uploaded artifact as one DI Document. No assumption is made that a merged multi-document PDF is already split.

Support for a merged dealer pack is therefore a distinct prerequisite/design increment. Until implemented and validated, the supported contract is one logical document per DI Document/upload. The workflow should make this explicit rather than silently classifying a 40-page mixed pack as one type.

## 11. Golden-set testing and exit criteria

A/B against an old profile is insufficient for new document types. Each implemented type requires labelled ground truth.

Initial target: **30–50 real representative documents per type**, including poor photos, skew/glare, partial illegibility and handwritten amendments where applicable. The exact minimum may be raised for high-variance document types.

Thresholds are defined before each wave and by criticality; there is no single universal accuracy number. Critical identifiers and amounts (VIN/chassis, registration, invoice total, discount amount, payment reference, etc.) require materially stronger acceptance than low-impact descriptive fields.

Wave test reporting includes:
- field precision/recall/accuracy against hand-keyed truth
- null/false/true behavior for three-state observations
- role-isolation assertions
- array row validity/completeness
- source-page/evidence localization coverage
- confidence retention
- profile/version lineage
- DMS/master comparison behavior
- latency/token/cost telemetry

## 12. Historical re-extraction policy

Publishing profile v2 never silently rewrites a historical finding.

Default policy:
1. Existing historical extracted facts/findings remain pinned to the versions that produced them.
2. New documents use the newly published profile.
3. Re-extraction of historical documents is an explicit operation producing a new processing run/fact version.
4. Re-extraction does not automatically mutate/close/re-open a prior finding; Audit Core creates a new evaluation or an explicit supersession/review event according to policy.
5. Bulk re-extraction requires an approved migration/backfill plan with cost and audit-impact review.

## 13. Parallel audit-control workstream

Starts in Phase 1 and is owned by the audit methodology/business-control layer, not DI.

First draft names leakage/control channels sufficiently to drive source mapping, including at minimum:
- standard vs actual vehicle price
- undocumented discount / above-scheme discount
- exchange valuation/bonus/ownership/hypothecation/NDC leakage
- accessory free/under-billed/unbilled leakage
- insurance charge/IDV/NCB/add-on variance
- RTO/statutory vs service-charge variance
- receipt/ledger/bank realization mismatch
- debit/credit-note post-sale adjustments
- approvals/authority overrides
- manual alterations / document-integrity observations
- DMS vs Tally reconciliation
- missing/unaudited booking or delivery population gaps

This draft precedes final Cost Sheet/ledger/invoice profile pruning.

## 14. Implementation sequence

### Phase 0 — isolation, baseline and lineage contract
- Freeze source hashes and this plan.
- Create/verify immutable database safety snapshot and isolated work branch.
- Capture current migration head, document types, canonical fields, profiles and profile versions.
- Define the DI-to-Audit lineage payload additions.
- Define role vocabulary/default/override mechanics.
- Verify whether the current production adapter performs real machine classification or hint pass-through; do not assume.

### Phase 1 — semantic mapping + audit controls (parallel)
- Complete the 18-document matrix:
  `source field -> document -> canonical -> effective role/default+override -> raw/derived -> EVIDENCE/REFERENCE/COMPARE -> consumer control`.
- Resolve RC instance-role assignment contract.
- Draft audit-control inputs in parallel.
- Correct the proposed schemas: nullable observations, remove model-derived categories where deterministic rules can own them, document-level ledger arrays.

### Phase 2 — foundation implementation in sandbox
- Add fact-role metadata without duplicating canonical keys.
- Add/version deterministic classification rulesets and lineage identifiers.
- Add structured-row validation hooks.
- Add ledger ambiguity/reconciliation quality checks.
- Extend DI/Audit integration lineage payload.
- Keep existing published profiles and production DB untouched.

### Wave 1 — prove safety mechanisms early
Implement a small set that exercises both simple extraction and role collision:
- GST Certificate
- Corporate ID profile alignment
- Bank Approval Letter
- Valuation Report (pulled forward specifically to exercise `EXCHANGE_VEHICLE` role)

Test one journey with the same canonical vehicle identifier in different roles and prove that subject/new and exchange facts remain distinct through DI and Audit Core.

### Wave 2 — vehicle/trade-in evidence
- Vehicle RC
- Transfer Letter
- NDC / existing `no_dues_certificate` alignment
- remaining valuation fields

### Wave 3 — structured transaction/control documents
- Debit Note
- Registration Invoice
- Gate Pass
- Third-Party Payment Declaration
- RTO Challan
- Purchase Order
- Authorization Letter

### Wave 4 — heavy audit documents
- Customer Ledger
- Cost Sheet
- Tally vehicle invoice enhancement while preserving `tax_invoice_tally`
- accessory invoice enhancement while preserving `accessory_invoice_tally`
- Delivery Photo minimal evidence extraction

Wave 4 profile fields are finalized only after the audit-control source matrix is available.

### Mixed-pack splitting — separate gated increment
Design and implement only after the one-document-per-upload schema path is stable. Do not mix this risk into initial profile rollout.

## 15. Promotion gate

Nothing is automatically merged/deployed/promoted from the sandbox.

Before promotion:
1. CI/unit/integration tests green.
2. Golden-set thresholds met per wave.
3. Role-collision E2E passed through Audit Core.
4. Lineage reconstructable from output to profile/ruleset versions.
5. Database schema diff reviewed.
6. Historical re-extraction behavior tested.
7. Explicit approval obtained for merge/database promotion/deployment.

## 16. Rollback posture

- Parent Neon branch remains unchanged during sandbox work.
- `pre-schema-v2-20260829` is the point-in-time safety branch captured before implementation.
- `schema-v2-sandbox` carries all experimental DB changes.
- Git implementation is isolated on `feature/schema-v2-document-extraction`.
- A rejected implementation can be discarded by deleting sandbox/work branches; the original DB and `dev` source remain available.
