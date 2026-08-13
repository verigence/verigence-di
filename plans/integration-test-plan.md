# Integration Test Plan — Post-Deployment Quality Gate

## Top-Level Overview

**Goal:** Build a configurable, two-tier test suite that gives confidence after every
deployment without running heavy tests on every single build.

**Problem being solved:** The current CI pipeline runs 107 unit tests (pure logic, no HTTP,
no DB) then deploys unconditionally. The entire API layer — all 54 REST operations — has
zero test coverage. A broken deployment is not caught until a human manually tests it.

**Two-tier test strategy:**

```
Tier 1 — SMOKE (fast, mandatory on every build)
  ∙ Runs on every push to dev, BEFORE deploy
  ∙ ~10 tests — health, auth acceptance/rejection, one subject round-trip
  ∙ Uses ASGITransport (no real HTTP), Neon DB, real R2 storage
  ∙ Real RSA-signed JWTs — exercises the real auth verification path
  ∙ If any fail → deploy is blocked

Tier 2 — EXTENDED (comprehensive, triggered on demand or scheduled)
  ∙ NOT run on every push — triggered manually via workflow_dispatch or on a schedule
  ∙ ~40 tests — full subject/document/worker/tenant-config coverage
  ∙ Same infrastructure as Tier 1: Neon DB, real R2, real JWTs
  ∙ End-to-end worker processing included
  ∙ Results reported as a separate CI job
```

**Post-deploy gate (both tiers):**
After Railway deploys, a `post-deploy-smoke` job runs the Tier 1 smoke tests
again — but this time against the **live Railway URL** using real HTTP. This confirms
the deployed service is actually serving traffic correctly.

**Auth strategy:** A dedicated RSA test key pair is generated once. The public key is
committed to the repo as `tests/fixtures/test_jwks.json`. The private key is stored
as a GitHub secret. All tests (both tiers and post-deploy) mint real signed JWTs with
`iss=verigence-security`, `aud=verigence-platform` — the **real JWT verification path**
is exercised, not the mock token bypass.

**Storage:** Both tiers use **real Cloudflare R2** with a dedicated test bucket
`verigence-di-test`. No fake/mock storage. This ensures storage integration is verified
on every run.

**Non-goals:**
- Load / performance testing
- Full coverage of all 54 operations — focus on critical path correctness
- Testing WhatsApp adapter (Phase 2 — not yet implemented)
- Replacing existing unit tests — they remain unchanged

---

## CI Pipeline Shape (after this plan is complete)

```
push to dev
    │
    ├── job: unit-test        (existing — lint + 107 unit tests, no_docker, always runs)
    │
    ├── job: smoke            (NEW — Tier 1, ~10 tests, always runs, blocks deploy)
    │       needs: unit-test
    │       markers: pytest -m smoke
    │       infra: ASGITransport + Neon DB + real R2 + real JWTs
    │
    ├── job: deploy-api       (existing — Railway GitHub integration)
    │       needs: [unit-test, smoke]
    ├── job: deploy-worker
    │       needs: [unit-test, smoke]
    │
    └── job: post-deploy-smoke (NEW — hits live Railway URL with real HTTP)
            needs: [deploy-api, deploy-worker]
            markers: pytest -m post_deploy_smoke


manual trigger (workflow_dispatch) or schedule:
    └── job: extended         (NEW — Tier 2, ~40 tests, on demand only)
            markers: pytest -m extended
            infra: same as smoke (Neon DB + real R2 + real JWTs)
```

---

## Sub-Tasks

---

### Sub-Task 1 — Test RSA Key Pair + JWKS Infrastructure

**Status:** [ ] pending

**Intent:**
Generate a dedicated test RSA key pair. The private key mints JWTs in both CI jobs
and local developer runs. The public key is committed to the repo as a JWKS JSON file.
The app (both in-process ASGITransport tests and the live Railway service) is pointed
at this JWKS file so the real `auth/verifier.py` code path is exercised end-to-end.

