# Verigence DI — Deployment Guide

**Last updated:** 2026-08-16  
**Live API URL:** `https://di-api-production.up.railway.app`

---

## Architecture

```
GitHub (dev branch)  →  GitHub Actions CI  →  Railway auto-deploy
                                                    ├── di-api    (FastAPI)
                                                    └── di-worker (processor)
```

Railway auto-deploys both services on every push to `dev` after CI passes.  
No manual deploy steps are needed for a normal code push.

---

## Current Infrastructure State

| Component | Location | Status |
|---|---|---|
| **di-api** | `https://di-api-production.up.railway.app` | ✅ Running |
| **di-worker** | Railway production env | ✅ Running |
| **Neon PostgreSQL** | `ep-royal-pond-ayci3m0f.c-5.us-east-2.aws.neon.tech` | ✅ Live, migration 0004 |
| **Cloudflare R2** | `verigence-di-bucket-dev` | ✅ Configured |
| **Google Document AI** | — | ⚠️ Mock only (`DI_DOCAI_MOCK=true`) |
| **Security module JWKS** | test_jwks.json (committed) | ⚠️ Test key, not production |

---

## Service Configuration (Railway Dashboard)

### di-api

| Setting | Where | Value |
|---|---|---|
| Config File Path | Settings → Build | `railway.toml` |
| Dockerfile Path | auto from railway.toml | `Dockerfile` |
| Start Command | auto from railway.toml | `sh -c 'uvicorn verigence.di.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}'` |
| Health Check Path | auto from railway.toml | `/health/live` |
| Health Check Timeout | auto from railway.toml | `60s` |

### di-worker

| Setting | Where | Value |
|---|---|---|
| Config File Path | Settings → Build | `railway.worker.toml` |
| Dockerfile Path | auto from railway.worker.toml | `Dockerfile.worker` |
| Start Command | auto from railway.worker.toml | `python -m verigence.di.workers` |
| Health Check | none | Workers have no HTTP server |

---

## Environment Variables

Set on **both services** unless noted.

### Application

| Variable | Value | Notes |
|---|---|---|
| `DI_ENV` | `dev` | Change to `production` only after JWKS + R2 production setup |
| `DI_SECRET_KEY` | (secret) | 32+ char random string — set in Railway |
| `DI_LOG_LEVEL` | `INFO` | Optional |

### Database

| Variable | Value |
|---|---|
| `DI_DATABASE_URL` | `postgresql+asyncpg://neondb_owner:...@ep-royal-pond-ayci3m0f.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require` |

### Storage (Cloudflare R2)

| Variable | Value |
|---|---|
| `DI_STORAGE_PROVIDER` | `r2` |
| `DI_STORAGE_ENDPOINT` | `https://a1e15a39a0a8f86dc1ca9c6a8726e428.r2.cloudflarestorage.com` |
| `DI_STORAGE_ACCESS_KEY_ID` | `46b4ddba143945fc0c9865f9d88c7090` |
| `DI_STORAGE_SECRET_ACCESS_KEY` | (secret — set in Railway) |
| `DI_STORAGE_BUCKET` | `verigence-di-bucket-dev` |
| `DI_STORAGE_REGION` | `auto` |

### Auth (di-api only)

| Variable | Value |
|---|---|
| `DI_SECURITY_JWKS_URL` | `https://raw.githubusercontent.com/verigence/verigence-di/dev/backend/tests/fixtures/test_jwks.json` |

### Document AI

| Variable | Value |
|---|---|
| `DI_DOCAI_MOCK` | `true` |

---

## Normal Deployment (code push)

```bash
git push origin dev
```

1. GitHub Actions `quality` job runs (lint + 107 unit tests)
2. GitHub Actions `smoke` job runs (integration tests — **blocks deploy if fails**)
3. Railway detects push → builds Docker image → deploys both services
4. `railway-dev-deploy.yml` gate waits for CI to pass before declaring success
5. Post-deploy smoke hits live URL

**Total time:** ~5 minutes build + ~2 minutes deploy = **~7 minutes end-to-end**

---

## First-Time Service Setup

Only needed when creating services from scratch.

### Step 1 — Create Railway project

1. https://railway.app → New Project → Empty Project → name: `verigence-di`
2. Note the **Project ID** (shown in project settings)

### Step 2 — Create di-api service

1. New Service → GitHub Repo → `verigence/verigence-di` → branch `dev`
2. Rename to `di-api`
3. Settings → Build → **Config File Path** → `railway.toml` → Save
4. Settings → Networking → **Generate Domain** → note the URL
5. Variables → add all env vars from table above
6. Redeploy

### Step 3 — Create di-worker service

1. New Service → GitHub Repo → same repo + branch
2. Rename to `di-worker`
3. Settings → Build → **Config File Path** → `railway.worker.toml` → Save
4. Variables → add all env vars **except** `DI_SECURITY_JWKS_URL`
5. Redeploy

