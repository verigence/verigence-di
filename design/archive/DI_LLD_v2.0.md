# Verigence Document Intelligence - Low-Level Design

**Baseline:** 2.0  
**Status:** BASELINED

## 1. Component contracts

### REST API Service

Responsibilities:

- authenticate principal;
- resolve actor/service identity;
- authorize Tenant, RBAC and resource scope;
- enforce registered-device policy where configured;
- set transaction-local Tenant for PostgreSQL RLS;
- accept binary uploads;
- expose Subject-centric enquiries, content/fields, verification and configuration APIs.

### WhatsApp Adapter

Responsibilities:

- authenticate provider webhook/signature;
- resolve Tenant route;
- retain sender/message/media provenance;
- download/stream media;
- register with configured SYSTEM actor after Tenant resolution;
- call the common intake service;
- quarantine Tenant-unresolved intake;
- leave Subject unresolved when deterministic matching is insufficient.

### Document Intake Service

1. allocate `document_id`;
2. persist immutable provenance and a `RECEIVING` Document row;
3. allocate ORIGINAL artifact ID/key;
4. stream bytes to `StorageAdapter` while calculating byte count + SHA-256;
5. finalize storage metadata;
6. move Document to `VALIDATING`;
7. invoke Upload Validator / Quality Service;
8. create INITIAL processing job only for `FIT` evidence.

### StorageAdapter

Provider-neutral operations:

- `put_stream(logical_key, stream, metadata) -> storage_id`
- `get_stream(storage_id) -> stream`
- `exists(storage_id) -> bool`
- `get_metadata(storage_id)`
- `delete(storage_id)` only under retention authorization

Logical key shapes:

- ORIGINAL: `tenants/{tenant_storage_key}/documents/{document_id}/original/{artifact_id}`
- DERIVED: `tenants/{tenant_storage_key}/documents/{document_id}/derived/{artifact_id}`

No Subject ID or cloud bucket/container name is part of the domain identity.

### Upload Validator / Quality Service

Integrity checks:

- configured maximum bytes and allowed MIME set;
- declared vs detected MIME/signature;
- file decode/parser structural validity;
- byte count/hash completion.

Integrity outcomes:

- storage/transport/incomplete timeout => `UPLOAD_FAILED`
- invalid bytes/structure => `CORRUPT`

Quality checks:

- load non-empty Tenant Quality Policy;
- execute only approved quality-rule implementation keys with configured parameters;
- persist one `document_quality_results` row per rule with parameters/measurement/outcome;
- any policy-defined quality failure => `NOT_FIT`;
- otherwise => `FIT`.

No AI-generated quality conclusion is used as a hidden deterministic control.

### Requirement Resolver

- load zero/one active Subject Requirement Profile assignment;
- use the exact immutable version referenced by the assignment even if a later version has been published;
- derive mandatory/optional requirements;
- derive actual Document classification (`MANDATORY|OPTIONAL|ADDITIONAL`);
- calculate current requirement states/counts;
- expose `REQUIREMENT_PROFILE_NOT_ASSIGNED` without blocking uploads.

### Extraction Profile Resolver

Resolution precedence:

1. currently PUBLISHED Tenant-specific profile for the classified Document Type;
2. currently PUBLISHED global/default profile.

No profile => non-retryable configuration failure.

Published profile is resolved once per Processing Run and cached by immutable profile/version ID.

### Processing Worker

1. claim a due job using `FOR UPDATE SKIP LOCKED`;
2. create immutable Processing Run;
3. set Document `PROCESSING`;
4. machine-classify Document Type; caller hint may narrow/boost candidates but cannot bypass classification;
5. accept classification only when exactly one selected candidate meets Tenant `classification_acceptance_score`;
6. otherwise fail non-retryably with classification ambiguity/unclassifiable code;
7. resolve Extraction Profile;
8. call `DocumentAIAdapter.extract()` with all enabled configured fields in one schema-capable call where supported;
9. normalize fields;
10. run deterministic validation rules;
11. persist immutable machine facts and current MACHINE accepted values;
12. calculate Document confidence score;
13. persist `verification_threshold_applied=90.00`;
14. derive Human Verification Status (`>90 OPTIONAL`, `<=90 MANDATORY`);
15. set `PROCESSED + CONFIRMED`.