**Expected Outcomes:**
- `backend/tests/fixtures/test_jwks.json` committed to repo — contains RSA public key in JWKS format
- Private key is NOT committed — stored only as GitHub secret `TEST_JWT_PRIVATE_KEY` (base64-encoded PEM)
- A `mint_jwt(tenant_id, actor_id, roles, permissions, exp_seconds=300)` helper function in `tests/jwt_helper.py`:
  - Reads private key from env var `TEST_JWT_PRIVATE_KEY`
  - Signs a JWT with correct claims: `iss=verigence-security`, `aud=verigence-platform`, `sub=<actor_id>`, `tenant_id`, `permissions[]`, `exp`
  - Returns the signed token string
- A `jwks_loader` patch in `conftest.py` that overrides JWKS HTTP fetch with local file load for in-process tests
- Railway `DI_SECURITY_JWKS_URL` updated to:
  `https://raw.githubusercontent.com/<org>/verigence-di/dev/backend/tests/fixtures/test_jwks.json`

**Todo List:**
1. Generate 2048-bit RSA key pair: `openssl genrsa -out test_private.pem 2048` and extract public key
2. Convert public key to JWK format with fields: `kid`, `kty=RSA`, `use=sig`, `alg=RS256`, `n`, `e`
3. Write `backend/tests/fixtures/test_jwks.json` as `{"keys": [<jwk>]}`
4. Base64-encode the private PEM and store as GitHub Actions secret `TEST_JWT_PRIVATE_KEY`
5. Create `backend/tests/jwt_helper.py` with `mint_jwt()` function using `python-jose` (already a prod dependency)
6. In `conftest.py`, add a session-scoped autouse fixture `_patch_jwks_cache` for smoke/extended tests that:
   - Monkeypatches `verigence.di.auth.jwks.JwksCache.get_key` to load from `tests/fixtures/test_jwks.json` instead of HTTP
7. Add `TEST_JWT_PRIVATE_KEY` to `ci-dev.yml` env block for smoke and extended test steps
8. Update Railway `DI_SECURITY_JWKS_URL` in the Railway dashboard to the raw GitHub URL of `test_jwks.json`
9. Update `SECRETS_CHECKLIST.md`: mark `DI_SECURITY_JWKS_URL` as ✅ on Railway; add `TEST_JWT_PRIVATE_KEY` row

**Relevant Context:**
- `backend/src/verigence/di/auth/verifier.py` — `_ISSUER = "verigence-security"`, `_AUDIENCE = "verigence-platform"`
- `backend/src/verigence/di/auth/jwks.py` — `JwksCache` class; reads `DI_SECURITY_JWKS_URL` env var
- `python-jose` already in `pyproject.toml` production dependencies — use for JWT signing
- `cryptography` library may need adding to dev dependencies for RSA key operations

---

### Sub-Task 2 — R2 Test Bucket + Storage Configuration

**Status:** [ ] pending

**Intent:**
Create a dedicated Cloudflare R2 bucket `verigence-di-test` for use by the test suite.
Tests use real R2 — not a fake. This bucket is separate from production (`verigence-di-prod`)
so tests cannot corrupt production data. A cleanup fixture deletes uploaded test objects
after each test.

**Expected Outcomes:**
- R2 bucket `verigence-di-test` exists in Cloudflare
- A separate R2 API token is created with read/write access to `verigence-di-test` only
- GitHub Actions secrets `TEST_R2_ENDPOINT`, `TEST_R2_ACCESS_KEY_ID`, `TEST_R2_SECRET_ACCESS_KEY` are set
- `conftest.py` has a `storage_cleanup` fixture that deletes all objects with key prefix `test-tenant-*/` after each test
- In CI, the smoke and extended jobs set `DI_STORAGE_BUCKET=verigence-di-test` and the test R2 credentials

