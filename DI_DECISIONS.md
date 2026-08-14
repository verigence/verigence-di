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
