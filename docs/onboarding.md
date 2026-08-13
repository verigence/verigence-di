# Verigence DI — Developer Onboarding Guide

**Audience:** New developer joining the project  
**Time to first working local environment:** ~20 minutes  
**Last updated:** 2026-08-16

---

## 1. What is Verigence DI?

Verigence Document Intelligence (DI) is a standalone backend service that:

- Accepts document uploads (PDF, JPEG, PNG, TIFF) from operators
- Runs quality checks on every upload (file size, format, corruption)
- Extracts structured field values using Google Document AI (mock in dev)
- Stores documents in Cloudflare R2 object storage
- Provides a REST API for subjects, documents, verifications, and configuration
- Runs a background worker that processes queued documents

**Two deployable containers:**
- `di-api` — FastAPI REST API, port 8080 on Railway
- `di-worker` — background document processor (no HTTP server)

---

## 2. Repository Layout

```
verigence-di/
├── Dockerfile               # API container
├── Dockerfile.worker        # Worker container
├── railway.toml             # Railway config for di-api
├── railway.worker.toml      # Railway config for di-worker
├── backend/
│   ├── pyproject.toml       # Python dependencies
│   ├── src/verigence/di/    # All application source code
│   │   ├── main.py          # FastAPI app factory
│   │   ├── settings.py      # All env var definitions
│   │   ├── api/
│   │   │   ├── health.py    # /health/live + /health/ready
│   │   │   └── v1/          # 54 REST endpoints
│   │   ├── auth/            # JWT verification + RBAC
│   │   ├── domain/          # Enums, confidence scoring
│   │   ├── repositories/    # DB queries (raw SQL via SQLAlchemy)
│   │   ├── storage/         # S3-compatible adapter (R2 + MinIO)
│   │   ├── workers/         # Background job processor
│   │   └── document_ai/     # Mock + real Google Document AI
│   ├── alembic/             # DB migrations
│   └── tests/               # 107 unit tests + integration tests
├── docs/                    # This folder — all documentation
├── infra/                   # docker-compose for local dev
├── plans/                   # Integration test plan
└── scripts/                 # Railway cost management scripts
```

---

## 3. Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.12 | `brew install python@3.12` |
| uv | latest | `brew install uv` |
| Docker Desktop | latest | https://docs.docker.com/desktop/mac/ |
| git | any | pre-installed on macOS |

---

## 4. Local Setup

### 4.1 Clone and install

```bash
git clone https://github.com/verigence/verigence-di.git
cd verigence-di/backend
uv sync
```

### 4.2 Create local env file

```bash
cp infra/.env.example infra/.env.local
```

Edit `infra/.env.local` with these values:

```bash
DI_ENV=local
DI_SECRET_KEY=local-dev-secret-key-minimum-32-chars
DI_DATABASE_URL=postgresql+asyncpg://diuser:dipass@localhost:5432/verigence_di
DI_DOCAI_MOCK=true
DI_SECURITY_JWKS_URL=http://localhost/mock-jwks
DI_STORAGE_PROVIDER=minio
DI_STORAGE_ENDPOINT=http://localhost:9000
DI_STORAGE_ACCESS_KEY_ID=minioadmin
DI_STORAGE_SECRET_ACCESS_KEY=minioadmin123
DI_STORAGE_BUCKET=verigence-di-dev
DI_WORKER_ENABLED=false
```

### 4.3 Start local infrastructure

```bash
cd infra
docker compose up -d
```

This starts:
- PostgreSQL on port 5432
- MinIO (S3-compatible storage) on port 9000 / console on port 9001

### 4.4 Run database migrations

```bash
cd backend
uv run alembic upgrade head
```

### 4.5 Start the API

```bash
cd backend
PYTHONPATH=src uv run uvicorn verigence.di.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

API is now running at `http://localhost:8000`

### 4.6 Verify it works

```bash
curl http://localhost:8000/health/live
# {"status":"live"}

curl http://localhost:8000/health/ready
# {"status":"ready","databaseReady":true}

curl http://localhost:8000/docs
# Opens OpenAPI UI in browser
```

---

## 5. Making API Calls Locally

All API routes are protected. Use a **mock token** in local/dev mode:

```
mock.<tenant_id>.<actor_id>.<ROLE>[.<ROLE>...]
```

Example — TENANT_ADMIN for tenant `my-company`:
```bash
TOKEN="mock.my-company.user-001.TENANT_ADMIN"

# Create a subject
curl -X POST http://localhost:8000/v1/tenants/my-company/subjects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"subjectType":"PERSON","displayName":"John Smith"}'

# Upload a document
curl -X POST http://localhost:8000/v1/tenants/my-company/subjects/<subjectId>/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/passport.pdf;type=application/pdf" \
  -F "documentTypeId=passport"
```

