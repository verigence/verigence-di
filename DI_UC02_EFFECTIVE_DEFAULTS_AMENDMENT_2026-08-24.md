# DI UC02 Effective Defaults / Project Lifecycle Amendment

**Date:** 2026-08-24  
**Status:** OWNER-APPROVED — supersedes conflicting UC02 readiness/admin assumptions  
**Scope:** DI behavior surfaced through UC02 Project Administration and consumed by UC03

## 1. Effective DI configuration, not tenant-only visibility

DI already provisions every globally active Document Type into a new Tenant through `tenant_document_types`. DI also owns globally published baseline Extraction Profiles for production document types such as Booking Form, PAN and Aadhaar.

UC02 Project Administration must therefore expose the **effective** configuration for a Tenant, not only rows physically owned by that Tenant.

For Project Administration:

- a globally owned Document Type is effective when it is `ACTIVE` and active in that Tenant's `tenant_document_types` mapping;
- a globally owned Extraction Profile is effective when it is `PUBLISHED` for a Document Type active for the Tenant;
- such rows are returned with provenance `configurationSource = VERIGENCE_DEFAULT` and `inherited = true`;
- tenant/Project-owned rows are returned with `configurationSource = PROJECT_CUSTOM` and `inherited = false`.

The purpose is visibility and inheritance. The global records are **not copied into every Tenant** merely to make the UC02 screen or Readiness green.

## 2. Use as-is / customize

A Project Admin may use inherited Verigence defaults as-is.

When different document types or extraction fields are required, customization follows the existing DI version lifecycle and creates Tenant/Project-specific configuration. Global published baseline records remain immutable.

The full DI Test Bench catalogue is not provisioned into every Project. Only effective production configuration is surfaced in UC02.

## 3. Requirement Profiles are optional

DI Requirement Profiles remain an available advanced DI capability, but they are **not a mandatory UC02 or UC03 prerequisite**.

Audit Core owns which evidence/documents are required for a Journey through its versioned `document_requirement_profile`. UC03 Booking/Delivery requirements are instantiated from that Audit Core model.

Therefore:

- do not create a synthetic default DI Requirement Profile for a new Project;
- do not require a DI Requirement Profile for Project activation;
- do not use DI Requirement Profile state to decide UC03 Journey evidence completeness.

This avoids duplicating business requirement ownership inside generic Document Intelligence.

## 4. Readiness treatment

DI provisioning/configuration remains visible in Project Readiness but is a **warning**, not an activation blocker.

If effective inherited Document Types and Extraction Profiles are available, the preferred message is:

> Using Verigence default Document Intelligence configuration. Customize it if this Project requires different document types or extraction fields.

If DI cannot be verified or customization is incomplete, the condition remains visible as `WARNING`/`PENDING` or `WARNING`/`FAIL`; it does not independently prevent Project activation.

Project validity and the Security Tenant lifecycle remain the technical activation gates outside DI.

## 5. Whole-Project hard-delete participation

Owner approval on 2026-08-24 permits whole-Project hard delete only when Audit Core confirms **Journey count = 0**. Audit Core owns and re-checks that gate.

When the orchestrator invokes DI Project cleanup, DI must:

1. remove Project/Tenant-owned document object-storage artifacts;
2. remove Tenant-scoped operational/configuration rows;
3. remove Tenant-owned Extraction Profiles and Document Types;
4. remove Tenant provisioning/settings/retention/document-type links;
5. preserve every globally owned Verigence Document Type, Canonical Field and Extraction Profile.

The DI Project purge endpoint is SuperAdmin-only and idempotent/retry-safe at the orchestration boundary. It does not decide whether the Project is eligible for deletion; the zero-Journey rule is enforced by Audit Core before DI cleanup is called.

The narrower provisioning-compensation DELETE remains separate: it exists only to compensate failed new-Project provisioning and continues to refuse compensation after operational document data exists.

## 6. Regression obligations

CI must cover at least:

- newly provisioned Tenant sees inherited `ACTIVE` global Document Types as `VERIGENCE_DEFAULT`;
- newly provisioned Tenant sees inherited `PUBLISHED` global Extraction Profiles as `VERIGENCE_DEFAULT`;
- no DI Requirement Profile is required for a newly provisioned Project;
- Project purge removes Tenant-owned state;
- Project purge preserves global Verigence defaults.