**Todo List:**
1. In Cloudflare dashboard → R2 → Create bucket named `verigence-di-test` (same account as prod)
2. R2 → Manage API Tokens → Create token `verigence-di-test-token` with Object Read & Write scoped to `verigence-di-test` only
3. Note the Access Key ID, Secret Access Key, and endpoint URL
4. Add three GitHub Actions secrets: `TEST_R2_ACCESS_KEY_ID`, `TEST_R2_SECRET_ACCESS_KEY`, `TEST_R2_ENDPOINT`
5. In `conftest.py`, add a `storage_cleanup` fixture (function-scoped) that:
   - After each test, lists all objects in `verigence-di-test` with prefix matching the test tenant_id
   - Deletes them via the `S3StorageAdapter.delete()` method
6. In `ci-dev.yml` smoke and extended job env blocks, set:
   - `DI_STORAGE_PROVIDER=r2`
   - `DI_STORAGE_BUCKET=verigence-di-test`
   - `DI_STORAGE_ENDPOINT` from `TEST_R2_ENDPOINT` secret
   - `DI_STORAGE_ACCESS_KEY_ID` from `TEST_R2_ACCESS_KEY_ID` secret
   - `DI_STORAGE_SECRET_ACCESS_KEY` from `TEST_R2_SECRET_ACCESS_KEY` secret
   - `DI_STORAGE_REGION=auto`

**Relevant Context:**
- `backend/src/verigence/di/storage/adapter.py` — `S3StorageAdapter`; same code works for test R2 bucket
- `backend/src/verigence/di/settings.py` — storage env vars: `DI_STORAGE_PROVIDER`, `DI_STORAGE_BUCKET`, etc.
- Cloudflare R2 dashboard — same account used for `verigence-di-prod`

---

### Sub-Task 3 — Test Infrastructure: Markers, Fixtures, conftest Extension

**Status:** [ ] pending

**Intent:**
Extend `conftest.py` with the shared infrastructure needed by both tiers: pytest markers,
the `api_client` fixture (ASGITransport wired to Neon DB + real R2), and tenant cleanup.
This sub-task creates no tests — only the plumbing that all subsequent test sub-tasks depend on.

**Expected Outcomes:**
- Three new markers registered: `smoke`, `extended`, `post_deploy_smoke`
- `api_client` fixture: `AsyncClient` over `ASGITransport(create_app())` with env vars overridden for test
- `test_tenant_id` fixture: returns a unique `test-tenant-<uuid4-short>` string per test
- `tenant_cleanup` fixture: deletes all `docintel.*` rows for `test_tenant_id` after each test using direct DB SQL
- Worker disabled (`DI_WORKER_ENABLED=false`) in `api_client` — keeps tests synchronous; worker invoked directly in e2e tests
- `ci-dev.yml` extended with `smoke` job (always runs, blocks deploy) and `extended` job (workflow_dispatch only)

**Todo List:**
1. Register markers in `conftest.py` `pytest_configure`: `smoke`, `extended`, `post_deploy_smoke`
2. Add `test_tenant_id` fixture (function-scoped) — returns `f"test-{uuid.uuid4().hex[:8]}"`
3. Add `api_client` fixture (function-scoped):
   - Sets env vars: `DI_DATABASE_URL` (Neon), `DI_ENV=dev`, `DI_DOCAI_MOCK=true`, `DI_WORKER_ENABLED=false`
   - Sets R2 test credentials via env vars
   - Calls `get_settings.cache_clear()` and resets DB engine singleton
   - Applies `_patch_jwks_cache` (from Sub-Task 1)
   - Returns `AsyncClient(transport=ASGITransport(create_app()), base_url="http://test")`
4. Add `tenant_cleanup` fixture (function-scoped, autouse for smoke/extended):
   - After yield, runs DELETE statements in correct FK order for `test_tenant_id`
   - Tables to clean: `processing_jobs`, `document_artifacts`, `documents`, `subjects`, `tenant_settings`, `actors`
5. In `ci-dev.yml`:
   - Add `smoke` job: `needs: unit-test`, runs `pytest -m smoke --no-cov -q`, passes Neon + R2 + JWT secrets
   - Change `deploy-api` and `deploy-worker` `needs` to `[unit-test, smoke]`
   - Add `extended` job with `on: workflow_dispatch` trigger only; runs `pytest -m extended --no-cov -q`
