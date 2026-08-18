# Plan: Step 9 — Gemini 2.5 Flash + Document Schema Registry

**Design authority:** `DI_GEMINI_DESIGN_v2.3.md`
**Baseline in force:** 2.2 (unchanged)
**New decisions:** D19–D23 (documented in `DI_GEMINI_DESIGN_v2.3.md`)
**Branch:** dev

---

## Context

The system is fully operational (108 tests passing, Railway live). Step 9 is
the only incomplete step. The Azure Document Intelligence provider was planned
but is blocked (portal.azure.com account issue). This plan switches the
provider to Gemini 2.5 Flash and introduces a Document Schema Registry.

### Hard constraints

- `MockDocumentAIAdapter` must not change. CI uses `DI_DOCAI_MOCK=true`.
- All 108 existing tests must continue to pass after every sub-task.
- `intake.py`, all REST API endpoints, Steps 1–9 and 11–17 of job_runner.py
  are untouched.
- No existing DB table is altered destructively. Migration 0007 is additive only.
- Every sub-task must compile cleanly: `python -m compileall -q src tests`

### Document type key ↔ display_name rule (from your instruction)

Every `document_type_key` in the schema registry MUST have a matching
`display_name` in the `document_types` table. The keys are the exact strings
used as `document_type_key` in the DB. Display names are the human-readable
names shown in the UI.

### Existing seed types in DB (migration 0005 — already applied to Neon)

| document_type_key   | display_name            | category    |
|---------------------|-------------------------|-------------|
| pan_card            | PAN Card                | GOVT_ID     |
| aadhaar             | Aadhaar Card            | GOVT_ID     |
| passport            | Passport                | GOVT_ID     |
| driving_licence     | Driving Licence         | GOVT_ID     |
| voter_id            | Voter ID                | GOVT_ID     |
| corporate_id        | Corporate ID            | PRINTABLE   |
| bank_statement      | Bank Statement          | PRINTABLE   |
| loan_statement      | Loan Statement          | PRINTABLE   |
| customer_ledger     | Customer Ledger         | PRINTABLE   |
| insurance_cover     | Insurance Cover Note    | PRINTABLE   |
| utility_bill        | Utility Bill            | PRINTABLE   |
| booking_docket      | Booking Docket          | PRINTABLE   |
| salary_slip         | Salary Slip             | PRINTABLE   |
| signed_declaration  | Signed Declaration      | HANDWRITTEN |
| supporting_document | Supporting Document     | ADDITIONAL  |

### New types added in migration 0007 (this plan)

| document_type_key   | display_name            | category    |
|---------------------|-------------------------|-------------|
| booking_form        | Booking Form            | HANDWRITTEN |
| dealer_receipt      | Dealer Receipt          | PRINTABLE   |
| bank_statement_extract | Bank Statement Extract | PRINTABLE  |
| upi_transaction     | UPI Transaction         | ADDITIONAL  |
| delivery_order_cover| Delivery Order Cover    | PRINTABLE   |
| upi_screenshot      | UPI Screenshot          | ADDITIONAL  |

Note: `insurance_cover` already exists — only its schema file is new.

---

## Sub-tasks

---

### T1 — Dependency + settings swap

**Status:** [ ] pending

**Intent**
Replace the Azure SDK dependency and env vars with Gemini equivalents.
No functional code changes — only configuration layer.

**Expected outcomes**
- `pyproject.toml` references `google-generativeai>=0.8.0` not `azure-ai-documentintelligence`
- `settings.py` has `docai_gemini_api_key: str = ""` replacing the two Azure fields
- Production safety check updated: when `DI_DOCAI_MOCK=false` in production,
  `DI_DOCAI_GEMINI_API_KEY` must be non-empty
- `python -m compileall -q src tests` passes
- All 108 tests pass (mock path unchanged)

**Todo**
1. In `pyproject.toml`: replace `"azure-ai-documentintelligence>=1.0.0"` with
   `"google-generativeai>=0.8.0"`
2. In `settings.py`: remove `docai_azure_endpoint` and `docai_azure_key`;
   add `docai_gemini_api_key: str = ""`
3. In `settings.py` `safety_rules()`: replace the Azure endpoint check with
   a check that `docai_gemini_api_key` is non-empty when `DI_DOCAI_MOCK=false`
   in production
4. Rename `document_ai/azure_adapter.py` → `document_ai/_azure_adapter_archived.py`
   (underscore prefix — not imported anywhere, not deleted)
5. Run compile check + tests

**Relevant files**
- `backend/pyproject.toml`
- `backend/src/verigence/di/settings.py`
- `backend/src/verigence/di/document_ai/azure_adapter.py` (rename)

