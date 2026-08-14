# Verigence Document Intelligence - Data Model

**Baseline:** 2.1  
**Status:** BASELINED FOR IMPLEMENTATION  
**Database:** PostgreSQL `docintel` schema

## 1. Identity

- Tenant is the isolation boundary.
- Subject is owned by Verigence and uses a server-generated UUID.
- Primary discovery is Tenant + Subject.
- Document IDs identify actual uploaded evidence only.

## 2. Main entities

### Tenant / access
`tenant_settings`, `actors`, `registered_devices`, `retention_policies`.

### `subjects`
Lightweight standalone registry: Tenant, Subject UUID, PERSON/ORGANIZATION/OTHER, optional display name, ACTIVE/INACTIVE, creator and timestamps. It groups evidence and is not a CRM.

`subject_identifiers` and `channel_identities` support deterministic matching to the Verigence Subject.

### Requirement configuration
`document_requirement_profiles`, `document_requirement_profile_items`, `subject_requirement_assignments`. Missing evidence is derived; no fake Document row exists.

### Extraction configuration
`document_types`, `canonical_fields`, rule catalogs, `extraction_profiles`, `extraction_profile_fields` and rule mappings. Document-specific field lists are data configuration, not Python constants.

### `documents`
Actual uploaded image/document with Tenant, nullable Subject only for unresolved WhatsApp, source/uploader provenance, timestamps, MIME/bytes/SHA-256, Upload/Process/Confirm states, confidence score, threshold snapshot, Human Verification Status, verification state, replacement/retention state and initial `correlation_id`.

### Evidence
`document_artifacts`, `document_quality_results`. Original artifacts are immutable from the application perspective.

### Processing
`processing_jobs`, `processing_runs`, `processor_invocations`, `document_classifications`, `extracted_facts`, `validation_results`, `document_field_values`.

Jobs/runs/invocations retain `correlation_id`. Processor invocation also retains provider-native `provider_request_id`.

### Human verification
`human_verifications`; HUMAN accepted-value versions link to the verification action. Machine facts and machine confidence remain immutable.

### Optional external links
`entity_links` stores generic outside references and creates no runtime dependency.

### WhatsApp/reliability/audit
`whatsapp_routes`, `integration_intake_events`, `system_intake_quarantine`, `idempotency_records`, Tenant/system audit chains. Intake/quarantine/audit retain correlation IDs.

## 3. Relationship

```text
Tenant
 |- Actors / Devices
 |- Subjects
 |   |- Identifiers / Channel Mappings
 |   |- Requirement Profile Assignment
 |   `- Documents
 |       |- Artifacts / Quality Results
 |       |- Processing Jobs -> Runs -> Provider Invocations
 |       |- Classifications / Facts / Validations
 |       |- Accepted Values
 |       |- Human Verification
 |       `- Optional Entity Links
 |- Configuration
 `- Audit Chain
```

## 4. Correlation lineage

```text
HTTP X-Correlation-ID
 -> documents.correlation_id
 -> processing_jobs.correlation_id
 -> processing_runs.correlation_id
 -> processor_invocations.correlation_id
 -> audit_events.correlation_id
```

WhatsApp also records it on intake/quarantine. EOD retry gets a new correlation ID because it is a new execution, while Document and Processing history keep the business linkage.

## 5. State invariants

- NOT_FIT/CORRUPT/UPLOAD_FAILED never enter AI.
- CONFIRMED requires FIT + PROCESSED + confidence + 90.00 threshold snapshot + OPTIONAL/MANDATORY.
- score >90 => OPTIONAL; score <=90 => MANDATORY.
- verification completion remains separate.
- first retryable failure => RETRY_PENDING; one EOD retry; second failure => FAILED/NOT_CONFIRMED.
- supported evidence outside requirement profile is ADDITIONAL.
- human correction never rewrites machine facts/confidence.
