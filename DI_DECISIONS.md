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
