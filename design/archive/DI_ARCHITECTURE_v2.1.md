# Verigence Document Intelligence - High-Level Architecture

**Baseline:** 2.1  
**Date:** 2026-08-11  
**Status:** BASELINED FOR IMPLEMENTATION  
**Scope:** Standalone Document Intelligence only.  
**Hosting:** Vendor neutral.

## 1. Purpose

Verigence Document Intelligence is a standalone system. It owns its Tenant-scoped Subject Registry, document evidence, configuration, processing state, extraction lineage, human verification state and audit history. No pre-existing business system is required for runtime operation. Generic external entity links are optional metadata only.

It accepts evidence from Mobile, Web/PC, API and WhatsApp; preserves original bytes; validates integrity and fitness; classifies the evidence; extracts database-configured fields; normalizes and deterministically validates values; calculates a 0-100 confidence score; derives Human Verification Status as OPTIONAL or MANDATORY; and exposes Tenant + Subject centric REST enquiries.

## 2. Fixed architecture principles

1. Verigence owns a lightweight Subject Registry.
2. Primary discovery is `tenant_id + subject_id`.
3. PostgreSQL is the transactional store using dedicated `docintel` schema.
4. Binary evidence is stored through vendor-neutral `StorageAdapter`.
5. Requirement and Extraction Profiles are versioned database configuration.
6. Deterministic integrity/lifecycle rules remain deterministic.
7. OCR/Vision/GenAI is behind `DocumentAIAdapter`.
8. Original evidence is immutable from the application perspective.
9. Every confirmed image/document has `confidence_score` 0-100.
10. `confidence_score > 90.00` => OPTIONAL; `<= 90.00` => MANDATORY.
11. Human verification completion is separate: NOT_VERIFIED / VERIFIED.
12. Phase 1 uses REST enquiries and PostgreSQL-backed jobs; no outbound event bus.
13. One `X-Correlation-ID` traces one execution chain across API, worker and AI adapter.
14. No vendor-specific tracing product is required.

## 3. Components

### Channels
Mobile/Web, API clients and WhatsApp. Future channels are adapters.

### Access/API
Authentication, RBAC, registered-device policy, correlation middleware, native Subject Registry APIs, Subject-centric Document APIs, configuration, verification and operations APIs.

### Subject Registry
Minimal internal identity for evidence grouping: server-generated Subject UUID, type, optional display name, status and identifiers. It is not a CRM.

### Intake/Storage
Binary streaming, SHA-256, MIME/signature/parser checks, deterministic quality checks, immutable original artifact and optional derived artifacts.

### Processing
PostgreSQL jobs, classification, profile resolution, provider-neutral extraction, normalization, deterministic validation, confidence scoring and one EOD retry for retryable first failure.

### Query/Verification
Subject completeness, exceptions, upload quality, verification queue and human-correction lineage.

### Audit/Observability
Hash-chained audit events, structured logs, metrics and one end-to-end correlation ID. Provider request IDs remain separate.

## 4. Correlation contract

- Request may supply `X-Correlation-ID`.
- Allowed characters: `A-Z a-z 0-9 . _ : -`; maximum 128.
- If absent, Verigence generates a UUID.
- Every HTTP response returns the correlation ID.
- Initial chain propagates the same value through Document -> Processing Job -> Processing Run -> Processor Invocation -> audit/log context.
- `provider_request_id` is provider lineage, not the Verigence correlation ID.
- EOD retry is a new technical execution and receives a new correlation ID while remaining linked to the same Document/history.
- No mandatory Jaeger/Zipkin/X-Ray/Application Insights/Datadog-style product is part of the architecture.

## 5. Core flow

```text
Mobile/Web/API -> Auth/RBAC -> Subject Registry validation
                  |
                  v
          Document Intake -- correlation_id --> StorageAdapter -> Object Storage
                  |
                  v
        Integrity + Quality Gate
         | bad              | FIT
         v                  v
 NOT_FIT/CORRUPT/     PostgreSQL Job
 UPLOAD_FAILED              |
                            v
                     Processing Worker
                      |            |
                      v            v
                 Config/Rules   DocumentAIAdapter -> OCR/Vision Provider
                      \            /
                       v          v
                    Normalize + Validate + Score
                              |
                              v
                     PROCESSED + CONFIRMED
                              |
                              v
                     Human Verification
                     when performed/required
```

## 6. WhatsApp

Tenant routing happens before Subject resolution. Unknown Tenant routes go to system quarantine. Resolved Tenant intake uses a SYSTEM actor. Sender identity is provenance, not automatic Subject identity. Unassigned documents can be processed and later attached to a Verigence Subject. The same correlation token follows webhook -> intake -> worker -> provider invocation.

## 7. Vendor-neutral deployment

Logical deployables: REST API, worker, scheduler/reconciliation process, WhatsApp adapter, optional Web/PWA, PostgreSQL, object storage implementation and configured OCR/Vision adapter. Changing hosting/cloud provider must not change public REST/domain/database contracts.
