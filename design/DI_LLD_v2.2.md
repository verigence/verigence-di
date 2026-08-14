# Verigence Document Intelligence - Low-Level Design

**Baseline:** 2.2  
**Status:** BASELINED

## 1. Standalone Subject ownership

Verigence owns a lightweight Tenant-scoped Subject Registry. Subject creation allocates a server-generated UUID. Mobile/Web/API upload requires an existing active Verigence Subject ID. The registry provides grouping identity only and is not a CRM/customer master. No external/legacy application is required to create or manage Subjects.

## 2. Correlation and observability contract

Phase 1 uses one vendor-neutral technical token: `X-Correlation-ID`.

1. API/webhook middleware accepts it when present.
2. Safe character set is `A-Z a-z 0-9 . _ : -`, length 1-128.
3. If absent, Verigence generates a UUID.
4. Every HTTP response returns it.
5. Initial intake persists it on the Document and Processing Job.
6. Worker copies it to the Processing Run and each Processor Invocation.
7. Structured logs include correlation ID plus Tenant/Subject/Document/job/run/invocation identifiers when known.
8. Provider `provider_request_id` remains separate.
9. EOD retry receives a new correlation ID because it is a new execution chain.
10. No vendor-specific distributed tracing product is mandatory. Structured logs + metrics + correlation ID are the Phase-1 observability contract.

## 3. JWT / RBAC contract

The normative security contract is `docs/DI_SECURITY_RBAC_v2.2.md` / `security/DI_RBAC_v2.2.yaml`.

- Tenant JWT audience: `verigence-document-intelligence`.
- Required claims: `iss, sub, aud, exp, iat, tenant_id, actor_id, actor_type, roles[], permissions[]`.
- USER additionally requires `device_id` and an ACTIVE registered-device row for the same Tenant + actor.
- Endpoint authorization checks the OpenAPI `x-required-permissions` list.
- Invalid/missing token/claims => `UNAUTHORIZED`; insufficient permission/scope => `FORBIDDEN`.
- System JWT audience: `verigence-document-intelligence-system`; `tenant_id` absent; system WhatsApp administration requires `platform:whatsapp:admin`.
- WhatsApp provider webhook uses provider signature verification, not JWT.

## 4. Error / Problem contract

The normative catalogue is `docs/DI_ERROR_CATALOG_v2.2.md` / `api/DI_ERROR_CATALOG_v2.2.yaml`.

Every application error response — regardless of which layer raised it — **must** conform to the Problem schema:

```json
{
  "type":          "https://docs.verigence.app/errors/{code_lower}",
  "code":          "DOCUMENT_NOT_FOUND",
  "title":         "Human-readable stable title",
  "status":        404,
  "retryable":     false,
  "category":      "RESOURCE",
  "detail":        "Optional caller-facing explanation",
  "correlationId": "abc-123"
}
```

Rules:

1. `code` is the only stable client decision key. Clients **must not** parse `title` or `detail` for logic.
2. Every error response returns `X-Correlation-ID` in the response header **and** `correlationId` in the body.
3. `retryable=true` means a technical retry may be attempted only when the operation is safe/idempotent.
4. Authentication claim failures use `UNAUTHORIZED`; permission/scope failures use `FORBIDDEN`.
5. Processing-run failure codes use the catalogue where applicable; raw provider error text is never a public client contract.

### Exception handling layers — required contract

**Layer 1 — FastAPI RequestValidationError handler (registered on app)**

Pydantic/FastAPI request validation failures must be caught by a registered `app.add_exception_handler(RequestValidationError, ...)` handler and returned as a Problem response with `code=INVALID_REQUEST`, HTTP 400. Without this, FastAPI emits its own 422 JSON that does not conform to the Problem schema.

**Layer 2 — FastAPI HTTPException handler (registered on app)**

All `HTTPException` instances raised inside route handlers must be intercepted by a registered `app.add_exception_handler(HTTPException, ...)` handler. This handler:
- If `exc.detail` is already a dict with a `code` key, pass it through as-is (it is already a Problem body).
- Otherwise wrap `str(exc.detail)` in a Problem body with `code=INTERNAL_ERROR`.
- Always attach `correlationId` from the current structlog context.
- Always set the `X-Correlation-ID` response header.

