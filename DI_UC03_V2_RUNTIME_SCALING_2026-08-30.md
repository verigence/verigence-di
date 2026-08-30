# UC03 V2 Runtime Scaling and Extraction Latency

Date: 2026-08-30
Status: Implementation decision for DEV validation

## Purpose

UC03 is an audit workflow. Document capture, classification and extraction are therefore both quality-critical and latency-critical. The runtime must preserve the original evidence and the accepted document classification, extract the configured facts with confidence and source localization, and make those facts available to Booking Review without avoidable orchestration delay.

This design applies to Document Capture V2 only. Existing `/v1` APIs, the `DocumentAIAdapter` contract, concrete Gemini extraction behaviour, V1 processing semantics, retry/backout rules and Audit Core persistence contracts remain unchanged.

## Booking runtime sequence

```text
PC uploads document
        |
        v
Direct R2 upload completes
        |
        v
Durable V2 classification job
        |
        v
Bounded V2 classifier pool
        |
        v
Accepted classification
        |--------------------------> Step-1 requirement satisfied
        |
        v
Durable processing job + pg_notify
        |
        v
Bounded V2 extraction pool
        |
        v
Existing provider extract() implementation
        |
        v
Normalization / validation / lineage / confidence / evidence region
        |
        v
DI facts available to Booking Review
```

Classification is the hard gate for leaving Step 1. Extraction starts immediately after successful classification but does not block the PC from entering Step 2. The PC's Step-2 interaction time is deliberately used as the extraction window.

## No artificial extraction lag

The normal V2 path uses PostgreSQL LISTEN/NOTIFY to wake extraction workers as soon as the classified document's processing job is committed. The existing V2 extraction fallback poll remains 0.5 seconds. It is a recovery path, not the primary dispatcher.

The UI may refresh document/extraction readiness approximately once per second while the PC is in Step 2 or while Review is preparing. Backend polling must not be increased from 0.5 seconds to 1 second because that would make the fallback slower.

## Dedicated Railway worker topology

The historical `di-worker` process previously hosted legacy/V1 processing, V2 classification, V2 extraction and the EOD scheduler together. Horizontally scaling that service would unintentionally duplicate the V1 lane and EOD scheduler.

The DEV topology is therefore split:

```text
Railway DEV

  di-api
    1 service

  di-worker
    1 replica
    DI_WORKER_MODE=legacy
    - one legacy/V1 processing lane
    - one EOD retry scheduler
    - no V2 pools

  di-worker-v2
    2 replicas initially
    DI_WORKER_MODE=v2
    each replica:
      - 4 V2 classification lanes
      - 4 V2 extraction lanes
    - no legacy/V1 processing lane
    - no EOD scheduler

  shared Postgres / Neon
    - durable classification jobs
    - durable processing jobs
    - row claiming with FOR UPDATE SKIP LOCKED
```

Initial aggregate V2 capacity is therefore 8 concurrent classification lanes and 8 concurrent extraction lanes across two Railway replicas.

The two V2 replicas consume the same durable PostgreSQL job tables. A queue or adapter instance is not created per PC. `FOR UPDATE SKIP LOCKED` ensures one queued job can only be claimed by one worker lane at a time.

## Why not one queue per PC

A per-PC queue would create idle resources, uneven load distribution, unnecessary operational complexity and poor scaling beyond the initial 20-PC target. PC, tenant, journey, document and correlation identifiers are job metadata; they do not need dedicated infrastructure.

The shared bounded pools provide backpressure and fairness while protecting Gemini, PostgreSQL and memory from an uncontrolled burst.

## Expected burst

Initial sizing assumption:

```text
20 PCs x 4 Booking documents = up to 80 documents in a burst
```

The two-replica DEV topology intentionally does not attempt 80 simultaneous Gemini calls. It begins with 8 extraction calls in flight and continuously claims the next due work as capacity becomes free.

Scale decisions must be evidence-based. Increase `di-worker-v2` from 2 to 3 or 4 replicas only when measured queue wait/P95 latency requires it and provider rate-limit/error metrics remain healthy.

## Quality guardrails

Concurrency must never change audit semantics. The following remain invariant:

1. Original evidence remains unchanged in object storage.
2. Step-1 classification must meet the configured acceptance threshold before satisfying a required-document slot.
3. V2 reuses the already-accepted classification; extraction must not invoke a second provider classification.
4. Extraction uses the same published extraction profile and the existing provider `extract()` implementation.
5. Raw value, confidence, page number and evidence region remain DI-owned facts.
6. Existing normalization, validation, lineage, verification, retry and backout behaviour remains active.
7. A provider timeout/rate-limit is a system retry concern; an already-uploaded document must not be lost or require PC re-upload.
8. Review must not invent a value, confidence, page or bounding box that DI did not return.

## Performance objectives

Engineering objectives, to be measured rather than assumed:

- Step 1 upload + mandatory classification: target P95 <= 10 seconds under supported network/file-size conditions.
- Classification-to-extraction dispatch lag: near-zero with LISTEN/NOTIFY; <= 0.5-second fallback pickup when notification is unavailable.
- App open -> Booking Review populated: target P95 < 2 minutes, including human Step-2 interaction.
- Review status refresh while extraction is outstanding: approximately 1 second.

## Required measurements

For each document record/log at minimum:

- upload_started / upload_completed
- classification_started / classification_completed
- extraction_job_created
- extraction_started / extraction_completed
- review_available
- provider duration and HTTP status
- prompt/response token counts where available
- fields requested/found
- low-confidence count
- fields with page localization
- fields with evidence regions
- retry/rate-limit/error class

Journey metric:

```text
app_open -> booking_review_available
```

Track P50/P95 and the maximum queue wait during the 20-PC x 4-document load test.

## Railway scaling rule

`di-worker-v2` is the only horizontally scaled DI worker service. The existing `di-worker` remains one replica.

DEV starts with two `di-worker-v2` replicas in the Railway region where that service is deployed. Deployment automation refuses to guess a region: it reads `RAILWAY_REPLICA_REGION` from the running V2 worker and scales that exact region to two replicas.

## Acceptance before production promotion

The DEV topology is accepted only after:

1. CI passes lint/type/test/migration gates.
2. `di-worker` proves `legacy` mode with one legacy lane and EOD scheduler and no V2 pool.
3. `di-worker-v2` proves `v2` mode with classification/extraction pools and no EOD/legacy lane.
4. Railway reports successful scale to two V2 replicas.
5. A real UC03 V2 Booking run proves upload -> classification gate -> extraction -> Review with extracted values and evidence.
6. A concurrent load test approximating 20 PCs x 4 documents records queue wait, P50/P95 extraction latency, Gemini 429/5xx, extraction failure rate and evidence-localization quality.

No production scale increase is justified solely by theoretical throughput calculations.
