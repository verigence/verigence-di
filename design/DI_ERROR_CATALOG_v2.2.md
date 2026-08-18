# Verigence Document Intelligence - Error / Problem Code Catalogue

**Baseline:** 2.2  
**Status:** BASELINED  
**Normative machine-readable source:** `api/DI_ERROR_CATALOG_v2.2.yaml`

## Contract

- Error bodies use the OpenAPI `Problem` schema.
- `code` is the stable client decision key. Clients **must not** parse `title` or `detail` for logic.
- Every application error response returns the same `X-Correlation-ID` in the response header and `correlationId` in the body.
- `retryable=true` means a technical retry may be attempted only when the operation is safe/idempotent; it does not override HTTP/idempotency semantics.
- Authentication claim failures use `UNAUTHORIZED`; permission/scope failures use `FORBIDDEN`.
- Processing-run failure codes may use this catalogue where applicable; provider-specific raw error text is never a public client contract.

## Catalogue

| Code | HTTP | Retryable | Category | Meaning | Client action |
|---|---:|---|---|---|---|
| `INVALID_REQUEST` | 400 | No | REQUEST | Request syntax/parameters/body are invalid. | Correct the request; do not retry unchanged. |
| `UNAUTHORIZED` | 401 | No | AUTHENTICATION | JWT is absent, invalid, expired, wrong issuer/audience, or required canonical claims are missing/invalid. | Re-authenticate/obtain a valid token, then retry. |
| `FORBIDDEN` | 403 | No | AUTHORIZATION | Authenticated actor lacks the required permission or Tenant/resource scope. | Do not retry unchanged; request appropriate access. |
| `TENANT_NOT_FOUND` | 404 | No | TENANT | Tenant does not exist or is not visible to the caller. | Correct Tenant context. |
| `TENANT_NOT_READY` | 409 | No | CONFIGURATION | Tenant activation prerequisites are incomplete. | Complete Tenant configuration, then retry. |
| `RETENTION_POLICY_NOT_CONFIGURED` | 409 | No | CONFIGURATION | Required active retention policy is missing. | Configure retention policy, then retry. |
| `DEVICE_NOT_REGISTERED` | 403 | No | AUTHORIZATION | USER token device_id is missing, revoked, or not registered for the actor/Tenant. | Register/use an active device and obtain/refresh token if required. |
| `REQUIREMENT_PROFILE_NOT_ASSIGNED` | 409 | No | CONFIGURATION | An operation requiring a Subject Requirement Profile has no active assignment. | Assign a published Requirement Profile. |
| `REQUIREMENT_PROFILE_NOT_PUBLISHED` | 409 | No | CONFIGURATION | Requested Requirement Profile is not in PUBLISHED state. | Publish/select a published profile. |
| `DOCUMENT_TYPE_NOT_FOUND` | 404 | No | CONFIGURATION | Document Type key/resource is not visible or does not exist. | Correct the type key or configuration. |
| `EXTRACTION_PROFILE_NOT_FOUND` | 404 | No | CONFIGURATION | Requested/effective Extraction Profile does not exist. | Create/publish the required Extraction Profile. |
| `SUBJECT_DOCUMENT_NOT_FOUND` | 404 | No | RESOURCE | No matching Document exists inside the supplied Tenant + Subject boundary. | Refresh/re-resolve Subject documents. |
| `DOCUMENT_NOT_CONFIRMED` | 409 | No | STATE | Requested operation requires machine CONFIRMED state. | Wait for successful processing or resolve the processing exception. |
| `DOCUMENT_CONTENT_PURGED` | 410 | No | RETENTION | Document metadata exists but content was purged under retention policy. | Do not retry content retrieval. |
| `IDEMPOTENCY_CONFLICT` | 409 | No | IDEMPOTENCY | Same idempotency key was reused with a different request identity/payload. | Use the original request or a new idempotency key. |
| `FILE_EMPTY` | 422 | No | UPLOAD | Uploaded file contains zero bytes. | Upload a non-empty file. |
| `FILE_TOO_LARGE` | 413 | No | UPLOAD | File exceeds configured Tenant limit. | Upload a file within configured limit. |
| `MIME_TYPE_NOT_ALLOWED` | 415 | No | UPLOAD | Declared/detected MIME type is not allowed. | Upload an allowed file type. |
| `INVALID_FILE_CONTENT` | 422 | No | UPLOAD | File signature/parser/structure validation failed. | Upload a valid non-corrupt file. |
| `INVALID_CONFIGURATION` | 409 | No | CONFIGURATION | Persisted configuration fails a deterministic activation/publication/runtime invariant. | Correct configuration; retry after correction. |
| `DOCUMENT_NOT_FOUND` | 404 | No | RESOURCE | Document resource does not exist or is not visible. | Refresh/re-resolve the resource. |
| `UNASSIGNED_DOCUMENT_NOT_FOUND` | 404 | No | RESOURCE | Unassigned Tenant Document does not exist or is not visible. | Refresh unassigned intake list. |
| `SUBJECT_DOCUMENT_MISMATCH` | 404 | No | RESOURCE | Document does not belong to the supplied Subject boundary. | Use the correct Tenant + Subject + Document path. |
| `INVALID_DOCUMENT_STATE` | 409 | No | STATE | Requested state transition/action is not valid for the current Document state. | Refresh state and follow allowed transition. |
| `DOCUMENT_REPLACEMENT_NOT_ALLOWED` | 409 | No | STATE | Replacement is allowed only for NOT_FIT, CORRUPT or UPLOAD_FAILED evidence under Phase-1 rules. | Do not replace a confirmed/otherwise ineligible Document. |
| `DOCUMENT_ALREADY_ASSIGNED` | 409 | No | STATE | Unassigned Document already has a Subject. | Refresh Document state; do not reassign through the unassigned flow. |
| `PROFILE_IMMUTABLE` | 409 | No | CONFIGURATION | Published/retired profile content is immutable. | Create/edit a DRAFT version. |
| `PROFILE_NOT_DRAFT` | 409 | No | CONFIGURATION | Requested profile mutation requires DRAFT state. | Create/select a DRAFT profile. |
| `WHATSAPP_ROUTE_NOT_FOUND` | 404 | No | INTEGRATION | No configured Tenant route matches the WhatsApp destination/account identity. | Configure the route or handle system quarantine. |
| `QUARANTINE_ITEM_NOT_FOUND` | 404 | No | INTEGRATION | System quarantine item does not exist or is no longer actionable. | Refresh quarantine list. |
| `STORAGE_WRITE_FAILED` | 503 | Yes | DEPENDENCY | Object-storage write/finalization failed transiently or was unavailable. | Retry with the same idempotency key using backoff where the operation is safe. |
| `STORAGE_READ_FAILED` | 503 | Yes | DEPENDENCY | Object-storage read failed transiently or was unavailable. | Retry with backoff. |
| `QUALITY_POLICY_NOT_CONFIGURED` | 409 | No | CONFIGURATION | Tenant quality policy is absent/invalid. | Configure a valid non-empty quality policy. |
| `CLASSIFICATION_NO_CANDIDATES` | 409 | No | CLASSIFICATION | Deterministic candidate formation produced no processing-ready Document Type. | Activate/configure a Document Type with an effective PUBLISHED Extraction Profile. |
| `CLASSIFICATION_AMBIGUOUS` | 422 | No | CLASSIFICATION | Classification did not yield exactly one acceptable candidate under Tenant acceptance policy. | Resolve configuration/input quality; no automatic client retry unchanged. |
| `SUBJECT_MATCH_AMBIGUOUS` | 409 | No | SUBJECT_MATCHING | Available deterministic identity evidence maps to more than one candidate Subject or does not meet acceptance rule. | Resolve/assign Subject through authorized review. |
| `SUBJECT_IDENTIFIER_CONFLICT` | 409 | No | SUBJECT_MATCHING | The same active VERIFIED identifier already belongs to another Subject in this Tenant. | Do not create a duplicate verified mapping; resolve the existing mapping. |
| `INTERNAL_ERROR` | 500 | Yes | INTERNAL | Unexpected server error not represented by a more specific code. | Retry only with backoff/idempotency where safe; provide correlation ID to support if persistent. |
