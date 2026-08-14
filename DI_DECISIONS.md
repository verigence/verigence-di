# Verigence DI — Locked Design Decisions

**READ THIS FIRST — before DI_MASTER_REFERENCE.md, before any code.**

This file is append-only. Every design decision agreed in conversation must be
recorded here before any code is written. If it is not in this file, it is not
decided. Do not implement anything that contradicts an entry here without
explicitly superseding it with a new dated entry.

---

## D1 — Document Type Master Catalogue (2026-08-17)

### Decision
A global `document_types` table holds the master catalogue of all possible
document kinds. These rows are system-seeded (owner_tenant_id IS NULL) and
visible to every tenant. Tenants may also define custom types
(owner_tenant_id = their tenant_id).

### Global seed document types (agreed list)

| document_type_key     | display_name           | category      |
|-----------------------|------------------------|---------------|
| pan_card              | PAN Card               | GOVT_ID       |
| aadhaar               | Aadhaar Card           | GOVT_ID       |
| passport              | Passport               | GOVT_ID       |
| driving_licence       | Driving Licence        | GOVT_ID       |
| voter_id              | Voter ID               | GOVT_ID       |
| corporate_id          | Corporate ID           | PRINTABLE     |
| bank_statement        | Bank Statement         | PRINTABLE     |
| loan_statement        | Loan Statement         | PRINTABLE     |
| customer_ledger       | Customer Ledger        | PRINTABLE     |
| insurance_cover       | Insurance Cover Note   | PRINTABLE     |
| utility_bill          | Utility Bill           | PRINTABLE     |
| booking_docket        | Booking Docket         | PRINTABLE     |
| salary_slip           | Salary Slip            | PRINTABLE     |
| signed_declaration    | Signed Declaration     | HANDWRITTEN   |
| supporting_document   | Supporting Document    | ADDITIONAL    |

### Status: AGREED — implemented in migration 0004

---

## D2 — Physical Form Type lives on tenant_document_types (2026-08-17)

### Decision
`physical_form_type` is NOT a column on the global `document_types` table.
It is a per-tenant configuration on a new `tenant_document_types` table.

Rationale: the same document type (e.g. driving_licence) may be classified
differently by different tenants for their workflow purposes.

### Four form types (exhaustive, no others)

| Value       | Meaning                                      | AI processing |
|-------------|----------------------------------------------|---------------|
| GOVT_ID     | Government-issued identity document          | YES           |
| PRINTABLE   | Machine-printed document (statement, bill)   | YES           |
| HANDWRITTEN | Handwritten or signed document               | YES           |
| ADDITIONAL  | Supporting/supplementary — no extraction     | NO            |

### Rule: ADDITIONAL always means requires_processing = false
There are no exceptions. ADDITIONAL documents are stored but never sent
to Document AI.

### Status: AGREED — implemented in migration 0004

---

## D3 — tenant_document_types table (2026-08-17)

### Decision
New table `docintel.tenant_document_types` maps which document types a given
tenant uses, and how each is configured.

Columns:
- tenant_id + document_type_id (composite PK)
- physical_form_type (GOVT_ID | PRINTABLE | HANDWRITTEN | ADDITIONAL)
- requires_processing BOOLEAN — derived from form type, overridable
- is_active BOOLEAN DEFAULT true
- display_order INTEGER DEFAULT 100

### Tenant onboarding (provision_tenant_document_types)
Called automatically in tenant_session() after provision_tenant() and
provision_retention_policy(). Seeds all global ACTIVE document_types into
tenant_document_types with their default physical_form_type.
Safe to call multiple times (ON CONFLICT DO NOTHING).

### Status: AGREED — implemented in migration 0004 + tenants.py

---

## D4 — Upload API: documentTypeKey resolution (2026-08-17)

### Decision
On document upload, documentTypeKey is resolved against tenant_document_types:

- If documentTypeKey is provided AND found in tenant_document_types:
    → use that row's physical_form_type and requires_processing
    → snapshot both values onto documents row at upload time
- If documentTypeKey is absent OR not found in tenant_document_types:
    → physical_form_type = 'ADDITIONAL'
    → requires_processing = false
    → NO error — silently treated as additional

