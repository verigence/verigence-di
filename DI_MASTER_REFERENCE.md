# Verigence Document Intelligence — Master Reference

**FIRST FILE TO READ at the start of every session.**
**Purpose:** single point of truth for document locations, implementation status, pending work, and session rules.

---

## 1. Baseline version in force

| Item | Value |
|---|---|
| Active baseline | **2.2** |
| Baseline date | 2026-08-11 |
| Status | BASELINED FOR IMPLEMENTATION |
| Design documents location | Workspace root (`/IDBP/`) |
| Code repository | `verigence-di/` |

> All design decisions are locked at Baseline 2.2 unless a new baseline is explicitly agreed and this file is updated. Do not infer design intent from older versioned files (v2.0, v2.1).

**Reading order for a new session:**
1. `DI_DECISIONS.md` — **READ THIS FIRST** — every locked design decision agreed in conversation
2. `DI_MASTER_REFERENCE.md` — this file (document map + step status)
3. `DI_DESIGN_SUMMARY.md` — 5-minute visual overview (diagrams, lifecycle, stack)
4. `PROGRESS.md` — current step detail and blockers
5. Relevant spec file from §2 only if implementing that specific component

---

## 2. Authoritative design documents (always read these first)

| Document | File (workspace root) | What it governs |
|---|---|---|
| Architecture | `DI_ARCHITECTURE_v2.2.md` | Fixed principles, component boundaries, core flow, WhatsApp flow |
| Low-Level Design | `DI_LLD_v2.2.md` | Component contracts, intake steps, worker steps, scoring, error handling |
| Data Model | `DI_DATA_MODEL_v2.2.md` | Every DB entity, relationships, state machines |
| PostgreSQL Schema | `DI_POSTGRESQL_SCHEMA_v2.2.sql` | Canonical DDL — single source of truth for table/column names |
| OpenAPI Spec | `DI_OPENAPI_v2.2.yaml` | All 54 operations, request/response schemas, `x-required-permissions` |
| RBAC / JWT | `DI_SECURITY_RBAC_v2.2.md` + `DI_RBAC_v2.2.yaml` | 27 permissions, 8 role bundles, JWT claim contract |
| Error Catalog | `DI_ERROR_CATALOG_v2.2.md` + `DI_ERROR_CATALOG_v2.2.yaml` | 38 stable problem codes, HTTP status, retryability |
| Classification | `DI_CLASSIFICATION_v2.2.md` | Deterministic candidate-set formation rules |
| Audit Model | `DI_AUDIT_MODEL_v2.2.md` | Entity-scoped hash-chain audit design |
| Baseline Audit Report | `DI_BASELINE_AUDIT_REPORT_v2.2.md` | Confirmed: 39/39 checks passed, 54 OAS ops, 38 error codes |

### Superseded — do not use

`DI_ARCHITECTURE_v2.0.md`, `DI_ARCHITECTURE_v2.1.md`, `DI_LLD_v2.0.md`, `DI_LLD_v2.1.md`,
`DI_DATA_MODEL_v2.1.md`, `DI_OPENAPI_v2.0.yaml`, `DI_OPENAPI_v2.1.yaml`,
`DI_POSTGRESQL_SCHEMA_v2.0.sql`, `DI_POSTGRESQL_SCHEMA_v2.1.sql`,
`DI_TECHNOLOGY_v2.0.md`, `DI_CONFIGURATION_MODEL_v2.0.md`, `BASELINE_MANIFEST.md`.

---

## 3. Repository structure

