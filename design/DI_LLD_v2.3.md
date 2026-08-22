# Verigence Document Intelligence — Low-Level Design UC02 Revision

**Baseline:** 2.3  
**Status:** DRAFT FOR IMPLEMENTATION REVIEW  
**Date:** 2026-08-21  
**Base LLD:** `design/DI_LLD_v2.2.md`  
**Architecture:** `design/DI_ARCHITECTURE_v2.3.md`  
**Locked decisions:** D28-D31 in `DI_DECISIONS.md`

> This is a delta LLD. Baseline 2.2 document intake/processing/extraction/verification logic remains in force except where explicitly superseded. No code, migration, OpenAPI/YAML or error-catalogue file is changed here.

---

## 1. Security dependency model

### 1.1 Security human JWT verifier

Protected human DI routes use the Security-issued human access JWT.

Dependency responsibilities:

```text
verify Security signature/JWKS
validate issuer/expiry/token actor semantics
extract trusted global USER ID
reject ServiceIntegration when route is human-admin-only
```

The human JWT is not the authoritative live permission store.

For authorization, DI uses its own Security `ServiceIntegration` identity with `aud=security` to call:

```text
POST /security/v1/authorization/check
```

with:

```text
USER ID derived from validated human JWT
Tenant ID from trusted route/target operation
registered DI permission/admin context required by operation
```

DI never trusts a browser/Audit Core request field as the human USER identity.

### 1.2 Machine dependency

Normal Audit Core -> DI integration validates:

```text
actor_type = SERVICE_INTEGRATION
aud = registered DI audience
```

No Tenant claim is required on the platform-global machine JWT under Security v2. Tenant isolation is enforced from route/resource + DI RLS/domain validation.

### 1.3 No machine fallback on admin route

If a human admin token is invalid, expired, denied or Security authorization is unavailable, DI does not retry the operation under Audit Core's ServiceIntegration identity.

---

## 2. Tenant provisioning control plane

Current `tenant_session()` idempotent provisioning remains the implementation base but UC02 needs an explicit ensure/status surface for automatic Project onboarding.

### 2.1 API

```text
PUT /v1/tenants/{tenantId}/admin/provisioning
GET /v1/tenants/{tenantId}/admin/provisioning
```

Caller for PUT:

```text
Security human SuperAdmin JWT forwarded by Audit Core
```

`Idempotency-Key` is required for PUT.

### 2.2 PUT behavior

1. validate human SuperAdmin administration;
2. check the platform-level DI Tenant lifecycle guard — provisioning is rejected if the same Tenant ID is `PURGING` or `PURGED`;
3. idempotently ensure the existing Baseline-2.2 Tenant-owned prerequisites:
   - `tenant_settings`;
   - default/active retention-policy state required by current provisioning;
   - `tenant_document_types` seeded from approved global Document Types;
   - any other prerequisite already part of current `provision_tenant*` helpers;
4. do not generate a new Tenant ID;
5. record safe provision operation/receipt;
6. return readiness summary.

The ensure API reuses current helpers. It does not create a second provisioning model.

### 2.3 GET response concept

Inside D8 envelope:

```json
{
  "tenantId": "uuid",
  "provisioningStatus": "READY | INCOMPLETE | PURGING | PURGED",
  "checks": [
    {"key": "<existing prerequisite key>", "status": "PASS | FAIL", "message": "..."}
  ]
}
```

Stable check/error keys are finalized in the later API/error-catalogue design update; this Markdown LLD does not invent numeric DI error codes.

---

## 3. Audit Storage Context service

### 3.1 Purpose

`AuditStorageContext` freezes the Audit Core business hierarchy used to construct object keys for one immutable Audit business context.

It is separate from Subject identity.

### 3.2 Internal API

```text
PUT /v1/tenants/{tenantId}/audit-storage-contexts/{externalContextRef}
```

Caller:

```text
Audit Core ServiceIntegration, aud=di
```

`Idempotency-Key` required.

Request concept:

```json
{
  "subjectId": "<DI Subject UUID>",
  "dealerId": "<Audit Core Dealer UUID>",
  "dealerOutletId": "<Audit Core Outlet UUID>",
  "customerId": "<Audit Core Customer UUID>",
  "displayContext": {
    "projectName": "...",
    "dealerName": "...",
    "dealerOutletName": "...",
    "customerName": "..."
  }
}
```

Rules:

