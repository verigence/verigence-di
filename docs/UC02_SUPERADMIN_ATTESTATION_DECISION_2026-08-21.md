# UC02 SuperAdmin Attestation Decision — 2026-08-21

**Status:** APPROVED FOR IMPLEMENTATION  
**Owner decision:** approved in UC02 implementation session on 2026-08-21  
**Repository:** `verigence/verigence-di`  
**Branch:** `dev`

## Decision

For UC02 human-control-plane operations in DI, the authoritative live SuperAdmin attestation is:

```text
GET /security/v1/platform/admin-context
```

DI uses the **same Security-issued human Bearer JWT** that originated in the Web request and was forwarded unchanged by Audit Core.

The approved flow is:

```text
Web SuperAdmin human JWT
  -> Audit Core (same JWT)
  -> DI human-admin endpoint (same JWT)
  -> Security /security/v1/platform/admin-context (same JWT)
  -> require current isSuperAdmin=true
```

## Mandatory checks

DI SHALL:

1. validate the Security-issued human JWT as identity/session evidence using Security JWKS, issuer and audience;
2. require the current minimal human token contract (`iss`, `sub`, `aud`, `iat`, `exp`, `jti`, `actor_type=USER`);
3. reject human control-plane tokens carrying embedded Tenant/role/permission/device/location/delegation authority claims (`tenant_id`, `roles`, `permissions`, `device_id`, `location_id`, `act`);
4. forward the exact same human Bearer token to Security admin-context;
5. require Security `admin-context.userId` to equal the validated JWT `sub`;
6. require `admin-context.isSuperAdmin=true`;
7. fail closed when Security cannot confirm current SuperAdmin status;
8. reject `ServiceIntegration` as a substitute for the human on a human-admin-only route;
9. never log or persist the Bearer token.

## Scope

This decision closes the explicit implementation gate in `design/DI_SECURITY_RBAC_v2.3.md` section 6.1 for the following UC02 control-plane operations:

- Tenant/Project provisioning ensure;
- Project/Tenant purge, preflight and retry;
- other DI operations explicitly classified by the approved UC02 design as human-SuperAdmin control-plane operations.

Existing DI configuration domains that already have an approved Security permission continue to use those approved permission contracts. This decision does **not** silently replace their permission checks with SuperAdmin classification.

## No new permission key

Phase 1 does not introduce invented permission keys such as `di.project.provision` or `di.project.purge` merely to unblock UC02. Security remains the live administrative authority through `/security/v1/platform/admin-context`.

## Authority boundary

- Security owns USER identity and current SuperAdmin classification.
- Audit Core preserves the initiating human JWT while orchestrating UC02.
- DI independently verifies/attests the human before executing its own human-admin operation.
- `ServiceIntegration` remains for approved machine/background integration only.