```
verigence-di/
├── DI_MASTER_REFERENCE.md        ← THIS FILE — read first every session
├── PROGRESS.md                   ← Implementation status per step — read second
├── SECRETS_CHECKLIST.md          ← Every env var, what is set / what is placeholder
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       └── 0002_schema_v2_2.py
│   └── src/verigence/di/
│       ├── main.py               FastAPI app factory + middleware
│       ├── settings.py           All env-var config (DI_ prefix)
│       ├── errors.py             Problem response helpers
│       ├── domain/
│       │   ├── enums.py          All state machine enums
│       │   └── scoring.py        Confidence scoring (0-100)
│       ├── api/
│       │   ├── health.py         GET /health, GET /ready
│       │   └── v1/
│       │       ├── schemas.py    Pydantic request/response models
│       │       ├── subjects.py   createSubject, listSubjects, getSubject
│       │       └── documents.py  uploadSubjectDocument, getSubjectDocuments, getSubjectDocument
│       ├── application/
│       │   └── intake.py         Document Intake use case (full 10-step flow)
│       ├── auth/
│       │   ├── principal.py      ActorPrincipal dataclass
│       │   ├── permissions.py    Permission enum (27) + ROLE_PERMISSIONS bundles (8)
│       │   ├── verifier.py       JWT verification (JWKS + mock-token protocol)
│       │   ├── jwks.py           JWKS cache with TTL
│       │   └── dependencies.py   require_actor, require_tenant_actor,
│       │                         require_permission, require_tenant_permission
│       ├── quality/
│       │   ├── rules.py          6 deterministic quality rules + REGISTRY
│       │   └── validator.py      validate_upload() — runs rules, persists results
│       ├── repositories/
│       │   ├── database.py       Async engine + tenant_session context manager
│       │   ├── subjects.py       create/get/list subjects
│       │   ├── documents.py      create/update/get/list documents
│       │   └── processing_jobs.py create_initial_job, claim_next_job, complete_job
│       ├── storage/
│       │   └── adapter.py        StorageAdapter → MinIO (local) / R2 (prod)
│       ├── document_ai/
│       │   └── adapter.py        DocumentAIAdapter → Google Doc AI (mock in dev)
│       ├── audit/
│       │   └── chain.py          SHA-256 hash-chain audit writer
│       ├── workers/              EMPTY — Step 10b
│       ├── scheduler/            EMPTY — Step 10b
│       └── whatsapp/             EMPTY — Step 14
├── ops-ui/
│   └── README.md                 EMPTY — Step 12
└── infra/
    ├── docker-compose.yml        PostgreSQL 16 + MinIO for local dev
    └── .env.example              All DI_ env vars with descriptions
```

---

## 4. Implementation steps — validated against design documents

> Validated against: `DI_OPENAPI_v2.2.yaml` (54 operations confirmed), `DI_LLD_v2.2.md` (21 sections), `DI_ARCHITECTURE_v2.2.md`, `DI_CLASSIFICATION_v2.2.md`, `DI_AUDIT_MODEL_v2.2.md`
>
> Status key: ✅ DONE | ⚠️ PARTIAL | ❌ NOT STARTED | 🔒 BLOCKED

### Corrections vs the original 14-step list

The original list had **4 gaps** discovered during validation against the design docs:

1. **Step 10b was conflating two things** — the Processing Worker and the EOD Retry Scheduler are separate LLD components with separate DB queries and scheduling logic. Split into 10b and 10c.
2. **Normalization + Validation rules were never listed** — `rules/` directory is empty. The LLD §Processing Worker steps 11–12 require deterministic normalization and validation rule execution. This is a missing step (new Step 9b).
3. **Audit Writer integration into routes was never listed** — `audit/chain.py` exists but is wired into nothing. The LLD §Audit Writer specifies it must be called from every state-changing route. Added as explicit sub-task of Step 11.
4. **Step 11 "all remaining APIs" understated scope** — the OAS has 54 operations. After Steps 3+7 implemented 6 of them, 48 remain. Step 11 is now itemized by OAS tag group so nothing is missed.

**Net result: 16 steps total (was 14). No design document was changed. Only the implementation step list was made more precise.**

---

