# Verigence Document Intelligence — Design Amendment v2.3
# Gemini 2.5 Flash + Document Schema Registry

**Status:** PROPOSED — awaiting sign-off before implementation  
**Supersedes decisions:** D13 (Azure → Gemini), D18 (all-scan — retained), D19 (new)  
**New decisions:** D19, D20, D21, D22, D23  
**Baseline in force:** 2.2 (unchanged — this document amends Step 9 only)  
**Author session:** 2026-08-19

---

## 1. Purpose

This document records the agreed design changes required to implement Step 9
(AI/OCR extraction) using **Gemini 2.5 Flash** instead of Azure Document
Intelligence, and to introduce a **Document Schema Registry** that makes the
system cleanly extensible as new document types are added over time.

Nothing in this document changes the Baseline 2.2 architecture, data model,
API contract, auth, audit, or infrastructure. The changes are confined to:

- The `document_ai/` package (provider swap + new schema registry sub-package)
- `settings.py` (env var names only)
- `pyproject.toml` (dependency swap)
- `workers/job_runner.py` (Step 10 signature passthrough — one call site)
- Migration 0007 (DB additions, no structural changes to existing tables)

---

## 2. What does NOT change

The following are explicitly out of scope and must not be touched:

| Component | Reason unchanged |
|---|---|
| `application/intake.py` | Upload, classification hint resolution, and processing-job creation are unchanged. Document type is already resolved at upload time. |
| `DocumentAIAdapter` abstract interface | The `classify()` + `extract()` contract remains. Concrete implementations change, not the interface. |
| `MockDocumentAIAdapter` | Unchanged. CI uses `DI_DOCAI_MOCK=true`. All 108 tests must continue to pass. |
| `workers/job_runner.py` Steps 1–9, 11–17 | Only Step 10 call site changes — two extra kwargs added to the `extract()` call. |
| All REST API endpoints | Zero changes to request/response contracts. |
| DB tables (existing) | No column renames, no dropped tables, no changed constraints. |
| Audit, RBAC, scoring, rules | Completely unchanged. |
| Baseline 2.2 design documents | Not modified. This document is the amendment layer. |

---

## 3. Why Gemini 2.5 Flash (D19 rationale)

Azure Document Intelligence is the right long-term provider for structured
prebuilt models (bank statements, ID documents). However, Azure account
creation is currently blocked. Gemini 2.5 Flash is selected as the production
provider for the following reasons grounded in the actual document types in use:

| Factor | Assessment |
|---|---|
| **Multimodal** | Accepts image bytes and PDFs directly — no separate OCR step |
| **Indian documents** | Tested on Aadhaar, PAN, handwritten forms, UPI screenshots |
| **Multi-page PDF** | Gemini 2.5 Flash handles multi-page PDFs natively in one API call |
| **Flexible output** | Returns structured JSON to any schema we define via prompt |
| **Free tier** | Generous quota; no credit card block |
| **Extensibility** | New document type = new schema file + new prompt. No SDK model routing table to maintain. |

**Known risks and mitigations:**

| Risk | Mitigation |
|---|---|
| Non-deterministic output | Pydantic response validation + retry on parse failure |
| Hallucination on numeric fields | Prompt instructs: return `null` + confidence `low` rather than guess |
| Rate limits on free tier | Worker already has poll interval; retryable error path handles 429 |
| Data privacy (documents sent to Google) | Acceptable for current stage; documented decision |

**Design rule:** The provider can be swapped again by implementing a new
concrete `DocumentAIAdapter` subclass. The schema registry, worker pipeline,
and DB model are provider-neutral.

---

## 4. Decision D19 — Switch OCR/AI provider to Gemini 2.5 Flash

**Status: PROPOSED**

### Change

| Before (D13) | After (D19) |
|---|---|
| Azure Document Intelligence | Gemini 2.5 Flash (`gemini-2.5-flash` model) |
| `azure-ai-documentintelligence>=1.0.0` | `google-generativeai>=0.8.0` |
| `DI_DOCAI_AZURE_ENDPOINT` | `DI_DOCAI_GEMINI_API_KEY` |
| `DI_DOCAI_AZURE_KEY` | _(removed)_ |
| `document_ai/azure_adapter.py` | `document_ai/gemini_adapter.py` (new) |

