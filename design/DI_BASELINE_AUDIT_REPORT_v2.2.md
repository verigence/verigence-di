# Verigence Document Intelligence - Baseline Audit Report

**Baseline:** 2.2  
**Result:** PASS

## Scope

Baseline 2.2 implements only the agreed corrections on top of Baseline 2.1: Error/Problem catalogue, JWT/RBAC contract, Subject-identifier concurrency, classification candidate-set formation and audit-chain write contention. Existing standalone, Tenant+Subject enquiry, Upload->Process->Confirm lifecycle, confidence/verification, storage, WhatsApp and correlation decisions remain unchanged unless explicitly superseded.

## Verified corrections

1. **Error contract:** 38 stable Problem codes with canonical HTTP status, retryability and client action. OpenAPI uses the same `ProblemCode` set and every operation documents a 500 Problem fallback.
2. **JWT/RBAC:** 27 canonical permissions and 8 generic role bundles. Every JWT-secured OpenAPI operation declares `x-required-permissions`; Tenant and system JWT claims are explicit.
3. **Subject identifier concurrency:** PostgreSQL partial UNIQUE index enforces at most one active VERIFIED Subject per Tenant + identifier type + normalized value. Concurrent conflict maps to `SUBJECT_IDENTIFIER_CONFLICT`.
4. **Classification:** candidate set is deterministic and does not exclude ADDITIONAL evidence. Caller hint is persisted, candidate snapshot is stored on the Processing Run, and the accepted run uses the snapshotted Extraction Profile.
5. **Audit scalability:** Tenant audit chain heads are entity-scoped (`tenant_id + entity_type + entity_id`). Only writes to the same audited entity serialize; unrelated Tenant entities proceed concurrently.

## Static validation

- Checks: **39**
- Passed: **39**
- Failed: **0**
- OpenAPI operations: **54**
- OpenAPI internal references resolved: **546**
- Error codes: **38**
- RBAC permissions: **27**
- RBAC role bundles: **8**

## Validation boundary

The OpenAPI/YAML/reference/permission/error contracts and SQL design deltas were statically checked in this workspace. The PostgreSQL DDL still must be executed against the selected PostgreSQL release as the normal migration/CI acceptance test before deployment.
