# Verigence DI — UC02 Excel Master Administration Alignment

**Status:** UC02 DESIGN ALIGNMENT — OWNER DECISION CONFIRMED  
**Date:** 2026-08-21  
**Repository:** `verigence/verigence-di`  
**Branch:** `dev`  
**Applies to:** `DI_DECISIONS.md`, `design/DI_ARCHITECTURE_v2.3.md`, `design/DI_LLD_v2.3.md`, `design/DI_DATA_MODEL_v2.3.md`  
**Related authority:** `docs/UC02_ADMIN_OPERATION_ALIGNMENT.md`, Audit Core `docs/AUDIT_CORE_UC02_MASTER_RESOLUTION_ALIGNMENT.md`

> This is a narrow UC02 design amendment. It adds Excel as an additional administration path for selected DI-owned configuration domains. It does not authorize code, migration, SQL or machine-readable OpenAPI changes.

## 1. Confirmed scope

For UC02 Project Masters, the following DI-owned domains support Excel administration **in addition to** their existing form/API administration:

- Document Types;
- Extraction Profiles;
- Requirement Profiles.

The native DI APIs and lifecycle rules remain valid. Excel is an additional controlled input channel, not a replacement source of truth.

Tenant Settings / Retention Policies and Quality configuration are not newly made Excel-driven by this decision.

## 2. Authority boundary

DI remains authoritative for DI-owned configuration.

Audit Core may expose the Project Masters UI and orchestrate the import experience, but it must not persist a second authoritative copy of DI configuration.

For a human administrative import, the original Security-issued SuperAdmin human JWT is propagated to the DI administrative boundary in accordance with D29. A `ServiceIntegration` identity must not replace the human administrator on a human-admin-only configuration operation.

## 3. Administration descriptor

The DI master/configuration descriptor surfaced to Audit Core must identify at least:

```text
masterKey
displayName
administrationModes = [FORM, EXCEL] for the three confirmed domains
template/version reference
lifecycle/version summary
whether an approved WEF/effective-date concept exists
```

The descriptor must be derived from DI's existing configuration catalogue/lifecycle. UC02 does not invent new DI business fields.

## 4. Excel import lifecycle

The controlled Excel path is:

```text
download/use DI-owned template
 -> upload .xlsx
 -> create import/staging operation
 -> parse rows
 -> validate structure, references and domain rules
 -> return parsed preview plus errors/warnings
 -> explicit SuperAdmin confirmation
 -> apply confirmed data into the existing DI DRAFT/version lifecycle
 -> publish separately where the existing DI domain requires publication
```

Upload alone does not mutate a published configuration.

A failed or partially valid workbook remains staging/import state until explicitly corrected/replaced/confirmed according to the eventual API design.

## 5. Domain-specific lifecycle preservation

### Document Types

Excel may create/update the draft/configurable representation allowed by the existing Document Type lifecycle. It must not silently reinterpret an existing stable document-type key.

### Extraction Profiles

Excel maps to the existing Extraction Profile version model and field/rule configuration. Published/retired versions remain immutable according to the current DI design.

The Python schema-registry authority established by D25 is not silently removed by UC02. The eventual implementation design must reconcile Excel-imported Extraction Profile configuration with that existing authority/consistency contract rather than creating a second contradictory definition.

### Requirement Profiles

Excel maps to the existing Requirement Profile draft/version/item model. Publication and explicit Subject assignment semantics remain unchanged unless separately approved.

## 6. WEF rule

Excel support does not make all DI configuration effective-dated.

- where an owning DI domain has an approved WEF/Valid-From concept, the value must be explicitly supplied and must not be server-defaulted;
- where no approved WEF concept exists, the import preserves the existing version/publish lifecycle and does not invent a WEF column merely because Excel is used.

## 7. Import reliability and audit

The implementation design must provide enough state to support:

- idempotent retry after browser/network timeout;
- file/template version identification;
- parsed-row preview;
- row-level validation errors/warnings;
- explicit confirmation actor/time;
- mapping from import/staging operation to resulting DI draft/version IDs;
- authoritative DI audit events without logging workbook secrets or sensitive document data.

Exact table names, route names and workbook columns are intentionally not invented by this design amendment.

## 8. Status

The owner decision is closed for Phase 1:

```text
Document Types       -> FORM + EXCEL
Extraction Profiles  -> FORM + EXCEL
Requirement Profiles -> FORM + EXCEL
```

Tenant Settings / Retention Policies and Quality configuration remain under their current administration model pending any later explicit decision.