- Tenant/Project is `{tenantId}` and is not duplicated as caller-provided authority;
- `externalContextRef` is the immutable Audit Core context/Journey reference chosen by the Audit Core integration contract;
- IDs are trusted only because the caller is authenticated Audit Core ServiceIntegration;
- DI verifies Subject belongs to Tenant;
- display names are sanitized for readable path slugs and are not identity;
- same external reference + same immutable IDs returns existing context;
- same external reference + conflicting Dealer/Outlet/Customer/Subject IDs returns conflict;
- display-name changes on a later repeated call do not rewrite the frozen context used by existing objects.

The request deliberately contains no storage key/path.

### 3.3 Storage-key construction

For Audit context documents, StorageAdapter uses the frozen context to construct:

```text
{project_slug}-{tenant_id_short}/
  dealers/{dealer_slug}-{dealer_id_short}/
    outlets/{outlet_slug}-{outlet_id_short}/
      customers/{customer_slug}-{customer_id_short}/
        documents/{physical_form_type_folder}/
          {doc_id_short}_{sanitised_filename}
```

Use the existing D5 safe slug/filename sanitization primitives where compatible. IDs are authoritative collision protection.

The exact slug length limits should reuse the existing adapter limits/conventions; no new arbitrary maximum is introduced by UC02.

### 3.4 Generic DI upload path

If a document is not Audit Core-originated and has no Audit storage context, existing generic D5 path behavior remains.

---

## 4. Audit Core document intake with storage context

Audit Core normal integration flow:

1. authenticate machine `ServiceIntegration`, `aud=di`;
2. reject Tenant if platform-level lifecycle guard is `PURGING` or `PURGED`;
3. resolve/create DI Subject through existing integration behavior;
4. resolve/create `AuditStorageContext`;
5. allocate Document;
6. link Document to the immutable Audit storage-context ID;
7. build object key from that context;
8. stream/store bytes;
9. continue the existing quality/process/Gemini/verification lifecycle.

Changing the object path does not change `tenant_id + subject_id` as DI's primary enquiry identity.

---

## 5. Tenant purge guard

### 5.1 Problem addressed

Current Baseline-2.2 `tenant_session()` auto-provisions Tenant settings on Tenant access. During/after a UC02 purge this behavior could accidentally recreate Tenant rows.

### 5.2 Required guard

Introduce a platform-level lifecycle guard outside the Tenant-owned purge cascade:

```text
ACTIVE/normal (no guard row or explicit ACTIVE)
PURGING
PURGED
```

Before any Tenant auto-provision or write transaction:

```text
if guard == PURGING or PURGED:
    reject write / do not auto-provision
```

Purge sets `PURGING` before deleting Tenant-owned data and sets `PURGED` only after DI zero-state verification.

Project recreation uses a new canonical Security Tenant ID, so a `PURGED` guard for the old Tenant ID does not block the new Project.

### 5.3 Read behavior during purge

Ordinary Tenant document/configuration reads may be rejected with the approved Tenant-unavailable/purge-in-progress error once purge begins. Administrative purge status remains readable through the platform-level purge-operation API.

---

## 6. Project purge API

### 6.1 Preflight

```text
POST /v1/tenants/{tenantId}/admin/purge-preflight
```

Human SuperAdmin only.

Returns inside D8 envelope a safe summary such as:

```text
Tenant exists/configured
Document count
Object/artifact count
Active/running processing work count
Subject count
Tenant-owned configuration count/category
whether another purge is already active
eligible=true/false with blocking safe reasons
```

Preflight is informational and does not itself delete data.

### 6.2 Start/resume purge

```text
POST /v1/tenants/{tenantId}/admin/purge-operations
```

Headers:

```text
Authorization: Bearer <forwarded Security human SuperAdmin JWT>
Idempotency-Key: required
```

Request carries the Audit Core lifecycle/deletion correlation reference but not credentials/tokens.

Returns:

```json
{
  "operationId": "uuid",
  "tenantId": "uuid",
  "status": "RUNNING | RECOVERY_REQUIRED | COMPLETED",
  "currentStep": "BARRIER | DRAIN_WORK | DELETE_OBJECTS | DELETE_METADATA | VERIFY"
}
```

Normally `202 Accepted` until completed.

### 6.3 Purge status independent of Tenant-owned data

```text
GET  /v1/admin/purge-operations/{operationId}
POST /v1/admin/purge-operations/{operationId}/retry
```

These endpoints read the platform-level purge receipt even after Tenant-owned DI rows are gone.