---

### T2 — `adapter.py` signature extension

**Status:** [ ] pending

**Intent**
Add `physical_form_type` and `document_type_key` as optional kwargs to the
abstract `extract()` interface and to `MockDocumentAIAdapter.extract()`.
Update `get_document_ai_adapter()` to return `GeminiDocumentAIAdapter`
when `DI_DOCAI_MOCK=false`.

**Expected outcomes**
- `DocumentAIAdapter.extract()` abstract method has two new optional kwargs
  with safe defaults (`physical_form_type="PRINTABLE"`, `document_type_key=None`)
- `MockDocumentAIAdapter.extract()` accepts both and ignores them — behaviour
  unchanged
- `get_document_ai_adapter()` imports `GeminiDocumentAIAdapter` from
  `document_ai.gemini_adapter` when mock is off (gemini_adapter.py does not
  exist yet — this import is in an `if not mock` branch, so CI is safe)
- All 108 tests pass

**Todo**
1. In `adapter.py`, add `physical_form_type: str = "PRINTABLE"` and
   `document_type_key: str | None = None` to both the abstract `extract()`
   signature and `MockDocumentAIAdapter.extract()` signature
2. In `get_document_ai_adapter()`, replace the Azure import+instantiation with:
   ```python
   from verigence.di.document_ai.gemini_adapter import GeminiDocumentAIAdapter
   return GeminiDocumentAIAdapter(api_key=s.docai_gemini_api_key)
   ```
3. Run compile check + tests

**Relevant files**
- `backend/src/verigence/di/document_ai/adapter.py`

---

### T3 — Document Schema Registry

**Status:** [ ] pending

**Intent**
Create the `document_ai/schemas/` package. One Python file per document type,
each containing a single `SchemaDefinition` constant. This package is
provider-neutral — it defines what to extract and how to prompt, not which API.

The registry must cover:
- All 6 new dealer-audit document types
- `insurance_cover` (already in DB, needs schema for Gemini extraction)
- `upi_screenshot` (D16 — already planned, same as upi_transaction schema but
  different key and display name)
- `_fallback` for any unregistered type

**Document type key → display name mapping (enforced)**
Every `document_type_key` in `SCHEMA_REGISTRY` must correspond to an existing
or migration-0007-added row in `document_types`. Keys and display names are:

| Schema file           | document_type_key      | display_name            |
|-----------------------|------------------------|-------------------------|
| booking_form.py       | booking_form           | Booking Form            |
| dealer_receipt.py     | dealer_receipt         | Dealer Receipt          |
| bank_statement.py     | bank_statement_extract | Bank Statement Extract  |
| upi_transaction.py    | upi_transaction        | UPI Transaction         |
| delivery_order.py     | delivery_order_cover   | Delivery Order Cover    |
| insurance_cover.py    | insurance_cover        | Insurance Cover Note    |
| upi_screenshot.py     | upi_screenshot         | UPI Screenshot          |
| _fallback.py          | (fallback — no key)    | (generic)               |

**`base.py` dataclasses (exact — no extras)**

```python
@dataclass(frozen=True)
class FieldSpec:
    key: str
    field_type: str        # "string"|"number"|"date"|"datetime"|"boolean"|"array"
    required: bool
    description: str | None = None
    enum: list[str] | None = None
    normalization: str | None = None  # "indian_currency"|"date_dd_mm_yyyy"|"phone_e164"

@dataclass(frozen=True)
class SchemaDefinition:
    document_type_key: str
    display_name: str       # must match document_types.display_name in DB
    schema_version: str     # e.g. "1.0"
    fields: list[FieldSpec]
    system_prompt: str
    prompt_notes: list[str]
```

`display_name` is stored on `SchemaDefinition` so the registry is
self-documenting and auditable without querying the DB.

**Field specifications per document type**
Implement exactly the fields from `DI_GEMINI_DESIGN_v2.3.md` §9 for each type.
For `insurance_cover`, extract: `insurer_name`, `policy_number`, `policy_type`,
`insured_name`, `insured_vehicle_reg`, `vehicle_make_model`, `premium_amount`,
`sum_insured`, `policy_start_date`, `policy_end_date`, `issue_date`.
For `upi_screenshot`, use the identical fields as `upi_transaction` — same
schema, different key and display name.

**System prompt construction rules**
Each system prompt must:
1. Identify the document type clearly
2. Instruct: return ONLY valid JSON with one key per field
3. Each field value must be `{"value": <extracted or null>, "confidence": "high"|"medium"|"low"}`
4. If a field is not found, return `{"value": null, "confidence": "low"}`
5. Never guess — return null + low confidence rather than an uncertain value
6. Include any document-type-specific instructions (e.g. Indian currency
   normalisation for booking_form, UTR extraction for bank_statement_extract)

