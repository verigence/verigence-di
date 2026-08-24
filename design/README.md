# Verigence DI — Design Documents

**Active baseline: v2.4 with additive post-baseline decisions**

This folder contains the authoritative design documents for Verigence Document Intelligence.

## Reading order (start of every session)

1. `../DI_DECISIONS.md` — **READ FIRST** — every locked design decision agreed in conversation
2. `../DI_MASTER_REFERENCE.md` — document map, step status, session rules
3. `../DI_DESIGN_SUMMARY.md` — 5-minute visual overview (diagrams, lifecycle, stack)
4. `../PROGRESS.md` — current step detail and blockers
5. Relevant spec file from this folder only if implementing that specific component

## Active design documents

| File | Governs |
|---|---|
| `DI_ARCHITECTURE_v2.2.md` | Fixed principles, component boundaries, core flow, WhatsApp flow |
| `DI_LLD_v2.2.md` | Component contracts, intake steps, worker steps, scoring, error handling |
| `DI_DATA_MODEL_v2.2.md` | Every DB entity, relationships, state machines |
| `DI_POSTGRESQL_SCHEMA_v2.2.sql` | Canonical baseline DDL — table/column naming reference |
| `DI_OPENAPI_v2.2.yaml` | Baselined API operations and schemas; additive post-baseline APIs are documented separately |
| `DI_SECURITY_RBAC_v2.2.md` | RBAC / JWT claim contract |
| `DI_RBAC_v2.2.yaml` | Machine-readable RBAC definitions |
| `DI_ERROR_CATALOG_v2.2.md` | Stable error codes, HTTP status, retryability |
| `DI_ERROR_CATALOG_v2.2.yaml` | Machine-readable error catalog |
| `DI_CLASSIFICATION_v2.2.md` | Deterministic candidate-set formation rules |
| `DI_AUDIT_MODEL_v2.2.md` | Entity-scoped hash-chain audit design |
| `DI_BASELINE_AUDIT_REPORT_v2.2.md` | Baseline audit evidence |
| `DI_CONFIGURATION_AUTHORING_v2.4.md` | **Additive AI-assisted admin authoring: sample → Gemini proposal → review → test → approve → publish/retire** |
| `DI_EVIDENCE_LOCALIZATION_v2.4.md` | **Additive field source localization: page + normalized bounding box for responsive human review, including safe PDF fallback** |
| `BASELINE_MANIFEST.md` | Full manifest of baseline design artefacts |
| `CHANGED_FILES_v2.2.md` | Historical delta from v2.1 → v2.2 |

## Important: design documents vs locked decisions

The v2.2 documents remain the original baseline artefacts. Decisions agreed after baseline are recorded in `../DI_DECISIONS.md` and additive design notes such as `DI_CONFIGURATION_AUTHORING_v2.4.md` and `DI_EVIDENCE_LOCALIZATION_v2.4.md`. Those later decisions take precedence where explicitly stated; they do not silently rewrite unrelated baseline contracts.

Current implementation principles relevant to configuration authoring and evidence review:
- runtime `documentTypeKey` remains caller-supplied; automatic classification is deferred;
- Gemini is used behind the DI API only;
- AI can propose configuration but cannot approve, publish, or write directly to DI tables;
- missing/uncertain values are not guessed or derived;
- positional evidence is optional metadata and is never guessed; invalid or uncertain boxes are discarded rather than repaired;
- field localization applies to all current document types, with particular value for handwritten documents;
- PDFs request the same page/box metadata but fall back safely to page-only or no localization until measured PDF box reliability is established;
- existing upload/extraction/analyse contracts remain unchanged and the existing `/fields` response is extended only with optional `pageNo`/`evidenceRegion` properties;
- current custom authoring scope is tenant-level because project-level Extraction Profile scope does not exist in the present DI data model.

## Archive

The `archive/` subfolder contains superseded historical versions. Do not use them for current implementation decisions unless a current document explicitly references them.
