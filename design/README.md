# Verigence DI — Design Documents

**Active baseline: v2.2**

This folder contains the authoritative design documents for Verigence Document Intelligence.

## Reading order (start of every session)

1. `../DI_DECISIONS.md` — **READ FIRST** — every locked design decision agreed in conversation
2. `../DI_MASTER_REFERENCE.md` — document map, step status, session rules
3. `../DI_DESIGN_SUMMARY.md` — 5-minute visual overview (diagrams, lifecycle, stack)
4. `../PROGRESS.md` — current step detail and blockers
5. Relevant spec file from this folder only if implementing that specific component

## Active v2.2 documents

| File | Governs |
|---|---|
| `DI_ARCHITECTURE_v2.2.md` | Fixed principles, component boundaries, core flow, WhatsApp flow |
| `DI_LLD_v2.2.md` | Component contracts, intake steps, worker steps, scoring, error handling |
| `DI_DATA_MODEL_v2.2.md` | Every DB entity, relationships, state machines |
| `DI_POSTGRESQL_SCHEMA_v2.2.sql` | Canonical DDL — single source of truth for table/column names |
| `DI_OPENAPI_v2.2.yaml` | All API operations, request/response schemas, `x-required-permissions` |
| `DI_SECURITY_RBAC_v2.2.md` | 27 permissions, 8 role bundles, JWT claim contract |
| `DI_RBAC_v2.2.yaml` | Machine-readable RBAC definitions |
| `DI_ERROR_CATALOG_v2.2.md` | Stable error codes, HTTP status, retryability |
| `DI_ERROR_CATALOG_v2.2.yaml` | Machine-readable error catalog |
| `DI_CLASSIFICATION_v2.2.md` | Deterministic candidate-set formation rules |
| `DI_AUDIT_MODEL_v2.2.md` | Entity-scoped hash-chain audit design |
| `DI_BASELINE_AUDIT_REPORT_v2.2.md` | Confirmed: 39/39 checks passed |
| `BASELINE_MANIFEST.md` | Full manifest of all v2.2 design artefacts |
| `CHANGED_FILES_v2.2.md` | Delta from v2.1 → v2.2 |

## Important: design documents vs locked decisions

These documents represent the **Baseline 2.2** design. Any decision agreed
**in conversation after baselineing** is recorded in `../DI_DECISIONS.md` — that
file takes precedence over anything in these docs where there is a conflict.

Known divergences (as of 2026-08-18):
- D8–D12: API contract redesigned (envelope, ACCEPTED/REJECTED, sourceChannel nullable, document-types endpoint)
- D13: Azure Document Intelligence replaces Google Document AI
- D1–D7: tenant_document_types, physical_form_type, R2 path redesign

## Archive

The `archive/` subfolder contains superseded versions (v2.0, v2.1) kept for
historical reference. Do not use these for implementation.
