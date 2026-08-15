# Verigence DI — Deployment Reference

Baseline v2.4 · Last updated 2026-08-15

---

## 1. Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.12 |
| uv (package manager) | ≥ 0.4 |
| PostgreSQL | 16 (or Neon serverless) |
| Object storage | Cloudflare R2 (prod) or MinIO (local) |

---

## 2. Local setup

```bash
# 1. Clone and install dependencies
git clone <repo> verigence-di && cd verigence-di/backend
uv sync

# 2. Copy and fill in env vars
cp infra/.env.example infra/.env.local
# Edit infra/.env.local — minimum required: DI_DATABASE_URL, DI_SECRET_KEY

# 3. Start local infrastructure (PostgreSQL 16 + MinIO)
docker compose -f infra/docker-compose.yml up -d

# 4. Apply all migrations
uv run alembic upgrade head

# 5. Start the API server
uv run uvicorn verigence.di.main:app --reload --port 8000
```

Browse API docs at `http://localhost:8000/docs`.

---

## 3. Environment variables reference

Full variable list with descriptions: [`infra/.env.example`](../infra/.env.example)

| Variable | Required | Default | Notes |
|---|---|---|---|
| `DI_ENV` | ✅ | `local` | `local` / `dev` / `production` |
| `DI_SECRET_KEY` | ✅ | — | Min 32 characters |
| `DI_DATABASE_URL` | ✅ | — | `postgresql+asyncpg://...` async URL |
| `DI_STORAGE_PROVIDER` | ✅ | `minio` | `minio` (local) or `r2` (prod) |
| `DI_STORAGE_ENDPOINT` | ✅ | `http://localhost:9000` | R2 endpoint for prod |
| `DI_STORAGE_ACCESS_KEY_ID` | ✅ | `minioadmin` | R2 key ID for prod |
| `DI_STORAGE_SECRET_ACCESS_KEY` | ✅ | `minioadmin123` | R2 secret for prod |
| `DI_STORAGE_BUCKET` | ✅ | `verigence-di-dev` | Bucket name |
| `DI_SECURITY_JWKS_URL` | ⚠️ | — | Security module JWKS URL (omit for mock-token mode) |
| `DI_DOCAI_MOCK` | ✅ | `true` | `true` = mock adapter; `false` = real Gemini |
| `DI_DOCAI_GEMINI_API_KEY` | ⚠️ | — | Required when `DI_DOCAI_MOCK=false` |
| `DI_WORKER_ENABLED` | — | `true` | `false` = API-only mode |
| `DI_VERIFICATION_THRESHOLD` | — | `90.00` | Confidence score below which human review is required |
| `DI_BACKOUT_TTL_HOURS` | — | `12` | Hours before failed job backout records expire |
| `DI_SENTRY_DSN` | — | — | Sentry DSN (leave empty to disable) |

---

## 4. Migration history

| Migration | What it adds |
|---|---|
| `0001_initial_schema.py` | Full baseline schema: all tables, indexes, constraints, global seed document types |
| `0002_schema_v2_2.py` | `subject_identifiers` unique partial index; `document_type_hint_key` on documents; `classification_candidate_set` on processing_runs; entity-scoped audit chain PK |
| `0003_verification_threshold.py` | Nullable `verification_threshold NUMERIC(5,2)` on `tenant_settings` |
| `0004_tenant_settings_relaxed.py` | Relaxed NOT NULL constraints on `tenant_settings` |
| `0005_tenant_document_types.py` | New `tenant_document_types` table; `physical_form_type` + `requires_processing` on documents; 15 global seed document types |
| `0006_source_channel_nullable.py` | `documents.source_channel` made nullable (D10) |
| `0007_search_index.py` | `document_search_index` table + GIN index + `pg_trgm`; `dealer_receipt` + `upi_screenshot` seed types |
| `0008_backout_queue.py` | `backout_jobs` dead-letter table + 2 indexes (D24) |