**Available roles:**
- `TENANT_ADMIN` — full access to everything
- `DOCUMENT_OPERATOR` — create subjects, upload documents
- `DOCUMENT_VERIFIER` — read documents, write verifications
- `OPERATIONS_VIEWER` — read-only
- `CONFIGURATION_ADMIN` — manage extraction profiles and quality config

Mock tokens are **rejected** when `DI_ENV=production`.

---

## 6. Project Code Tour

### Auth flow
```
Request → correlation middleware → auth middleware
    → verify_token() (verifier.py)
        → mock token (dev only) OR real JWT via JWKSCache
    → require_tenant_permission() (dependencies.py)
        → checks permissions[] claim against required permission
    → handler
```

### Document upload flow
```
POST /subjects/:id/documents
    → quality validator (validator.py) — checks size, mime, corruption
    → S3StorageAdapter.upload() — writes to R2/MinIO
    → processing_jobs INSERT — queues for worker
    → returns documentId + uploadStatus (FIT/NOT_FIT/CORRUPT)
```

### Worker processing flow
```
ProcessingWorker.claim_and_run()
    → CLAIM job (status=IN_PROGRESS, worker_id=hostname)
    → DocumentAIAdapter.extract() — calls Google DocAI or mock
    → score confidence → compare to verification threshold
    → update document: processingStatus, confirmationStatus, humanVerificationStatus
    → COMPLETE job
```

### Tenant auto-provisioning
Every `tenant_session()` call automatically creates `tenant_settings` and `actors` rows if they don't exist (ON CONFLICT DO NOTHING). New tenants work immediately without any setup step.

---

## 7. Key Concepts

### Tenant isolation
Every table has a `tenant_id` column. PostgreSQL RLS (Row Level Security) enforces isolation at the DB level. Every session sets `app.tenant_id` before any query.

### Permissions vs Roles
- **Roles** are informational labels (`TENANT_ADMIN`, `DOCUMENT_OPERATOR`, etc.)
- **Permissions** are the authoritative claim (`di.subject.create`, `di.document.upload`, etc.)
- The JWT `permissions[]` array is what the API checks — never the role name
- In mock token mode, permissions are derived from role bundles in `permissions.py`

### Upload status
| Status | Meaning |
|---|---|
| `FIT` | Quality gate passed — document queued for processing |
| `NOT_FIT` | Failed quality check (too small, wrong format, etc.) — can be deleted |
| `CORRUPT` | File is unreadable/corrupt — can be deleted |

### Processing status
| Status | Meaning |
|---|---|
| `PENDING` | Waiting for worker to claim |
| `IN_PROGRESS` | Worker is processing |
| `PROCESSED` | Worker completed — fields extracted |
| `FAILED` | Worker hit an unrecoverable error |

---

## 8. Useful Commands

```bash
# Run all unit tests (no Docker needed)
cd backend && PYTHONPATH=src uv run pytest -m no_docker --no-cov -q

# Run linter
cd backend && PYTHONPATH=src uv run ruff check .

# Check migration status
cd backend && DI_DATABASE_URL=<url> uv run alembic current

# Run a new migration
cd backend && DI_DATABASE_URL=<url> uv run alembic upgrade head

# View OpenAPI docs
open http://localhost:8000/docs

# Check Railway service status
./scripts/railway-cost-report.sh

# Pause Railway services (save costs)
./scripts/railway-services-stop.sh

# Resume Railway services
./scripts/railway-services-start.sh
```

---

## 9. What is NOT yet implemented

| Feature | Status | Notes |
|---|---|---|
| React PWA ops-ui | ❌ Not started | `ops-ui/` has README only |
| Google Document AI (real) | ❌ Not started | Mock adapter used in all envs |
| WhatsApp adapter | ❌ Phase 2 | Not started |
| Audit chain wired to routes | ❌ Phase 2 | Code exists but not called |
| Registered device enforcement | ❌ Phase 2 | Not started |
| Idempotency records | ❌ Phase 2 | Not started |

---

## 10. Getting Help

- Architecture: `DI_MASTER_REFERENCE.md` — authoritative design document
- Progress log: `PROGRESS.md` — every session's changes recorded
- Secrets: `SECRETS_CHECKLIST.md` — what is set vs placeholder
- Deployment: `docs/deployment.md`
- Testing: `docs/testing.md`
