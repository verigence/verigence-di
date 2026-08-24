# Verigence DI — AI-Assisted Configuration Authoring v2.4

**Status:** Implemented as an additive administration capability on 2026-08-24.  
**Scope:** Tenant-scoped Document Type / Extraction Profile authoring.  
**Non-goal:** Runtime document classification. Runtime callers continue to supply `documentTypeKey`.

## 1. Purpose

Verigence must support recurring customer/dealer documents without requiring a code release for every new form. An authorised administrator can upload a representative sample and ask DI to propose an extraction schema. DI may use Gemini to assist the author, but AI is never the configuration authority.

The design preserves the audit rule: **no guess, no hallucination, no direct model-to-database write, and no model-initiated publish.**

## 2. Trust boundary

```text
Admin UI
  -> DI Configuration Authoring API
     -> sample stored in DI object storage
     -> Gemini proposes structured JSON
     -> deterministic DI validation
     -> PROPOSED configuration
  -> Admin reviews/edits
  -> Test Extraction (preview only)
  -> Admin Approves
     -> DI materialises DRAFT configuration in existing tables
  -> authorised Publish action
     -> PUBLISHED Extraction Profile
```

Gemini receives document bytes only through DI. The browser never receives a Gemini API key and never calls Gemini directly. Gemini receives no database credentials and cannot call configuration persistence operations.

## 3. Existing runtime contracts are unchanged

This capability adds administration APIs only. It does **not** change the request or response contract of:

- `POST /v1/tenants/{tenantId}/subjects/{subjectId}/documents`
- `GET /v1/tenants/{tenantId}/subjects/{subjectId}/documents/{documentId}`
- `GET /v1/tenants/{tenantId}/subjects/{subjectId}/documents/{documentId}/fields`
- `POST /v1/tenants/{tenantId}/analyse`
- existing Document Type / Extraction Profile APIs

Runtime classification remains the current caller-hint pass-through. There is no Gemini classification call in this change.

## 4. Authoring lifecycle

```text
PROPOSED -> DRAFT -> TESTED -> APPROVED -> PUBLISHED -> RETIRED
                 ^       |
                 |-------|  edit after test clears test evidence and requires re-test
```

- **PROPOSED** — Gemini-generated, untrusted proposal stored for human review.
- **DRAFT** — admin-edited proposal; previous test result is invalidated.
- **TESTED** — latest proposal was preview-extracted against the stored sample.
- **APPROVED** — DI has materialised a DRAFT Extraction Profile and its fields; nothing is active yet.
- **PUBLISHED** — separate publish permission made the profile available to runtime processing.
- **RETIRED** — profile and tenant document mapping are no longer active.

A proposal cannot move directly from PROPOSED/DRAFT to APPROVED. The latest edit must be tested first.

## 5. Anti-hallucination contract

The schema-authoring prompt and deterministic validator enforce:

1. Propose a field only when the sample contains a visible label, table header, form caption, or unambiguous visible structural anchor supporting it.
2. Every field carries `evidenceLabels`; fields without evidence anchors are rejected by DI.
3. `derived=true` or `calculated=true` is rejected.
4. A field is `required=false` by default because one sample cannot prove universal mandatory presence.
5. Missing or uncertain runtime values must be `null`; no reconstruction of masked identifiers.
6. Extraction instructions are hardened with: never infer, calculate, reconstruct, or guess.
7. Gemini suggestions are editable and must be reviewed by the administrator.

This prevents an AI suggestion from becoming audit evidence merely because it was generated.

## 6. API surface

All endpoints use the existing D8 response envelope and existing Extraction Configuration permissions.