6. In `ci-dev.yml` add `post-deploy-smoke` job: `needs: [deploy-api, deploy-worker]`, runs `pytest -m post_deploy_smoke --no-cov -q`, passes `RAILWAY_API_URL` secret

**Relevant Context:**
- `backend/tests/conftest.py` — existing conftest; extend, do not replace
- `backend/src/verigence/di/settings.py` — `get_settings` uses `@lru_cache`; must `cache_clear()` before each test
- `backend/src/verigence/di/repositories/database.py` — `_engine` module-level singleton; must dispose and recreate when DB URL changes
- `backend/src/verigence/di/main.py` — `create_app()` factory; called fresh per test
- `.github/workflows/ci-dev.yml` — extend this file

---

### Sub-Task 4 — Tier 1 Smoke Tests (always runs, blocks deploy)

**Status:** [ ] pending

**Intent:**
The bare-minimum test suite that must pass on every push to `dev` before deploy.
Fast — no worker processing, no upload-to-processed flow. Covers the three things
that would make the whole system unusable: API not serving, auth broken, or
subject resource completely broken.

**Expected Outcomes:**
- Test file: `backend/tests/test_smoke.py`
- All tests marked `@pytest.mark.smoke`
- Run time target: under 30 seconds
- ~10 tests covering health, auth, and subject round-trip

**Todo List — test cases:**
1. `test_health_returns_ok` — GET /health → 200, `{"status": "ok"}`
2. `test_ready_returns_ok` — GET /ready → 200
3. `test_correlation_id_echoed_in_response` — X-Correlation-ID request header is echoed back
4. `test_correlation_id_generated_when_absent` — response always has X-Correlation-ID header
5. `test_missing_auth_returns_401` — GET /v1/tenants/x/subjects with no token → 401
6. `test_invalid_token_returns_401` — Bearer garbage-token → 401
7. `test_wrong_tenant_returns_403` — valid JWT for tenant-A, path tenant-B → 403
8. `test_insufficient_permission_returns_403` — VIEWER role token on POST /subjects → 403
9. `test_create_subject_returns_201` — TENANT_ADMIN token → POST /subjects → 201, body has `subjectId`
10. `test_get_subject_returns_created_subject` — create then GET by id → fields match
11. `test_error_response_is_problem_json` — any 401 response → body has `code`, `title`, `status` fields

**Relevant Context:**
- `backend/src/verigence/di/auth/permissions.py` — `ROLE_PERMISSIONS` for TENANT_ADMIN and VIEWER bundles
- `backend/src/verigence/di/api/v1/subjects.py` — createSubject, getSubject
- `backend/src/verigence/di/errors.py` — Problem JSON shape
- `backend/tests/jwt_helper.py` — `mint_jwt()` from Sub-Task 1

---

### Sub-Task 5 — Tier 2 Extended Tests: Auth & Tenant Isolation (on demand)

**Status:** [ ] pending

**Intent:**
Deeper auth coverage than Tier 1. Tests expired tokens, cross-tenant data isolation,
permission boundaries at the field level, and CORS headers. These edge cases matter
for security but don't need to block every build.

**Expected Outcomes:**
- Test file: `backend/tests/test_extended_auth.py`
- All tests marked `@pytest.mark.extended`

**Todo List — test cases:**
1. `test_expired_token_returns_401` — JWT with `exp` in the past → 401
2. `test_token_wrong_audience_returns_401` — JWT with `aud=wrong-service` → 401
3. `test_token_wrong_issuer_returns_401` — JWT with `iss=wrong-issuer` → 401
4. `test_tenant_isolation_subjects` — subject created under tenant-A → GET under tenant-B → 404
5. `test_tenant_isolation_documents` — document uploaded under tenant-A → GET under tenant-B → 404
6. `test_viewer_cannot_create_subject` — VIEWER role → POST /subjects → 403
7. `test_viewer_cannot_delete_document` — VIEWER role → DELETE /documents/:id → 403
8. `test_operator_can_upload_but_not_delete` — OPERATOR role → upload OK (201), delete → 403
9. `test_multiple_roles_union_permissions` — token with OPERATOR + VERIFIER roles → can both upload and verify

