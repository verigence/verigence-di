# Verigence Document Intelligence — Data Model UC02 Revision

**Baseline:** 2.3  
**Status:** DRAFT FOR IMPLEMENTATION REVIEW  
**Date:** 2026-08-21  
**Base model:** `design/DI_DATA_MODEL_v2.2.md`  
**Architecture/LLD:** `design/DI_ARCHITECTURE_v2.3.md`, `design/DI_LLD_v2.3.md`  
**Locked decisions:** D28-D31

> Baseline 2.2 remains authoritative for existing DI tables. This document defines only the logical data-model additions/changes required by UC02 and Security v2 alignment. It does not change SQL or migrations.

---

## 1. Existing Tenant/Subject/Document model retained

DI remains Tenant-isolated and Subject-centric.

Existing identities remain:

```text
Tenant
Subject
Document
Artifact
Processing / Extraction / Verification
Configuration
Audit
```

UC02 does not replace Subject with Audit Core Customer and does not make Dealer/Outlet first-class DI business masters.

Instead, UC02 adds an **Audit storage context** linked to existing DI Subject/Document identity.

---

## 2. Security identity persistence correction

Baseline 2.2 `actors` / `registered_devices` rows may remain for existing DI provenance/deferred capabilities, but they are not the authoritative Phase-1 source of human authorization under Security v2.

The authoritative human identity is the global USER ID obtained from a validated Security human JWT; current authorization is resolved through Security.

No Clerk subject, Clerk Organization or Clerk role is added to the UC02 data model.

No new mandatory Device ID/Tenant permission snapshot is added merely for UC02.

---

## 3. Audit storage contexts — new Tenant-owned entity

### 3.1 Purpose

An Audit storage context freezes the Audit Core hierarchy used when object keys are created.

Conceptual table:

```text
docintel.audit_storage_contexts
  tenant_id
  storage_context_id uuid
  external_context_ref varchar/string
  subject_id uuid
  dealer_id uuid
  dealer_outlet_id uuid
  customer_id uuid
  project_slug
  dealer_slug
  dealer_outlet_slug
  customer_slug
  created_at_utc
  created_by_service_principal nullable / provenance according to current actor model
  PRIMARY KEY (tenant_id, storage_context_id)
  UNIQUE (tenant_id, external_context_ref)
```

Rules:

- `tenant_id` is also the Audit Core Project/Security Tenant ID;
- Subject must belong to same Tenant;
- Dealer/Outlet/Customer IDs are external trusted Audit Core UUIDs, not DI-owned FKs;
- `external_context_ref` is the immutable Audit Core Journey/context reference selected by the integration contract;
- slugs are frozen path metadata, not business identity;
- repeated create with same reference and same immutable IDs is idempotent;
- conflicting IDs under same reference are rejected;
- changing source display names later does not update frozen slugs for existing context.

No Google Place ID/address/latitude/longitude is stored here because Audit Core owns Outlet geography and DI does not need it to identify storage hierarchy.

### 3.2 Document link

Add a nullable link concept to `documents`:

```text
audit_storage_context_id nullable
```

For Audit Core-originated vehicle-audit documents the link is required by that intake contract.

For generic/non-Audit DI documents it remains null and D5 generic path behavior continues.

The final DDL may implement the FK as `(tenant_id, audit_storage_context_id)` to preserve Tenant isolation.

---

## 4. Audit object-key derivation

No `object_path` authored by Audit Core/browser is persisted as authority.

`document_artifacts` continues to store the actual storage identifier/key required for retrieval/deletion.

For an Audit document, that key is derived from the linked frozen `audit_storage_contexts` values plus existing document/form-type/filename rules.

The data model therefore preserves both:

- business-context lineage through `audit_storage_context_id`;
- exact provider-neutral storage identifier through the existing artifact model.

---

## 5. Platform-level Tenant lifecycle guard — new

### 5.1 Requirement

A UC02 purge must prevent current Baseline-2.2 automatic Tenant provisioning from recreating data while/after purge.