| Method | Endpoint | Permission | Purpose |
|---|---|---|---|
| POST | `/v1/tenants/{tenantId}/configuration-proposals` | `di.extraction_config.write` | Upload sample, store it, call Gemini, validate and create PROPOSED schema |
| GET | `/v1/tenants/{tenantId}/configuration-proposals` | `di.extraction_config.read` | List recent proposals |
| GET | `/v1/tenants/{tenantId}/configuration-proposals/{proposalId}` | `di.extraction_config.read` | Fetch proposal, fields and latest test |
| PUT | `/v1/tenants/{tenantId}/configuration-proposals/{proposalId}` | `di.extraction_config.write` | Admin edits proposal; resets state to DRAFT and clears stale test |
| POST | `/.../{proposalId}/test` | `di.extraction_config.write` | Preview extraction against stored sample; does not create business evidence |
| POST | `/.../{proposalId}/approve` | `di.extraction_config.write` | Materialise DRAFT Document Type/Profile/canonical mapping |
| POST | `/.../{proposalId}/publish` | `di.extraction_config.publish` | Publish approved profile; retire prior tenant PUBLISHED version atomically |
| POST | `/.../{proposalId}/retire` | `di.extraction_config.publish` | Retire the currently published proposal/profile and deactivate tenant mapping |

The existing `CONFIGURATION_ADMIN` and `TENANT_ADMIN` permission bundles already contain these extraction-config permissions. No Security API contract is changed.

## 7. Gemini role

Configuration-time Gemini is a schema authoring assistant. It proposes:

- `documentTypeKey`
- display name / description
- physical form type
- canonical field keys (reuse existing only for exact semantic matches)
- display labels
- data types
- visible evidence labels
- extraction aliases observed in the sample
- extraction instructions
- warnings for ambiguity

The DI backend sends the currently visible canonical-field catalogue to Gemini as a reuse hint, then independently validates the response.

The model does not publish, approve, execute SQL, calculate missing document values, or alter runtime classification.

## 8. Test Extraction semantics

`POST .../test` retrieves the authoring sample from DI object storage and calls the existing Document AI adapter with the proposed field list.

The result is an **authoring preview** only:

- no Subject is created;
- no runtime Document row is created;
- no field version is persisted as business evidence;
- no reconciliation/audit decision is generated.

The preview is stored only on the configuration proposal so the admin can judge the schema before approval.

## 9. Materialisation on approval

Approval executes a single DI-controlled transaction using the existing configuration model:

1. Resolve an effective Document Type by key or create a tenant-owned DRAFT Document Type.
2. For each proposed field, reuse an exact active tenant/global canonical key where data type matches; otherwise create a tenant-owned canonical field.
3. Create a new tenant-scoped DRAFT `extraction_profiles` version.
4. Create `extraction_profile_fields` with evidence labels/aliases and anti-hallucination extraction instructions.
5. Upsert `tenant_document_types` with the approved physical form type, `requires_processing=true`, `is_active=true`.
6. Record the materialised IDs on the proposal.

A canonical field data-type conflict is rejected instead of silently changing an established field.

## 10. Publish and versioning

Publish is separate from approval and requires `di.extraction_config.publish`.

Publishing:

- verifies the materialised profile is still DRAFT;
- retires the prior tenant-scoped PUBLISHED profile for the same Document Type;
- activates a DRAFT parent Document Type when applicable;
- publishes the approved profile with actor/time lineage;
- marks the proposal PUBLISHED.

Published historical profiles are never edited in place.

## 11. Storage and data model

Migration `0015_configuration_authoring.py` adds only `docintel.configuration_proposals` plus indexes. Existing configuration and runtime tables are unchanged.

Sample storage key pattern:

```text
{tenant}/configuration-proposals/{proposalId}/{sanitisedFilename}
```

The proposal table stores the sample object key, model/token lineage, proposal JSON, latest test result, state, actor/time lineage, and materialised Document Type/Profile IDs.

## 12. Current scope versus future scope

The current DI schema natively supports **global** and **tenant-scoped** Document Types/Extraction Profiles. This implementation therefore materialises custom authoring at **tenant scope**.

Project-specific extraction-profile precedence was discussed as a useful future capability, but it is **not represented as an existing DI profile scope today** and is deliberately not invented by this change. A future project-scope design must be separately approved and migrated.

## 13. Administration UX

Administration exposes **Document Intelligence Configuration** with:

- Create from Sample Document
- Gemini proposal review
- Document Type metadata
- Canonical field mapping / evidence labels
- Extraction instructions
- Test Extraction
- Approval
- Publish / Retire
- Proposal/profile status and version lineage

The UI calls DI APIs only. It never contains a Gemini key or a direct model integration.