Retry requires the human SuperAdmin JWT and resumes the same operation.

### 6.4 Purge algorithm

#### Step A — authorize and claim operation

- validate same human SuperAdmin identity;
- claim idempotency key/semantic request;
- if a compatible purge is already RUNNING/RECOVERY_REQUIRED, return/resume it;
- no second purge operation for same idempotent request.

#### Step B — barrier

- acquire/transition Tenant lifecycle guard to `PURGING`;
- all ordinary Tenant writes and auto-provisioning now fail closed.

#### Step C — drain/invalidate work

Using actual current DI tables/state:

- stop new job claims for Tenant;
- mark/cancel/invalidate queued jobs as required by final delete graph;
- ensure currently running worker execution cannot commit new Tenant rows/artifacts after purge barrier;
- scheduler/backout/EOD paths honor the same guard.

The exact worker cancellation mechanism is implementation-specific and must be designed against current transaction boundaries; do not silently ignore RUNNING work.

#### Step D — delete object bytes

- enumerate original/derived storage IDs/keys from `document_artifacts` and any other current object-bearing metadata;
- delete each object through `StorageAdapter.delete()`/approved purge-capable storage operation;
- treat already-absent object as idempotent success only after existence/response semantics prove absence;
- retain metadata/key until corresponding object deletion succeeds;
- persist safe progress so retry does not lose which objects remain.

#### Step E — delete Tenant-owned metadata

After object deletion succeeds, remove Tenant-owned rows in FK-safe order generated from the final approved DI schema.

Categories include current Tenant-owned rows for:

- backout/retry/processing/search state;
- verification/extraction/validation/current field values;
- entity links;
- quality/artifact/document rows;
- Audit storage contexts;
- Subject assignments/identifiers/channel mappings/Subjects;
- Tenant-owned Requirement/Extraction configuration and profile assignments;
- Tenant document-type mappings and Tenant-owned custom Document Types/configuration where applicable;
- Tenant settings/retention/quality configuration;
- Tenant actors/devices where those rows are Tenant-owned DI records;
- Tenant audit-chain rows/events as part of full Project rollback.

Global/system-seeded DI catalogue rows are not deleted merely because one Tenant is purged.

Exact table order must be derived from `DI_POSTGRESQL_SCHEMA` before code and is not guessed here.

#### Step F — verify zero state

Verify at minimum:

```text
no Tenant Document/Artifact rows
no Tenant object-storage keys tracked by DI
no Tenant Subjects/Audit storage contexts
no Tenant processing/backout/search rows
no Tenant-owned DI configuration/settings/retention/profile assignment rows
no active Tenant worker/scheduler work capable of recreating rows
```

Then set guard=`PURGED` and operation=`COMPLETED`.

### 6.5 Purge failure

Any failed step:

- operation = `RECOVERY_REQUIRED`;
- guard remains `PURGING`;
- safe error/step persisted;
- ordinary Tenant writes remain blocked;
- Audit Core receives non-complete status;
- retry resumes from verified state.

---

## 7. Zero-state contract for Audit Core

The purge status response exposes a compact zero-state result:

```text
metadataRowsRemaining
objectsRemaining
activeJobsRemaining
configurationRowsRemaining
subjectsRemaining
storageContextsRemaining
zeroStateVerified
```

Exact count categories may be aggregated to avoid coupling Audit Core to DI private table names.

`zeroStateVerified=true` is required before Audit Core proceeds to its own Project delete.

---

## 8. DI-owned Project Masters descriptor

### 8.1 API

```text
GET /v1/tenants/{tenantId}/admin/master-types
```

Human admin request through Audit Core; current Security authorization is evaluated according to the descriptor/domain.

Response descriptor concept:

```json
{
  "masterKey": "<DI-owned stable key>",
  "displayName": "<DI-owned display name>",
  "administrationMode": "FORM | EXCEL",
  "requiresWef": false,
  "templateVersion": null,
  "lifecycleModel": "<existing DI lifecycle summary>"
}
```

The descriptor set is derived from existing DI configuration domains only:

- Document Types;
- Extraction Profiles;
- Requirement Profiles;
- Tenant Settings / Retention;
- Quality configuration.

No extra UC02 DI master is invented.

### 8.2 Existing native configuration

Until a specific DI domain is explicitly approved as Excel-driven, its Baseline-2.2 native form/configuration APIs remain authoritative.

Audit Core may route the UI to the corresponding administration form/facade based on `administrationMode=FORM`.

