# Verigence Document Intelligence — High-Level Architecture UC02 Revision

**Baseline:** 2.3  
**Date:** 2026-08-21  
**Status:** DESIGN REVISION FOR IMPLEMENTATION REVIEW  
**Base architecture:** `design/DI_ARCHITECTURE_v2.2.md`  
**Locked decisions:** `DI_DECISIONS.md` D28-D31  
**Scope:** Security v2 alignment + UC02 Project Onboarding/Administration delta

> Baseline 2.2 remains authoritative for document processing, Subject Registry, extraction, verification, audit, quality and provider behavior except where this 2.3 revision explicitly supersedes it. No code, SQL, YAML/OpenAPI or deployment configuration is changed by this document.

---

## 1. Architecture principles retained

DI remains a standalone Tenant-isolated document-intelligence service that owns:

- Subject Registry;
- documents and immutable artifacts;
- processing/extraction/verification state;
- DI-owned configuration;
- object storage;
- DI audit history.

Audit Core remains the user-facing façade for Audit vehicle-audit document workflows.

DI does not become the owner of Project, Dealer, Dealer Outlet, Customer business data merely because those IDs are used as trusted storage context.

---

## 2. Security v2 boundary

The Baseline-2.2 assumption that DI authorizes humans directly from embedded `permissions[]`, Tenant claims and mandatory device claims is superseded for the current Phase-1 platform architecture.

Security is the Verigence authentication and live authorization authority.

### 2.1 Human request to DI

A Security-issued human JWT establishes the global Verigence USER identity.

For a protected human DI operation:

```text
Human / Audit Core-proxied SuperAdmin action
  -> DI with Security human JWT
       -> DI validates Security JWT/JWKS
       -> DI derives global USER ID
       -> DI calls Security /authorization/check using DI ServiceIntegration, aud=security
       -> Security evaluates current USER/Tenant/admin permission state
       -> DI executes or denies
```

DI does not use Clerk and does not trust caller-provided USER identity.

### 2.2 Normal machine integration

Normal Audit Core -> DI document integration uses:

```text
Security-issued ServiceIntegration JWT
actor_type = SERVICE_INTEGRATION
aud = registered DI audience
```

The machine principal is platform-global under Security v2. The Tenant resource remains identified by the DI route/resource and enforced by DI RLS/resource checks; Tenant authorization is not taken from an invented machine `tenant_id` claim.

### 2.3 Human-admin operation

For UC02 administration owned by DI, including Project/Tenant provision/purge and DI-owned Project Master configuration administration, Audit Core passes the **same Security human JWT** that initiated the SuperAdmin action.

A valid Audit Core ServiceIntegration token cannot substitute for the SuperAdmin on a human-admin-only endpoint.

---

## 3. UC02 Project provisioning

The normal Project onboarding UI does not expose a DI provisioning step.

Audit Core creates/obtains the canonical Security Tenant ID and ensures DI is provisioned for that same ID.

DI SHALL reuse its existing idempotent Tenant provisioning behavior rather than create a second Tenant concept.

UC02 architecture requires an explicit administration/status boundary sufficient for Audit Core to:

- ensure Tenant settings/default retention/document-type setup exists;
- receive a deterministic ready/not-ready result;
- retry safely after timeout;
- use the canonical Security `tenant_id` only.

If the explicit ensure call performs administrative creation/configuration, it uses the forwarded human SuperAdmin JWT according to D29.

---

## 4. Audit-specific storage context

### 4.1 Generic DI path remains

D5 remains valid for generic/non-Audit DI documents.

### 4.2 Audit Core-originated path

For Audit Core-originated vehicle-audit evidence, D28 supersedes D5 and introduces:

```text
Project
 -> Dealer
   -> Dealer Outlet
     -> Customer
       -> Documents
```

Audit Core supplies trusted immutable context IDs; DI constructs the actual object key.

The browser never supplies object-storage path strings.

### 4.3 Storage context as a first-class DI integration entity

A Subject is an identity/evidence grouping concept, while an Audit storage context identifies where a particular Audit Core business context belongs in the Project/Dealer/Outlet/Customer hierarchy.

The same Subject/customer can participate in multiple Audit contexts over time. Therefore DI persists an immutable `AuditStorageContext` separate from Subject identity.

Conceptually:

```text
AuditStorageContext
  tenant/project
  externalAuditContextRef
  subject
  dealerId
  dealerOutletId
  customerId
  frozen readable slugs
```

Documents created through the Audit Core integration link to one Audit storage context.

Changing a Dealer/Outlet/Customer display name later does not move existing objects.

---

## 5. UC02 document-intake flow

For Audit Core-originated evidence:

```text
Browser
 -> Audit Core
    -> authenticate/authorize human business action
    -> resolve Project/Dealer/Dealer Outlet/Customer/Journey
    -> DI using ServiceIntegration, aud=di
       -> create/resolve AuditStorageContext from trusted Audit Core IDs
       -> create DI Subject if the existing integration requires it / resolve existing Subject
       -> DI document intake
       -> DI constructs Audit-specific object key
       -> existing processing pipeline
```

The normal Gemini/extraction/quality/verification pipeline is unchanged by UC02 storage hierarchy.

