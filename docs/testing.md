# Verigence DI — Testing Guide

**Last updated:** 2026-08-16

---

## Overview

The test suite has three tiers:

```
Tier 0 — Unit tests        (no DB, no network, runs on every push)
Tier 1 — Smoke tests       (Neon DB + R2 + real JWTs, runs on every push, blocks deploy)
Tier 2 — Extended tests    (Neon DB + R2 + real JWTs, triggered on demand)
Post-deploy — Live smoke   (hits live Railway URL, runs after deploy)
```

**Current count:** 107 unit tests, 11 smoke tests, 25+ extended tests, 8 post-deploy tests

---

## Running Tests Locally

### Tier 0 — Unit tests (always works, no setup needed)

```bash
cd backend
PYTHONPATH=src uv run pytest -m no_docker --no-cov -q
```

Expected: `107 passed, 1 xfailed`

These tests have zero external dependencies — no DB, no network, no Docker.

### Tier 1 — Smoke tests (requires Neon DB + R2 + private key)

```bash
cd backend
export DI_DATABASE_URL="postgresql+asyncpg://<neon-url>?ssl=require"
export DI_ENV=dev
export DI_DOCAI_MOCK=true
export DI_WORKER_ENABLED=false
export DI_STORAGE_PROVIDER=r2
export DI_STORAGE_BUCKET=verigence-di-test
export DI_STORAGE_ENDPOINT=https://<account>.r2.cloudflarestorage.com
export DI_STORAGE_ACCESS_KEY_ID=<key>
export DI_STORAGE_SECRET_ACCESS_KEY=<secret>
export DI_STORAGE_REGION=auto
export DI_SECURITY_JWKS_URL=https://raw.githubusercontent.com/verigence/verigence-di/dev/backend/tests/fixtures/test_jwks.json
export TEST_JWT_PRIVATE_KEY=<base64-encoded-private-pem>

PYTHONPATH=src uv run pytest -m smoke --no-cov -q
```

### Tier 2 — Extended tests (same env as smoke)

```bash
PYTHONPATH=src uv run pytest -m extended --no-cov -q
```

### Post-deploy smoke (requires live Railway URL)

```bash
export RAILWAY_API_URL=https://di-api-production.up.railway.app
export TEST_JWT_PRIVATE_KEY=<base64-encoded-private-pem>
export SMOKE_TENANT_ID=post-deploy-smoke-tenant

PYTHONPATH=src uv run pytest -m post_deploy_smoke --no-cov -q
```

---

## CI Pipeline Shape

```
push to dev branch
    │
    ├── job: quality  (always runs)
    │       - ruff lint
    │       - python -m compileall
    │       - pytest -m no_docker (107 unit tests)
    │       - pip check
    │
    ├── job: smoke  (needs: quality, always runs, BLOCKS deploy if fails)
    │       - pytest -m smoke (~11 tests)
    │       - Neon DB + R2 test bucket + real RSA JWTs
    │
    └── Railway auto-deploys on push (after CI passes)

manual trigger (GitHub Actions → workflow_dispatch → run_extended=true):
    └── job: extended  (~25 tests, Tier 2)

after Railway deploys:
    └── job: post-deploy-smoke  (8 tests, hits live Railway URL)
```

---

## Test Infrastructure

### JWT authentication in tests

Tests use **real RS256-signed JWTs** — the same verification path as production.

**How it works:**
1. RSA key pair generated once (`kid: verigence-di-test-key-1`)
2. Public key committed to repo: `backend/tests/fixtures/test_jwks.json`
3. Private key stored as GitHub secret `TEST_JWT_PRIVATE_KEY` (base64-encoded PEM)
4. `tests/jwt_helper.py` mints JWTs using the private key
5. `conftest.py` patches `JWKSCache.get_key` to serve from the committed JSON file

```python
from tests.jwt_helper import mint_jwt

token = mint_jwt(
    tenant_id="my-tenant",
    actor_id="actor-001",
    roles=["TENANT_ADMIN"],
)
headers = {"Authorization": f"Bearer {token}"}
```

### Test fixtures (conftest.py)

| Fixture | Scope | What it does |
|---|---|---|
| `_patch_jwks_cache` | session | Patches JWKS HTTP fetch to load from test_jwks.json |
| `test_tenant_id` | function | Returns unique `test-<8hex>` string per test |
| `api_client` | function | AsyncClient over ASGITransport + Neon DB + R2 |
| `tenant_cleanup` | function | Deletes all DB rows for test_tenant_id after test |
| `storage_cleanup` | function | Deletes all R2 objects with test prefix after test |