### Worker behaviour
- requires_processing = true  → full pipeline (classify → extract → score)
- requires_processing = false → skip Document AI; set processingStatus=PROCESSED,
                                confirmationStatus=CONFIRMED, confidence_score=NULL

### Snapshot rule
physical_form_type and requires_processing are snapshotted onto the documents
row at upload time. Subsequent changes to tenant_document_types do NOT
retroactively affect already-uploaded documents.

### Status: AGREED — implemented in intake.py

---

## D5 — R2 Storage Path (2026-08-17)

### Decision
Storage path format:

  {tenant_slug}/subjects/{subject_slug}-{subject_id_short}/
    documents/{physical_form_type_folder}/{doc_id_short}_{sanitised_filename}

Where:
  tenant_slug          = tenant_id lowercased, non-alphanum → hyphen, max 40 chars
  subject_slug         = subjects.display_name slugified, max 30 chars
  subject_id_short     = first 8 hex chars of subject_id UUID
  physical_form_type_folder = one of: govt_id | printable | handwritten | additional
  doc_id_short         = first 8 hex chars of document_id UUID
  sanitised_filename   = original_filename with path separators stripped,
                         spaces → underscores, max 80 chars, extension preserved

### Concrete example
  acme-bank/subjects/john-smith-a3f2b1c0/documents/govt_id/d74194e2_passport.pdf

### No artifact_id in path
artifact_id is generated internally and stored in document_artifacts but
never appears in the R2 object key. One ORIGINAL artifact per document in
Phase 1.

### Fallback filename (when original_filename is absent)
  {doc_id_short}_{physical_form_type}.{ext_from_mime}
  e.g. d74194e2_govt_id.pdf

### subject_id used in path (not subject name alone)
Prevents collision when two subjects have identical display names.

### Status: AGREED — implemented in storage/adapter.py + intake.py

---

## D6 — category column on document_types (2026-08-17)

### Decision
The existing free-text `category varchar(100)` column on `document_types`
is repurposed to hold the DEFAULT physical_form_type for seeding purposes
(GOVT_ID | PRINTABLE | HANDWRITTEN | ADDITIONAL).
It is NOT dropped — removing columns from a live table requires care.
Application code does not read it at runtime; it is metadata only.

### Status: AGREED

---

## D7 — requires_processing default derivation (2026-08-17)

### Decision
When inserting into tenant_document_types, requires_processing defaults as:
  GOVT_ID     → true
  PRINTABLE   → true
  HANDWRITTEN → true
  ADDITIONAL  → false (always — no override permitted at this level)

### Status: AGREED — enforced in provision_tenant_document_types()

---

## D8 — Universal API Response Envelope (2026-08-18)

### Decision
Every API response (success and error) is wrapped in a universal JSON envelope:

```json
{
  "errorCode": "000",
  "errorMessage": "string",
  "data": { ... } | null
}
```

Rules:
- `errorCode` and `errorMessage` are ALWAYS present — never absent
- `errorCode: "000"` means success
- `errorCode: "E001"` ... `"E010"` (and beyond) means failure
- `data` contains the payload on success; `null` on failure
- HTTP status codes are preserved (201 for create, 200 for get, 404 for not found etc.)
  — Option B: correct HTTP status codes + error envelope

### Error code catalogue

| errorCode | Meaning                                        | HTTP status | Retryable |
|-----------|------------------------------------------------|-------------|-----------|
| 000       | Success                                        | 200 / 201   | —         |
| E001      | Quality check failed — file not fit            | 200         | No        |
| E002      | File corrupt or unreadable                     | 200         | No        |
| E003      | Storage error — safe to retry                  | 500         | Yes       |
| E004      | Subject not found                              | 404         | No        |
| E005      | Document not found                             | 404         | No        |
| E006      | Unsupported file type                          | 400         | No        |
| E007      | File too large                                 | 400         | No        |
| E008      | Document not yet confirmed (fields unavailable)| 409         | No        |
| E009      | Unauthorised — missing or invalid token        | 401         | No        |
| E010      | Forbidden — insufficient permissions           | 403         | No        |