### DocumentAIAdapter

Canonical operations:

- `classify(artifact, candidate_types, hint?) -> classifications[]`
- `extract(artifact, extraction_schema) -> field_results[]`

Each field result includes a canonical 0-100 confidence or a deterministic adapter mapping from provider-native confidence. An adapter unable to provide a documented deterministic normalization is not eligible for production configuration.

### Confidence Scoring Service

For enabled `score_included=true` fields:

- only `found_status=FOUND` is treated as present;
- FOUND => normalized field confidence participates with configured weight;
- NOT_FOUND/AMBIGUOUS/field-level ERROR are treated as missing;
- missing expected => confidence 0 participates with configured weight;
- missing non-expected => excluded;
- weighted mean is rounded to two decimals;
- positive total score weight is mandatory at profile publication;
- fixed threshold 90.00 determines OPTIONAL/MANDATORY;
- deterministic validation failures are reported separately and do not silently alter this status in Phase 1.

### Human Verification Service

Available only after machine `CONFIRMED`.

A verification action can:

- accept extracted values;
- add remarks;
- correct fields where profile allows manual correction.

Phase 1 allows at most one successful verification action per Document; if `verification_state=VERIFIED`, a second attempt returns HTTP 409 invalid state.

On successful review:

1. append the single `human_verifications` row;
2. for each correction create a new HUMAN `document_field_values` version linked by `source_verification_id`;
3. mark prior accepted value non-current transactionally;
4. set Document `verification_state=VERIFIED`;
5. never recalculate or overwrite machine confidence/facts.

The product-facing Human Verification Status remains the machine-derived `OPTIONAL|MANDATORY` value.

### EOD Retry Scheduler

At configured Tenant local EOD time:

1. select `RETRY_PENDING` Documents with no EOD_RETRY job;
2. insert one EOD_RETRY job (`attempt_no=2`);
3. worker retries the same immutable FIT original evidence;
4. success => `PROCESSED/CONFIRMED`;
5. failure => `FAILED/NOT_CONFIRMED`.

INITIAL jobs are `attempt_no=1`. Database constraint prevents swapping attempt numbers.

### Query/Operations Service

Provides:

- Subject document/completeness view;
- Subject exceptions covering missing requirements and actual Document exceptions;
- Tenant-wide exceptions covering missing requirements and actual Document exceptions;
- per-Document quality results;
- verification queue;
- upload-quality metrics by uploader;
- unassigned WhatsApp list/metadata/content/fields/quality results/assignment.

### Audit Writer

Tenant audit append transaction:

1. `SELECT audit_chain_heads ... FOR UPDATE` for Tenant;
2. use current `last_event_hash` as `previous_event_hash`;
3. canonicalize event payload and calculate SHA-256 event hash;
4. INSERT immutable `audit_events` row;
5. UPDATE Tenant chain head;
6. commit.

This prevents concurrent audit-chain forks. UPDATE/DELETE of audit event rows is rejected by DB trigger.

Pre-Tenant quarantine uses the separate singleton `system_audit_chain_head` + immutable `system_audit_events` chain.

## 2. Mobile/Web/API upload flow

Endpoint:

`POST /v1/tenants/{tenantId}/subjects/{subjectId}/documents`

1. authenticate/authorize actor;
2. require Tenant + Subject path values;
3. enforce registered device where role policy applies;
4. optional `documentTypeKey` must resolve to a supported visible type but remains a non-authoritative hint;
5. Requirement Profile assignment is **not** required for upload;
6. create `RECEIVING` Document;
7. create ORIGINAL logical artifact identity;
8. stream raw multipart bytes; no Base64 transformation;
9. hash/count while streaming;
10. storage/transport failure => `UPLOAD_FAILED`;
11. storage success => `VALIDATING`;
12. invalid structure => `CORRUPT`;
13. deterministic quality-policy failure => `NOT_FIT`;
14. usable => `FIT` + INITIAL job;
15. return Document metadata/state.