**Relevant Context:**
- `backend/src/verigence/di/auth/permissions.py` — full ROLE_PERMISSIONS bundles
- `backend/src/verigence/di/auth/verifier.py` — issuer/audience validation logic

---

### Sub-Task 6 — Tier 2 Extended Tests: Document Upload & Intake (on demand)

**Status:** [ ] pending

**Intent:**
Full coverage of the document upload and intake flow. Tests quality gate outcomes
(FIT/NOT_FIT/CORRUPT), storage write to real R2, processing job creation, document
listing/retrieval endpoints, and document delete eligibility. This is the highest-value
API path for operators.

**Expected Outcomes:**
- Test file: `backend/tests/test_extended_documents.py`
- All tests marked `@pytest.mark.extended`
- Real R2 bucket `verigence-di-test` is used — confirmed by verifying object exists after upload

**Todo List — test cases:**
1. `test_upload_pdf_returns_201_and_fit` — POST multipart with minimal valid PDF → 201, `uploadStatus=FIT`
2. `test_upload_writes_to_r2` — after upload, object exists in `verigence-di-test` bucket at expected logical key
3. `test_upload_creates_processing_job` — after FIT upload, query DB directly → processing job row exists with status `NOT_STARTED`
4. `test_upload_empty_file_is_not_fit` — 0-byte file → 201, `uploadStatus=NOT_FIT`
5. `test_upload_oversized_file_is_not_fit` — file > 30 MB → 201, `uploadStatus=NOT_FIT`
6. `test_upload_unsupported_mime_is_not_fit` — text/html file → 201, `uploadStatus=NOT_FIT`
7. `test_upload_requires_document_upload_permission` — VIEWER token → 403
8. `test_list_documents_returns_uploaded_doc` — upload then GET /subjects/:id/documents → doc appears
9. `test_get_document_by_id_returns_all_fields` — upload then GET /documents/:id → all response schema fields present and typed correctly
10. `test_get_document_not_found` — GET /documents/{random-uuid} → 404
11. `test_delete_not_fit_document_succeeds` — upload NOT_FIT → DELETE → 204
12. `test_delete_fit_document_returns_409` — upload FIT → DELETE → 409, `errorCode=DOCUMENT_NOT_ELIGIBLE_FOR_DELETE`

**Relevant Context:**
- `backend/src/verigence/di/api/v1/documents.py` — upload, list, get, delete endpoints
- `backend/src/verigence/di/application/intake.py` — intake flow; 10-step process
- `backend/src/verigence/di/quality/validator.py` — FIT/NOT_FIT/CORRUPT determination
- `backend/src/verigence/di/repositories/processing_jobs.py` — job creation after FIT upload
- `backend/src/verigence/di/storage/adapter.py` — `S3StorageAdapter.exists()` to verify R2 write

---

### Sub-Task 7 — Tier 2 Extended Tests: End-to-End Worker Processing (on demand)

**Status:** [ ] pending

**Intent:**
Test the complete document lifecycle — from upload to PROCESSED/CONFIRMED state.
The worker is invoked directly and synchronously within the test (not as a background
daemon). Uses `MockDocumentAIAdapter`. This is the single most important correctness
test in the entire suite.

**Expected Outcomes:**
- Test file: `backend/tests/test_extended_e2e.py`
- All tests marked `@pytest.mark.extended`
- Document reaches `processingStatus=PROCESSED`, `confirmationStatus=CONFIRMED`
- Extracted field values accessible via `GET /documents/:id/fields`

