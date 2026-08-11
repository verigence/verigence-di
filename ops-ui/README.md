# ops-ui — Verigence DI Operator Interface

React 18 + TypeScript + Vite PWA — scaffold placeholder.

Full implementation in Step 12 (after API is complete).

## Planned pages

- **Upload** — create Subject, upload document, track status
- **Subject View** — completeness view, documents, confidence scores, HV status
- **Verification Queue** — MANDATORY/NOT_VERIFIED documents for human review
- **Exceptions** — subject and tenant-wide exception lists
- **Configuration** — Document Types, Extraction Profiles, Requirement Profiles, Tenant Settings

## API client

TypeScript client auto-generated from `DI_OPENAPI_v2.1.yaml` using `@hey-api/openapi-ts`.
No hand-written fetch wrappers.

## Auth

Clerk React provider. JWT attached automatically to every API call.