| Step | What | LLD / OAS source | Status |
|---|---|---|---|
| **1** | PostgreSQL schema + Alembic migrations | `DI_POSTGRESQL_SCHEMA_v2.2.sql` | ✅ DONE |
| **2** | Domain enums + confidence scoring | LLD §Confidence Scoring Service | ✅ DONE |
| **3** | Settings, StorageAdapter, Document AI mock adapter | LLD §StorageAdapter, §DocumentAIAdapter | ✅ DONE |
| **4** | Audit chain writer | LLD §Audit Writer + `DI_AUDIT_MODEL_v2.2.md` | ✅ DONE (not yet wired into routes) |
| **5** | Auth middleware — Security module JWT + RBAC | Security module token model | ✅ DONE — awaiting `DI_SECURITY_JWKS_URL` env var |
| **6** | Document Intake use case + Subject/Document REST endpoints | LLD §Document Intake Service; OAS: `createSubject`, `listSubjects`, `getSubject`, `uploadSubjectDocument`, `getSubjectDocuments`, `getSubjectDocument` | ✅ DONE |
| **7** | Quality rules + Upload Validator wired into intake | LLD §Upload Validator / Quality Service | ✅ DONE |
| **8** | Normalization + Validation rules (`rules/` package) | LLD §Processing Worker steps 11–12 | ✅ DONE |
| **9** | Real Google Document AI adapter | LLD §DocumentAIAdapter | ❌ NOT STARTED — needs GCP project + processor |
| **10a** | Processing Worker — full job claim loop + classification + extraction + scoring | LLD §Processing Worker (17 steps) + `DI_CLASSIFICATION_v2.2.md` | ✅ DONE |
| **10b** | EOD Retry Scheduler | LLD §EOD Retry Scheduler | ✅ DONE |
| **11** | All remaining 48 REST API operations (see breakdown below) | `DI_OPENAPI_v2.2.yaml` — 54 total, 54 done | ✅ DONE |
| **12** | React PWA ops-ui | Architecture §Components / Access/API | ❌ NOT STARTED |
| **13** | Secrets → Railway + Cloudflare Pages + CI/CD | Architecture §7 Vendor-neutral deployment | ✅ DONE — both services live on Railway via GitHub integration |
| **14** | WhatsApp adapter — webhook, media download, intake, quarantine | LLD §WhatsApp Adapter + §11 WhatsApp flow | ❌ NOT STARTED (Phase 2) |
| **15** | Registered device enforcement for USER actors | LLD §3 JWT/RBAC — `device_id` check | ❌ NOT STARTED (Phase 2) |
| **16** | Idempotency records (`idempotency_records` table) | LLD §13 Idempotency | ❌ NOT STARTED (Phase 2) |

---

### Step 11 — 48 remaining OAS operations by tag group

| Tag group | Operations | Count |
|---|---|---|
| Subject Documents (extensions) | `getSubjectDocumentContent`, `getSubjectDocumentFields`, `getSubjectDocumentExceptions`, `getSubjectDocumentQuality` | 4 |
| Human Verification | `verifySubjectDocument`, `getVerificationQueue` | 2 |
| External Links | `getDocumentEntityLinks`, `addDocumentEntityLink` | 2 |
| Operations | `getTenantDocumentExceptions`, `getUploadQuality` | 2 |
| Requirement Profiles | `listRequirementProfiles`, `createRequirementProfile`, `getRequirementProfile`, `updateDraftRequirementProfile`, `publishRequirementProfile`, `assignRequirementProfile` | 6 |
| Extraction Profiles | `listExtractionProfiles`, `createExtractionProfile`, `getExtractionProfile`, `updateDraftExtractionProfile`, `publishExtractionProfile`, `listNormalizationRules`, `listValidationRules` | 7 |
| Document Types | `listDocumentTypes`, `createDocumentType`, `getDocumentType`, `updateDocumentType` | 4 |
| Tenant Configuration | `getTenantSettings`, `putTenantSettings`, `listRetentionPolicies`, `createRetentionPolicy`, `updateRetentionPolicy` | 5 |
| Quality Configuration | `getQualityPolicy`, `putQualityPolicy`, `listQualityRules` | 3 |
| Subject Matching | `addSubjectIdentifier`, `putWhatsappSenderMapping` | 2 |
| WhatsApp (Tenant-scoped) | `getUnassignedDocuments`, `getUnassignedDocument`, `getUnassignedDocumentContent`, `getUnassignedDocumentFields`, `getUnassignedDocumentQuality`, `assignDocumentSubject` | 6 |
| WhatsApp (System-scoped) | `putWhatsappRoute`, `getWhatsappQuarantine`, `replayWhatsappQuarantine`, `discardWhatsappQuarantine` | 4 |
| WhatsApp webhook | `whatsappWebhook` | 1 |
| **Total** | | **48** |

