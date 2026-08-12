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

| Variable | Description | Local dev | Railway dev | Railway prod |
|---|---|---|---|---|
| **Application** |||||
| `DI_ENV` | Environment name: `local` / `dev` / `production` | ⚠️ `local` | ❌ | ❌ |
| `DI_SECRET_KEY` | App secret key — minimum 32 chars | ⚠️ placeholder | ❌ | ❌ |
| `DI_LOG_LEVEL` | Logging level | ⚠️ `INFO` | ❌ | ❌ |
| **Database** |||||
| `DI_DATABASE_URL` | asyncpg PostgreSQL connection string | ⚠️ local docker | ❌ Neon dev | ❌ Neon prod |
| **Object Storage** |||||
| `DI_STORAGE_PROVIDER` | `minio` or `r2` | ⚠️ `minio` | ❌ `r2` | ❌ `r2` |
| `DI_STORAGE_ENDPOINT` | S3-compatible endpoint URL | ⚠️ `http://localhost:9000` | ❌ R2 endpoint | ❌ R2 endpoint |
| `DI_STORAGE_ACCESS_KEY_ID` | S3 access key | ⚠️ `minioadmin` | ❌ | ❌ |
| `DI_STORAGE_SECRET_ACCESS_KEY` | S3 secret key | ⚠️ `minioadmin123` | ❌ | ❌ |
| `DI_STORAGE_BUCKET` | Bucket name | ⚠️ `verigence-di-dev` | ❌ | ❌ |
| `DI_STORAGE_REGION` | Region | ⚠️ `us-east-1` | ❌ `auto` (R2) | ❌ `auto` (R2) |
| **Auth — Clerk** |||||
| `DI_CLERK_PUBLISHABLE_KEY` | Clerk frontend key (`pk_...`) | ⚠️ `pk_test_mock` | ❌ | ❌ |
| `DI_CLERK_SECRET_KEY` | Clerk backend key (`sk_...`) | ⚠️ `sk_test_mock` | ❌ | ❌ |
| `DI_CLERK_JWKS_URL` | JWKS endpoint from Clerk dashboard | ⚠️ not needed (mock mode) | ❌ | ❌ |
| **Google Document AI** |||||
| `DI_DOCAI_MOCK` | `true` = use mock adapter | ✅ `true` | ✅ `true` | ❌ `false` |
| `DI_DOCAI_PROJECT_ID` | GCP project ID | N/A (mock) | N/A (mock) | ❌ |
| `DI_DOCAI_LOCATION` | Processor location (`us` / `eu`) | N/A (mock) | N/A (mock) | ❌ `us` |
| `DI_DOCAI_PROCESSOR_ID` | Document AI processor ID | N/A (mock) | N/A (mock) | ❌ |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON | N/A (mock) | N/A (mock) | ❌ |
| **Monitoring** |||||
| `DI_SENTRY_DSN` | Sentry project DSN | ⚠️ empty | ⚠️ empty | ❌ |
| **WhatsApp (Phase 2)** |||||
| `DI_WHATSAPP_VERIFY_TOKEN` | Webhook verification token | N/A | N/A | ❌ |
| `DI_WHATSAPP_ACCESS_TOKEN` | Meta Cloud API access token | N/A | N/A | ❌ |
| `DI_WHATSAPP_PHONE_NUMBER_ID` | WhatsApp phone number ID | N/A | N/A | ❌ |
| **ops-ui (Cloudflare Pages)** |||||
| `VITE_CLERK_PUBLISHABLE_KEY` | Clerk publishable key for frontend | N/A | ❌ | ❌ |
| `VITE_API_BASE_URL` | Backend API base URL | N/A | ❌ | ❌ |

---

## How to get each secret

### Clerk (`DI_CLERK_*` and `VITE_CLERK_*`)
1. Go to https://clerk.com → create application
2. Dashboard → API Keys: copy `Publishable key` → `DI_CLERK_PUBLISHABLE_KEY`
3. Dashboard → API Keys: copy `Secret key` → `DI_CLERK_SECRET_KEY`
4. Dashboard → JWT Templates → New template:
   - Name: `verigence-di`
   - Audience: `verigence-document-intelligence`
   - Add claims: `tenant_id`, `actor_id`, `actor_type`, `roles`, `permissions`
5. Dashboard → JWKS: copy URL → `DI_CLERK_JWKS_URL`

### Cloudflare R2 (`DI_STORAGE_*`)
1. Cloudflare dashboard → R2 → Create bucket
2. R2 → Manage API tokens → Create API token (Object Read & Write)
3. Copy endpoint from bucket settings → `DI_STORAGE_ENDPOINT`
4. Copy Access Key ID → `DI_STORAGE_ACCESS_KEY_ID`
5. Copy Secret Access Key → `DI_STORAGE_SECRET_ACCESS_KEY`

### Neon PostgreSQL (`DI_DATABASE_URL`)
1. https://neon.tech → create project → create database `verigence_di`
2. Connection string → replace `postgresql://` with `postgresql+asyncpg://`
3. Append `?sslmode=require` for production

### Google Document AI (`DI_DOCAI_*`)
1. GCP Console → Enable Document AI API
2. Create processor (Form Parser recommended)
3. Create service account → download JSON key
4. Note project ID, location (`us`), processor ID

### Sentry (`DI_SENTRY_DSN`)
1. https://sentry.io → create project (Python / FastAPI)
2. Copy DSN from project settings

---

## Local setup (.env.local)

```bash
cp verigence-di/infra/.env.example verigence-di/infra/.env.local
# Fill in real values for DI_CLERK_JWKS_URL, etc.
# Never commit .env.local
```

The `.gitignore` already excludes `*.env.local` and `*.env.prod`.
