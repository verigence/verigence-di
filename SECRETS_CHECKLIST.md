# Verigence DI — Secrets Checklist

**Never commit actual values. This file tracks what is set vs placeholder.**
Update this file whenever a secret is added, rotated, or confirmed.

---

## Status key
- ✅ Set with real value
- ⚠️ Placeholder / mock value only
- ❌ Not set at all
- N/A Not applicable for this environment

---

## Environment variable matrix

| Variable | Description | Local dev | Railway (production env) |
|---|---|---|---|
| **Application** ||||
| `DI_ENV` | Environment name: `local` / `dev` / `production` | ⚠️ `local` | ✅ `production` |
| `DI_SECRET_KEY` | App secret key — minimum 32 chars | ⚠️ placeholder | ✅ set |
| `DI_LOG_LEVEL` | Logging level | ⚠️ `INFO` | ⚠️ not set (defaults to INFO) |
| **Database** ||||
| `DI_DATABASE_URL` | asyncpg PostgreSQL connection string | ⚠️ local docker | ✅ Neon URL set |
| **Object Storage** ||||
| `DI_STORAGE_PROVIDER` | `minio` or `r2` | ⚠️ `minio` | ⚠️ `minio` (placeholder — R2 not yet configured) |
| `DI_STORAGE_ENDPOINT` | S3-compatible endpoint URL | ⚠️ `http://localhost:9000` | ⚠️ placeholder |
| `DI_STORAGE_ACCESS_KEY_ID` | S3 access key | ⚠️ `minioadmin` | ⚠️ placeholder |
| `DI_STORAGE_SECRET_ACCESS_KEY` | S3 secret key | ⚠️ `minioadmin123` | ⚠️ placeholder |
| `DI_STORAGE_BUCKET` | Bucket name | ⚠️ `verigence-di-dev` | ⚠️ placeholder |
| `DI_STORAGE_REGION` | Region | ⚠️ `us-east-1` | ⚠️ placeholder |
| **Auth — Security module** ||||
| `DI_SECURITY_JWKS_URL` | JWKS endpoint from Security module | ⚠️ `http://localhost/mock-jwks` | ✅ `https://raw.githubusercontent.com/verigence/verigence-di/dev/backend/tests/fixtures/test_jwks.json` |
| **Gemini 2.5 Flash — AI/OCR (D19)** ||||
| `DI_DOCAI_MOCK` | `true` = use mock adapter (local/CI) | ✅ `true` | ✅ `true` |
| `DI_DOCAI_GEMINI_API_KEY` | Google AI Studio API key (`https://aistudio.google.com/app/apikey`) | N/A (mock) | ❌ not set |
| **Monitoring** ||||
| `DI_SENTRY_DSN` | Sentry project DSN | ⚠️ empty | ⚠️ not set |
| **WhatsApp (Phase 2)** ||||
| `DI_WHATSAPP_VERIFY_TOKEN` | Webhook verification token | N/A | ❌ |
| `DI_WHATSAPP_ACCESS_TOKEN` | Meta Cloud API access token | N/A | ❌ |
| `DI_WHATSAPP_PHONE_NUMBER_ID` | WhatsApp phone number ID | N/A | ❌ |
| **ops-ui (Cloudflare Pages)** ||||
| `VITE_API_BASE_URL` | Backend API base URL | N/A | ❌ |

---

## Railway project IDs (confirmed 2026-08-13)

| Item | Value |
|---|---|
| Project ID | `62c22163-78d0-4a86-a2f7-dbf39e64aa4d` |
| di-api service ID | `7a608cd3-67d2-45b6-afaa-4d41c01cc664` |
| di-worker service ID | `228d06f9-1750-4654-be05-56083f6ec12a` |
| Environment ID (production) | `3e696b3a-1128-4970-b6c0-5a8c25d8fcb0` |
| di-api Railway URL | set by Railway on first successful deploy |

---

## GitHub Actions secrets required

| Secret name | Value | Status |
|---|---|---|
| `DI_SECRET_KEY` | 32+ char random string | ✅ set |
| `DEV_DATABASE_URL` | Neon PostgreSQL asyncpg URL | ✅ set |
| `TEST_JWT_PRIVATE_KEY` | Base64-encoded RSA private PEM for minting test JWTs | ⚠️ **must add** — see below |
| `RAILWAY_API_URL` | Live Railway URL for post-deploy smoke tests | ⚠️ **must add** — `https://verigence-di-production.up.railway.app` |
| `TEST_R2_ENDPOINT` | R2 endpoint URL for `verigence-di-test` bucket | ⚠️ **must add** after R2 bucket created |
| `TEST_R2_ACCESS_KEY_ID` | R2 access key for `verigence-di-test` bucket | ⚠️ **must add** after R2 bucket created |
| `TEST_R2_SECRET_ACCESS_KEY` | R2 secret key for `verigence-di-test` bucket | ⚠️ **must add** after R2 bucket created |

> Note: `RAILWAY_*` secrets are no longer used — deployment is via Railway's native GitHub integration (auto-deploys on push to `dev`).

### Adding TEST_JWT_PRIVATE_KEY to GitHub

The base64-encoded private key was generated on 2026-08-16. Add it as a GitHub Actions secret:
1. GitHub → verigence/verigence-di → Settings → Secrets and variables → Actions
2. New repository secret → name: `TEST_JWT_PRIVATE_KEY`
3. Value: the base64 string output from the key generation step (from this session)

The matching public key is committed to the repo at:
`backend/tests/fixtures/test_jwks.json` — kid: `verigence-di-test-key-1`

---

## How to get each secret

### Cloudflare R2 (`DI_STORAGE_*`) — next priority
1. Cloudflare dashboard → R2 → Create bucket named `verigence-di-prod`
2. R2 → Manage API tokens → Create API token (Object Read & Write)
3. Copy endpoint from bucket settings → `DI_STORAGE_ENDPOINT`
4. Copy Access Key ID → `DI_STORAGE_ACCESS_KEY_ID`
5. Copy Secret Access Key → `DI_STORAGE_SECRET_ACCESS_KEY`
6. Set `DI_STORAGE_PROVIDER=r2`, `DI_STORAGE_REGION=auto`

### Neon PostgreSQL (`DI_DATABASE_URL`)
1. https://neon.tech → create project → create database `verigence_di`
2. Connection string → replace `postgresql://` with `postgresql+asyncpg://`
3. Append `?sslmode=require`

### Security module (`DI_SECURITY_JWKS_URL`)
- Set once Security module is deployed: `https://<security-host>/.well-known/jwks.json`
- Until then mock mode is active (`DI_ENV != production` bypasses real JWT verification)

### Gemini 2.5 Flash (`DI_DOCAI_GEMINI_API_KEY`) — D19
1. https://aistudio.google.com/app/apikey → Sign in → Create API key
2. Copy the key → `DI_DOCAI_GEMINI_API_KEY`
3. Set `DI_DOCAI_MOCK=false` on Railway di-api + di-worker services
4. Set `DI_DOCAI_GEMINI_API_KEY` on Railway → di-api service Variables AND di-worker service Variables

### Sentry (`DI_SENTRY_DSN`)
1. https://sentry.io → create project (Python / FastAPI)
2. Copy DSN from project settings

---

## Local setup (.env.local)

```bash
cp verigence-di/infra/.env.example verigence-di/infra/.env.local
# Fill in real values
# Never commit .env.local
```

The `.gitignore` already excludes `*.env.local` and `*.env.prod`.
