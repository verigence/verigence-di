# Verigence Document Intelligence - Technology and Hosting Baseline

**Baseline:** 2.0  
**Status:** BASELINED  
**Goal:** startup-cost optimized, open-source first where operationally sensible, vendor neutral.

## 1. Application stack

### Backend

- Python 3.x
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- OpenAPI 3.1

Python contains reusable platform capabilities, adapters and approved generic rule implementations. Document-specific field lists, requirement lists and quality-rule parameters remain database configuration.

### Frontend

- React + TypeScript responsive PWA where a direct UI is deployed.
- Same functional REST surface for Mobile and Web in Phase 1.
- Mobile/browser camera capture may be used where available.
- A consuming system may use only REST and provide its own UI.

### Relational database

- PostgreSQL
- dedicated `docintel` schema
- Row-Level Security for Tenant isolation
- PostgreSQL row locking for work claiming and audit-chain serialization
- JSONB only for bounded extensible metadata/configuration such as rule parameters, evidence regions, diagnostics and the Tenant Quality Policy.

### Object storage

Provider-neutral `StorageAdapter` supporting:

- streaming write;
- streaming read;
- metadata/existence check;
- retention-authorized delete.

Provider-neutral key shapes are defined by Verigence rather than a cloud service. A reference implementation may use S3-compatible or equivalent object storage, but no provider-specific bucket/container URL appears in public/domain contracts.

### Image/PDF handling

- safe image/PDF decoders/parsers;
- OpenCV-compatible deterministic image measurements may implement approved quality rules;
- preprocessing produces derived artifacts and never overwrites original evidence.

### OCR / Vision / GenAI

- providers sit behind `DocumentAIAdapter`;
- classification/extraction use one canonical domain contract;
- provider confidence is deterministically normalized to Verigence 0-100 before domain scoring;
- provider choice can change without changing REST contracts, PostgreSQL business schema or Extraction Profiles.

AI does not decide deterministic lifecycle/integrity/verification-threshold rules.

### Background processing

- PostgreSQL `processing_jobs`
- workers claim due jobs transactionally with `FOR UPDATE SKIP LOCKED`
- INITIAL and one EOD_RETRY attempt are DB-constrained
- no external broker/event bus in Phase 1.

### Scheduling

- lightweight scheduler service/process;
- Tenant timezone and EOD time are configuration;
- one automatic EOD retry for retryable first processing failure.

### WhatsApp

- separate adapter boundary for provider webhook authentication/signature verification, media download and payload translation;
- Tenant route resolution occurs before tenant-owned Document creation;
- core module consumes a canonical internal intake request.

## 2. Logical deployables

1. REST API service
2. Processing worker service
3. EOD/reconciliation scheduler
4. WhatsApp adapter
5. Web/PWA assets where needed
6. PostgreSQL
7. object storage implementation

The WhatsApp adapter may share the API process initially to reduce cost, while remaining a distinct code/module boundary.

## 3. Internal module boundaries

Recommended Python packages/interfaces:

- `domain` - state machines/value objects/scoring rules
- `api` - REST schemas/controllers
- `application` - intake/query/verification/configuration use cases
- `repositories` - PostgreSQL persistence interfaces
- `storage` - `StorageAdapter`
- `document_ai` - `DocumentAIAdapter`
- `quality` - approved deterministic quality-rule implementations
- `rules` - approved normalizer/validator implementations
- `whatsapp` - canonical adapter interface
- `workers` - job claiming/processing
- `scheduler` - EOD/reconciliation
- `audit` - canonical event hashing/chain append

Document-specific extraction definitions do not belong in source code.

## 4. Environments

- Local developer
- DEV/UAT
- Production

Production uses separate credentials and database/object-storage namespaces from non-production.

Tenant configuration must pass activation validation before production intake is enabled.

## 5. Security technology baseline

- OIDC/JWT-compatible authentication adapter
- application RBAC
- registered-device enforcement for configured roles
- PostgreSQL RLS with `SET LOCAL app.tenant_id`
- authorized service-mediated content retrieval
- hash-chained append-only audit events
- secrets supplied by deployment secret management rather than database profile tables
- sensitive document contents excluded from normal logs.

Phase 1 intentionally does not mask data after authorized retrieval, per product decision.

## 6. Cost/scale posture

Start simple:

- PostgreSQL-backed queue instead of dedicated broker;
- in-process cache of immutable published profiles;
- stateless API/worker replicas;
- binary evidence outside PostgreSQL;
- no external workflow engine inside standalone Document Intelligence;
- no outbound event infrastructure until measured need justifies it.

## 7. Vendor-neutrality acceptance test

The baseline is vendor neutral when:

- changing object storage changes only StorageAdapter/configuration;
- changing OCR/Vision provider changes only adapter/configuration;
- changing hosting platform does not change public API/domain model;
- Phase 1 does not depend on cloud-native queue/event services;
- PostgreSQL DDL contains no AWS/Azure/GCP-specific datatype/resource dependency.
