# Verigence DI — Railway Deployment Runbook

**Written:** 2026-08-16  
**Purpose:** Step-by-step guide so deployment never takes more than 15 minutes.

---

## Architecture

```
GitHub (dev branch)
    │  push
    ▼
GitHub Actions (ci.yml)
    ├── job: quality  — ruff + 107 unit tests
    └── job: smoke    — integration tests (needs: quality)

Railway (auto-deploy on push to dev)
    ├── di-api service     — FastAPI + uvicorn
    └── di-worker service  — background processor
```

---

## Service Configuration (Railway Dashboard)

### di-api service

| Setting | Value |
|---|---|
| **Source** | GitHub → verigence/verigence-di, branch: dev |
| **Config File Path** | `railway.toml` |
| **Dockerfile Path** | `Dockerfile` (set in railway.toml) |
| **Start Command** | set in `railway.toml` — do NOT set in dashboard |
| **Health Check Path** | `/health/live` (set in railway.toml) |
| **Public URL** | `https://di-api-production.up.railway.app` |

### di-worker service

| Setting | Value |
|---|---|
| **Source** | GitHub → verigence/verigence-di, branch: dev |
| **Config File Path** | `railway.worker.toml` |
| **Dockerfile Path** | `Dockerfile.worker` (set in railway.worker.toml) |
| **Start Command** | set in `railway.worker.toml` — do NOT set in dashboard |
| **Health Check** | none (workers have no HTTP server) |

---

## Environment Variables (both services unless noted)

| Variable | Value | Notes |
|---|---|---|
| `DI_ENV` | `dev` | Change to `production` only when R2 + JWKS fully configured |
| `DI_SECRET_KEY` | 32+ char random string | Set once, never rotate without notice |
| `DI_DATABASE_URL` | Neon asyncpg URL | `postgresql+asyncpg://...?sslmode=require` |
| `DI_DOCAI_MOCK` | `true` | Until Google Document AI is configured |
| `DI_SECURITY_JWKS_URL` | `https://raw.githubusercontent.com/verigence/verigence-di/dev/backend/tests/fixtures/test_jwks.json` | di-api only |
| `DI_STORAGE_PROVIDER` | `r2` | |
| `DI_STORAGE_ENDPOINT` | `https://a1e15a39a0a8f86dc1ca9c6a8726e428.r2.cloudflarestorage.com` | |
| `DI_STORAGE_ACCESS_KEY_ID` | (R2 key) | |
| `DI_STORAGE_SECRET_ACCESS_KEY` | (R2 secret) | |
| `DI_STORAGE_BUCKET` | `verigence-di-bucket-dev` | |
| `DI_STORAGE_REGION` | `auto` | |

---

## First-Time Setup Checklist

### Step 1 — Create Railway services

1. Railway dashboard → New Project → `verigence-di`
2. Add service → "Deploy from GitHub repo" → `verigence/verigence-di`, branch `dev`
3. Rename service to `di-api`
4. Add second service → same repo/branch → rename to `di-worker`

### Step 2 — Configure di-api

1. Settings → Build → **Config File Path** → `railway.toml` → Save
2. Settings → Networking → Generate Domain → note the URL
3. Variables → add all env vars from table above

### Step 3 — Configure di-worker

1. Settings → Build → **Config File Path** → `railway.worker.toml` → Save
2. Settings → Build → **Dockerfile Path** → `Dockerfile.worker` → Save
3. Variables → add same env vars (except `DI_SECURITY_JWKS_URL`)

### Step 4 — Verify health

```bash
curl https://di-api-production.up.railway.app/health/live
# Expected: {"status":"live"}

curl https://di-api-production.up.railway.app/health/ready
# Expected: {"status":"ready","databaseReady":true}
```

---

## Deployment Flow (normal push)

```bash
git push origin dev
```

1. GitHub Actions runs `quality` job (lint + unit tests)
2. GitHub Actions runs `smoke` job (integration tests against Neon + R2)
3. If both pass → Railway auto-deploys both services from Dockerfile
4. `railway-dev-deploy.yml` gate job waits for CI to pass
5. Post-deploy smoke hits live Railway URL

**No manual steps needed for a normal deploy.**

---

## Troubleshooting

### "executable cd not found"

**Cause:** Railway dashboard has an old start command with `cd /app/backend && ...`  
**Fix:**
1. Railway dashboard → service → Settings → Build → **Config File Path** → set to `railway.toml`
2. Clear any start command in the Settings → Deploy section
3. Redeploy

### Health check failure (service unavailable)

**Cause 1:** App crashes at startup (check Railway deployment logs)  
**Cause 2:** `healthcheckPath` points to `/health/ready` which returns 503 if DB unreachable  
**Fix:** `railway.toml` uses `/health/live` — if changed, revert it

### 500 on POST /subjects (or any write operation)

**Cause:** Missing `tenant_settings` or `actors` FK rows  
**Fix:** Handled automatically since commit `2616697` — `provision_tenant()` and `provision_actor()` are called on every `tenant_session()` open

### App starts but returns wrong port

**Cause:** `$PORT` not expanded (Railway sets 8080, not 8000)  
**Fix:** `railway.toml` uses `sh -c '... --port ${PORT:-8000}'` — shell expands `$PORT`

### DI_SECURITY_JWKS_URL validator blocks startup

**Cause:** `DI_ENV=production` requires a real (non-mock) JWKS URL  
**Fix:** Set `DI_ENV=dev` on Railway until production JWKS is configured, OR set `DI_SECURITY_JWKS_URL` to the committed test JWKS URL

---

## Key Files

| File | Purpose |
|---|---|
| `Dockerfile` | API container — `pip install` + uvicorn CMD |
| `Dockerfile.worker` | Worker container — `pip install` + python -m CMD |
| `railway.toml` | di-api build + deploy config (builder, startCommand, healthcheck) |
| `railway.worker.toml` | di-worker build + deploy config |
| `backend/src/verigence/di/settings.py` | All env var definitions + production safety validator |
| `backend/src/verigence/di/repositories/tenants.py` | `provision_tenant()` + `provision_actor()` — auto-create FK rows |
| `backend/alembic/versions/` | DB migrations — run `alembic upgrade head` on new DB |

---

## Neon Database

**Connection:** `postgresql+asyncpg://neondb_owner:...@ep-royal-pond-ayci3m0f.c-5.us-east-2.aws.neon.tech/neondb?ssl=require`

**Run migrations:**
```bash
cd backend
DI_DATABASE_URL="<neon-url>" uv run alembic upgrade head
```

**Current migration state:** `0004` (head)

| Migration | What |
|---|---|
| 0001 | Full initial schema — all tables, FKs, RLS policies |
| 0002 | v2.2 delta — new columns + indexes |
| 0003 | `verification_threshold` column on `tenant_settings` |
| 0004 | Relax `quality_policy` check (allow empty array) |

---

## GitHub Actions Secrets Required

| Secret | Purpose |
|---|---|
| `DI_SECRET_KEY` | App secret key |
| `DEV_DATABASE_URL` | Neon URL for CI unit tests |
| `TEST_JWT_PRIVATE_KEY` | RSA private key for smoke test JWT minting |
| `RAILWAY_API_URL` | Live Railway URL for post-deploy smoke |
| `TEST_R2_ENDPOINT` | R2 endpoint for test bucket |
| `TEST_R2_ACCESS_KEY_ID` | R2 key for test bucket |
| `TEST_R2_SECRET_ACCESS_KEY` | R2 secret for test bucket |