Add a guard outside the Tenant-owned purge cascade.

Conceptual table:

```text
docintel.tenant_lifecycle_guards
  tenant_id PK
  lifecycle_state ACTIVE | PURGING | PURGED
  operation_id nullable
  updated_by_user_id nullable
  created_at_utc
  updated_at_utc
```

Rules:

- absence may be treated as normal/ACTIVE according to implementation convention;
- `PURGING` blocks Tenant auto-provision and ordinary writes;
- `PURGED` blocks Tenant auto-provision and ordinary writes for the old canonical Tenant ID;
- lifecycle guard is not deleted as part of Tenant-owned purge;
- a new Project uses a new Security Tenant ID and therefore a different guard key.

The exact schema namespace/RLS treatment must ensure the purge coordinator can read/write the guard even after Tenant-owned rows have been removed.

---

## 6. Platform-level administrative operation receipt — new

DI needs durable provisioning/purge status independent of Tenant-owned rows.

Conceptual table:

```text
docintel.administrative_operations
  operation_id uuid PK
  operation_type TENANT_PROVISION | TENANT_PURGE | CONFIG_IMPORT
  tenant_id
  idempotency_key
  semantic_request_hash
  status RECEIVED | RUNNING | RECOVERY_REQUIRED | COMPLETED | FAILED
  current_step nullable
  initiated_by_user_id nullable
  correlation_id nullable
  safe_progress jsonb nullable
  safe_result jsonb nullable
  last_error_code nullable
  last_error_summary nullable
  created_at_utc
  updated_at_utc
  completed_at_utc nullable
```

Rules:

- not cascaded when Tenant-owned data is deleted;
- no JWT/credential/PII-heavy payload stored;
- request hash protects idempotent-key reuse with a conflicting semantic request;
- purge receipt remains queryable after `tenant_settings`, Subjects, Documents and other Tenant-owned rows are gone;
- exact retention duration is not invented by UC02.

If existing DI idempotency infrastructure can safely serve part of this purpose, implementation may reuse it, but purge status still must survive Tenant deletion and remain readable without auto-provisioning the Tenant.

---

## 7. Purge progress / object deletion

The final implementation needs retry-safe progress across potentially many object keys.

The physical implementation may use either:

- safe progress rows keyed by operation + artifact/storage ID; or
- a bounded resumable cursor/progress structure that can deterministically re-enumerate remaining artifacts.

Mandatory semantic rule:

> Metadata containing the last authoritative storage key for an object cannot be deleted until that object's delete has succeeded or its absence has been proved idempotently.

This design does not force one new table shape before the final DDL/FK review.

---

## 8. Purge ownership by table group

Whole-Tenant UC02 purge removes Tenant-owned live rows across the current Baseline-2.2 model, including the relevant Tenant rows in these groups:

### Processing / transient

- processing jobs/runs/invocations;
- backout rows;
- search index;
- classifications/facts/validation/current accepted values;
- quality results;
- human verification;
- other Tenant processing/retry rows from the approved schema.

### Document / storage

- entity links;
- document artifacts after object bytes are removed;
- documents;
- Audit storage contexts.

### Subject

- requirement assignments;
- subject identifiers/channel mappings;
- Subjects.

### Tenant-owned configuration

- Tenant document-type mappings;
- Tenant-owned custom Document Types where ownership is this Tenant;
- Tenant-owned Extraction/Requirement configuration and child mappings;
- Tenant settings;
- retention policies;
- quality policy/configuration;
- other Tenant-owned configuration in the current approved schema.

### Tenant-owned access/provenance

- Tenant-scoped actor/device records where they are part of current DI persistence.

### Tenant audit

- Tenant audit-chain heads/events as part of the explicitly approved whole-Project hard rollback.

Not deleted by one Tenant purge:

- global/system-seeded Document Types;
- global extraction/reference/rule catalogues;
- platform/system WhatsApp configuration not owned by the Tenant;
- other Tenants' rows;
- platform-level purge operation receipt/lifecycle guard.