**`__init__.py` registry**
```python
SCHEMA_REGISTRY: dict[str, SchemaDefinition] = { ... }

def get_schema(document_type_key: str) -> SchemaDefinition:
    """Return registered schema or fallback. Never raises."""
    return SCHEMA_REGISTRY.get(document_type_key, FALLBACK_SCHEMA)
```

**Expected outcomes**
- `document_ai/schemas/` package with `__init__.py`, `base.py`, 7 schema files,
  `_fallback.py`
- `get_schema("booking_form")` returns `BOOKING_FORM_SCHEMA`
- `get_schema("unknown_type")` returns `FALLBACK_SCHEMA`
- `python -m compileall -q src tests` passes
- All 108 tests pass (registry not yet called by production code)

**Todo**
1. Create `document_ai/schemas/base.py` with `FieldSpec` and `SchemaDefinition`
2. Create `document_ai/schemas/_fallback.py` with `FALLBACK_SCHEMA`
3. Create one schema file per document type (7 files)
4. Create `document_ai/schemas/__init__.py` with `SCHEMA_REGISTRY` + `get_schema()`
5. Run compile check + tests

**Relevant files**
- `backend/src/verigence/di/document_ai/schemas/` (new package — all files new)
- `DI_GEMINI_DESIGN_v2.3.md` §9 (field specifications)

---

### T4 — `gemini_adapter.py` implementation

**Status:** [ ] pending

**Intent**
Implement `GeminiDocumentAIAdapter` — the production Gemini 2.5 Flash adapter.
This is only invoked when `DI_DOCAI_MOCK=false`, so CI remains safe.

**Expected outcomes**
- `GeminiDocumentAIAdapter` implements `DocumentAIAdapter` fully
- `adapter_key` = `"gemini_2_5_flash_v1"`
- `classify()` is pass-through (hint at confidence 100, no Gemini call)
- `extract()`:
  1. Calls `get_schema(document_type_key)` → `SchemaDefinition`
  2. Builds Gemini prompt from schema fields + system_prompt + prompt_notes
  3. Sends document bytes (image or PDF) + prompt to Gemini API
  4. Parses and validates JSON response
  5. On parse failure: retries once; on second failure returns all fields as
     `NOT_FOUND` with `confidence=0` (document reaches `NEEDS_REVIEW`, not crash)
  6. Maps confidence: `"high"→92.00`, `"medium"→70.00`, `"low"→40.00`
  7. Returns `AIInvocationResult` with `FieldResult[]`
- `python -m compileall -q src tests` passes
- All 108 tests pass (adapter not called in mock mode)

**Todo**
1. Create `document_ai/gemini_adapter.py`
2. Implement `GeminiDocumentAIAdapter.__init__(self, api_key: str)`
3. Implement `classify()` as pass-through (copy pattern from archived Azure adapter)
4. Implement `extract()` per the behaviour spec above
5. Add a `_build_prompt()` helper that constructs the user message from
   `SchemaDefinition.fields` (type, required, description, enum)
6. Add a `_parse_response()` helper that validates the JSON and returns
   `list[FieldResult]`; on failure returns the fallback NOT_FOUND list
7. Run compile check + tests

**Relevant files**
- `backend/src/verigence/di/document_ai/gemini_adapter.py` (new)
- `backend/src/verigence/di/document_ai/adapter.py` (interface to implement)
- `backend/src/verigence/di/document_ai/schemas/__init__.py` (get_schema)
- `DI_GEMINI_DESIGN_v2.3.md` §6 (extract() behaviour spec)

---

### T5 — `job_runner.py` Step 10 passthrough

**Status:** [ ] pending

**Intent**
Pass `physical_form_type` and `document_type_key` from the worker's resolved
document state into the `ai_adapter.extract()` call at Step 10.
This is the only change to `job_runner.py`.

**Expected outcomes**
- At Step 10, `physical_form_type` is fetched from `tenant_document_types`
  for the accepted `document_type_id` (already resolved at Step 9)
- `ai_adapter.extract()` is called with both new kwargs
- Mock adapter ignores them — existing tests unaffected
- All 108 tests pass

**Todo**
1. In `_execute_steps()`, after Step 9 resolves `document_type_id`, add a DB
   query to fetch `physical_form_type` from `docintel.tenant_document_types`
   for `(tenant_id, document_type_id)`
2. Also read `document_type_key` from the accepted candidate dict (already
   available as `accepted["document_type_key"]`)