### Step 4 — Run database migrations

Migrations run automatically on CI using `DEV_DATABASE_URL` secret.  
To run manually:

```bash
cd backend
DI_DATABASE_URL="postgresql+asyncpg://neondb_owner:...@.../neondb?ssl=require" \
  uv run alembic upgrade head
```

Current migration state: **0004** (head)

### Step 5 — Verify

```bash
curl https://di-api-production.up.railway.app/health/live
# {"status":"live"}

curl https://di-api-production.up.railway.app/health/ready
# {"status":"ready","environment":"dev","databaseReady":true}
```

---

## Managing Railway Costs

Railway charges ~$0.25/hour per running service. Use the scripts to control costs:

```bash
# Pause both services (end of day — stops compute billing)
./scripts/railway-services-stop.sh

# Resume both services (start of day)
./scripts/railway-services-start.sh

# Check current status and estimated cost
./scripts/railway-cost-report.sh
```

**Note:** Pausing services does NOT pause Neon PostgreSQL (~$20/month always running).

**Warning:** Any push to `dev` will trigger a redeploy and restart paused services. Don't push while paused if you want to keep them stopped.

---

## Troubleshooting

### "executable cd not found"

**Cause:** Railway dashboard has an old start command with `cd /app/backend && ...` OR Config File Path is blank so `railway.toml` is ignored.

**Fix:**
1. Railway dashboard → service → Settings → Build → **Config File Path** → set to `railway.toml`
2. Do NOT put anything in the Start Command field in the dashboard — let `railway.toml` control it
3. Redeploy

### Health check failure

**Cause 1:** `DI_ENV=production` with `DI_SECURITY_JWKS_URL` containing "mock" → validator crashes app  
**Fix:** Set `DI_ENV=dev` OR set a real JWKS URL

**Cause 2:** `healthcheckPath=/health/ready` returns 503 if DB is slow to connect  
**Fix:** `railway.toml` uses `/health/live` — if it was changed, revert it

### 500 on POST requests (subject/document create)

**Cause:** Tenant not provisioned — FK constraint on `tenant_settings` or `actors` violated  
**Fix:** Fixed in code since commit `2616697` — `provision_tenant()` and `provision_actor()` run automatically on every `tenant_session()` call

### Port mismatch (service starts but health check fails)

**Cause:** Railway assigns port 8080 via `$PORT` env var, but uvicorn was hardcoded to 8000  
**Fix:** `railway.toml` uses `sh -c '... --port ${PORT:-8000}'` — shell expands `$PORT` at runtime

### App starts but `DI_ENV=production` rejects mock tokens

**Cause:** Production mode requires real RS256-signed JWTs — mock tokens (`mock.tenant.actor.ROLE`) are blocked  
**Fix:** Keep `DI_ENV=dev` for now. To use production mode, set `DI_SECURITY_JWKS_URL` to a real JWKS endpoint and use proper JWTs.

---

## Promoting to Production

When ready to flip `DI_ENV=production`:

1. Confirm `DI_SECURITY_JWKS_URL` points to a real, live JWKS endpoint (not the test GitHub raw URL)
2. Confirm `DI_STORAGE_PROVIDER=r2` with real R2 credentials
3. Confirm `DI_DOCAI_MOCK=false` only if Google Document AI processor is configured (otherwise keep `true`)
4. Change `DI_ENV` from `dev` to `production` on both Railway services
5. Redeploy and verify `/health/ready` returns 200

---

## Database Migrations

Migrations live in `backend/alembic/versions/`.

| Migration | What changed |
|---|---|
| `0001_initial_schema.py` | Full schema — all tables, FKs, RLS |
| `0002_schema_v2_2.py` | v2.2 delta — new columns |
| `0003_verification_threshold.py` | Per-tenant verification threshold column |
| `0004_relax_tenant_constraints.py` | Allow empty quality_policy array (auto-provisioning) |

**Adding a new migration:**
```bash
cd backend
uv run alembic revision -m "describe_your_change"
# Edit the generated file in alembic/versions/
DI_DATABASE_URL=<neon-url> uv run alembic upgrade head
```

---

## Key Files Reference

| File | Purpose |
|---|---|
| `Dockerfile` | API container — `pip install` from pyproject.toml, uvicorn CMD |
| `Dockerfile.worker` | Worker container — same install, `python -m` CMD |
| `railway.toml` | di-api: builder, startCommand, healthcheck |
| `railway.worker.toml` | di-worker: builder, startCommand |
| `backend/src/verigence/di/settings.py` | All env vars, production safety validator |
| `backend/src/verigence/di/repositories/tenants.py` | `provision_tenant()` + `provision_actor()` |
| `backend/alembic/` | Database migration scripts |
| `scripts/railway-*.sh` | Cost management scripts |
| `docs/deployment.md` | This file |