### errorMessage for success
- Upload success: `"File Uploaded Successfully"`
- All other success: `"Success"`

### Status: AGREED — to be implemented

---

## D9 — Upload API request simplification (2026-08-18)

### Decision
Upload request form fields reduced to the minimum:

**Kept:**
- `file` — the document bytes (required)
- `documentTypeKey` — matches master catalogue key e.g. `"bank_statement"` (optional)

**Removed from request:**
- `sourceChannel` — system derives it internally (see D10)
- `capturedAt` — not required for Phase 1
- `sourceReference` — not required for Phase 1
- `replacesDocumentId` — not required for Phase 1

### Upload response (inside envelope data)
```json
{
  "documentId": "uuid",
  "uploadStatus": "ACCEPTED" | "REJECTED",
  "processingStatus": "PENDING" | "PROCESSING" | "PROCESSED" | "FAILED" | null
}
```

`uploadStatus` replaces the internal 4-value enum (FIT/NOT_FIT/CORRUPT/UPLOAD_FAILED):
- `ACCEPTED` = was FIT internally
- `REJECTED` = was NOT_FIT, CORRUPT, or UPLOAD_FAILED

`processingStatus` public values:
- `PENDING`     = internal NOT_STARTED + RECEIVING + RETRY_PENDING
- `PROCESSING`  = internal PROCESSING
- `PROCESSED`   = internal PROCESSED
- `FAILED`      = internal FAILED
- `null`        = upload was REJECTED (no processing attempted)

### Internal storage
Internal DB columns `upload_status` and `processing_status` keep their full value sets
(FIT/NOT_FIT/CORRUPT/UPLOAD_FAILED and NOT_STARTED/PROCESSING/RETRY_PENDING/PROCESSED/FAILED).
The public-facing simplification happens only at the API response layer.

### Status: AGREED — to be implemented

---

## D10 — sourceChannel made nullable, derived internally (2026-08-18)

### Decision
`source_channel` on `docintel.documents` is made nullable (migration 0006).

**Rationale:** The front-end application is responsible for maintaining channel context.
The DI module does not require it for any processing logic.

**Internal behaviour:**
- Upload via REST API endpoint → `source_channel = NULL` (no longer hardcoded to 'API')
- WhatsApp webhook intake (Phase 2) → `source_channel = 'WHATSAPP'` (set by whatsapp adapter)
- `source_channel` is never returned in any public API response

### Migration required
Migration 0006: `ALTER TABLE docintel.documents ALTER COLUMN source_channel DROP NOT NULL`

### Status: AGREED — to be implemented in migration 0006

---

## D11 — Document GET response shape (2026-08-18)

### Decision
All document GET responses (single + list) return the same slim document object
inside the universal envelope:

```json
{
  "documentId": "uuid",
  "documentTypeKey": "bank_statement" | null,
  "uploadStatus": "ACCEPTED" | "REJECTED",
  "processingStatus": "PENDING" | "PROCESSING" | "PROCESSED" | "FAILED" | null,
  "confirmationStatus": "CONFIRMED" | "PENDING" | "NOT_CONFIRMED" | null,
  "confidenceScore": 94.5 | null,
  "registeredAtUtc": "ISO8601"
}
```

**Fields deliberately excluded from public response:**
- `sourceChannel` — not relevant to caller
- `verificationState`, `contentState`, `humanVerificationStatus`, `verificationThresholdApplied`
- `originalFilename`, `declaredMimeType`, `detectedMimeType`, `fileSizeBytes`, `contentHashSha256`, `pageCount`
- `correlationId`, `processedAtUtc`, `confirmedAtUtc`
- `uploadIssueCode`, `uploadIssueDetail`, `processingFailureCode`
- `duplicateOfDocumentId`, `replacesDocumentId`

These internal fields remain in the DB and are accessible to internal/ops tooling
but are not exposed through the public document API.

### documentTypeKey resolution
Returned from `docintel.document_types.document_type_key` via join on `documents.document_type_id`.
Returns `null` if document type was not resolved at upload time (ADDITIONAL/unknown).

### Status: AGREED — to be implemented

---

## D12 — New document-types summary endpoint (2026-08-18)