The exact row-order is generated from the actual final DDL and FK graph before code. No broad cascade is assumed without review.

---

## 9. Provisioning model

No new DI Tenant identity table is introduced.

Existing Tenant-owned configuration rows remain the provisioned state.

`TENANT_PROVISION` administrative operation records only the orchestration receipt/health checks; it does not become an authoritative duplicate Tenant configuration store.

Provisioning uses the same canonical Security Tenant ID supplied in the request path.

---

## 10. DI-owned configuration/master descriptor

The UC02 Project Masters façade requires metadata describing existing DI configuration domains.

This descriptor may initially be generated from static/module configuration rather than persisted as a new database table if the set is fixed by the DI design.

Descriptor properties:

```text
master_key
display_name
administration_mode FORM | EXCEL
requires_wef boolean
template_version nullable
lifecycle_model/current version summary where relevant
```

The descriptor does not create a new authoritative configuration domain.

Current source domains remain:

- Document Types;
- Extraction Profiles;
- Requirement Profiles;
- Tenant Settings / Retention;
- Quality configuration.

No physical Excel-import tables are mandatory until a DI domain is explicitly approved with `administration_mode=EXCEL`.

---

## 11. Conditional DI Excel-import staging

If a DI-owned domain is later approved as Excel-driven within UC02 Phase 1, add/reuse a generic DI configuration-import staging model following D31:

```text
config_imports
  import_id
  tenant_id
  master_key
  effective_from nullable/required only where descriptor requires WEF
  template_version
  file metadata/hash
  status
  validation counters
  created/confirmed actor/timestamps
```

```text
config_import_rows
  tenant_id
  import_id
  row_number
  parsed_data
  validation state/messages
```

These tables are **conditional**, not approved for migration merely by this data-model document. A domain must first be explicitly designated Excel-driven.

Existing native DRAFT/PUBLISHED profile tables remain authoritative where they already exist.

---

## 12. RLS / isolation implications

Tenant-owned `audit_storage_contexts` follows existing Tenant RLS/ownership patterns.

`tenant_lifecycle_guards` and platform-level `administrative_operations` are control-plane records required to function when Tenant-owned data is absent/deleting. Their access cannot depend on a normal `tenant_session()` that auto-provisions Tenant state.

The final DDL/security review must define least-privilege access for these control-plane tables and prevent ordinary document users/services from mutating them.

---

## 13. Audit/provenance implications

Document/audit lineage gains:

```text
document -> audit_storage_context -> trusted Audit Core hierarchy
```

UC02 human-admin provenance in DI admin operation/audit records uses the Security global USER ID.

Normal Audit Core document integration provenance uses the authenticated ServiceIntegration identity plus existing safe external/entity/correlation context.

Do not persist bearer JWTs.

---

## 14. Zero-state definition

For DI's UC02 purge step:

```text
zero_state_verified = true
```

only when the approved checks prove no remaining live target-Tenant:

- object bytes tracked by DI;
- Document/Artifact rows;
- Subject/Audit storage-context rows;
- processing/backout/search rows;
- Tenant-owned configuration/settings/retention rows;
- active worker/scheduler work capable of recreating data.

The platform-level lifecycle guard and purge receipt intentionally remain and are **not** counted as Tenant business/configuration state.

---

## 15. No changes to Google Maps/Product Master

DI stores no Google Place ID/Outlet geolocation for UC02.

DI has no Product Master model. Product Master remains Audit Core-owned.

---

## 16. Deferred/unknown items — do not guess

Before SQL/migration work:

1. derive the exact FK-safe purge row order from `design/DI_POSTGRESQL_SCHEMA_v2.2.sql` plus approved v2.3 additions;
2. decide the exact persistence form for large purge progress if re-enumeration is insufficient;
3. approve which DI configuration domains, if any, are Excel-driven in UC02;
4. update the machine-readable OpenAPI/error catalogue only after design approval.

No other business entities are added by UC02.