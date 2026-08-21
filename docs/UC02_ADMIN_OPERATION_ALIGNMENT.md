# Verigence DI — UC02 Administrative Operation Alignment

**Status:** UC02 DESIGN ALIGNMENT — OWNER DECISIONS CONFIRMED  
**Date:** 2026-08-21  
**Repository:** `verigence/verigence-di`  
**Branch:** `dev`  
**Related authority:** `DI_DECISIONS.md`, `DI_MASTER_REFERENCE.md`, `docs/SECURITY_AUTHORIZATION_ALIGNMENT_INCREMENT_I.md`

> This document is a narrow UC02 alignment amendment. It does not supersede DI's generic document-processing design except where explicitly stated for UC02 administration. Any storage-path change must still be recorded as a new append-only decision in `DI_DECISIONS.md` before implementation.

## 1. Human administrative actor rule

UC02 keeps the browser behind Audit Core.

When Audit Core invokes a DI **administrative** operation on behalf of SuperAdmin — including Project/Tenant purge/reset or module-owned configuration administration — Audit Core passes the same Security-issued human Bearer token/identity through to DI.

DI must authorize that human actor using the Security authorization model applicable to the endpoint. Audit Core must not replace the human administrator with a `ServiceIntegration` token for a human-admin-only DI operation.

`ServiceIntegration` remains appropriate for normal non-administrative Audit Core → DI document processing/integration calls.

## 2. Phase-1 Project/Tenant purge required for UC02 rollback

UC02 Phase 1 requires an internal/admin Project/Tenant purge capability because a Project may need to be hard-deleted and rebuilt even after activation.

DI must provide an idempotent, resumable administrative purge/status contract that can remove the Project/Tenant-owned DI state required by the approved deletion contract, including object-storage content before final metadata removal.

Required properties:

- human SuperAdmin authorization;
- ServiceIntegration rejected if the purge endpoint is classified human-admin-only;
- idempotent retry after timeout/partial failure;
- exact object keys retained until object deletion succeeds;
- active processing/retry work is stopped/drained or made purge-safe;
- zero-state verification is available to the Audit Core orchestrator;
- canonical Security Tenant is not deleted by DI.

The exact route/response schema is not invented here and must be added to the DI API/design before implementation.

## 3. Storage hierarchy change remains a separate locked decision

Current locked D5 uses Tenant → Subject → Documents object keys.

UC02 requires Audit Core-originated vehicle-audit documents to follow trusted business context:

`Project → Dealer → Dealer Outlet → Customer → Documents`

Before code changes, add a new append-only `DI_DECISIONS.md` entry that supersedes D5 for this Audit Core-originated path. The browser must never author object-storage paths directly.

## 4. Optional Google Maps data is not a DI concern

Google Place ID / Outlet map coordinates are owned by Audit Core Project landscape data. DI must not become the system of record for Google Places metadata merely to construct storage keys.
