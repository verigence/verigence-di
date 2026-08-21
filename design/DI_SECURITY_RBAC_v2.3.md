# Verigence Document Intelligence — Security / RBAC UC02 Revision

**Baseline:** 2.3  
**Status:** DRAFT FOR IMPLEMENTATION REVIEW  
**Date:** 2026-08-21  
**Base security design:** `design/DI_SECURITY_RBAC_v2.2.md`  
**Related authority:** `docs/SECURITY_AUTHORIZATION_ALIGNMENT_INCREMENT_I.md`, `DI_DECISIONS.md` D29-D31

> This document aligns DI with the current Verigence Security v2 Phase-1 model and UC02 administrative routing. It supersedes Baseline-2.2 claim/enforcement assumptions where they conflict. No RBAC YAML, code or Security catalogue is changed by this document.

---

## 1. Security authority

Verigence Security is the authentication and live authorization authority.

DI has no Clerk integration and does not use Clerk Organizations/roles/JWTs as authorization authority.

DI trusts only Security-issued tokens/JWKS according to actor type.

---

## 2. Human token contract

A Security human access JWT is primarily trusted identity/session evidence.

Required DI checks on a human token are the canonical Security human-token checks, including:

- Security issuer/signature/JWKS;
- expiry/time validity;
- human actor semantics;
- global Verigence USER identity.

The current Security v2 target does **not** require the human JWT itself to be the authoritative store of:

- Tenant membership;
- live operating role;
- live permission list;
- mandatory Device/Geo state.

Therefore Baseline-2.2 DI requirements for authoritative embedded `permissions[]`, mandatory `tenant_id` and mandatory `device_id` on every human token are superseded for the active Phase-1 Security-v2 flow.

Tenant context comes from the protected DI resource/route and the live Security authorization request.

---

## 3. Human authorization flow

For a protected human DI operation:

```text
DI validates Security human JWT
 -> trusted global USER ID
 -> DI obtains ServiceIntegration JWT, aud=security
 -> POST /security/v1/authorization/check
      userId = trusted USER ID
      tenantId = target Tenant where applicable
      permissionKey = existing registered DI permission required by operation
 -> Security ALLOW/DENY
 -> DI resource/RLS checks
```

DI must not trust:

- caller-supplied USER ID;
- role-name strings as permission authority;
- stale embedded permission claims as replacement for the current Security decision.

If Security authorization is unavailable, human-protected operations fail closed.

---

## 4. ServiceIntegration contract

Normal Audit Core -> DI integration uses the Security v2 machine model:

```text
actor_type = SERVICE_INTEGRATION
registered service identity
aud = registered DI audience
short-lived Security-signed machine JWT
```

The machine identity is platform-global and not authorized through a Tenant permission bundle.

DI validates exact expected audience for its normal machine endpoints.

Tenant isolation is enforced by:

- target Tenant route/resource;
- authenticated registered Audit Core service;
- DI domain validation/RLS;
- no cross-Tenant foreign/resource references.

DI does not require a machine `tenant_id` claim that Security v2 no longer defines for platform-global ServiceIntegration.

---

## 5. UC02 human-admin routes

The following UC02 operation classes are human-admin-only when implemented:

- explicit Tenant/Project provision ensure;
- Project/Tenant purge/preflight/retry;
- DI-owned configuration/master administration when initiated by SuperAdmin through Project Administration.

Audit Core passes the same Security human JWT from the browser to DI.

DI independently verifies/authorizes the human.

A valid Audit Core ServiceIntegration token is rejected on a route classified human-admin-only.

---

## 6. Existing DI permissions retained

The existing registered DI permission concepts remain authoritative for their corresponding configuration/business operations, including current permissions for:

- Subjects;
- Documents/content/fields/quality;
- Verification;
- entity links;
- operations;
- Requirement Profiles;
- Extraction configuration;
- Quality configuration;
- Tenant configuration;
- Subject matching;
- WhatsApp administration.

This Markdown revision does not rename or add entries to the machine-readable RBAC catalogue.

### 6.1 UC02 purge/provision administrative authority

The existing Baseline-2.2 DI permission catalogue does not define a Project/Tenant destructive-purge permission.

UC02 Phase-1 purge is therefore an explicit **SuperAdmin control-plane operation**, not a permission silently granted to `TENANT_ADMIN`, `CONFIGURATION_ADMIN` or `SERVICE_INTEGRATION`.

DI must establish the live Security SuperAdmin administrative classification for purge/provision control-plane operations.

