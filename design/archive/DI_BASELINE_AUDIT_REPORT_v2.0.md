# Verigence Document Intelligence — Baseline Audit Report

**Baseline:** 2.0  
**Date:** 2026-08-11  
**Result:** **PASS — BASELINE FOR IMPLEMENTATION**

## 1. What was reviewed

The baseline review covered the complete standalone Document Intelligence artifact set together, not one file in isolation:

- Product/design decision register
- Source traceability
- High-level architecture
- Technology/hosting baseline
- Configuration model
- Data model
- Low-level design
- OpenAPI contract
- PostgreSQL schema
- HLA, ERD and lifecycle diagrams

The uploaded historical material was re-checked only as source evidence for document diversity and audit/compliance context. Historical SPR rules were not silently promoted into standalone Verigence behavior.

## 2. Baseline conclusion

There are **no unresolved design questions in Baseline 2.0**. The documents now use one deterministic model for:

- Tenant/Subject identity and discovery;
- Mobile/Web/API/WhatsApp intake;
- original evidence storage and retrieval;
- upload integrity and deterministic quality fitness;
- classification and extraction;
- configurable extraction fields;
- requirement/completeness calculation;
- processing retry/failure;
- confirmation;
- confidence scoring;
- Human Verification Status and actual verification completion;
- human correction lineage;
- uploader accountability;
- multi-tenancy/RLS;
- audit tamper evidence;
- retention;
- generic external entity linking.

Values that inherently vary by Tenant/environment are governed **runtime master/configuration**, not missing decisions. Activation validation prevents production use when mandatory configuration is absent.

## 3. Confirmed machine and human-verification semantics

Machine lifecycle:

`Upload → Process → Confirm`

Bad source:

- `NOT_FIT`
- `CORRUPT`
- `UPLOAD_FAILED`

These do not enter AI/OCR processing and are corrected by a new upload; the prior attempt remains retained for audit.

Processing:

- retryable first AI/OCR failure → `RETRY_PENDING`;
- one EOD automatic retry;
- retry success → `PROCESSED/CONFIRMED`;
- retry failure → `FAILED/NOT_CONFIRMED`.

Every successfully extracted image/document has `confidence_score` in the range 0–100.

Fixed Phase-1 product rule:

- `confidence_score > 90.00` → `humanVerificationStatus = OPTIONAL`
- `confidence_score <= 90.00` → `humanVerificationStatus = MANDATORY`

Exactly 90.00 is MANDATORY.

Actual human-review completion is deliberately separate:

- `verificationState = NOT_VERIFIED`
- `verificationState = VERIFIED`

No critical-field or validation override silently changes OPTIONAL/MANDATORY in this baseline.

## 4. Hidden/contradictory issues found and closed during review

The baseline review found and corrected the following risks rather than carrying them forward:

1. **Document-ID-only enquiry risk** — primary discovery is now Tenant + Subject; Document ID is secondary after discovery.
2. **Human verification semantic collision** — `humanVerificationStatus` is only OPTIONAL/MANDATORY; completion is `verificationState`.
3. **Configurable 90 threshold risk** — removed; 90.00 is the fixed confirmed product rule and is persisted on confirmed Documents.
4. **Source quality ambiguity** — integrity/corruption and deterministic quality fitness are separately modeled; per-rule evidence is retained.
5. **Caller document-type bypass risk** — caller type is only a hint; machine classification still verifies it.
6. **Manual profile-version risk** — service allocates versions; administrators do not type version numbers.
7. **Multiple current published profile risk** — publishing atomically retires the prior current version in the same scope.
8. **Active Document Type without extraction config** — tenant-created type starts DRAFT; first valid published Extraction Profile activates it.
9. **Stale requirement classification risk** — MANDATORY/OPTIONAL/ADDITIONAL is derived at enquiry time, not stored as authoritative Document state.
10. **Human correction lineage gap** — human accepted values link directly to the Human Verification action.
11. **Audit hash-chain fork risk** — Tenant chain-head rows serialize audit appends; pre-Tenant quarantine has a separate system chain.
12. **WhatsApp cross-Tenant replay risk** — quarantine replay does not accept caller Tenant; Tenant is re-resolved from corrected routing.
13. **Uploader actor/type mismatch risk** — actor identity and type are jointly constrained.
14. **Scoring denominator ambiguity** — a published profile requires an enabled expected score-bearing field with positive weight; missing-field behavior is explicit.
15. **Superseded bad-upload noise** — replaced bad attempts remain historical but are excluded from current actionable exceptions by default.
16. **Unnecessary workflow coupling** — Document Intelligence does not own/hold booking or delivery; generic external entity links are optional.
17. **Arbitrary configuration defaults** — invented upload-timeout and WhatsApp Subject-reference defaults were removed; explicit governed configuration is required.

## 5. Static validation result

Machine-readable result: `DI_STATIC_VALIDATION_v2.0.json`.

All static checks passed, including:

- OpenAPI YAML parsing;
- 292 internal OpenAPI references resolved;
- 40 API paths with matching path parameters;
- 51 unique operation IDs;
- no stale Document-ID-only primary status endpoint;
- exact Human Verification enums and 90.00 boundary;
- SQL table/FK/unique-target structural validation;
- balanced SQL parentheses and PL/pgSQL dollar delimiters;
- trigger target/function reference checks;
- RLS coverage for Tenant-owned application tables, with `whatsapp_routes` deliberately reserved for the privileged system-routing role;
- API/SQL lifecycle enum equality;
- no stale `humanVerificationRequirement` terminology;
- no TODO/TBD/open-design markers;
- no cloud-provider-specific SQL dependency;
- HLA/ERD/lifecycle DOT/SVG/PNG rendering.

## 6. Required runtime configuration — not open design

The following are intentionally not hard-coded because no universal product value exists. They must be configured before production activation:

- Tenant timezone and EOD retry time;
- upload timeout;
- maximum upload bytes;
- allowed MIME types;
- non-empty deterministic quality policy and parameters;
- active retention policy;
- configured OCR/Vision adapter;
- document classification acceptance calibration;
- WhatsApp extracted-identifier Subject-matching confidence calibration;
- WhatsApp explicit Subject-reference convention where used;
- Document Type catalogue;
- published Extraction Profiles and field definitions;
- Requirement Profiles/Subject assignments where completeness is required.

The system fails activation/configuration validation when required values are absent rather than inventing defaults.

## 7. Validation limitation

A running PostgreSQL engine/parser is not available in this workspace. Therefore the SQL was **statically structurally validated but not executed as a live migration** here. Applying the schema to the selected supported PostgreSQL deployment must be an automated CI/deployment acceptance test before production release. This is a deployment verification step, not an unresolved system-design decision.

## 8. Baseline rule

All pre-2.0 Document Intelligence drafts are superseded. Implementation must use the Baseline 2.0 package as one coherent source-of-truth set; individual older files must not be mixed with it.