### Decision
New endpoint added:

```
GET /v1/tenants/{tenantId}/subjects/{subjectId}/document-types
```

Returns count of documents per documentTypeKey for the given subject.
Counts only ACCEPTED (FIT) uploads — REJECTED documents excluded.

Response (inside envelope):
```json
{
  "subjectId": "uuid",
  "documentTypes": [
    { "documentTypeKey": "bank_statement", "count": 3 },
    { "documentTypeKey": "passport",       "count": 1 }
  ]
}
```

Documents where `document_type_id IS NULL` (uploaded as ADDITIONAL/unknown)
are excluded from this summary — they have no documentTypeKey.

### Status: AGREED — to be implemented

---

## D13 — OCR/AI Provider: Azure Document Intelligence (2026-08-18)

### Decision
Azure Document Intelligence replaces the originally planned Google Document AI.

**Rationale:**
- Single provider (one Azure subscription, one billing account)
- Has prebuilt models for all document types in the catalogue
- Best-in-class handwriting OCR (prebuilt-read) for freeform multi-style handwriting
- 6x cheaper than Google Document AI at target volume (~12,000 docs/month)
- `prebuilt-bankStatement` model returns structured `transactions[]` array
- Indian document coverage (Aadhaar, PAN, bank statements) verified

**Model routing by physical_form_type + document_type_key:**

| Condition | Azure model |
|-----------|-------------|
| GOVT_ID (any) | `prebuilt-idDocument` |
| PRINTABLE — bank_statement, loan_statement, customer_ledger | `prebuilt-bankStatement` |
| PRINTABLE — salary_slip | `prebuilt-payStub` |
| PRINTABLE — insurance_cover, utility_bill, booking_docket | `prebuilt-invoice` |
| PRINTABLE — corporate_id, others | `prebuilt-layout` |
| HANDWRITTEN (any) | `prebuilt-read` |

**Classification strategy:**
AI classification is skipped. The `documentTypeKey` supplied at upload (stored as
`document_type_hint_key`) is treated as the accepted classification.
The `classify()` call returns a pass-through result with the hint key at confidence 100.

**Settings changes (DI_ prefix):**
- Remove: `docai_project_id`, `docai_location`, `docai_processor_id`
- Add: `docai_azure_endpoint` (e.g. `https://<resource>.cognitiveservices.azure.com/`)
- Add: `docai_azure_key` (API key)

**Dependency change:**
- Remove: `google-cloud-documentai`
- Add: `azure-ai-documentintelligence>=1.0.0`

**New file:** `document_ai/azure_adapter.py`
- Implements `DocumentAIAdapter` abstract interface
- `classify()` → pass-through using hint key (no Azure API call)
- `extract()` → calls Azure Document Intelligence, routes model by form type + doc type key

### Status: AGREED — implementation pending (after API contract changes)

---

## D14 — document_search_index table (2026-08-18)

### Decision
A new table `docintel.document_search_index` stores a denormalised, queryable
representation of extracted field values for every processed document.
One row per document, updated after each successful processing run.

