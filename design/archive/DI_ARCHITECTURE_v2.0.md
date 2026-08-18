# Verigence Document Intelligence - High-Level Architecture

**Baseline:** 2.0  
**Date:** 2026-08-11  
**Status:** BASELINED  
**Scope:** Standalone Document Intelligence only.

## 1. Purpose

Verigence Document Intelligence accepts evidence from Mobile, Web/PC, API and WhatsApp; preserves the original; validates technical integrity and image/document fitness; classifies the evidence; extracts database-configured fields; normalizes and deterministically validates extracted values; calculates a 0-100 extraction confidence score; determines Human Verification Status as OPTIONAL or MANDATORY; stores evidence/source lineage; and exposes Subject-centric REST enquiries.

The module does not depend on booking, delivery, dealership, audit case, claim, loan, CRM, ERP or another business workflow. Consuming systems may associate their own objects through generic entity links.

## 2. Architecture principles

1. **Minimum manual entry:** Mobile/Web/API provide Tenant + Subject context and evidence; the system derives classification and configured fields where possible.
2. **API first:** all module functions are exposed through versioned REST contracts.
3. **Vendor neutral:** storage, OCR/Vision and hosting technologies sit behind adapters/configuration rather than public-domain contracts.
4. **PostgreSQL core:** relational state is stored in PostgreSQL under dedicated schema `docintel`.
5. **No external event bus in Phase 1:** asynchronous work uses an internal PostgreSQL job queue.
6. **Configuration over document-specific code:** Document Types, Requirement Profiles, Extraction Profiles and quality/rule parameters are data.
7. **Original evidence immutability:** preprocessing creates derived artifacts; it never overwrites source evidence.
8. **AI assists extraction; controls remain deterministic:** lifecycle transitions, integrity checks, quality-rule evaluation, confidence formula, the 90.00 verification boundary, validation and completeness resolution are deterministic.
9. **Evidence lineage:** every machine field can be traced to a Processing Run and source page/region; every human correction can be traced to its Human Verification action.
10. **Tenant isolation:** tenant-aware APIs, PostgreSQL RLS and tenant-scoped storage keys are designed in from Phase 1.
11. **Flag, do not hold:** missing/bad/failed/unverified evidence is surfaced as a compliance/operations condition; this module never blocks an external delivery/business workflow.

## 3. Primary identity model

Primary business discovery:

`tenant_id + subject_id`

- `tenant_id`: opaque business string.
- `subject_id`: opaque business string supplied by Mobile/Web/API or assigned after WhatsApp intake.
- `document_id`: internal UUID for an actual uploaded Document.

A caller can ask “what evidence exists or is missing for this Subject?” without knowing any Document ID.

## 4. Intake channels

### Mobile / Web / API

`POST /v1/tenants/{tenantId}/subjects/{subjectId}/documents`

- Subject ID is required.
- Raw binary is sent as `multipart/form-data`; normal upload is not Base64.
- A caller may supply a Document Type hint, but the hint is non-authoritative and never bypasses machine classification verification.
- Uploader actor/device and server UTC registration time are retained.

### WhatsApp

The WhatsApp adapter:

1. authenticates the provider webhook/signature;
2. resolves Tenant from configured destination/account routing;
3. retains sender/message/media provenance;
4. registers Tenant-resolved media using that route's SYSTEM actor;
5. streams media through the same Document Intake service;
6. resolves Subject only by deterministic rules;
7. leaves the Document UNASSIGNED when no safe unique Subject match exists.

If Tenant cannot be resolved, the intake is placed in system quarantine. No arbitrary Tenant is inferred.

## 5. Machine lifecycle

### Upload stage

`RECEIVING -> VALIDATING -> FIT`

Terminal upload exceptions:

- `NOT_FIT`: file decodes/opens but fails one or more configured deterministic quality rules.
- `CORRUPT`: bytes, signature, format or parser/decoder structure cannot be trusted.
- `UPLOAD_FAILED`: accepted intake could not be completely persisted/validated, including transport/storage failure or stale incomplete upload.

Only `FIT` evidence enters AI/OCR processing.

### Process stage

`NOT_STARTED -> PROCESSING -> PROCESSED`

Retry path:

`PROCESSING -> RETRY_PENDING -> EOD_RETRY -> PROCESSED | FAILED`

One automatic EOD retry is performed for a retryable first-attempt AI/OCR failure.