**Todo List — test cases:**
1. `test_document_reaches_processed_state`:
   - Seed: `tenant_settings` row (needs `classification_acceptance_score`), document type + PUBLISHED extraction profile with 2 canonical fields, subject
   - Upload a valid PDF → FIT
   - Invoke `ProcessingWorker.claim_and_run(session, tenant_id)` directly against the test DB session
   - Assert: `GET /documents/:id` → `processingStatus=PROCESSED`, `confirmationStatus=CONFIRMED`, `confidenceScore` is set
2. `test_document_fields_available_after_processing`:
   - Same setup and upload + claim-and-run as above
   - Assert: `GET /documents/:id/fields` → returns list of field values, each with `valueSource=MACHINE`
3. `test_verification_threshold_applied`:
   - Set tenant `verification_threshold=99.00` (very high — forces human verification)
   - Upload + process
   - Assert: `humanVerificationStatus=REQUIRES_HUMAN_VERIFICATION`
4. `test_classification_no_candidates_fails_gracefully`:
   - No document types configured for tenant
   - Upload + attempt to run worker
   - Assert: processing job status = `FAILED`, error_code = `CLASSIFICATION_NO_CANDIDATES`

**Relevant Context:**
- `backend/src/verigence/di/workers/job_runner.py` — `run_processing_job()` entry point
- `backend/src/verigence/di/workers/processor.py` — `ProcessingWorker` — `claim_and_run()`
- `backend/src/verigence/di/document_ai/adapter.py` — `MockDocumentAIAdapter`
- `backend/src/verigence/di/domain/scoring.py` — scoring + threshold → HVS derivation

---

### Sub-Task 8 — Tier 2 Extended Tests: Tenant Config & Verification Threshold (on demand)

**Status:** [ ] pending

**Intent:**
Verify the per-tenant verification threshold feature end-to-end — the DB column,
the API exposure, the fallback to system default, and the worker respecting it.

**Expected Outcomes:**
- Test file: `backend/tests/test_extended_tenant_config.py`
- All tests marked `@pytest.mark.extended`

**Todo List — test cases:**
1. `test_get_tenant_settings_returns_null_threshold_for_new_tenant` — no settings row → `verificationThreshold=null`
2. `test_put_updates_verification_threshold` — PUT `{verificationThreshold: 85.00}` → GET returns `85.00`
3. `test_put_requires_tenant_config_write` — VIEWER token → PUT → 403
4. `test_threshold_persists_across_requests` — PUT then separate GET → same value
5. `test_null_threshold_uses_system_default` — null DB value → `get_verification_threshold()` returns None → worker falls back to `DI_VERIFICATION_THRESHOLD` env var

**Relevant Context:**
- `backend/src/verigence/di/api/v1/tenant_config.py` — GET/PUT tenant settings endpoints
- `backend/src/verigence/di/repositories/documents.py` — `get_verification_threshold()`
- `backend/alembic/versions/0003_verification_threshold.py` — migration that added the column

---

### Sub-Task 9 — Post-Deploy Smoke Tests (hits live Railway URL)

**Status:** [ ] pending

**Intent:**
After Railway deploys both services, a CI job hits the **live Railway URL** using real
HTTP (not ASGITransport) and real signed JWTs. This is the final deployment gate —
it catches the class of failures that only manifest on the real infrastructure: bad env
vars, startup crashes, DB connection failures, misconfigured CORS, etc.

**Expected Outcomes:**
- Test file: `backend/tests/post_deploy/test_post_deploy_smoke.py`
- All tests marked `@pytest.mark.post_deploy_smoke`
- CI job `post-deploy-smoke` runs after both deploy jobs, fails CI if any test fails
- Tests use `httpx.AsyncClient` with real `base_url=RAILWAY_API_URL`
- Railway `DI_SECURITY_JWKS_URL` already updated (Sub-Task 1) — real JWT path works on live service