### Purpose
Enables cross-document queries (e.g. "find all documents for this subject where
amount = X or UTR contains Y") without joining across extracted_facts +
document_field_values. Required by the `POST /analyse` endpoint (D15).

### Schema (key columns)
- `tenant_id`, `document_id` (PK)
- `subject_id`, `document_type_key`
- `indexed_fields JSONB` — flat key→value map of all extracted canonical fields
- `created_at_utc`, `updated_at_utc`

### Index
- GIN index on `indexed_fields` for JSONB containment queries
- `pg_trgm` extension for fuzzy string search within field values

### Write path
Worker writes to `document_search_index` at Step 17 (after CONFIRMED).
A new `document_search_index` row is upserted (INSERT … ON CONFLICT UPDATE).

### Status: AGREED — implementation pending (Step 9b)

---

## D15 — POST /analyse endpoint (2026-08-18)

### Decision
New endpoint:

```
POST /v1/tenants/{tenantId}/analyse
```

**Request body:**
```json
{ "documentIds": ["uuid", "uuid", ...] }
```

**Purpose:** Load extracted field values for the given document IDs and run
the seven reconciliation rules (D17). Returns a structured findings report
with a summary verdict.

**Authorization:** requires `di.document.read` permission.

**Response** (inside D8 envelope):
```json
{
  "analysedDocuments": 3,
  "findings": [ { "ruleKey": "R1_AMOUNT_MATCH", "result": "PASS", "detail": "..." }, ... ],
  "summary": "RECONCILED" | "DISCREPANCY" | "INSUFFICIENT_DATA"
}
```

### Status: AGREED — implementation pending (Step 9d)

---

## D16 — Two new document types: dealer_receipt and upi_screenshot (2026-08-18)

### Decision
Two new global seed document types are added to the master catalogue:

| document_type_key | display_name       | category  |
|-------------------|--------------------|-----------|
| dealer_receipt    | Dealer Receipt     | PRINTABLE |
| upi_screenshot    | UPI Screenshot     | PRINTABLE |

**Model routing (per D13):**
- `dealer_receipt` → `prebuilt-invoice` (printed receipt with amounts, dates, RTGS ref)
- `upi_screenshot` → `prebuilt-read` (phone screenshot — treated like HANDWRITTEN for OCR)

Added in migration 0007 as INSERT … ON CONFLICT DO NOTHING alongside the
`document_search_index` table.

### Status: AGREED — implementation pending (Step 9c)

---

## D17 — Seven reconciliation rules for POST /analyse (2026-08-18)

### Decision
The `POST /analyse` endpoint (D15) runs seven deterministic reconciliation rules:

| Rule | Key | Description |
|------|-----|-------------|
| R1 | AMOUNT_MATCH | Sum of dealer receipt amounts equals booking docket total |
| R2 | UTR_SUFFIX_MATCH | RTGS reference on receipt is a suffix of the UTR in bank statement |
| R3 | DATE_PROXIMITY | Payment date on receipt is within ±3 days of bank statement transaction date |
| R4 | NAME_MATCH | Payee/payer name on receipt matches subject display name (fuzzy, ≥80% similarity) |
| R5 | TOTAL_CHECK | All receipts for a subject sum to the expected booking total (±₹1 tolerance) |
| R6 | DATE_SEQUENCE | Delivery order date is after the latest receipt date |
| R7 | DUPLICATE_DETECTION | No two receipts for the same subject have identical amount + date + RTGS reference |

**UTR suffix matching rule (R2):**
Indian RTGS/NEFT UTR numbers (e.g. `KKBK0007395659`) often contain the
last 6–9 digits of the dealer-facing RTGS reference (e.g. `395659`).
The rule checks: `utr_number.endswith(rtgs_reference)` after stripping
leading zeros from the receipt reference.

### Status: AGREED — implementation pending (Step 9d)

---

## D18 — All documents scanned on upload regardless of type (2026-08-19)

### Decision
**Every uploaded document is sent to Azure Document Intelligence for OCR/field
extraction, regardless of `physical_form_type` or `document_type_key`.**

This supersedes the D4 rule that `ADDITIONAL` documents skip processing.

### Rationale
- The client needs extraction results even from documents originally classified
  as supplementary/supporting (e.g. WhatsApp photos, miscellaneous receipts).
- Eliminating the ADDITIONAL skip path simplifies the worker pipeline.
- Azure Document Intelligence is cheap enough (~$0.01/page) that the marginal
  cost of scanning "supporting" documents is acceptable.

### What changes

| Before (D4 rule) | After (D18 rule) |
|---|---|
| `ADDITIONAL` documents set `requires_processing = false` | All documents set `requires_processing = true` |
| Worker skips ADDITIONAL documents | Worker processes every document |
| `processing_status` for ADDITIONAL = PROCESSED immediately at upload | `processing_status` starts NOT_STARTED; worker drives it to PROCESSED |

### What does NOT change
- `physical_form_type` column still exists and is still snapshotted at upload
- `document_type_key` is still resolved and snapshotted
- D2 `ADDITIONAL` form type label is retained (it means "no extraction profile required",
  not "skip OCR") — use `prebuilt-read` model for ADDITIONAL documents
- D13 model routing table gains a new row: `ADDITIONAL → prebuilt-read`

### Updated model routing table (D13 + D18)

| Condition | Azure model |
|-----------|-------------|
| GOVT_ID (any) | `prebuilt-idDocument` |
| PRINTABLE — bank_statement, loan_statement, customer_ledger | `prebuilt-bankStatement` |
| PRINTABLE — salary_slip | `prebuilt-payStub` |
| PRINTABLE — insurance_cover, utility_bill, booking_docket, dealer_receipt | `prebuilt-invoice` |
| PRINTABLE — corporate_id, others | `prebuilt-layout` |
| HANDWRITTEN (any) | `prebuilt-read` |
| ADDITIONAL (any) | `prebuilt-read` |
| upi_screenshot (any physical_form_type) | `prebuilt-read` |

### Status: AGREED — 2026-08-19


---

## D19 — Switch OCR/AI provider to Gemini 2.5 Flash (2026-08-19)

### Decision
**Gemini 2.5 Flash replaces Azure Document Intelligence as the production
OCR/field extraction provider.** D13 (Azure) is superseded by D19.

### Rationale
- Azure portal account creation blocked (practical blocker)
- Gemini 2.5 Flash accepts image bytes and PDFs directly — no separate OCR step
- Handles multi-page PDFs natively in one API call
- Generous free tier — no credit card block for getting started
- New document type = new schema file + one registry entry; no SDK model routing table to maintain
- Provider can be swapped again by implementing a new `DocumentAIAdapter` subclass

### Changes

| Before (D13) | After (D19) |
|---|---|
| Azure Document Intelligence | Gemini 2.5 Flash (`gemini-2.5-flash`) |
| `azure-ai-documentintelligence>=1.0.0` | `google-generativeai>=0.8.0` |
| `DI_DOCAI_AZURE_ENDPOINT` | `DI_DOCAI_GEMINI_API_KEY` |
| `DI_DOCAI_AZURE_KEY` | _(removed)_ |
| `document_ai/azure_adapter.py` | `document_ai/gemini_adapter.py` |

### What stays the same
- `DI_DOCAI_MOCK=true` → `MockDocumentAIAdapter` (unchanged — CI safe)
- `classify()` → pass-through at confidence 100 (no AI call)
- All `FieldResult[]` / `AIInvocationResult` data structures unchanged
- `adapter_key` = `"gemini_2_5_flash_v1"` (stored in `processor_invocations`)

### Status: AGREED — implemented 2026-08-19

---

## D20 — Document Schema Registry (2026-08-19)

### Decision
A new Python package `document_ai/schemas/` is the single source of truth for
per-document-type extraction behaviour. One file per document type.

### Design
```
document_ai/schemas/
  __init__.py          SCHEMA_REGISTRY + get_schema()
  base.py              FieldSpec + SchemaDefinition dataclasses
  booking_form.py      BOOKING_FORM_SCHEMA
  dealer_receipt.py    DEALER_RECEIPT_SCHEMA
  bank_statement.py    BANK_STATEMENT_SCHEMA
  upi_transaction.py   UPI_TRANSACTION_SCHEMA
  delivery_order.py    DELIVERY_ORDER_SCHEMA
  insurance_cover.py   INSURANCE_COVER_SCHEMA
  upi_screenshot.py    UPI_SCREENSHOT_SCHEMA
  _fallback.py         FALLBACK_SCHEMA (used for unregistered types)
```

### Key rule
Every `document_type_key` in `SCHEMA_REGISTRY` must correspond to a row in
`docintel.document_types`. `display_name` on `SchemaDefinition` must match
`document_types.display_name`.

### Extensibility contract
Adding a new document type = create one schema file + register one line in `__init__.py`.
No changes to adapter, worker, settings, or migrations beyond the seed row.

### Status: AGREED — implemented 2026-08-19

---

## D21 — GeminiDocumentAIAdapter behaviour (2026-08-19)

### Decision

**classify():** Pass-through. Hint key accepted at confidence 100. No Gemini API call.

**extract():**
1. `get_schema(document_type_key)` → `SchemaDefinition`
2. Build prompt from schema fields + system_prompt + prompt_notes
3. Call Gemini with document bytes (image or PDF, multi-page supported natively)
4. Parse and validate JSON response
5. On parse failure: retry once; on second failure return all fields as `NOT_FOUND`
   with confidence=0 (document reaches `NEEDS_REVIEW`, pipeline does not crash)
6. Map confidence: `"high"→92.00`, `"medium"→70.00`, `"low"→40.00`
7. Return `AIInvocationResult` with `FieldResult[]`

### Status: AGREED — implemented 2026-08-19

---

## D22 — extract() signature extension (2026-08-19)

### Decision
`DocumentAIAdapter.extract()` abstract method gains two optional kwargs:
- `physical_form_type: str = "PRINTABLE"`
- `document_type_key: str | None = None`

`MockDocumentAIAdapter.extract()` accepts both and ignores them — CI behaviour unchanged.

`job_runner.py` at Step 10 fetches `physical_form_type` from `tenant_document_types`
for the accepted `document_type_id` and passes both to `ai_adapter.extract()`.

### Status: AGREED — implemented 2026-08-19

---

## D23 — Migration 0007 contents (2026-08-19)

### Decision
Migration 0007 (`0007_gemini_schema_registry.py`) contains:

1. `CREATE EXTENSION IF NOT EXISTS pg_trgm` (D14 prerequisite)
2. `docintel.document_search_index` table + GIN + btree indexes (D14)
3. New global seed document types:
   - `booking_form` / Booking Form / HANDWRITTEN
   - `dealer_receipt` / Dealer Receipt / PRINTABLE
   - `bank_statement_extract` / Bank Statement Extract / PRINTABLE
   - `upi_transaction` / UPI Transaction / ADDITIONAL
   - `delivery_order_cover` / Delivery Order Cover / PRINTABLE
   - `upi_screenshot` / UPI Screenshot / ADDITIONAL
4. `UPDATE tenant_document_types SET requires_processing = true` (D18 flip)

All changes additive. No existing table altered destructively.

### Status: AGREED — implemented 2026-08-19

---


## D24 — Processing Backout Queue (today's session)

### Problem
During smoke testing, documents were observed getting stuck in the job queue
permanently when processing fails. Two specific stuck states:

1. **`job_status = RUNNING` — worker crash mid-job**: no heartbeat exists; the job
   never self-heals.
2. **`processing_status = RETRY_PENDING` — waiting for EOD**: documents wait up
   to ~24 hours for the EOD Retry Scheduler window; during testing this makes
   the queue visibly blocked.

The EOD Retry Scheduler remains in place for its intended purpose (end-of-day
business retry). The backout queue is a **separate, faster drain** for failed
documents so the active queue stays clean during testing and production.

### Decision

Introduce a dedicated `backout_jobs` table. Any processing job that ends in
failure — whether retryable or non-retryable — is moved to the backout queue
immediately. The document `processing_status` is set to `FAILED` and
`confirmation_status` to `NOT_CONFIRMED` at the same time.

**TTL:** Backout entries expire after **12 hours** (`expires_at_utc`). A
lightweight sweeper (runs every 60 s inside the existing `EODRetryScheduler`
tick) hard-deletes expired rows. No reprocessing happens from the backout queue
— it is a dead-letter store, not a retry mechanism.

**The EOD Retry Scheduler is NOT changed.** It still inserts `EOD_RETRY` jobs
for `RETRY_PENDING` documents. With D24 in place, a document only stays
`RETRY_PENDING` if the operator explicitly decides to keep it retryable (i.e.
does not move it to backout). For the current smoke-testing phase, **all
failures go directly to backout** — the `RETRY_PENDING` path is effectively
bypassed.

### Behaviour contract

| Event | Old behaviour | New behaviour (D24) |
|---|---|---|
| Retryable failure | `processing_status = RETRY_PENDING`, job `FAILED`, wait for EOD | `processing_status = FAILED`, `confirmation_status = NOT_CONFIRMED`, insert backout row |
| Non-retryable failure | `processing_status = FAILED`, `confirmation_status = NOT_CONFIRMED` | Same + insert backout row |
| Worker crash (`RUNNING` stuck) | Stuck forever | Not addressed by D24 — Phase-2 heartbeat improvement |
| Backout TTL expires (12 h) | N/A | Row hard-deleted from `backout_jobs`; document record untouched (already `FAILED`) |

### `backout_jobs` table

```sql
CREATE TABLE docintel.backout_jobs (
    tenant_id           varchar(128)  NOT NULL,
    backout_job_id      uuid          NOT NULL,
    document_id         uuid          NOT NULL,
    processing_job_id   uuid          NOT NULL,   -- FK to the failed processing_jobs row
    processing_run_id   uuid,                     -- FK to the failed processing_runs row (nullable — may not exist if worker crashed before run was created)
    error_class         varchar(20)   NOT NULL
                          CHECK (error_class IN ('RETRYABLE','NON_RETRYABLE')),
    error_code          varchar(120),
    error_detail        text,
    expires_at_utc      timestamptz   NOT NULL,   -- created_at_utc + backout_ttl_hours
    created_at_utc      timestamptz   NOT NULL,
    PRIMARY KEY (tenant_id, backout_job_id),
    UNIQUE (tenant_id, document_id),              -- one backout row per document at any time
    FOREIGN KEY (tenant_id, document_id)
      REFERENCES docintel.documents(tenant_id, document_id),
    FOREIGN KEY (tenant_id, processing_job_id)
      REFERENCES docintel.processing_jobs(tenant_id, processing_job_id)
);

CREATE INDEX ix_backout_jobs_ttl
ON docintel.backout_jobs(expires_at_utc);

CREATE INDEX ix_backout_jobs_document
ON docintel.backout_jobs(tenant_id, document_id);
```

**No change** to `processing_jobs` schema. The `job_type` constraint
`CHECK (job_type IN ('INITIAL','EOD_RETRY'))` and the `attempt_no` constraint
remain untouched. The backout table is a separate, parallel record.

### `DI_BACKOUT_TTL_HOURS` setting

New optional env var `DI_BACKOUT_TTL_HOURS` (default: `12`) controls the TTL.
Parsed as `settings.backout_ttl_hours: int = 12`.

### Sweeper

The sweeper runs inside the existing `EODRetryScheduler._run_eod_check()` loop
every 60 seconds. It executes one bounded delete:

```sql
DELETE FROM docintel.backout_jobs
WHERE expires_at_utc <= NOW();
```

Safe to run on every tick — expired rows are already dead-letter records.

### What does NOT change

- `processing_jobs` schema — untouched
- `EOD_RETRY` path — still present and still fires at EOD for any document left
  in `RETRY_PENDING` state (which under D24 is none during smoke-test phase,
  but the mechanism is preserved for later operational use)
- Document state machine invariant constraints — the DB constraint
  `ck_documents_confirmation_invariants` already permits `FAILED +
  NOT_CONFIRMED` so no schema constraint change is required on `documents`
- All existing error codes — `backout_jobs.error_code` uses values from the
  existing `errors.py` catalogue

### Migration

New migration `0008_backout_queue.py`:
1. `CREATE TABLE docintel.backout_jobs`
2. Two indexes (`ix_backout_jobs_ttl`, `ix_backout_jobs_document`)

### Implementation files

| File | Change |
|---|---|
| `backend/alembic/versions/0008_backout_queue.py` | New migration |
| `backend/src/verigence/di/settings.py` | Add `backout_ttl_hours: int = 12` |
| `backend/src/verigence/di/repositories/backout.py` | New — `insert_backout_job()`, `sweep_expired_backout_jobs()` |
| `backend/src/verigence/di/workers/processor.py` | `_handle_failure()` writes document to `FAILED/NOT_CONFIRMED` and calls `insert_backout_job()` for ALL failures (retryable and non-retryable) |
| `backend/src/verigence/di/scheduler/beat.py` | `_run_eod_check()` calls `sweep_expired_backout_jobs()` on every tick |
| `design/DI_POSTGRESQL_SCHEMA_v2.2.sql` | Add `backout_jobs` table + indexes |
| `design/DI_LLD_v2.2.md` | New §Backout Queue Sweeper section; update §Processing Worker failure path |

### Status: AGREED — design documented; implementation is next step

---
