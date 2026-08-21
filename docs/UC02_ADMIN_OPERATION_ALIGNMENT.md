# Verigence DI — UC02 Administrative Operation Alignment

**Status:** UC02 DESIGN ALIGNMENT — OWNER DECISIONS CONFIRMED  
**Date:** 2026-08-21  
**Repository:** `verigence/verigence-di`  
**Branch:** `dev`  
**Related authority:** `DI_DECISIONS.md`, `DI_MASTER_REFERENCE.md`, `docs/SECURITY_AUTHORIZATION_ALIGNMENT_INCREMENT_I.md`, `docs/UC02_SUPERADMIN_ATTESTATION_DECISION_2026-08-21.md`

> This document is a narrow UC02 alignment amendment. It does not supersede DI's generic document-processing design except where explicitly stated for UC02 administration. **Owner clarification dated 2026-08-21 is authoritative: Phase 1 uses hard delete. Resumable/process-oriented purge is deferred to Phase 2.** Any older Phase-1 wording that calls the delete operation a purge is superseded by this document.

## 1. Human administrative actor rule

UC02 keeps the browser behind Audit Core.

When Audit Core invokes a DI **administrative** operation on behalf of SuperAdmin — including Project/Tenant provisioning, Phase-1 hard delete, or module-owned configuration administration — Audit Core passes the same Security-issued human Bearer token/identity through to DI.

DI authorizes the human using the approved live Security administrative-attestation contract:

```text
GET /security/v1/platform/admin-context
```

with the same forwarded Security human JWT. DI requires the current Security result to establish `isSuperAdmin=true` for the UC02 control-plane operations that are SuperAdmin-only.

Audit Core must not replace the human administrator with a `ServiceIntegration` token for a human-admin-only DI operation.

`ServiceIntegration` remains appropriate for normal non-administrative Audit Core → DI document processing/integration calls.

## 2. Phase-1 Project/Tenant hard delete

UC02 Phase 1 requires an internal/admin **hard-delete** capability because the product is new and a Project may need to be deleted and rebuilt even after activation.

Phase 1 does **not** introduce the later process-oriented purge lifecycle, purge operation receipt, purge retry endpoint, `PURGING/PURGED` lifecycle states, retention-preserving purge, or soft-delete semantics. Those are Phase-2 concerns.

DI Phase-1 hard delete must:

- require the forwarded human SuperAdmin JWT;
- independently confirm live `isSuperAdmin=true` through Security `/platform/admin-context`;
- reject `ServiceIntegration` on the human-admin-only hard-delete endpoint;
- be idempotent: deleting an already hard-deleted Tenant ID returns the successful deleted/zero-state result rather than recreating it;
- establish a deletion guard/tombstone before deleting Tenant-owned state so stale Tenant-scoped writes cannot auto-provision the deleted Tenant again;
- fail closed if active RUNNING processing work cannot safely be deleted;
- delete object-storage bytes before deleting the last metadata that identifies those objects;
- delete Tenant-owned metadata/configuration in FK-safe order;
- preserve global/system-seeded DI catalogue rows;
- expose/return zero-state verification to Audit Core;
- never delete the canonical Security Tenant; Security deletion is performed later by Audit Core and remains the final cross-module step.

### 2.1 Phase-1 hard-delete sequencing

```text
validate current human SuperAdmin
 -> establish Tenant delete guard = DELETING
 -> block new Tenant auto-provision/writes
 -> verify no RUNNING Tenant processing work
 -> enumerate authoritative object keys
 -> delete object bytes
 -> verify object absence
 -> break current/self document references required by FK graph
 -> delete Tenant-owned metadata/configuration in FK-safe order
 -> verify zero Tenant-owned DI state
 -> mark delete guard = DELETED
 -> return zeroStateVerified=true
```

If a technical failure occurs after `DELETING` is established, the caller retries the same hard-delete endpoint. Phase 1 does not expose a separate purge-operation resource or process-oriented recovery workflow.

## 3. Phase-2 direction

Phase 2 may introduce an explicit process-oriented purge model with richer lifecycle state, durable operation receipts/progress, retry/recovery endpoints, retention/history rules and stronger operational coordination. None of that is a prerequisite for UC02 Phase 1.

## 4. Storage hierarchy change remains a separate locked decision

Current locked D5 uses Tenant → Subject → Documents object keys.

UC02 requires Audit Core-originated vehicle-audit documents to follow trusted business context:

`Project → Dealer → Dealer Outlet → Customer → Documents`

Before storage-key code changes, the approved UC02 Audit storage-context contract must be used. The browser must never author object-storage paths directly.

## 5. Optional Google Maps data is not a DI concern

Google Place ID / Outlet map coordinates are owned by Audit Core Project landscape data. DI must not become the system of record for Google Places metadata merely to construct storage keys.