**Todo List — test cases:**
1. `test_health_live` — GET /health → 200, `{"status": "ok"}`
2. `test_ready_live` — GET /ready → 200
3. `test_unauthenticated_rejected_live` — no token → 401
4. `test_invalid_token_rejected_live` — garbage token → 401
5. `test_authenticated_list_subjects_live` — valid TENANT_ADMIN JWT → GET /subjects → 200
6. `test_wrong_tenant_rejected_live` — valid JWT tenant-A, path tenant-B → 403
7. `test_create_subject_live` — POST /subjects → 201, subject created on live DB
8. `test_correlation_id_present_live` — any response → X-Correlation-ID header present

**Todo List — CI wiring:**
1. Create `backend/tests/post_deploy/` directory with `__init__.py`
2. Add `post-deploy-smoke` job to `ci-dev.yml`:
   - `needs: [deploy-api, deploy-worker]`
   - `if: github.event_name == 'push' && github.ref == 'refs/heads/dev'`
   - env: `RAILWAY_API_URL` (from GitHub secret), `TEST_JWT_PRIVATE_KEY`, `SMOKE_TENANT_ID=post-deploy-smoke-tenant`
   - run: `pytest -m post_deploy_smoke --no-cov -q`
3. Add `RAILWAY_API_URL` GitHub Actions secret: `https://verigence-di-production.up.railway.app`
4. Add `post_deploy_cleanup` fixture — DELETE rows for `post-deploy-smoke-tenant` via direct Neon DB connection after test run

**Relevant Context:**
- `backend/src/verigence/di/auth/verifier.py` — `DI_ENV=production` rejects mock tokens; real JWT required
- Railway service URL: `https://verigence-di-production.up.railway.app`
- Railway `DI_SECURITY_JWKS_URL` must point to `test_jwks.json` raw GitHub URL (done in Sub-Task 1)

---

### Sub-Task 10 — PROGRESS.md + SECRETS_CHECKLIST.md Update

**Status:** [ ] pending

**Intent:**
Update both tracking documents to reflect the new test infrastructure, new secrets,
and updated CI pipeline shape.

**Expected Outcomes:**
- `PROGRESS.md` has a new session record documenting the two-tier test suite
- `SECRETS_CHECKLIST.md` has new rows for all test-related secrets
- Railway `DI_SECURITY_JWKS_URL` row marked ✅

**Todo List:**
1. Add to `SECRETS_CHECKLIST.md` GitHub Actions secrets section:
   - `TEST_JWT_PRIVATE_KEY` — RSA private key for minting test JWTs
   - `RAILWAY_API_URL` — live Railway URL for post-deploy smoke tests
   - `TEST_R2_ACCESS_KEY_ID` — R2 API key for `verigence-di-test` bucket
   - `TEST_R2_SECRET_ACCESS_KEY` — R2 secret for `verigence-di-test` bucket
   - `TEST_R2_ENDPOINT` — R2 endpoint URL
2. Update `DI_SECURITY_JWKS_URL` row in Railway column → ✅ (pointing at committed test_jwks.json)
3. Add session record to `PROGRESS.md` with: what was built, CI pipeline shape, new markers, R2 test bucket name

**Relevant Context:**
- `verigence-di/PROGRESS.md`
- `verigence-di/SECRETS_CHECKLIST.md`

---

## Key Decisions Recorded

| Decision | Choice | Reason |
|---|---|---|
| Test frequency | Two tiers — Tier 1 mandatory, Tier 2 on demand | Tier 2 hits real R2 + DB heavily; too slow and costly for every push |
| Storage | Real Cloudflare R2 — dedicated `verigence-di-test` bucket | No fake adapters; validates actual storage integration |
| Auth | Real RSA-signed JWTs from committed test JWKS | Exercises real JWT verification path; no mock token bypass |
| Post-deploy auth | Same real JWT approach, JWKS served from raw GitHub URL | Railway production rejects mock tokens; real path required |
| Worker in integration tests | Disabled in api_client; invoked directly in e2e tests | Keeps test control — no race with background daemon |
| Tenant cleanup | Delete rows for `test-tenant-*` prefix after each test | Tests share Neon DB; isolation without full reset |
| Extended trigger | `workflow_dispatch` only — not automatic | On-demand gives flexibility; can also be scheduled if needed later |
