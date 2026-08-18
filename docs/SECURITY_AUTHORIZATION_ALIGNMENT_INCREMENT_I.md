# Verigence DI — Security Authorization Alignment (Increment I)

**Status:** AUTHORITATIVE FOR SECURITY/DI INTEGRATION  
**Date:** 2026-08-14  
**Repository:** `verigence/verigence-di`

This document supersedes any older DI recovery/setup guidance that instructs DI to trust Clerk directly, create Clerk Organizations for DI authorization, or configure Clerk JWT templates for DI.

## Trust boundary

```text
Human USER
   -> Clerk authenticates credentials / email verification
   -> Verigence Security owns USER lifecycle and authorization
   -> Security issues Verigence JWT
   -> DI verifies Security JWKS/JWT locally
   -> DI authorizes from permissions[]
```

DI does **not** call Clerk to authorize a business request and does not treat Clerk roles/organizations as DI authorization authority.

## Canonical Security JWT contract consumed by DI

```text
issuer      = verigence-security
audience    = verigence-platform
actor_type  = USER | SYSTEM | SERVICE_INTEGRATION
tenant_id   = Tenant scope for Tenant operations
roles[]     = informational/backward-compatible
permissions[] = authoritative authorization contract
```

Unknown or missing `actor_type` fails closed. It must never default to USER.

Security-issued Tenant-scoped SYSTEM identities are valid. A SYSTEM token is not a Platform Admin token.

## Tenant isolation

For every Tenant-scoped DI operation:

```text
JWT tenant_id == route Tenant ID
```

A Tenant A token used against a Tenant B URL must return `403`.

Historical `{tenantId}` and `{tenant_id}` route spellings are both recognized by the shared fail-closed dependency until route naming is fully normalized; a request with conflicting values is rejected.

## Permission enforcement

Every DI business operation must enforce the canonical `di.*` permission declared by the approved DI contract. Tenant identity alone is not sufficient authorization.

Increment I specifically corrected older Subject/Document read operations that previously performed Tenant validation without their required read permission.

## Configuration

DI uses:

```text
DI_SECURITY_JWKS_URL
```

for Security JWKS discovery. `DI_CLERK_JWKS_URL`, Clerk publishable/secret keys, Clerk Organizations and Clerk DI JWT templates are not part of the DI authorization contract.

## Increment I acceptance

- `SERVICE_INTEGRATION` is the canonical service actor type.
- Unknown/missing actor types fail closed.
- Tenant-scoped SYSTEM tokens are accepted where SYSTEM is required.
- Non-SYSTEM actors cannot enter SYSTEM-only endpoints.
- Tenant path mismatch returns `403`.
- Tenant routes use explicit permission gates, not identity-only gates.
- Subject and Document read operations enforce their canonical read permissions.
- CI/Neon smoke proves JWT verification, permission denial and cross-Tenant denial.

## Relationship to Increment J

Increment J is the deployed proof that a real Security-issued Tenant JWT is accepted by DI when it contains the required `di.*` permission and rejected when permission or Tenant scope is wrong.