> Note: `whatsappWebhook`, `putWhatsappRoute`, quarantine operations, and `putWhatsappSenderMapping` / `addSubjectIdentifier` are included in Step 11 as stubs (correct HTTP routing + auth) even though their full business logic is delivered in Step 14.

---

## 5. Repositories

| Repo | Location | Branch model |
|---|---|---|
| Main code repo | `verigence-di/` (this workspace) | `main` → prod, `dev` → dev/UAT, `feature/*` → PR to dev |

---

## 6. Step 6 — What Clerk setup is still required (manual steps)

The JWT verification **code** is complete. The following human actions are still needed before any real token will work:

| # | Action | Who | Status |
|---|---|---|---|
| 6.1 | Create Clerk application at clerk.com | You | ❌ |
| 6.2 | Copy JWKS URL from Clerk dashboard → `DI_CLERK_JWKS_URL` | You | ❌ |
| 6.3 | Create JWT template in Clerk that emits: `tenant_id`, `actor_id`, `actor_type`, `roles[]`, `permissions[]`, audience = `verigence-document-intelligence` | You | ❌ |
| 6.4 | Create Clerk Organizations to represent Tenants; map org ID → `tenant_id` | You | ❌ |
| 6.5 | Set `DI_CLERK_PUBLISHABLE_KEY` and `DI_CLERK_SECRET_KEY` in Railway | You | ❌ |
| 6.6 | Test: verify a real Clerk-issued token returns `200` from a protected endpoint | Both | ❌ |

Until 6.1–6.5 are done, set `DI_DOCAI_MOCK=true` and use mock tokens (`mock.<tenant>.<actor>.<ROLE>`) for all local and CI testing.

---

## 7. Secrets checklist (never commit actual values)

See `SECRETS_CHECKLIST.md` for the full per-environment matrix. Summary of required variables:

| Variable | Local dev | Railway dev | Railway prod |
|---|---|---|---|
| `DI_SECRET_KEY` | any 32+ char string | ✅ set | ❌ |
| `DI_DATABASE_URL` | local docker pg | Neon dev URL | Neon prod URL |
| `DI_STORAGE_PROVIDER` | `minio` | `r2` | `r2` |
| `DI_STORAGE_ENDPOINT` | `http://localhost:9000` | R2 endpoint | R2 endpoint |
| `DI_STORAGE_ACCESS_KEY_ID` | `minioadmin` | R2 key | R2 key |
| `DI_STORAGE_SECRET_ACCESS_KEY` | `minioadmin123` | R2 secret | R2 secret |
| `DI_STORAGE_BUCKET` | `verigence-di-dev` | bucket name | bucket name |
| `DI_CLERK_JWKS_URL` | _(mock mode — not needed)_ | ❌ not set | ❌ not set |
| `DI_CLERK_PUBLISHABLE_KEY` | `pk_test_mock` | ❌ not set | ❌ not set |
| `DI_CLERK_SECRET_KEY` | `sk_test_mock` | ❌ not set | ❌ not set |
| `DI_DOCAI_MOCK` | `true` | `true` | `false` |
| `DI_DOCAI_PROJECT_ID` | _(not needed)_ | _(not needed)_ | ❌ not set |
| `DI_DOCAI_PROCESSOR_ID` | _(not needed)_ | _(not needed)_ | ❌ not set |
| `DI_SENTRY_DSN` | empty | empty | ❌ not set |
| `DI_ENV` | `local` | `dev` | `production` |

---

## 8. Key design decisions (immutable at v2.2)