Run all migrations:

```bash
uv run alembic upgrade head
```

Check current revision:

```bash
uv run alembic current
```

---

## 5. Railway deployment

Both services auto-deploy on every push to `dev` branch via GitHub integration.

**Setup (one-time per service):**

Railway dashboard → New Service → Source: GitHub → select repo → branch: `dev` → root directory: blank.
Build and start commands are read from `railway.toml` in each service directory.

**Services:**

| Service | Root dir | Start command |
|---|---|---|
| `di-api` | `backend/` | `uvicorn verigence.di.main:app --host 0.0.0.0 --port $PORT` |
| `di-worker` | `backend/` | `python -m verigence.di.workers.runner` (worker-only mode) |

**Environment variables to set in Railway (per service):**

- `DI_ENV=dev` (or `production`)
- `DI_SECRET_KEY=<random 32+ char string>`
- `DI_DATABASE_URL=<Neon async connection string>`
- `DI_STORAGE_PROVIDER=r2`
- `DI_STORAGE_ENDPOINT=<R2 endpoint>`
- `DI_STORAGE_ACCESS_KEY_ID=<R2 key>`
- `DI_STORAGE_SECRET_ACCESS_KEY=<R2 secret>`
- `DI_STORAGE_BUCKET=<bucket name>`
- `DI_SECURITY_JWKS_URL=<JWKS URL>` (or leave unset for mock-token mode)
- `DI_DOCAI_MOCK=true` (dev) / `false` (production)
- `DI_DOCAI_GEMINI_API_KEY=<Google AI Studio key>` (production only)
- `DI_WORKER_ENABLED=false` (for `di-api`), `true` (for `di-worker`)

Health check path: `/health` (liveness) and `/health/ready` (readiness).

---

## 6. Auth model

All protected API routes require a **Bearer JWT** in the `Authorization` header.

**Production tokens** are issued by the Verigence Security module:
- `iss`: `verigence-security`
- `aud`: `verigence-platform`
- Claims: `tenant_id`, `actor_id`, `actor_type`, `roles[]`, `permissions[]`

Set `DI_SECURITY_JWKS_URL` to the Security module's JWKS endpoint.

**Dev / CI mock tokens** — used when `DI_SECURITY_JWKS_URL` is unset:

```
Authorization: Bearer mock.<tenantId>.<actorId>.<ROLE>[.<ROLE>...]
```

Example: `mock.tenant-abc.user-123.REVIEWER`

Available roles: `UPLOADER`, `REVIEWER`, `VERIFIER`, `OPS_ADMIN`, `TENANT_ADMIN`, `SYSTEM_ACTOR`, `EXTRACTION_EDITOR`, `EXTRACTION_PUBLISHER`

---

## 7. AI provider

| Mode | Setting | Notes |
|---|---|---|
| Mock (local/CI) | `DI_DOCAI_MOCK=true` | Returns deterministic fake extraction results; no API calls made |
| Real (production) | `DI_DOCAI_MOCK=false` + `DI_DOCAI_GEMINI_API_KEY=<key>` | Uses Gemini 2.5 Flash (`gemini-2.5-flash`) via Google AI Studio |

Model: **Gemini 2.5 Flash** (`gemini-2.5-flash`). Decision locked in D19.

Every document is processed on upload regardless of type (D18). The adapter returns structured JSON conforming to the `DocumentSchema` registry in `document_ai/schemas/`.

---

## 8. Health endpoints

| Endpoint | Purpose | Auth |
|---|---|---|
| `GET /health` | Liveness — always 200 if process is running | None |
| `GET /health/live` | Liveness (canonical) — always 200 | None |
| `GET /health/ready` | Readiness — 200 if DB reachable, 503 otherwise | None |

Railway health check path: `/health` (liveness probe).

```bash
# Quick check
curl https://<host>/health/ready
# {"status":"ready","environment":"dev","databaseReady":true}
```