3. Pass both to `ai_adapter.extract(...)` at Step 10:
   `physical_form_type=physical_form_type, document_type_key=document_type_key`
4. Run compile check + tests

**Relevant files**
- `backend/src/verigence/di/workers/job_runner.py` (Steps 9–10 only)

---

### T6 — Migration 0007

**Status:** [ ] pending

**Intent**
Apply additive DB changes: `pg_trgm`, `document_search_index` table,
new seed document types, `requires_processing=true` flip for all existing rows.

No existing table is altered destructively. All changes are additive.

**Expected outcomes**
- `0007_gemini_schema_registry.py` migration file exists
- Migration runs cleanly against Neon: `alembic upgrade head`
- New seed types exist in `document_types` with correct keys and display names
- `document_search_index` table exists with GIN index
- All existing `tenant_document_types` rows have `requires_processing=true`
- All 108 tests pass (migration tested against test DB in CI)

**Todo**
1. Create `alembic/versions/0007_gemini_schema_registry.py`
2. Add `revision = "0007"`, `down_revision = "0006"`
3. `upgrade()`:
   a. `CREATE EXTENSION IF NOT EXISTS pg_trgm`
   b. `CREATE TABLE IF NOT EXISTS docintel.document_search_index` (schema per
      `DI_GEMINI_DESIGN_v2.3.md` §8)
   c. `CREATE INDEX` (GIN on indexed_fields, btree on subject)
   d. Seed 6 new document types using WHERE NOT EXISTS guard (same pattern as
      migration 0005). Exact keys + display names + categories per the table
      in this plan's Context section
   e. `UPDATE docintel.tenant_document_types SET requires_processing = true`
      (D18 — flip all existing rows)
4. `downgrade()`: reverse all changes cleanly
5. Run `alembic upgrade head` against local test DB
6. Run compile check + tests

**Relevant files**
- `backend/alembic/versions/0007_gemini_schema_registry.py` (new)
- `DI_GEMINI_DESIGN_v2.3.md` §8 (document_search_index schema)

---

### T7 — Documentation updates

**Status:** [ ] pending

**Intent**
Update all documentation files to reflect the completed D19–D23 decisions.
No code changes in this sub-task.

**Expected outcomes**
- `DI_DECISIONS.md`: D19–D23 sections added, D13 status updated to superseded
- `SECRETS_CHECKLIST.md`: Azure vars replaced with `DI_DOCAI_GEMINI_API_KEY`
- `DI_MASTER_REFERENCE.md`: Step 9 status → done, provider → Gemini 2.5 Flash,
  secrets table updated, immutable decisions table updated
- `DI_DESIGN_SUMMARY.md`: technology stack row updated
- `PROGRESS.md`: new session record added

**Todo**
1. `DI_DECISIONS.md` — add D19 (provider swap), D20 (schema registry),
   D21 (adapter behaviour), D22 (signature extension), D23 (migration 0007)
   Mark D13 as "SUPERSEDED by D19"
2. `SECRETS_CHECKLIST.md` — replace `DI_DOCAI_AZURE_ENDPOINT` +
   `DI_DOCAI_AZURE_KEY` rows with single `DI_DOCAI_GEMINI_API_KEY` row
3. `DI_MASTER_REFERENCE.md` — update Step 9 row, secrets table, decisions table
4. `DI_DESIGN_SUMMARY.md` — update AI/OCR row in technology stack table
5. `PROGRESS.md` — write new session record for this session

**Relevant files**
- `verigence-di/DI_DECISIONS.md`
- `verigence-di/SECRETS_CHECKLIST.md`
- `verigence-di/DI_MASTER_REFERENCE.md`
- `verigence-di/DI_DESIGN_SUMMARY.md`
- `verigence-di/PROGRESS.md`

---

## Validation — definition of done

After all 7 sub-tasks are complete and before marking Step 9 done:

1. `python -m compileall -q src tests` → clean
2. `pytest` → all tests pass (108+ expected)
3. Manual smoke test with real `DI_DOCAI_GEMINI_API_KEY`:
   - Upload one document (booking form or dealer receipt)
   - Verify document reaches `CONFIRMED`
   - Verify extracted fields are populated in `document_field_values`
   - Verify `processor_invocations.adapter_key = "gemini_2_5_flash_v1"`
4. `PROGRESS.md` updated with smoke test result

---

## What is deferred (not in this plan)

| Item | When |
|---|---|
| Step 9c — worker writes to `document_search_index` | After T6 is applied to Neon |
| Step 9d — `POST /analyse` endpoint (R1–R5) | After Step 9c |
| Step 12 — React PWA ops-ui | Separate track |
| Steps 14–16 — Phase 2 | Phase 2 |
