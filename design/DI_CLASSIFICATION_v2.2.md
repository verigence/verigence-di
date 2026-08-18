# Verigence Document Intelligence - Classification Candidate Formation

**Baseline:** 2.2  
**Status:** BASELINED

## 1. Purpose

This specification removes ambiguity about which Document Types are sent to the classifier. Requirement Profiles and caller hints must never prevent valid additional evidence from being classified.

## 2. Deterministic candidate-set algorithm

For a Processing Run and its Tenant:

1. Load visible `document_types` where `status=ACTIVE` and `owner_tenant_id` is either the current Tenant or NULL (global).
2. Group by `document_type_key`. If both a Tenant-owned ACTIVE type and global ACTIVE type use the same key, keep only the Tenant-owned type; otherwise keep the visible type. This is the effective Document Type for that key.
3. For each effective type, resolve an effective PUBLISHED Extraction Profile using existing precedence:
   - PUBLISHED profile scoped to the current Tenant for that `document_type_id`;
   - otherwise PUBLISHED global/default profile for that `document_type_id`.
4. Remove any type for which no effective PUBLISHED Extraction Profile exists. Such a type is not processing-ready.
5. The remaining set is the complete classification candidate set. **Do not filter it to the Subject Requirement Profile.** This preserves classification of ADDITIONAL evidence.
6. If the candidate set is empty, fail the Processing Run NON_RETRYABLE with `CLASSIFICATION_NO_CANDIDATES`; Document becomes `FAILED/NOT_CONFIRMED`.
7. Persist the exact candidate snapshot on `processing_runs.classification_candidate_set` before invoking the classifier. Each entry contains only `documentTypeId`, `documentTypeKey`, `profileId`, `isRequirementExpected`, and `isCallerHint`.
8. Determine context flags:
   - `isRequirementExpected=true` when the Subject's currently assigned immutable Requirement Profile contains the same `document_type_key`;
   - `isCallerHint=true` when the persisted upload `document_type_hint_key` equals the candidate key.
9. Candidate payload order is deterministic: caller-hint candidate first, then requirement-expected candidates, then remaining candidates; ties sort by `document_type_key` ascending. Ordering is not a synthetic confidence boost.
10. `DocumentAIAdapter.classify()` receives the full candidate set and context flags. It returns canonical 0-100 classification scores.
11. Verigence does **not** add an undisclosed numeric boost. Acceptance remains: exactly one candidate meets the Tenant `classification_acceptance_score`; otherwise `CLASSIFICATION_AMBIGUOUS`.
12. After a candidate is accepted, extraction uses the `profileId` from the persisted candidate snapshot; the worker does not re-resolve a newer profile during the same Processing Run.

## 3. Caller hint

`documentTypeKey` supplied during Mobile/Web/API upload is non-authoritative. It must resolve to a visible ACTIVE type key at intake and is persisted as `documents.document_type_hint_key`. It never removes other eligible candidates and never bypasses machine classification.

## 4. Requirement Profile

The assigned Requirement Profile contributes only `isRequirementExpected` context. It does not constrain the candidate set because Baseline 2.2 accepts supported documents outside the mandatory/optional list as ADDITIONAL evidence.

## 5. Reproducibility

The persisted candidate snapshot plus the Processing Run's `pipeline_version`, Tenant classification threshold and invocation lineage are sufficient to explain which candidates were available to that classification execution. EOD retry creates a new Processing Run and therefore creates its own candidate snapshot from configuration effective at retry time.
