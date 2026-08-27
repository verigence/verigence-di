# UC03 Direct R2 Review Amendment — 27-Aug-2026

## Status

Implementation amendment for PC Booking Journey document upload/review performance.

## Recovery snapshots taken before implementation

No code changes were made before the following recovery branches were created:

- Audit Core: `snapshot/uc03-direct-r2-prechange-20260827` at `d871cb7416f4dec129d1ea3a88e59723fd0e6871`
- Document Intelligence: `snapshot/uc03-direct-r2-prechange-20260827` at `a57c606a2e908a29b03b2458f901072af7a4d7c1`

Audit Core is not changed by this amendment. Its snapshot exists because the PC Booking review contract spans Audit Core and DI and was explicitly requested as a safe recovery baseline.

## Decision

For PC Booking Review, Document Intelligence remains responsible for document intake, extraction facts, confidence, page number, evidence region and authorization to access document content. Large original document bytes must not be proxied through the DI Railway service on the normal Review path.

The normal data path is therefore:

```text
Step 1 upload
Web / Mobile -> DI -> R2
                 |
                 +-> upload response contains short-lived signed content URL

Review
Web / Mobile -> DI extraction-review   (small JSON)
Web / Mobile -> R2 signed URL           (PDF/image bytes directly)

Save Review
Web / Mobile -> Audit Core              (reviewed field batch)
```

The existing DI `/content` streaming endpoint remains available as a backward-compatible route, but the PC Review UI must prefer signed direct-storage access.

## Upload-time content URL

A successful direct PC Booking upload returns:

- `documentId`
- `uploadStatus`
- `processingStatus`
- `contentUrl`
- `contentUrlExpiresAtUtc`
- `mimeType`

The content URL is generated immediately after the original artifact has been written. URL generation is a performance/access convenience and must not turn a successfully stored upload into a failed upload. If signing fails, the upload response may contain a null URL; Review can mint one later.

## URL lifetime and refresh

The initial signed URL lifetime is **30 minutes**.

A new lightweight endpoint is available for an expired, missing or near-expiry URL:

```http
GET /v1/tenants/{tenantId}/audit-storage-contexts/{externalContextRef}/pc-booking-documents/{documentId}/content-url
```

The endpoint:

1. requires the existing human permission `di.document.content.read`;
2. verifies tenant, Audit Storage Context and document membership;
3. verifies that the original artifact exists and has not been purged;
4. returns a fresh short-lived signed object-storage GET URL.

Only the URL-minting request goes through DI. The document bytes still travel directly from R2/MinIO to the browser/mobile WebView.

## Security boundary

- The R2 bucket remains private.
- R2 access key/secret are never exposed to Web or Mobile.
- The browser/mobile client does not sign URLs.
- Signed URLs are temporary bearer URLs and are not persisted as permanent business data.
- DI never returns the internal `logical_object_key` in this PC Review contract.
- A signed R2 fetch must not send the user's Security bearer token or application cookies to R2.

## R2 CORS requirement

Because PC Review fetches the signed R2 URL from browser JavaScript / Capacitor WebView, the R2 bucket must allow CORS for the Verigence Web origins.

Required origins must include the deployed Web DEV/PROD origins and the Capacitor Android origin used by the application (`https://localhost`). The bucket must remain private.

Recommended minimum policy:

```json
[
  {
    "AllowedOrigins": [
      "<WEB_DEV_ORIGIN>",
      "<WEB_PROD_ORIGIN>",
      "https://localhost"
    ],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["Range", "Content-Type"],
    "ExposeHeaders": [
      "Content-Type",
      "Content-Length",
      "ETag",
      "Accept-Ranges",
      "Content-Range"
    ],
    "MaxAgeSeconds": 3600
  }
]
```

Use the actual deployed origins rather than wildcards where possible. Public bucket access is **not** required.

## Mobile compatibility

The Android application is a Capacitor WebView using the same Web Review implementation. Direct signed HTTPS object reads therefore use the same `fetch()` path. The one additional infrastructure requirement is that R2 CORS includes the Capacitor origin (`https://localhost`). No R2 credential, native S3 SDK or Android-specific storage implementation is required.

## Performance intent

This amendment is specifically intended to remove two forms of avoidable latency:

1. Review must not wait for unrelated Audit Core workspace/snapshot reads before beginning document review.
2. Large PDF/image bytes must not traverse `R2 -> DI Railway -> client`; the normal path is `R2 -> client`.

Documents are loaded lazily in Review so the first document becomes useful without waiting for every Booking document to finish downloading.

## Compatibility

- Existing extraction-review APIs remain unchanged.
- Existing DI `/content` endpoint remains available for older callers.
- Audit Core schema/API behavior is unchanged by this amendment.
- MinIO/local development uses the same S3-compatible presigning abstraction.