### 8.3 Conditional Excel import contract

For a DI descriptor explicitly approved as `EXCEL`, DI will expose:

```text
GET  /v1/tenants/{tenantId}/admin/masters/{masterKey}/template
POST /v1/tenants/{tenantId}/admin/masters/{masterKey}/imports
GET  /v1/tenants/{tenantId}/admin/master-imports/{importId}
GET  /v1/tenants/{tenantId}/admin/master-imports/{importId}/rows
GET  /v1/tenants/{tenantId}/admin/master-imports/{importId}/error-report
DELETE /v1/tenants/{tenantId}/admin/master-imports/{importId}
POST /v1/tenants/{tenantId}/admin/master-imports/{importId}/confirm
```

If `requiresWef=true`, WEF is mandatory and never defaulted.

Upload -> staging -> validation -> parsed preview -> explicit confirm.

No authoritative configuration version is created simply by upload.

Publish remains a separate operation only for DI domains whose existing lifecycle has DRAFT/PUBLISHED semantics.

This LLD deliberately does not mark a particular DI domain EXCEL without an explicit owner/module decision.

---

## 9. D8 response envelope

New v2.3 APIs follow locked D8:

```json
{
  "errorCode": "000",
  "errorMessage": "Success",
  "data": { }
}
```

HTTP status remains meaningful.

New provisioning/storage-context/purge/admin errors require additions to the DI error catalogue in a later design/API artifact update. This Markdown-only change does not invent `E0xx` values.

Where Baseline-2.2 LLD text still describes the older Problem body, D8 and this v2.3 design are authoritative for new/updated APIs.

---

## 10. Audit events

At minimum record safe events for:

```text
TENANT_PROVISION_ENSURED
AUDIT_STORAGE_CONTEXT_CREATED
AUDIT_STORAGE_CONTEXT_CONFLICT
TENANT_PURGE_REQUESTED
TENANT_PURGE_STARTED
TENANT_PURGE_STEP_FAILED
TENANT_PURGE_COMPLETED
DI_CONFIG_IMPORT_CREATED/CONFIRMED/PUBLISHED where Excel import exists
```

These are conceptual event purposes; final event keys must follow the existing DI audit-event naming catalogue/convention during implementation. This Markdown document does not require exact strings above to become code constants.

Actor rule:

- human admin operations -> original Security global USER ID;
- normal Audit Core integration -> authenticated ServiceIntegration plus separately retained safe source context where existing integration contract permits.

---

## 11. Test design

### Security

- human SuperAdmin token accepted on admin endpoint;
- ServiceIntegration denied on admin provisioning/purge/config endpoint;
- ordinary USER denied where SuperAdmin required;
- normal Audit Core ServiceIntegration accepted on storage-context/document integration;
- wrong audience denied;
- no Clerk dependency.

### Storage context

- same context retry idempotent;
- conflicting immutable context rejected;
- same customer/Subject can have two different external Audit contexts at different Outlets;
- display-name update does not move old object;
- path contains Project/Dealer/Outlet/Customer hierarchy and collision-safe IDs;
- generic non-Audit upload still follows D5.

### Provisioning

- same ensure call repeated safely;
- canonical Tenant ID only;
- incomplete provisioning reported;
- PURGING/PURGED guard prevents re-provision.

### Purge

- no new writes after barrier;
- running/queued job race tested;
- object deletion failure retains key metadata and leaves operation recoverable;
- metadata delete failure after object delete resumes safely;
- duplicate purge click/request returns same logical operation;
- process/browser/Audit Core retry does not duplicate effects;
- zero-state false while any object/row/active job remains;
- global document types/system catalogue survive;
- operation receipt survives Tenant-row deletion;
- Security Tenant is not deleted by DI.

### Masters

- descriptor comes from DI-owned configuration catalogue;
- FORM domain remains form-native;
- EXCEL domain, if approved, enforces staging/preview/confirm;
- WEF required only when descriptor requires it;
- no default WEF.

---

## 12. Implementation prerequisites intentionally left as design-only

Before any DI code/migration is authorized:

1. update the machine-readable DI OpenAPI only after this LLD review;
2. update DI error catalogue with stable codes for new operations;
3. derive the exact purge FK/delete graph from the actual current DI schema;
4. select the exact database location/constraints for lifecycle guard and admin operation receipt in the physical DDL review;
5. explicitly decide which, if any, DI configuration domains are Excel-driven in UC02.

No code should guess these items.