| Decision | Value |
|---|---|
| Primary document lookup key | `tenant_id + subject_id` |
| Confidence threshold for MANDATORY verification | `≤ 90.00` |
| JWT audience (tenant) | `verigence-document-intelligence` |
| JWT audience (system) | `verigence-document-intelligence-system` |
| Authorization check | `permissions[]` array in JWT — NOT role names |
| Problem response field clients must branch on | `code` (stable) — never `title` |
| Max upload size (default) | 30 MB |
| Allowed MIME types (default) | `image/jpeg`, `image/png`, `image/webp`, `image/tiff`, `application/pdf` |
| Processing job locking | `SELECT … FOR UPDATE SKIP LOCKED` |
| Retry policy | 1 EOD retry for retryable failures; non-retryable → FAILED immediately |
| Audit chain key | `(tenant_id, entity_type, entity_id)` — entity-scoped, not tenant-wide |
| WhatsApp source channel | `WHATSAPP` — subject_id nullable until assigned |
| Mock token format (dev/CI) | `mock.<tenant_id>.<actor_id>.<ROLE>[.<ROLE>...]` |

---

## 9. Rules for working with this project

### Start of every session
1. Read `DI_MASTER_REFERENCE.md` (this file)
2. Read `PROGRESS.md` for current step status
3. Read `SECRETS_CHECKLIST.md` if the work touches deployment or config
4. If the step involves a specific component, read the relevant design doc from §2

### Before writing any code
- Confirm the step being worked on with the human
- State what file(s) will be changed and why
- Confirm definition of done

### End of every session
- Update `PROGRESS.md` with what was completed and what was left incomplete
- List any new blockers discovered
- Do not mark a step DONE unless tests pass

### Design change rule
If a design decision needs to change, the human must agree, a new baseline version must be declared, and this file must be updated before any code is written. Do not silently deviate from the baselined design docs.

---

## 10. Next step

**Current: Step 12 — React PWA ops-ui** ❌ NOT STARTED

---

### Infrastructure status — 2026-08-17 (current)

| Service | Status |
|---|---|
| di-api (Railway) | ✅ Running — `https://di-api-production.up.railway.app` — commit `b93ae4e` |
| di-worker (Railway) | ✅ Running |
| Neon PostgreSQL | ✅ All 5 migrations at head (0001–0005) — verified 2026-08-17 |
| Cloudflare R2 | ✅ Working — new slug-based path with 4 form-type folders |
| Security module JWKS | ✅ Using GitHub raw test JWKS — mock tokens rejected in production |
| CI pipeline | ✅ Green — `108 passed, 0 xfailed` |

### Schema changes beyond Baseline 2.2 spec

| Migration | Change |
|---|---|
| `0002` | `subject_identifiers`: non-unique → UNIQUE partial index on active VERIFIED identifiers |
| `0002` | `documents`: added `document_type_hint_key varchar(120)` |
| `0002` | `processing_runs`: added `classification_candidate_set jsonb` |
| `0002` | `audit_chain_heads`: rebuilt from per-tenant to entity-scoped PK `(tenant_id, entity_type, entity_id)` |
| `0003` | `tenant_settings`: added nullable `verification_threshold NUMERIC(5,2)` |

### Code additions beyond Baseline 2.2 spec

| Addition | Files | Detail |
|---|---|---|
| Delete Document API | `api/v1/documents.py`, `repositories/documents.py`, `errors.py`, `auth/permissions.py` | `DELETE .../documents/{id}` — hard delete for failed/not-fit documents. Permission: `di.document.delete` |
| Configurable verification threshold | `settings.py`, `domain/scoring.py`, `workers/job_runner.py`, `api/v1/tenant_config.py`, `0003` migration | Per-tenant threshold stored in DB; env var fallback |
| Auth migrated to Security module | `auth/verifier.py`, `auth/jwks.py`, `auth/principal.py`, `settings.py` | Issuer `verigence-security`, audience `verigence-platform`, `DI_SECURITY_JWKS_URL` replaces Clerk vars |
| All permissions renamed | `auth/permissions.py` | All strings now `di.*` dot-separated (was colon-separated) |

### Railway deployment method (no CLI token needed)

Railway dashboard → service → Settings → Source → Connect Repo → select repo/branch `dev` → root directory blank.
Auto-deploys on every push. Build/start commands read from `railway.toml`.

See `PROGRESS.md` §Session 2026-08-14 for complete schema change log, all "what didn't work" failures, and next actions.