**Layer 3 — Correlation middleware catch-all**

The correlation middleware must catch all unhandled `Exception` instances that escape both handlers above. It must:
- Log `exc_type`, `exc_msg`, and full traceback at ERROR level.
- Return a JSON response (never `text/plain`) with HTTP 500, `code=INTERNAL_ERROR`, `retryable=true`, and `correlationId`.
- Use `problem_response(ErrorCode.INTERNAL_ERROR, ...)` — never a hand-rolled dict.

**Layer 4 — Route handlers**

All `raise` statements inside route handlers must use `raise problem(...)` from `errors.py`. Raw `HTTPException` with a plain string or non-Problem dict detail is **prohibited**. The `problem()` helper always uses the HTTP status from the `_ErrorDef`, never from the caller's first argument (which is ignored).

**Layer 5 — Application layer (intake, worker)**

Application-layer code must raise typed domain exceptions, not bare `ValueError` or `RuntimeError`. The router catches these and maps them to the correct `ErrorCode`. An unmapped exception from the application layer is treated as `INTERNAL_ERROR` by the middleware.

## 5. Component contracts

### REST API Service

Responsibilities:

- authenticate principal;
- resolve actor/service identity;
- authorize Tenant, RBAC and resource scope;
- enforce registered-device policy where configured;
- set transaction-local Tenant for PostgreSQL RLS — `SET LOCAL app.tenant_id = '{safe_tid}'`; PostgreSQL rejects bind parameters in `SET` statements so the value must be sanitised (allow only `[A-Za-z0-9\-_]`) and interpolated directly;
- auto-provision `tenant_settings` row and default retention policy on first request for any Tenant (idempotent `ON CONFLICT DO NOTHING` upsert inside every `tenant_session()`);
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

0. `tenant_session()` has already ensured `tenant_settings` and a default retention policy exist before this service is entered.
1. allocate `document_id`;
2. persist immutable provenance and a `RECEIVING` Document row;
3. allocate ORIGINAL artifact ID/key;
4. stream bytes to `StorageAdapter` while calculating byte count + SHA-256;
5. finalize storage metadata;
6. move Document to `VALIDATING`;
7. invoke Upload Validator / Quality Service;
8. create INITIAL processing job only for `FIT` evidence.
9. raise typed `IntakeError` (not bare `ValueError`) on domain precondition failures so the router can map them to the correct Problem code.

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
4. form the candidate set exactly as defined by `DI_CLASSIFICATION_v2.2.md`: effective ACTIVE Tenant/global types, Tenant type shadows same-key global type, only types with an effective PUBLISHED Extraction Profile remain; Requirement Profile and persisted caller hint are context only and never remove ADDITIONAL candidates;
5. persist the exact `classification_candidate_set` snapshot on the Processing Run before classifier invocation;
6. zero candidates => NON_RETRYABLE `CLASSIFICATION_NO_CANDIDATES`;
7. call machine classification with the full candidate set;
8. accept classification only when exactly one candidate meets Tenant `classification_acceptance_score`; otherwise NON_RETRYABLE `CLASSIFICATION_AMBIGUOUS`;
9. use the exact `profileId` already snapshotted for the accepted candidate; do not re-resolve a different profile mid-run;
10. call `DocumentAIAdapter.extract()` with all enabled configured fields in one schema-capable call where supported;
11. normalize fields;
12. run deterministic validation rules;
13. persist immutable machine facts and current MACHINE accepted values;
14. calculate Document confidence score;
15. persist `verification_threshold_applied=90.00`;
16. derive Human Verification Status (`>90 OPTIONAL`, `<=90 MANDATORY`);
17. set `PROCESSED + CONFIRMED`.

**Failure path (D24):** When any step raises a `ProcessingError` (retryable or
non-retryable), the worker must:

1. mark the Processing Run `FAILED` with `error_class`, `error_code`,
   `error_detail`;
2. set Document `processing_status = FAILED`, `confirmation_status =
   NOT_CONFIRMED`, `processing_failure_code`, `processing_failure_detail`;