### Confirm stage

- `PENDING`
- `CONFIRMED`
- `NOT_CONFIRMED`

A Document is `CONFIRMED` when:

1. Upload is `FIT`;
2. classification/extraction execution completes without a processing/configuration exception;
3. results are persisted;
4. `confidence_score` is calculated;
5. `verification_threshold_applied` is persisted as the fixed Phase-1 value `90.00`;
6. Human Verification Status is derived.

`CONFIRMED` does not mean human review has occurred.

## 6. Confidence and human verification

Every successfully extracted Document/image has a Document-level `confidence_score` from 0.00 through 100.00.

Fixed Phase-1 product rule:

- score `> 90.00` => **Human Verification Status = OPTIONAL**
- score `<= 90.00` => **Human Verification Status = MANDATORY**

Exactly 90.00 is MANDATORY.

Human review completion is a separate state:

- `verification_state = NOT_VERIFIED`
- `verification_state = VERIFIED`

Therefore this is valid:

`CONFIRMED + confidence=82.40 + humanVerificationStatus=MANDATORY + verificationState=NOT_VERIFIED`

It is a compliance flag, not a processing failure or delivery hold.

## 7. Confidence calculation

The exact published Extraction Profile defines score-bearing fields and weights.

For each participating field `i`:

- canonical field confidence `c_i` is normalized to 0-100 by the configured provider adapter;
- weight `w_i` is non-negative.

Document score:

`confidence_score = SUM(c_i * w_i) / SUM(w_i)`

Rules:

- only enabled `score_included=true` fields participate;
- only `found_status=FOUND` is present for scoring; NOT_FOUND/AMBIGUOUS/field-level ERROR are treated as missing;
- missing expected scored field contributes confidence 0 with its configured weight;
- missing non-expected scored field is excluded from numerator and denominator;
- published profile must contain positive total score weight;
- result is rounded to two decimals;
- deterministic validation results do not secretly override OPTIONAL/MANDATORY in Phase 1.

## 8. Upload Quality Policy

Integrity and quality are separate.

### Integrity checks

- byte count;
- SHA-256;
- declared vs detected MIME/signature;
- parser/decoder structural validity.

Structural failure => `CORRUPT`.

### Quality checks

Tenant quality policy is a non-empty set of approved quality-rule keys plus parameters stored in database configuration. The quality service executes these deterministic implementations and persists per-rule result, parameters applied and measurement.

Quality-rule failure => `NOT_FIT`.

Exact calibration values are deliberately configuration because source devices/document types differ; no undocumented threshold is hard-coded.

## 9. Classification

Document Type classification is machine-verified even when a caller supplies a hint.

Automatic acceptance requires:

- one selected classification candidate; and
- candidate score meeting Tenant `classification_acceptance_score`.

Otherwise processing ends as a non-retryable classification ambiguity/unclassifiable failure (`FAILED/NOT_CONFIRMED`).

This threshold is Tenant calibration, not the Human Verification threshold.

## 10. Requirement/completeness model

Requirement Profiles are versioned database configuration defining expected Document Types as MANDATORY or OPTIONAL with a minimum count.

A Subject may have zero or one active assignment.

- If assigned, Subject enquiry calculates completeness against the exact assigned immutable profile version.
- If no profile is assigned, upload/processing still works; enquiry exposes `REQUIREMENT_PROFILE_NOT_ASSIGNED`, an empty requirement set and actual evidence separately.
- A supported Document Type outside the assigned profile is accepted and returned as `ADDITIONAL`.
- Missing evidence is derived; no fake Document record is created.
- Requirement classification is derived at enquiry time rather than persisted as authoritative Document state.

## 11. Configuration/versioning

### Document Type
Supported evidence class.

### Extraction Profile
Versioned extraction configuration for one Document Type.

### Requirement Profile
Versioned mandatory/optional document set assigned to a Subject.

### Rule catalogs
Approved reusable normalization, validation and quality implementations referenced by stable keys.

### Tenant settings
Runtime policy/calibration such as timezone, EOD time, upload limit, MIME set, quality policy, retention policy, classification acceptance score and Subject-matching confidence.

Profile rules:

- service allocates version numbers;
- DRAFT is editable;
- PUBLISHED/RETIRED content is immutable;
- publishing a DRAFT atomically retires the prior effective PUBLISHED version in the same scope;
- existing Subject Requirement Profile assignments remain pinned until explicitly reassigned;
- historical Processing Runs retain the Extraction Profile version used.