The exact Security `/authorization/check` administrative-attestation response needed to prove that classification must be frozen before code. This design deliberately does not invent a new DI purge permission key or trust a role string embedded in the JWT.

If the platform later chooses to add a canonical DI administrative permission key instead, that requires a separate approved RBAC catalogue change.

---

## 7. Configuration/master authorization

DI-owned Project Masters remain DI-owned configuration domains.

Where an existing configuration operation already has a registered permission, the same existing permission is used through live Security authorization.

Examples by existing domain concept:

```text
Requirement Profile read/write/publish
Extraction Config read/write/publish
Quality Config read/write
Tenant Config read/write
```

UC02 does not grant configuration capability merely because a UI screen is called Project Masters.

Audit Core cannot elevate the human beyond Security's current DI authority.

---

## 8. Audit storage-context endpoint authorization

`AuditStorageContext` creation/resolution is a normal trusted module-integration operation, not a human configuration operation.

Caller:

```text
Audit Core ServiceIntegration, aud=DI
```

DI must reject unregistered/wrong-audience callers.

The machine endpoint accepts business-context IDs only; it never accepts a caller-authored object-storage key.

No new per-service functional permission matrix is introduced in Phase 1; access follows the Security-v2 registered ServiceIntegration + target-audience model and endpoint actor-type policy.

---

## 9. Purge operation actor and isolation

For purge:

1. human JWT -> original global USER;
2. Security live admin decision proves SuperAdmin;
3. target Tenant ID comes from the admin operation/path, not a trusted embedded Tenant claim;
4. DI lifecycle guard blocks ordinary machine/user Tenant writes;
5. platform-level purge receipt remains accessible to authorized SuperAdmin even after Tenant-owned rows are deleted.

A Tenant A purge operation cannot accept resource IDs/objects from Tenant B; every delete query/object enumeration is scoped to the target Tenant from authoritative DI metadata.

---

## 10. SYSTEM actor

Existing WhatsApp/system actor behavior remains where still used by the approved DI design.

UC02 does not use SYSTEM as a substitute for SuperAdmin or Audit Core ServiceIntegration.

Any Baseline-2.2 `SERVICE` naming is normalized to Security-v2 `SERVICE_INTEGRATION` in the active target implementation.

---

## 11. Device/Geo rule

Security v2 defers Device/Geo/Schedule/VPN as mandatory Phase-1 human authorization gates.

DI therefore must not reject a valid current Security human JWT solely because the old Baseline-2.2 `device_id` claim/registered-device requirement is absent from the current Security-v2 human contract.

Existing DI device tables/code may remain for future/deferred use; they are not UC02 authorization authority.

---

## 12. Error behavior

Authentication failure remains HTTP 401; authorization/scope failure remains HTTP 403 according to DI's approved HTTP semantics.

Response body follows locked D8 universal envelope for the current target API layer.

New UC02 admin/storage/purge error codes are added only through the later approved DI error-catalogue update; no numeric/string code is invented in this Markdown document.

---

## 13. Security test matrix

### Human admin

- Security human SuperAdmin JWT accepted;
- same global USER is recorded as actor after Audit Core proxy hop;
- ordinary operating USER denied purge/provision where SuperAdmin required;
- TenantAdmin/ConfigurationAdmin denied Phase-1 full Project purge unless a later explicit decision changes it;
- ServiceIntegration denied human-admin endpoint;
- invalid/expired human JWT denied;
- Security authorization unavailable -> fail closed.

### Normal machine

- registered Audit Core ServiceIntegration + correct DI audience accepted on normal integration/storage-context endpoint;
- wrong audience denied;
- unknown/unregistered service denied;
- machine token cannot enter purge/config admin endpoint merely because it is valid.

### Isolation

- Tenant A resource IDs cannot be used under Tenant B;
- storage-context Subject belongs to route Tenant;
- purge enumeration/deletion remains Tenant-scoped;
- lifecycle guard for one Tenant does not block another Tenant.

### Legacy assumptions

- no Clerk validation path required;
- human permission result changes in Security affect next DI authorization decision without requiring a new DI-local permission snapshot;
- missing old mandatory `device_id` does not cause Phase-1 denial under Security v2.

---

## 14. Machine-readable RBAC follow-up

`security/DI_RBAC_v2.2.yaml` is intentionally not modified in this design-only task.

Before implementation, the Security/DI contract artifacts must be reconciled so they no longer require obsolete Baseline-2.2 human claim semantics.

Any new canonical permission key requires explicit catalogue approval; this document does not create one.