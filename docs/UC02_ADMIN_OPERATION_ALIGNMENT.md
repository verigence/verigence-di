# Verigence DI — UC02 Administrative Operation Alignment

**Status:** UC02 DESIGN ALIGNMENT — OWNER DECISIONS CONFIRMED  
**Date:** 2026-08-21  
**Repository:** `verigence/verigence-di`  
**Branch:** `dev`  
**Related authority:** `DI_DECISIONS.md`, `DI_MASTER_REFERENCE.md`, `docs/SECURITY_AUTHORIZATION_ALIGNMENT_INCREMENT_I.md`, `docs/UC02_SUPERADMIN_ATTESTATION_DECISION_2026-08-21.md`

> This document is a narrow UC02 alignment amendment. It does not supersede DI's generic document-processing design except where explicitly stated for UC02 administration. **Owner clarification dated 2026-08-21 is authoritative: Phase 1 uses hard delete only. Resumable/process-oriented purge is deferred to Phase 2.** Any older Phase-1 wording that calls the delete operation a purge, or introduces a persistent delete guard/tombstone solely to prevent recreation of a deleted Tenant, is superseded by this document.

## 1. Human administrative actor rule

UC02 keeps the browser behind Audit Core.

When Audit Core invokes a DI **administrative** operation on behalf of SuperAdmin — including Project/Tenant provisioning, Phase-1 hard delete, or module-owned configuration administration — Audit Core passes the same Security-issued human Bearer token/identity through to DI.

DI authorizes the human using the approved live Security administrative-attestation contract:

```text
GET /security/v1/platform/admin-context
```

with the same forwarded Security human JWT. DI requires the current Security result to establish `isSuperAdmin=true` for the UC02 control-plane operations that are SuperAdmin-only.

Audit Core must not replace the human administrator with a `ServiceIntegration` token for a human-admin-only DI operation.

`ServiceIntegration` remains appropriate for normal non-administrative Audit Core -> DI document processing/integration calls.

## 2. Phase-1 Project/Tenant hard delete

UC02 Phase 1 requires an internal/admin **hard-delete** capability because the product is new and a Project may need to be deleted and rebuilt even after activation.

Phase 1 does **not** introduce:

- a process-oriented purge lifecycle;
- purge operation receipts;
- purge retry/status resources;
- `PURGING` / `PURGED` / `DELETING` / `DELETED` lifecycle state persisted solely for deletion;
- a persistent post-delete tombstone/guard whose purpose is to prevent recreation of the old Tenant ID;
- retention-preserving purge;
- soft-delete semantics.

Those concepts are outside UC02 Phase 1 and may be considered in Phase 2 only if separately approved.

DI Phase-1 hard delete must do only what is required for the hard-delete operation:

- require the forwarded human SuperAdmin JWT;
- independently confirm live `isSuperAdmin=true` through Security `/platform/admin-context`;
- reject `ServiceIntegration` on the human-admin-only hard-delete endpoint;
- delete DI-owned object-storage bytes before deleting the last DI metadata that identifies those objects;
- delete Tenant-owned DI metadata/configuration in FK-safe order;
- preserve global/system-seeded DI catalogue rows;
- return/allow verification that the target Tenant's DI-owned state is zero before Audit Core proceeds;
- never delete the canonical Security Tenant; Security deletion is performed later by Audit Core and remains the final cross-module step.

No additional lifecycle or recreation-prevention behavior is implied by this requirement.

### 2.1 Phase-1 hard-delete sequencing

```text
validate current human SuperAdmin
 -> identify target Tenant-owned DI state
 -> enumerate authoritative object keys
 -> delete object bytes
 -> verify required object deletion
 -> delete Tenant-owned metadata/configuration in FK-safe order
 -> verify zero Tenant-owned DI state
 -> return hard-delete result
```

If implementation inspection exposes a concrete FK, worker, transaction or object-storage safety requirement needed to make the hard delete correct, implement only the smallest source-backed mechanism required for that condition. Do not introduce a persistent purge/deletion lifecycle or recreation-prevention tombstone without a separate approved requirement.

## 3. Phase-2 direction

Phase 2 may introduce an explicit process-oriented purge model with richer lifecycle state, durable operation receipts/progress, retry/recovery endpoints, retention/history rules and stronger operational coordination. None of that is a prerequisite for UC02 Phase 1.

## 4. Storage hierarchy change remains a separate locked decision

Current locked D5 uses Tenant -> Subject -> Documents object keys.

UC02 requires Audit Core-originated vehicle-audit documents to follow trusted business context:

`Project -> Dealer -> Dealer Outlet -> Customer -> Documents`

Before storage-key code changes, the approved UC02 Audit storage-context contract must be used. The browser must never author object-storage paths directly.

## 5. Optional Google Maps data is not a DI concern

Google Place ID / Outlet map coordinates are owned by Audit Core Project landscape data. DI must not become the system of record for Google Places metadata merely to construct storage keys.
