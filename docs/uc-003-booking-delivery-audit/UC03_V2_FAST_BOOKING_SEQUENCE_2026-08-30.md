# UC03 V2 — Fast Booking Capture, Classification and Extraction Sequence

**Status:** implementation amendment  
**Date:** 2026-08-30  
**Scope:** UC03 Document Capture V2 only. Existing V1 APIs, V1 worker semantics and provider adapter contracts are not changed.

## Product objective

The Process Consultant (PC) is KPI-driven. The system must prevent avoidable rework while keeping the Booking journey fast.

Engineering objectives:

- App open to populated Booking Review: **P95 target < 2 minutes** under supported operating conditions.
- Four normal Booking evidence files: upload + accepted classification **engineering target <= 10 seconds** under supported network/file-size conditions.
- Do not represent either target as a guarantee for arbitrary mobile networks or arbitrary file sizes. Measure P50/P95 in DEV/UAT.

## Frozen journey rule

**Classification is the hard Step-1 gate. Extraction is not the Step-1 gate.**

A PC may leave Documents only after every currently-required Booking document has been safely uploaded and classified into a document type that satisfies the active Booking requirement set.

Extraction starts immediately after an accepted classification and continues while the PC completes Booking Details.

A file that has safely reached object storage must not require a second upload merely because classification/extraction has a transient system/provider failure. Retry is a system responsibility. A replacement upload is appropriate only when the evidence itself cannot be accepted/identified (for example genuinely UNKNOWN/ambiguous or unusable evidence).

## Sequence

```text
PC opens Capture New Booking
        |
        v
Booking conditions determine active requirements
(GST / Corporate / Exchange etc.)
        |
        v
PC selects/captures required documents
        |
        +--> file A -- direct PUT --> R2 -- classify --> accepted -- extract -- facts
        +--> file B -- direct PUT --> R2 -- classify --> accepted -- extract -- facts
        +--> file C -- direct PUT --> R2 -- classify --> accepted -- extract -- facts
        +--> file D -- direct PUT --> R2 -- classify --> accepted -- extract -- facts
                                    |                    |
                                    |                    +--> extraction is asynchronous
                                    |                         and does not hold Step 1
                                    |
                                    +--> classification reconciles the
                                         Booking requirement checklist
        |
        v
ALL REQUIRED DOCUMENTS IDENTIFIED
        |
        v
Step 1 COMPLETE -> Booking Details
        |
        |  V2 extraction continues concurrently
        v
PC completes additional Booking information
        |
        v
Submit Booking
        |
        v
Booking Attribute Review
(attribute / resolved value / confidence / document type / evidence link)
        |
        v
Click evidence -> original document + page + bounding box
```

## Upload behaviour

Document Capture V2 keeps the approved direct-to-object-storage architecture:

1. Audit Core creates V2 upload intents.
2. Browser/mobile uploads bytes directly to R2/MinIO using presigned PUT URLs.
3. Files in one selection are uploaded concurrently.
4. `finalize` is a latency hint, not the durability boundary. Status reads can reconcile an object when the client finalize request is lost.
5. The original evidence object is retained unchanged. Classification may use an in-memory first-page/downscaled payload; it does not replace the audit original.

## Classification behaviour

- V2 classification is byte-based and separate from the legacy adapter classification contract.
- The dedicated worker deployment already runs a bounded V2 classification pool.
- Classification is performed once for the Step-1 decision.
- An accepted V2 classification sets the document type/hint and queues durable processing.
- The processing pipeline reuses that accepted V2 classification locally. It does **not** make a second provider classification request.
- If classification is UNKNOWN/ambiguous after its supported retry behaviour, the requirement remains unsatisfied and the PC sees which document is still required.

## Extraction behaviour

Accepted V2 classifications are routed to a bounded V2 processing pool instead of waiting behind the sequential legacy/V1 processing lane.

The V2 pool:

1. claims only durable processing jobs associated with classified V2 capture documents;
2. reuses the accepted V2 document type and classification confidence;
3. invokes the existing processing pipeline with a V2-only preclassified adapter wrapper;
4. delegates `extract()` unchanged to the configured provider adapter;
5. keeps the existing normalization, deterministic validation, extracted-fact lineage, current machine values, confidence scoring, verification status, retry and backout behaviour;
6. processes up to four V2 documents concurrently in the current implementation;
7. uses LISTEN/NOTIFY for immediate wake-up and a short V2-only fallback poll when notification is unavailable.

The sequential legacy/V1 processing lane is preserved. V1 APIs and concrete adapter implementations are untouched.

## Booking UI contract

Step 1 should communicate the business state, not internal worker vocabulary.

Preferred states:

- `Uploading...`
- `Identifying...`
- `Identified` / classified document label
- `Could not identify` only for a genuine classification outcome that requires user action
- `All required documents identified` when the hard gate is satisfied

`NOT_STARTED` is an internal processing status and should not be presented as if the document upload failed.

Extraction readiness can be shown as a secondary non-blocking indicator (`Extracting...` / `Values ready`) but must not obscure the classification gate.

## Booking Review contract

When Booking Details are submitted, Review reads the common attribute-resolution view already defined for UC03:

- business/Excel attribute;
- resolved/extracted value;
- confidence;
- source document type;
- evidence link;
- review state.

Clicking evidence opens the original DI document at the source page and highlights the returned evidence region/bounding box when available.

If one extraction is still legitimately running when Booking is submitted, Review must show available values and a bounded processing state for the outstanding evidence. It must not require re-upload of a safely stored document.

## Performance telemetry

At minimum record/derive these timestamps per document:

- upload intent created;
- object upload completed/reconciled;
- classification started;
- classification completed;
- extraction started;
- extraction completed;
- Review value available.

Journey telemetry should derive:

- App open -> Capture New Booking ready;
- first file selected -> all required documents classified;
- Booking Details submit -> Review rendered;
- App open -> populated Review rendered.

P50 and P95 must be reviewed from DEV/UAT evidence before changing the performance objectives.

## Non-goals / invariants

This amendment does **not**:

- change `/v1` API contracts;
- change `DocumentAIAdapter` interface;
- modify existing Gemini/other concrete adapter implementations;
- make Audit Core a duplicate store of DI extracted values;
- make extraction a prerequisite for leaving Step 1;
- allow processing order to become source precedence;
- invent a document type when V2 classification is below the configured acceptance threshold.