A stale `RECEIVING` row older than configured upload timeout is finalized to `UPLOAD_FAILED` by reconciliation.

## 3. Bad-source replacement

Only `NOT_FIT`, `CORRUPT` or `UPLOAD_FAILED` may be explicitly replaced through `replacesDocumentId` in Phase 1.

Rules:

- replacement and prior Document must belong to same Tenant;
- when both have Subject, Subject must match;
- prior Document remains retained and gets `replaced_by_document_id`;
- replacement creates a new `document_id`, new immutable original and fresh processing path;
- confirmed evidence is not silently superseded by this recovery mechanism.

## 4. Processing failure taxonomy

### Retryable

Examples: provider timeout, temporary network/provider failure, transient worker failure.

- Processing Run = FAILED, `error_class=RETRYABLE`;
- Document = `RETRY_PENDING`;
- confirmation stays PENDING;
- EOD handles one automatic retry.

### Non-retryable

Examples:

- classification ambiguous/unclassifiable under configured acceptance policy;
- no published Extraction Profile;
- invalid published configuration detected despite publication checks;
- unsupported content for configured Document Type.

Result:

- Processing Run = FAILED, `error_class=NON_RETRYABLE`;
- Document = `FAILED/NOT_CONFIRMED`.

A provider may successfully extract low/zero-confidence fields. That is not a processing exception; the Document can still become `CONFIRMED` with a low score and `MANDATORY` human verification.

## 5. Requirement resolution

Upload and completeness are deliberately decoupled.

If no active Requirement Profile assignment exists:

- upload/processing continues;
- Subject enquiry returns `configurationStatus=REQUIREMENT_PROFILE_NOT_ASSIGNED`;
- `requirements=[]`;
- classified evidence is returned as additional evidence and unclassified evidence remains separately visible.

When a profile is assigned/reassigned later, the next enquiry reclassifies existing Document relationships against that profile without reprocessing bytes.

A newer published Requirement Profile version does not automatically alter an existing Subject assignment.

## 6. Subject enquiry

Primary endpoint:

`GET /v1/tenants/{tenantId}/subjects/{subjectId}/documents`

Response includes:

- active assigned Requirement Profile reference or null;
- configuration status;
- mandatory/optional requirement rows and derived machine state;
- actual Documents per requirement;
- `confidenceScore` per confirmed Document;
- `humanVerificationStatus = OPTIONAL|MANDATORY`;
- `verificationState = NOT_VERIFIED|VERIFIED`;
- additional/unclassified evidence;
- uploader provenance;
- provider-neutral `originalStorageId` once storage finalization is complete.

There is no primary `/v1/documents/{documentId}/status` discovery endpoint.

## 7. WhatsApp flow

### 7.1 Tenant resolution

`whatsapp_routes` maps provider destination/account identifier to:

- Tenant;
- registered SYSTEM actor.

Unknown route:

1. store quarantine metadata and temporary storage reference under system namespace;
2. append system audit event;
3. do not create a tenant-owned Document;
4. authorized operator corrects route and calls replay;
5. replay creates normal Tenant-owned Document, streams/copies media into the Tenant logical storage key, records source lineage, then deletes temporary quarantine content only after successful Tenant persistence;
6. append system audit replay result and Tenant audit intake event.

A system-authorized discard endpoint is provided for invalid/unwanted quarantine items; it deletes temporary media only after marking the item DISCARDED in a system-audited transaction.

### 7.2 Subject resolution

For a Tenant-resolved WhatsApp Document:

1. parse explicit configured Subject reference and validate format/value;
2. else use exactly one active sender mapping;
3. else after extraction evaluate profile fields marked `use_for_subject_matching=true`;
4. candidate field must be FOUND, normalized, pass applicable deterministic validation and meet Tenant `subject_matching_min_confidence`;
5. exact match must return exactly one active VERIFIED Subject identifier;
6. otherwise keep `subject_id=NULL` / UNASSIGNED.