3. mark the Processing Job `FAILED`;
4. insert one row in `docintel.backout_jobs` with `expires_at_utc =
   NOW() + backout_ttl_hours` (default 12 h).

The `RETRY_PENDING` document state is **not used** under this failure path.
The EOD Retry Scheduler remains present but only activates for documents
that are explicitly left in `RETRY_PENDING` state through other mechanisms.

### DocumentAIAdapter

Canonical operations:

- `classify(artifact, candidate_types_with_context) -> classifications[]`
- `extract(artifact, extraction_schema, physical_form_type) -> field_results[]`

`physical_form_type` is the `category` value from the classified `document_types` row. Allowed values: `GOVT_ID`, `PRINTED`, `HANDWRITTEN`. The concrete adapter implementation uses this to select the appropriate scanner/model:

| `physical_form_type` | Intended scanner/model |
|---|---|
| `GOVT_ID` | ID-document processor (structured fields, MRZ, barcode) |
| `PRINTED` | Form parser (printed text, structured layout) |
| `HANDWRITTEN` | OCR with handwriting model (mixed print + handwritten or fully handwritten) |

The mock adapter accepts `physical_form_type` and ignores it. A `NULL` value (document type with no category set) falls back to the `PRINTED` behaviour. An adapter unable to provide a documented deterministic normalization is not eligible for production configuration.

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
5. failure => `FAILED/NOT_CONFIRMED` + insert backout row (D24).

INITIAL jobs are `attempt_no=1`. Database constraint prevents swapping attempt numbers.

On every scheduler tick (every 60 s), regardless of EOD window, the scheduler
also runs the Backout Queue Sweeper (see below).

### Backout Queue Sweeper (D24)

Runs on every EODRetryScheduler tick (every 60 s). Executes one bounded delete:

```sql
DELETE FROM docintel.backout_jobs
WHERE expires_at_utc <= NOW();
```

Expired backout rows are dead-letter records. Deleting them does not change the
Document row — the document remains `FAILED / NOT_CONFIRMED`. The sweeper
merely keeps the backout table from growing unboundedly.

**Backout Queue contract:**

- One `backout_jobs` row per document at any time (enforced by
  `UNIQUE (tenant_id, document_id)`).
- TTL controlled by `DI_BACKOUT_TTL_HOURS` env var (default `12`).
- No reprocessing is triggered from the backout queue. It is a dead-letter
  store only.
- `error_class` records whether the failure was `RETRYABLE` or `NON_RETRYABLE`
  — this is retained for diagnostics even after the row would otherwise have
  been retried under the old path.

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

Tenant audit chains are entity-scoped, as defined by `DI_AUDIT_MODEL_v2.2.md`. For the audited `(tenant_id, entity_type, entity_id)`:

1. `INSERT ... ON CONFLICT DO NOTHING` the chain-head row;
2. `SELECT audit_chain_heads ... FOR UPDATE` for that **entity chain only**;
3. use current `last_event_hash` as `previous_event_hash`;
4. canonicalize event payload and calculate SHA-256 event hash;
5. INSERT immutable `audit_events` row;
6. UPDATE that entity chain head;
7. commit.

Concurrent writes to the same entity serialize intentionally; unrelated entities in the same Tenant do not. UPDATE/DELETE of audit event rows is rejected by DB trigger. Pre-Tenant quarantine retains its separate system audit chain.

## 6. Mobile/Web/API upload flow

Endpoint:

`POST /v1/tenants/{tenantId}/subjects/{subjectId}/documents`

1. authenticate/authorize actor;
2. require Tenant + Subject path values;
3. enforce registered device where role policy applies;
4. optional `documentTypeKey` must resolve to a supported visible ACTIVE type, is persisted as `document_type_hint_key`, and remains a non-authoritative hint;
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

## 7. Bad-source replacement

Only `NOT_FIT`, `CORRUPT` or `UPLOAD_FAILED` may be explicitly replaced through `replacesDocumentId` in Phase 1.

Rules:

- replacement and prior Document must belong to same Tenant;
- when both have Subject, Subject must match;
- prior Document remains retained and gets `replaced_by_document_id`;
- replacement creates a new `document_id`, new immutable original and fresh processing path;
- confirmed evidence is not silently superseded by this recovery mechanism.

## 8. Processing failure taxonomy

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

## 9. Requirement resolution

Upload and completeness are deliberately decoupled.

If no active Requirement Profile assignment exists:

- upload/processing continues;
- Subject enquiry returns `configurationStatus=REQUIREMENT_PROFILE_NOT_ASSIGNED`;
- `requirements=[]`;
- classified evidence is returned as additional evidence and unclassified evidence remains separately visible.

When a profile is assigned/reassigned later, the next enquiry reclassifies existing Document relationships against that profile without reprocessing bytes.

A newer published Requirement Profile version does not automatically alter an existing Subject assignment.

## 10. Subject enquiry

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

## 11. WhatsApp flow

### 11.1 Tenant resolution

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

### 11.2 Subject resolution

For a Tenant-resolved WhatsApp Document:

1. parse explicit configured Subject reference and validate format/value;
2. else use exactly one active sender mapping;
3. else after extraction evaluate profile fields marked `use_for_subject_matching=true`;
4. candidate field must be FOUND, normalized, pass applicable deterministic validation and meet Tenant `subject_matching_min_confidence`;
5. exact match must return exactly one active VERIFIED Subject identifier;
6. otherwise keep `subject_id=NULL` / UNASSIGNED.

Unassigned Documents remain processable/retrievable. Authorized assignment sets Subject and immediately re-evaluates requirement relationships. Original sender/uploader provenance is immutable.

## 12. Duplicate handling

After full SHA-256 + byte count is available:

- search same Tenant for identical SHA-256 + size;
- record `duplicate_of_document_id` if exact duplicate is found;
- do not automatically reject because duplicate evidence can be legitimate.

## 13. Idempotency

For mutation APIs supporting `Idempotency-Key`:

- scope = Tenant + actor + operation;
- first request creates in-progress idempotency record;
- request fingerprint excludes unstable transport metadata and includes stable command metadata; file upload fingerprint is finalized with content SHA-256;
- completed response/resource ID is persisted;
- same key + same fingerprint => original response;
- same key + different fingerprint => HTTP 409 `IDEMPOTENCY_CONFLICT`.

## 14. Content retrieval

After Subject discovery, specific Document operations remain under Tenant + Subject:

- metadata;
- original content;
- extracted fields;
- deterministic quality results;
- human verification;
- entity links.

For unassigned WhatsApp, equivalent Tenant + unassigned-document endpoints allow an authorized resolver to inspect evidence before assignment.

If retention purged content, metadata remains and content retrieval returns HTTP 410 `DOCUMENT_CONTENT_PURGED`.

## 15. Configuration lifecycle APIs

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

## 16. Retention

At Document registration:

- require an active Tenant retention policy for production intake;
- snapshot retention policy ID, calculated `retention_until_utc` and disposition.

On expiry:

- purge/retain content according to snapshot;
- preserve metadata and audit lineage;
- original/derived deletions occur only through retention-authorized StorageAdapter action;
- content state changes to PURGED after successful deletion.

## 17. Audit history

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

## 18. Observability

Required log context:

- `correlation_id` on every API/worker/provider-chain log;
- Tenant/Subject/Document identifiers when known;
- job/run/invocation identifiers when known;
- provider request ID when available;
- no raw sensitive document content in normal logs.

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

## 19. Activation validation

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


## 20. Exception-history behavior

Subject/Tenant exception APIs return current actionable conditions by default. A terminal bad upload that has been explicitly replaced is retained for audit/upload-quality metrics but is excluded from the active exception list. `includeResolvedHistory=true` exposes those historical superseded attempts.


## 21. Normative companion specifications

- `DI_SECURITY_RBAC_v2.2.md` - JWT claims, permissions and role bundles.
- `DI_ERROR_CATALOG_v2.2.md` - stable Problem code behaviour.
- `DI_CLASSIFICATION_v2.2.md` - deterministic classification candidate formation.
- `DI_AUDIT_MODEL_v2.2.md` - entity-scoped tamper-evident audit append model.