### What stays the same

- `DI_DOCAI_MOCK=true` → `MockDocumentAIAdapter` (unchanged)
- `DI_DOCAI_MOCK=false` → new `GeminiDocumentAIAdapter`
- `classify()` → still pass-through at confidence 100 using `document_type_hint_key`
- `extract()` → returns the same `FieldResult[]` structure, populated from Gemini response

### File actions

| File | Action |
|---|---|
| `document_ai/azure_adapter.py` | Rename to `document_ai/_azure_adapter_archived.py` — preserved, not deleted, not imported anywhere |
| `document_ai/gemini_adapter.py` | **New** — production implementation |
| `pyproject.toml` | Swap dependency |
| `settings.py` | Swap env vars |
| `document_ai/adapter.py` | Update `get_document_ai_adapter()` only |

---

## 5. Decision D20 — Document Schema Registry

**Status: PROPOSED**

### Problem

The current system stores extraction field lists in the database
(`extraction_profile_fields`). That works for flat field lists but does not
capture:

- Field types and required flags (needed to build a typed Gemini prompt)
- Normalization hints per field (e.g. Indian currency formatting)
- The Gemini system prompt for each document type
- Per-type prompt notes (special instructions for that document's characteristics)

As new document types are added, there must be a single place to define all of
this per type — version-controlled in code, not scattered across DB rows that
are hard to review and diff.

### Design

A new Python package `document_ai/schemas/` is introduced. It is the **single
source of truth for per-document-type extraction behaviour**. It is
provider-neutral — it defines *what* to extract and *how to prompt*, not
which API to call.

```
document_ai/
  schemas/
    __init__.py          Registry: maps document_type_key → SchemaDefinition
    base.py              FieldSpec + SchemaDefinition dataclasses
    booking_form.py      BOOKING_FORM_SCHEMA
    dealer_receipt.py    DEALER_RECEIPT_SCHEMA
    bank_statement.py    BANK_STATEMENT_SCHEMA
    upi_transaction.py   UPI_TRANSACTION_SCHEMA
    delivery_order.py    DELIVERY_ORDER_SCHEMA
    _fallback.py         FALLBACK_SCHEMA — used for any unregistered type
```

### `base.py` types (exact, no extras)

```python
@dataclass(frozen=True)
class FieldSpec:
    key: str                        # matches canonical_field_key in DB
    field_type: str                 # "string" | "number" | "date" | "datetime" | "boolean" | "array"
    required: bool                  # true = absence reduces confidence
    description: str | None = None  # human-readable; included in Gemini prompt
    enum: list[str] | None = None   # allowed values if constrained
    normalization: str | None = None  # hint: "indian_currency" | "date_dd_mm_yyyy" | "phone_e164"

@dataclass(frozen=True)
class SchemaDefinition:
    document_type_key: str   # must match a row in document_types table
    schema_version: str      # e.g. "1.0" — bump when fields change
    fields: list[FieldSpec]
    system_prompt: str       # full Gemini system prompt for this document type
    prompt_notes: list[str]  # extra instructions appended to user message
```

No `ExtractionStrategy`, no extraction modes. Every document type uses full
schema extraction. This can be revisited later without any design change.

### Registry (`__init__.py`)

```python
SCHEMA_REGISTRY: dict[str, SchemaDefinition] = {
    "booking_form": BOOKING_FORM_SCHEMA,
    "dealer_receipt": DEALER_RECEIPT_SCHEMA,
    "bank_statement_extract": BANK_STATEMENT_SCHEMA,
    "upi_transaction": UPI_TRANSACTION_SCHEMA,
    "delivery_order_cover": DELIVERY_ORDER_SCHEMA,
}

def get_schema(document_type_key: str) -> SchemaDefinition:
    """Return registered schema or fallback. Never raises."""
    return SCHEMA_REGISTRY.get(document_type_key, FALLBACK_SCHEMA)
```

### Adding a new document type

1. Create `document_ai/schemas/<new_type>.py` with a `SchemaDefinition`
2. Register it in `SCHEMA_REGISTRY` in `__init__.py`
3. Add a seed row in the next migration (if it's a new global type)

No other code changes required.

### Relationship to existing DB tables

The schema registry does **not** replace `extraction_profile_fields`. It
**augments** it:

| Source | What it provides |
|---|---|
| `extraction_profile_fields` (DB) | `canonical_field_key`, `aliases`, `extraction_instruction`, `score_weight`, `expected`, `enabled` |
| `SchemaDefinition` (code registry) | `field_type`, `required`, `enum`, `normalization`, Gemini `system_prompt`, `prompt_notes` |

The worker at Step 10 loads both: DB profile fields for scoring/storage config,
code registry for the Gemini prompt structure. They are joined on `field_key`.

---

## 6. Decision D21 — GeminiDocumentAIAdapter behaviour

**Status: PROPOSED**

### `classify()` — no change to behaviour

Pass-through. The `document_type_hint_key` supplied at upload is accepted at
confidence 100. No Gemini API call is made during classification. This is
identical to the Azure adapter behaviour (D13).

Rationale: classification is already resolved at upload time by the caller
supplying `documentTypeKey`. Re-classifying with Gemini during the worker run
would be redundant and introduce latency + cost with no benefit.

### `extract()` — new implementation

The adapter receives `artifact_bytes`, `mime_type`, `fields` (from DB profile),
`document_type_key`, and `physical_form_type`.

Execution:

1. Call `get_schema(document_type_key)` → `SchemaDefinition`
2. Build Gemini prompt:
   - System message: `schema.system_prompt`
   - User message: field list with types/required/description/enum + `schema.prompt_notes`
   - Required output format: JSON object with one key per field, each value being `{value, confidence: "high"|"medium"|"low"}`
3. Call Gemini API with document bytes (image or PDF) + prompt
4. Parse and validate JSON response with Pydantic
5. On parse failure: retry once. On second failure: return all fields as
   `FoundStatus.NOT_FOUND` with `confidence=0` so document reaches
   `NEEDS_REVIEW` rather than crashing the worker
6. Map Gemini confidence strings to numeric scores:
   - `"high"` → `Decimal("92.00")`
   - `"medium"` → `Decimal("70.00")`
   - `"low"` → `Decimal("40.00")`
   - field absent in response → `FoundStatus.NOT_FOUND`, `confidence=None`
7. Return `AIInvocationResult` with `FieldResult[]`

### Multi-page PDF handling

Gemini 2.5 Flash accepts multi-page PDFs natively. The full PDF bytes are
passed in one API call. No page splitting is required. This is a significant
simplification vs Azure's per-page model routing.

### `adapter_key`

`"gemini_2_5_flash_v1"` — stored in `processor_invocations.adapter_key` for
lineage. Changing provider means a new `adapter_key` value automatically
appears in the audit trail.

---

## 7. Decision D22 — `extract()` signature extension

**Status: PROPOSED**

The abstract `DocumentAIAdapter.extract()` in `adapter.py` currently lacks
`physical_form_type` and `document_type_key` as parameters. These are needed
by `GeminiDocumentAIAdapter` (and would have been needed by Azure too).

### Changes to `adapter.py`

```python
# Abstract method — add two optional kwargs
@abc.abstractmethod
async def extract(
    self,
    artifact_bytes: bytes,
    mime_type: str,
    fields: list[ExtractionField],
    correlation_id: str | None = None,
    physical_form_type: str = "PRINTABLE",   # NEW — optional, defaults safe
    document_type_key: str | None = None,    # NEW — optional, defaults safe
) -> AIInvocationResult: ...
```

### Changes to `MockDocumentAIAdapter.extract()`

Accepts the two new kwargs and ignores them. Behaviour unchanged. CI stays green.

### Changes to `workers/job_runner.py`

At Step 10, fetch `physical_form_type` from `tenant_document_types` for the
accepted `document_type_id` (already resolved at Step 9). Pass both to
`ai_adapter.extract(...)`.

This is the **only change** to `job_runner.py`. Steps 1–9 and 11–17 are untouched.

---

## 8. Decision D23 — Migration 0007 (DB additions)

**Status: PROPOSED**

Migration 0007 contains only additive DB changes. No existing table is altered
destructively.

### Changes

| Change | Reason |
|---|---|
| `CREATE EXTENSION IF NOT EXISTS pg_trgm` | Required for fuzzy text search in `document_search_index` (D14) |
| New table `docintel.document_search_index` | D14 — cross-document query layer for `POST /analyse` |
| GIN index on `document_search_index.indexed_fields` | D14 — JSONB containment queries |
| Seed: `booking_form` global document type | New dealer audit domain types |
| Seed: `upi_transaction` global document type | New dealer audit domain type |
| Seed: `delivery_order_cover` global document type | New dealer audit domain type |
| Seed: `dealer_receipt` global document type | D16 (moved from 0007 note to actual 0007 migration) |
| Seed: `upi_screenshot` global document type | D16 |
| `UPDATE tenant_document_types SET requires_processing = true` | D18 — flip all existing rows |

### `document_search_index` table schema

```sql
CREATE TABLE docintel.document_search_index (
    tenant_id           varchar(120)    NOT NULL,
    document_id         uuid            NOT NULL,
    subject_id          uuid,
    document_type_key   varchar(120),
    indexed_fields      jsonb           NOT NULL DEFAULT '{}',
    schema_version      varchar(20),
    created_at_utc      timestamptz     NOT NULL DEFAULT now(),
    updated_at_utc      timestamptz     NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, document_id)
);

CREATE INDEX idx_document_search_index_fields
    ON docintel.document_search_index
    USING GIN (indexed_fields);

CREATE INDEX idx_document_search_index_subject
    ON docintel.document_search_index (tenant_id, subject_id);
```

### Worker write path (Step 9c — separate sub-task, not in this migration)

After Step 17 (CONFIRMED), the worker upserts into `document_search_index`.
This is a future sub-task; the table must exist first (this migration).

---

## 9. Document schemas — five initial schemas

All five schemas below are implemented as separate files in
`document_ai/schemas/`. They are derived directly from the domain specification
agreed in conversation. Each schema file contains exactly one
`SchemaDefinition` instance exported as a module-level constant.

### 9.1 `booking_form` — Booking Form

**Characteristics:** handwritten or printed, variable dealer layouts
(Mahindra-style tabular, Hyundai-style price breakdown), often phone photos
that are skewed or low-contrast.

**Special prompt instructions:**
- Handwritten values override printed placeholder text
- If a numeric field is genuinely illegible, return `null` + confidence `"low"`
- Currency values in Indian numbering (e.g. `"8,58,600"`) → normalize to plain
  integer `858600`
- `total_price`: use the grand total row if explicitly present; otherwise
  compute as visible sum of charges minus deductions and note this in the
  `_extraction_notes` field

**Fields:**

| key | type | required |
|---|---|---|
| dealer_name | string | true |
| dealer_branch | string | false |
| booking_reference_number | string | false |
| booking_date | date | true |
| customer_name | string | true |
| customer_phone | string | false |
| customer_email | string | false |
| customer_address | string | false |
| vehicle_model | string | true |
| vehicle_variant | string | false |
| vehicle_color | string | false |
| sales_person | string | false |
| ex_showroom_price | number | false |
| insurance_amount | number | false |
| road_tax_registration | number | false |
| accessories_cost | number | false |
| other_charges | number | false |
| total_price | number | true |
| booking_amount_paid | number | true |
| balance_amount | number | false |
| mode_of_payment | string (enum) | false |
| payment_reference_no | string | false |
| expected_delivery | string | false |

`mode_of_payment` enum: `cash`, `cheque`, `demand_draft`, `neft_rtgs`, `payorder`

---

### 9.2 `dealer_receipt` — Dealer Receipt

**Characteristics:** clean, printed, tabular. Highest-confidence document type.
`receipt_no` and `payment_reference_no` are the primary join keys for R2
reconciliation against bank/UPI records.

**Special prompt instructions:**
- `payment_reference_no` is the cheque/DD/RTGS/UTR number — extract it even if
  embedded in a longer remarks field
- `receipt_date` may include time; extract as `DD-MM-YYYY HH:mm:ss` if present

**Fields:**

| key | type | required |
|---|---|---|
| dealer_name | string | true |
| dealer_gstin | string | false |
| customer_id | string | false |
| customer_name | string | true |
| customer_phone | string | false |
| receipt_no | string | true |
| receipt_date | datetime | true |
| receipt_amount | number | true |
| mode_of_payment | string (enum) | true |
| payment_reference_no | string | false |
| payment_reference_date | date | false |
| bank_name | string | false |
| bank_location | string | false |
| remarks | string | false |
| amount_in_words | string | false |

`mode_of_payment` enum: `cash`, `cheque`, `rtgs`, `neft`, `upi`, `card`, `dd`

---

### 9.3 `bank_statement_extract` — Bank Statement Row

**Characteristics:** screenshot or scanned excerpt of a bank statement
transaction table. May include manual annotations (highlighting, circles,
underlines) indicating a verified match.

**Special prompt instructions:**
- `description` strings pack reference numbers inline, e.g.
  `"BY TRANSFER-NEFT*ICIC0SF0002*IN42613257395659*DIBYENDU KUNDU*B-"`
- Extract the numeric/alphanumeric reference after the NEFT/RTGS/IMPS/UTR
  marker into `reference_no` — this is the PRIMARY JOIN KEY against
  `dealer_receipt.payment_reference_no`
- If highlighted text (yellow, circled, underlined) is visible, set
  `manually_flagged: true`

**Fields:**

| key | type | required |
|---|---|---|
| transaction_date | date | true |
| value_date | date | false |
| description | string | true |
| reference_no | string | false |
| counterparty_name | string | false |
| debit_amount | number | false |
| credit_amount | number | false |
| running_balance | number | false |
| manually_flagged | boolean | false |

---

### 9.4 `upi_transaction` — UPI Transaction Screenshot

**Characteristics:** mobile payment app screenshot (PhonePe, GPay, Paytm).
`transaction_id` is the PRIMARY join key. `utr_no` is the SECONDARY join key
that matches `bank_statement_extract.reference_no`.

**Fields:**

| key | type | required |
|---|---|---|
| app_name | string | false |
| status | string (enum) | true |
| amount | number | true |
| transaction_datetime | datetime | true |
| transaction_id | string | true |
| utr_no | string | false |
| payer_name | string | false |
| payer_masked_phone | string | false |
| payee_store_name | string | false |
| payee_id | string | false |
| payment_method | string (enum) | false |

`status` enum: `completed`, `pending`, `failed`
`payment_method` enum: `qr`, `upi_id`, `card`

---

### 9.5 `delivery_order_cover` — Delivery Order Cover Page

**Characteristics:** wrapper or cover page of a multi-page delivery order PDF.
Subsequent pages will be other document types (receipts, checklists, feedback
forms) and will be uploaded separately or classified independently. This schema
captures only the cover page fields.

`embedded_document_types` is a list of document type keys found within the
same PDF — populated by the uploader or operator, not by extraction.

**Fields:**

| key | type | required |
|---|---|---|
| customer_name | string | true |
| vehicle_model | string | false |
| chassis_no | string | false |
| engine_no | string | false |
| delivery_date | date | false |
| delivered_by | string | false |
| embedded_document_types | array | false |

---

### 9.6 `_fallback` — Generic Schema

Used when `document_type_key` has no registered schema. Extracts all fields
provided by the DB extraction profile using a generic OCR prompt. Returns raw
text values with confidence `"medium"` for any field found.

This ensures the pipeline never fails due to a missing schema registration —
it degrades gracefully to generic extraction.

---

## 10. Reconciliation rules — updated R1–R5

The five reconciliation rules agreed in conversation supersede the placeholder
R1–R7 in D17. The `POST /analyse` endpoint (D15) implements these rules.

| Rule | Key | Description |
|---|---|---|
| R1 | RECEIPT_SUM_MATCHES_BOOKING | `SUM(dealer_receipt.receipt_amount WHERE customer_id = X)` must equal `booking_form.total_price - booking_form.balance_amount`. Tolerance: ±₹100. |
| R2 | PAYMENT_REFERENCE_VERIFIED | For every `dealer_receipt.payment_reference_no`, a matching `bank_statement_extract.reference_no` OR `upi_transaction.utr_no` must exist for the same subject. Unmatched receipt = "payment not verified" flag. |
| R3 | NO_UNRECEIPTED_BANK_CREDIT | For every `bank_statement_extract` credit row tagged to a known customer (by `counterparty_name` fuzzy match), a matching `dealer_receipt.receipt_no` must exist. Unmatched credit = "unreceipted payment" audit risk flag. |
| R4 | DELIVERY_WITH_ZERO_BALANCE | `delivery_order_cover.delivery_date` must be null/absent OR `booking_form.balance_amount == 0` at time of delivery. Violation = "delivered with balance outstanding" flag. |
| R5 | VEHICLE_CONSISTENCY | `vehicle_model` / `chassis_no` must be consistent across `booking_form`, `dealer_receipt.remarks` (free text), and `delivery_order_cover`. Flag mismatches. |

These replace the previous R1–R7 placeholder rules in D17. Step 9d implements
all five.

---

## 11. Complete file change manifest

### Files changed (edit)

| File | What changes | What stays the same |
|---|---|---|
| `pyproject.toml` | `azure-ai-documentintelligence` → `google-generativeai>=0.8.0` | Everything else |
| `settings.py` | `docai_azure_endpoint` + `docai_azure_key` → `docai_gemini_api_key: str = ""` | All other settings |
| `document_ai/adapter.py` | `extract()` abstract signature: add `physical_form_type` + `document_type_key` kwargs. `MockDocumentAIAdapter.extract()`: accept + ignore new kwargs. `get_document_ai_adapter()`: import + return `GeminiDocumentAIAdapter` | `classify()` contract, `ClassificationCandidate`, `FieldResult`, `AIInvocationResult`, `ExtractionField` — all unchanged |
| `workers/job_runner.py` | Step 10: fetch `physical_form_type` from `tenant_document_types` for accepted `document_type_id`; pass `physical_form_type` + `document_type_key` to `ai_adapter.extract()` | Steps 1–9, 11–17 — untouched |
| `DI_DECISIONS.md` | Add D19–D23 sections | D1–D18 unchanged |
| `SECRETS_CHECKLIST.md` | `DI_DOCAI_AZURE_ENDPOINT` + `DI_DOCAI_AZURE_KEY` → `DI_DOCAI_GEMINI_API_KEY` | All other variables |
| `DI_MASTER_REFERENCE.md` | Step 9 status, provider name, secrets table row, immutable decisions table row | All other sections |
| `DI_DESIGN_SUMMARY.md` | Technology stack row: Azure DI → Gemini 2.5 Flash | All other sections |
| `PROGRESS.md` | New session record | All prior session records |

### Files created (new)

| File | Purpose |
|---|---|
| `document_ai/gemini_adapter.py` | `GeminiDocumentAIAdapter` — production implementation |
| `document_ai/schemas/__init__.py` | `SCHEMA_REGISTRY` + `get_schema()` |
| `document_ai/schemas/base.py` | `FieldSpec` + `SchemaDefinition` dataclasses |
| `document_ai/schemas/booking_form.py` | `BOOKING_FORM_SCHEMA` |
| `document_ai/schemas/dealer_receipt.py` | `DEALER_RECEIPT_SCHEMA` |
| `document_ai/schemas/bank_statement.py` | `BANK_STATEMENT_SCHEMA` |
| `document_ai/schemas/upi_transaction.py` | `UPI_TRANSACTION_SCHEMA` |
| `document_ai/schemas/delivery_order.py` | `DELIVERY_ORDER_SCHEMA` |
| `document_ai/schemas/_fallback.py` | `FALLBACK_SCHEMA` |
| `backend/alembic/versions/0007_*.py` | Migration 0007 per §8 |

### Files renamed (preserved)

| From | To | Reason |
|---|---|---|
| `document_ai/azure_adapter.py` | `document_ai/_azure_adapter_archived.py` | Preserved for reference; underscore prefix excludes from import discovery; not referenced by any production code |

### Files NOT changed

`intake.py`, `quality/`, `auth/`, `audit/`, `rules/`, `repositories/`,
`storage/`, `scheduler/`, `domain/`, `api/`, `main.py`, `errors.py`,
all test files.

---

## 12. What is explicitly deferred (not in this amendment)

| Item | Deferred to |
|---|---|
| Step 9c — worker writes to `document_search_index` | After migration 0007 is applied |
| Step 9d — `POST /analyse` endpoint with R1–R5 | After Step 9c |
| Step 12 — React PWA ops-ui | Separate track |
| Steps 14–16 — WhatsApp, device enforcement, idempotency | Phase 2 |

---

## 13. Implementation sub-tasks (ordered)

When this design is approved, implementation proceeds in this order.
Each sub-task is independently reviewable before the next starts.

| # | Sub-task | Files | CI safe? |
|---|---|---|---|
| T1 | Dependency + settings swap | `pyproject.toml`, `settings.py` | ✅ Yes — mock path unchanged |
| T2 | `adapter.py` signature extension + `get_document_ai_adapter()` update | `document_ai/adapter.py` | ✅ Yes — mock adapter ignores new kwargs |
| T3 | Schema registry — `base.py` + all 5 schemas + `_fallback.py` + `__init__.py` | `document_ai/schemas/` (new package) | ✅ Yes — not called yet |
| T4 | `gemini_adapter.py` full implementation | `document_ai/gemini_adapter.py` | ✅ Yes — only invoked when `DI_DOCAI_MOCK=false` |
| T5 | `job_runner.py` Step 10 passthrough | `workers/job_runner.py` | ✅ Yes — mock ignores new kwargs |
| T6 | Migration 0007 | `alembic/versions/0007_*.py` | ✅ Yes — additive only |
| T7 | Documentation updates | `DI_DECISIONS.md`, `SECRETS_CHECKLIST.md`, `DI_MASTER_REFERENCE.md`, `DI_DESIGN_SUMMARY.md`, `PROGRESS.md` | N/A |

**Validation after all sub-tasks:**
- `python -m compileall -q src tests` — must pass
- `pytest` — all 108+ tests must pass
- `DI_DOCAI_MOCK=false` + real `DI_DOCAI_GEMINI_API_KEY` — manual smoke test: upload one document, verify it reaches CONFIRMED with extracted fields

---

## 14. Extensibility contract — adding a new document type

This is the most important long-term property of this design.

Adding a new document type in the future requires exactly these steps:

1. **Code** — create `document_ai/schemas/<new_type_key>.py` with a
   `SchemaDefinition` constant
2. **Registry** — add one entry to `SCHEMA_REGISTRY` in
   `document_ai/schemas/__init__.py`
3. **Migration** — add a seed row to `document_types` in the next migration
4. **DB config** — via existing API: create `canonical_fields` + an
   `extraction_profile` for the new type

No changes to `gemini_adapter.py`, `job_runner.py`, `intake.py`,
`settings.py`, or any other file.

---

## 15. Open questions — resolved

| Question | Resolution |
|---|---|
| One document = one type? | Yes. One upload = one `document_type_key`. Multi-page PDFs are sent as-is; Gemini handles them natively. No page-splitting at intake or worker level. |
| Page-level classification? | Not needed. Classification is resolved at upload time from the caller-supplied `documentTypeKey` hint. The worker uses the accepted classification from Step 8. No additional Gemini classification call. |
| Extraction modes (FULL vs LIGHTWEIGHT)? | Removed. All document types use full schema extraction. Revisit only if cost becomes a concern. |
| Delivery order sub-pages? | Each page type (receipt, checklist, feedback) is uploaded as a separate document with its own `document_type_key`. The `delivery_order_cover` schema covers only the cover page; `embedded_document_types` is a list field that can reference the other types. |

---

*End of DI_GEMINI_DESIGN_v2.3.md*