## 12. WhatsApp Subject resolution

After Tenant resolution, Subject is resolved in this order:

1. explicit Subject reference in the canonical message convention, if valid;
2. exactly one active exact sender-to-Subject mapping;
3. after extraction, exactly one active VERIFIED Subject identifier matching a configured extracted identifier, but only when the field is found, deterministic validation passes and field confidence meets Tenant `subject_matching_min_confidence`;
4. otherwise UNASSIGNED.

Sender identity remains provenance even after Subject assignment.

## 13. Persistence boundary

### PostgreSQL (`docintel`)

Stores:

- tenant/access projections and settings;
- retention/configuration/rule catalogs;
- Subject matching metadata;
- Document metadata/state/integrity;
- deterministic quality results;
- processing jobs/runs/invocations/classification;
- machine extracted facts and accepted value versions;
- deterministic validation results;
- human verification history;
- generic external entity links;
- WhatsApp route/intake/quarantine lineage;
- idempotency;
- tenant and pre-Tenant system audit chains.

### Object storage through `StorageAdapter`

Stores immutable original evidence and configured derived artifacts.

Provider-neutral logical key shapes:

- Original: `tenants/{tenant_storage_key}/documents/{document_id}/original/{artifact_id}`
- Derived: `tenants/{tenant_storage_key}/documents/{document_id}/derived/{artifact_id}`

Subject ID is intentionally excluded so later Subject assignment/correction does not move immutable objects.

Public Document metadata exposes the ORIGINAL logical `originalStorageId` after storage finalization and the content API retrieves bytes; provider-specific bucket/container URLs are never exposed.

## 14. Security/access boundary

- authentication adapter resolves principal;
- API authorizes Tenant/resource/RBAC scope;
- registered-device policy applies to configured Mobile/Web roles;
- service sets transaction-local Tenant context;
- PostgreSQL RLS enforces tenant-row isolation;
- content retrieval is authorized before storage streaming;
- Phase 1 does not mask authorized evidence;
- normal application roles cannot update/delete audit events;
- audit events are hash-chained and serialized through chain-head rows.

## 15. Audit/tamper evidence

Tenant audit append flow is serialized per Tenant by locking its chain-head row, using that row's `last_event_hash` as `previous_event_hash`, inserting the immutable event and then advancing the head in the same transaction.

WhatsApp quarantine exists before Tenant is known, so it uses a separate system audit chain. This avoids inventing a Tenant merely to record pre-routing actions.

## 16. Recovery and operational enquiries

### Bad source

`NOT_FIT`, `CORRUPT` and `UPLOAD_FAILED` are corrected by a new upload. Prior attempts remain for accountability and may be linked as replacement history.

### AI/OCR processing failure

Retryable first failure => `RETRY_PENDING`; one Tenant-local EOD retry is scheduled. Retry failure => `FAILED/NOT_CONFIRMED`.

### Enquiries

The service exposes:

- Subject document/completeness view;
- Subject exceptions;
- Tenant-wide exceptions;
- deterministic quality results;
- upload-quality metrics by uploader;
- mandatory human-verification queue;
- unassigned WhatsApp documents and assignment;
- authorized document content/fields.

There is no primary document-only status discovery endpoint.

## 17. Scalability

Phase 1 scales with stateless API/worker replicas. PostgreSQL row locking prevents duplicate job claims. Published profile versions are cached. Binary evidence stays outside PostgreSQL.

A broker/queue may be introduced later behind the internal dispatcher only when measured throughput justifies it; public REST/domain contracts remain unchanged.

## 18. Deployment readiness rule

A Tenant/document type is activated only after the required configuration exists and validates. The system therefore never invents operational values for:

- retention duration/disposition;
- allowed MIME set/file-size limit/upload timeout;
- non-empty deterministic quality policy and its parameters;
- Tenant timezone/EOD retry time;
- OCR/Vision adapter;
- classification acceptance score;
- extracted-identifier Subject matching minimum confidence;
- Document Type and published Extraction Profile;
- extraction field list/scoring weights;
- Requirement Profile assignment where completeness measurement is required.

These are governed master/configuration values, not unresolved architecture semantics. The Human Verification threshold is not on this list because Phase 1 fixes it at 90.00.
