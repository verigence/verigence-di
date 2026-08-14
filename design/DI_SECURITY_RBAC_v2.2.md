# Verigence Document Intelligence - JWT Claims and RBAC Taxonomy

**Baseline:** 2.2  
**Status:** BASELINED  
**Normative machine-readable source:** `security/DI_RBAC_v2.2.yaml`

## 1. Security boundary

Document Intelligence uses provider-neutral OIDC/JWT authentication. Clerk, Auth0 or another issuer may be used behind the identity boundary, but the API consumes only the canonical claims below.

### Tenant JWT

Audience: `verigence-document-intelligence`

Required standard claims: `iss`, `sub`, `aud`, `exp`, `iat`.

Required canonical claims:

- `tenant_id` - must equal the Tenant path value for Tenant-scoped endpoints;
- `actor_id` - stable Verigence actor identifier;
- `actor_type` - `USER|SERVICE|SYSTEM`;
- `roles` - array of canonical role names;
- `permissions` - array of canonical effective permissions and the **authoritative authorization input**.

For `actor_type=USER`, `device_id` is required and must resolve to an ACTIVE `registered_devices` row for the same Tenant + actor. SERVICE/SYSTEM tokens do not use registered-device checks.

Missing/invalid signature, issuer, audience, expiry or required canonical claim => HTTP 401 `UNAUTHORIZED`.
Authenticated token without required permission/Tenant/resource scope => HTTP 403 `FORBIDDEN`.

### Platform/System JWT

Audience: `verigence-document-intelligence-system`.

Required claims: `iss`, `sub`, `aud`, `exp`, `iat`, `actor_id`, `actor_type`, `roles`, `permissions`. `tenant_id` must be absent. Phase-1 system operations require `platform:whatsapp:admin`.

The inbound Meta/WhatsApp webhook is not JWT-authenticated; it uses the configured provider webhook/signature verification in the WhatsApp adapter.

## 2. Permission catalogue

| Permission | Meaning |
|---|---|
| `subject:create` | Create a Verigence Subject. |
| `subject:read` | Read/search Subjects. |
| `document:upload` | Upload/replace evidence for an existing Subject. |
| `document:read` | Read Document metadata/completeness/exception state. |
| `document:content:read` | Read original Document bytes. |
| `document:fields:read` | Read extracted/accepted field values. |
| `document:quality:read` | Read deterministic quality results. |
| `verification:read` | Read verification queue/state. |
| `verification:write` | Perform one human verification/correction action. |
| `entity_link:read` | Read optional external entity links. |
| `entity_link:write` | Create optional external entity links. |
| `operations:read` | Read Tenant exception and upload-quality operational views. |
| `unassigned_document:read` | Read Tenant-unassigned intake/document evidence. |
| `unassigned_document:assign` | Assign an unassigned Document to a Subject. |
| `requirement_profile:read` | Read Requirement Profiles. |
| `requirement_profile:write` | Create/update DRAFT Requirement Profiles. |
| `requirement_profile:publish` | Publish a Requirement Profile. |
| `requirement_profile:assign` | Assign a published Requirement Profile to a Subject. |
| `extraction_config:read` | Read Document Types, Extraction Profiles and rule catalogues. |
| `extraction_config:write` | Create/update Document Types/DRAFT Extraction Profiles. |
| `extraction_config:publish` | Publish Extraction Profiles. |
| `quality_config:read` | Read quality policy/rule catalogue. |
| `quality_config:write` | Update Tenant quality policy. |
| `tenant_config:read` | Read Tenant runtime settings/retention configuration. |
| `tenant_config:write` | Update Tenant runtime settings/retention configuration. |
| `subject_matching:write` | Register verified Subject identifiers/channel mappings. |
| `platform:whatsapp:admin` | Manage system WhatsApp routes and pre-Tenant quarantine. |

## 3. Canonical role bundles

Roles are convenience bundles. Endpoint authorization checks permissions, not role-name strings.

| Role | Default permissions |
|---|---|
| `DOCUMENT_OPERATOR` | `subject:create`, `subject:read`, `document:upload`, `document:read`, `document:content:read`, `document:fields:read`, `document:quality:read`, `entity_link:read`, `entity_link:write` |
| `DOCUMENT_VERIFIER` | `subject:read`, `document:read`, `document:content:read`, `document:fields:read`, `document:quality:read`, `verification:read`, `verification:write` |
| `OPERATIONS_VIEWER` | `subject:read`, `document:read`, `verification:read`, `operations:read` |
| `UNASSIGNED_INTAKE_OPERATOR` | `subject:read`, `document:read`, `document:content:read`, `document:fields:read`, `document:quality:read`, `unassigned_document:read`, `unassigned_document:assign` |
| `CONFIGURATION_ADMIN` | `requirement_profile:read`, `requirement_profile:write`, `requirement_profile:publish`, `requirement_profile:assign`, `extraction_config:read`, `extraction_config:write`, `extraction_config:publish`, `quality_config:read`, `quality_config:write`, `tenant_config:read` |
| `TENANT_ADMIN` | `document:content:read`, `document:fields:read`, `document:quality:read`, `document:read`, `document:upload`, `entity_link:read`, `entity_link:write`, `extraction_config:publish`, `extraction_config:read`, `extraction_config:write`, `operations:read`, `quality_config:read`, `quality_config:write`, `requirement_profile:assign`, `requirement_profile:publish`, `requirement_profile:read`, `requirement_profile:write`, `subject:create`, `subject:read`, `subject_matching:write`, `tenant_config:read`, `tenant_config:write`, `unassigned_document:assign`, `unassigned_document:read`, `verification:read`, `verification:write` |
| `SERVICE_INTEGRATION` | `subject:create`, `subject:read`, `document:upload`, `document:read`, `document:fields:read`, `entity_link:read`, `entity_link:write` |
| `PLATFORM_ADMIN` | `platform:whatsapp:admin` |

The standalone module contains only the canonical roles/permissions defined here. Any consuming application may map its own business roles to these permissions without changing Document Intelligence.

## 4. Enforcement order

1. Verify JWT signature using the configured OIDC issuer/JWKS; `alg=none` is rejected.
2. Validate exact `iss`, expected `aud`, `exp` and required claims.
3. Resolve ACTIVE Verigence actor.
4. For USER, validate `device_id` against ACTIVE registered device.
5. Validate Tenant claim equals Tenant resource path where applicable.
6. Check every permission listed by the operation's OpenAPI `x-required-permissions` extension.
7. Set PostgreSQL transaction-local `app.tenant_id` only after authorization succeeds.
8. Apply resource ownership/RLS checks.

No provider-specific role/claim name is allowed inside business services.