The storage-context call is idempotent by Tenant + external Audit context reference.

---

## 6. UC02 Project hard purge

Phase 1 requires a full Project rollback capability, including after activation.

Audit Core is the cross-module orchestrator; DI owns its deletion step.

Sequence inside DI:

```text
validate human SuperAdmin
 -> create/resume purge operation
 -> prevent/drain Tenant-scoped active processing writes
 -> enumerate authoritative object keys
 -> delete object bytes
 -> verify object deletion
 -> delete Tenant-owned DI metadata/configuration in dependency-safe order
 -> verify zero live DI state
 -> return purge receipt
```

Audit Core does not proceed to its own Project delete until the DI step reaches the approved successful zero-state condition.

Security Tenant deletion occurs later and is not performed by DI.

A timeout after object deletion or metadata deletion must be resumable using the same purge operation.

---

## 7. Object deletion ordering

The existing DI model stores authoritative object identifiers/keys in metadata.

Therefore Phase-1 Project purge follows this invariant:

> Do not delete the last metadata needed to locate an object before the object deletion has succeeded or has been proved already absent.

This differs from normal retention, where metadata/audit lineage is intentionally retained after content purge. UC02 whole-Project rollback is an explicitly approved full Tenant/Project purge operation.

---

## 8. Active processing during purge

DI purge must establish a Tenant-level purge barrier/state sufficient to prevent race conditions such as:

- a queued job writing extraction rows after purge began;
- a worker creating a derived artifact after its original was deleted;
- a background scheduler recreating retry/backout state;
- a new Audit Core machine upload arriving while purge is active.

Exact lock/flag implementation is defined in v2.3 LLD/data model, but the architecture requires fail-closed rejection/termination of new Tenant-scoped writes while purge is active.

---

## 9. Project Masters administration

UC02 Project Masters is an Audit Core UI façade over module-owned configuration.

DI remains authoritative for DI-owned domains currently defined by Baseline 2.2:

- Document Types;
- Extraction Profiles;
- Requirement Profiles;
- Tenant Settings / Retention;
- Quality configuration.

DI exposes a descriptor catalogue so Audit Core does not hard-code or reinterpret DI configuration.

A descriptor identifies whether the DI administration experience is:

- existing native/form API; or
- Excel import where DI explicitly supports it.

UC02 does not automatically convert all DI configuration into Excel.

For a DI descriptor explicitly declared Excel + effective-dated, D31 requires explicit WEF, staging, validation, parsed preview and explicit confirmation before an authoritative DRAFT/version is created.

No new DI master domain is invented by UC02.

---

## 10. Readiness contribution

Audit Core owns the aggregate Project Readiness UI/API.

DI contributes only DI-owned readiness information, including as applicable:

- Tenant provisioning exists;
- required DI Tenant settings/configuration exist;
- required document/extraction/requirement configuration is publish/processing-ready under existing DI rules;
- Audit storage-context capability is available;
- no provisioning/purge operation makes the Tenant unavailable.

Audit Core decides how DI readiness combines with Dealer/Outlet/role/master checks.

Google Place ID/latitude/longitude are not DI readiness data.

---

## 11. Audit and observability

Existing DI document/audit logging remains.

UC02 additionally requires safe administrative audit events for:

- Project/Tenant provision ensure;
- Audit storage-context creation/resolution;
- DI-owned configuration import/confirm/publish where applicable;
- Project purge request/start/step/failure/completion.

The original human SuperAdmin USER ID is recorded for human-admin actions.

ServiceIntegration is recorded as the machine actor for normal document integration.

No JWT, credential or raw master/document secret is written to audit records.

---

## 12. Failure behavior

### Provisioning failure

Return a durable/retryable status to Audit Core. Do not silently create a second Tenant context.

### Storage-context mismatch

If the same external Audit context reference is later supplied with conflicting Dealer/Outlet/Customer immutable IDs, fail with a conflict; do not rewrite the historical context.

### Purge partial failure

Remain `RECOVERY_REQUIRED`/equivalent with safe step/error receipt. Repeated operation resumes.

### Security unavailable for human admin operation

Fail closed. Do not fall back to ServiceIntegration.

### Normal machine integration token invalid/wrong audience

Deny before Tenant work.

---

## 13. Phase-2 deferrals

Not part of this revision:

- Project Product Master reuse — owned by Audit Core Phase 2;
- process-oriented/maker-checker Project deletion;
- changing old object keys when business display names change;
- exposing storage-path configuration to SuperAdmin;
- forcing all DI configuration to Excel/effective-dated administration.

---

## 14. Supersession map

For Phase 1, this 2.3 architecture supersedes Baseline 2.2 where it conflicts on:

- human authentication/authorization source (Security human JWT + live Security AuthZ; no Clerk authority);
- mandatory human Tenant/device/embedded-permission claims;
- machine actor name/semantics (`SERVICE_INTEGRATION`, platform-global, audience-bound);
- Audit Core-originated storage path (D28 instead of D5);
- UC02 human-admin token pass-through;
- Project provisioning/purge control plane.

All existing DI document-processing lifecycle, Subject Registry, quality, Gemini, extraction, confidence, verification and general audit principles remain authoritative.