### Pytest markers

| Marker | When runs | Purpose |
|---|---|---|
| `no_docker` | always | Unit tests — no external deps |
| `smoke` | every push | Fast integration tests, blocks deploy |
| `extended` | on demand | Full coverage, costs more |
| `post_deploy_smoke` | after deploy | Hits live Railway URL |

---

## Test Files

| File | Tier | Tests | What it covers |
|---|---|---|---|
| `tests/test_auth.py` | 0 | 15 | Permission checks, mock token parsing |
| `tests/test_health.py` | 0 | 4 | Health endpoint responses |
| `tests/test_intake_quality.py` | 0 | 18 | Quality gate intake flow |
| `tests/test_quality_rules.py` | 0 | 22 | Individual quality rule logic |
| `tests/test_quality_validator.py` | 0 | 20 | Quality validator FIT/NOT_FIT/CORRUPT |
| `tests/test_rules.py` | 0 | 20 | Normalization + validation rules |
| `tests/test_scoring.py` | 0 | 8 | Confidence scoring + threshold |
| `tests/test_smoke.py` | 1 | 11 | Health, auth, subject round-trip |
| `tests/test_extended_auth.py` | 2 | 7 | Token edge cases, tenant isolation |
| `tests/test_extended_documents.py` | 2 | 11 | Upload quality, R2 write, list/get/delete |
| `tests/test_extended_e2e.py` | 2 | 2 | End-to-end worker processing |
| `tests/test_extended_tenant_config.py` | 2 | 5 | Verification threshold CRUD |
| `tests/post_deploy/test_post_deploy_smoke.py` | post-deploy | 8 | Live Railway URL smoke |

---

## GitHub Actions Secrets Required for Testing

| Secret | Used by | How to get |
|---|---|---|
| `DI_SECRET_KEY` | quality, smoke, extended | Any 32+ char random string |
| `DEV_DATABASE_URL` | quality, smoke, extended | Neon connection string |
| `TEST_JWT_PRIVATE_KEY` | smoke, extended, post-deploy | Base64-encoded RSA PEM — see below |
| `RAILWAY_API_URL` | post-deploy | `https://di-api-production.up.railway.app` |
| `TEST_R2_ENDPOINT` | smoke, extended | R2 endpoint for `verigence-di-test` bucket |
| `TEST_R2_ACCESS_KEY_ID` | smoke, extended | R2 API key for `verigence-di-test` bucket |
| `TEST_R2_SECRET_ACCESS_KEY` | smoke, extended | R2 secret for `verigence-di-test` bucket |

### Adding TEST_JWT_PRIVATE_KEY

The RSA private key was generated on 2026-08-16. The base64-encoded value was output during that session.

To regenerate if needed:
```bash
# Generate new key pair
openssl genrsa -out test_private.pem 2048
openssl rsa -in test_private.pem -pubout -out test_public.pem

# Convert public key to JWK format and update test_jwks.json
# (Use the key generation script in the session notes)

# Base64 encode the private key for GitHub
base64 -i test_private.pem | tr -d '\n'
```

Add to GitHub: repo → Settings → Secrets and variables → Actions → New repository secret → `TEST_JWT_PRIVATE_KEY`

---

## R2 Test Bucket Setup

The smoke and extended tests use a **dedicated test bucket** `verigence-di-test` — separate from production `verigence-di-bucket-dev`.

**Create the test bucket:**
1. Cloudflare dashboard → R2 → Create bucket → name: `verigence-di-test`
2. R2 → Manage R2 API Tokens → Create API Token
3. Permissions: Object Read & Write, Scope: `verigence-di-test` only
4. Note endpoint, Access Key ID, Secret Access Key
5. Add three GitHub secrets: `TEST_R2_ENDPOINT`, `TEST_R2_ACCESS_KEY_ID`, `TEST_R2_SECRET_ACCESS_KEY`

**This bucket is not yet created.** Until it is, smoke tests skip storage operations.

---

## Known Test Issues

| Issue | File | Status |
|---|---|---|
| `test_empty_policy_no_rules_returns_fit` returns CORRUPT instead of FIT | `test_quality_validator.py` | Open — marked `@pytest.mark.xfail` |

---

## Triggering Extended Tests Manually

GitHub → Actions → DI CI → Run workflow → set `run_extended=true` → Run workflow

This runs Tier 2 extended tests (~25 tests) against Neon + R2 on demand.