Unassigned Documents remain processable/retrievable. Authorized assignment sets Subject and immediately re-evaluates requirement relationships. Original sender/uploader provenance is immutable.

## 8. Duplicate handling

After full SHA-256 + byte count is available:

- search same Tenant for identical SHA-256 + size;
- record `duplicate_of_document_id` if exact duplicate is found;
- do not automatically reject because duplicate evidence can be legitimate.

## 9. Idempotency

For mutation APIs supporting `Idempotency-Key`:

- scope = Tenant + actor + operation;
- first request creates in-progress idempotency record;
- request fingerprint excludes unstable transport metadata and includes stable command metadata; file upload fingerprint is finalized with content SHA-256;
- completed response/resource ID is persisted;
- same key + same fingerprint => original response;
- same key + different fingerprint => HTTP 409 `IDEMPOTENCY_CONFLICT`.

## 10. Content retrieval

After Subject discovery, specific Document operations remain under Tenant + Subject:

- metadata;
- original content;
- extracted fields;
- deterministic quality results;
- human verification;
- entity links.

For unassigned WhatsApp, equivalent Tenant + unassigned-document endpoints allow an authorized resolver to inspect evidence before assignment.

If retention purged content, metadata remains and content retrieval returns HTTP 410 `DOCUMENT_CONTENT_PURGED`.

## 11. Configuration lifecycle APIs

### Document Type / Extraction Profile

- tenant Document Type create => status DRAFT; first valid Extraction Profile publication atomically activates it;
- Extraction Profile create => server allocates next `version_no`, status DRAFT;
- update => DRAFT content only; version/type/scope immutable;
- publish => in one DB transaction retire current PUBLISHED in same type/scope and publish target DRAFT;
- no separate Phase-1 retire API is needed for replacement rollout;
- DB triggers prevent editing/deleting published or retired profile content.

### Requirement Profile

- create => server allocates next `version_no` within Tenant + `profile_key`;
- update => DRAFT content only; key/version immutable;
- publish => atomically retires prior PUBLISHED version of same key and publishes target DRAFT;
- existing Subject assignment to prior immutable version remains valid until explicit reassignment;
- DB triggers prevent editing/deleting published or retired profile content/items.

## 12. Retention

At Document registration:

- require an active Tenant retention policy for production intake;
- snapshot retention policy ID, calculated `retention_until_utc` and disposition.

On expiry:

- purge/retain content according to snapshot;
- preserve metadata and audit lineage;
- original/derived deletions occur only through retention-authorized StorageAdapter action;
- content state changes to PURGED after successful deletion.

## 13. Audit history

Every material state/configuration/verification/link/assignment action appends an audit event containing:

- Tenant, or system chain for pre-Tenant quarantine;
- actor;
- event/action;
- entity ID/type;
- UTC timestamp;
- relevant before/after state;
- correlation metadata;
- previous hash;
- event hash.

Sensitive document contents are not copied into audit payloads or normal logs.

## 14. Observability

Required metrics:

- upload count by channel/uploader;
- FIT/NOT_FIT/CORRUPT/UPLOAD_FAILED;
- per-quality-rule failure frequency;
- first-pass FIT rate;
- processing success/retry/final failure;
- EOD retry success/failure;
- classification ambiguity rate;
- processing/provider latency;
- confidence distribution by Document Type;
- MANDATORY human-verification rate/backlog;
- unassigned WhatsApp backlog.

## 15. Activation validation

A Tenant is not marked production-ready until required settings exist:

- active retention policy;
- non-empty MIME set/file size/upload timeout;
- non-empty valid Quality Policy;
- timezone/EOD retry time;
- classification acceptance score;
- extracted-identifier Subject matching confidence;
- configured OCR/Vision adapter.

A Document Type is not processing-ready until it has a current published Extraction Profile satisfying scoring/rule validation.

These are deterministic activation checks, not open design questions.


## 16. Exception-history behavior

Subject/Tenant exception APIs return current actionable conditions by default. A terminal bad upload that has been explicitly replaced is retained for audit/upload-quality metrics but is excluded from the active exception list. `includeResolvedHistory=true` exposes those historical superseded attempts.
