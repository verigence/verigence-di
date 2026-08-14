# Verigence Document Intelligence - Configuration Model

**Baseline:** 2.0  
**Status:** BASELINED

## 1. Governing rule

Configuration changes tenant/document behavior without changing document-specific Python code. Configuration stores declarative keys and parameters only; executable business logic remains in approved platform implementations. Published Requirement/Extraction Profile versions are immutable.

The Phase-1 product rule for Human Verification is **not configuration**:

- `confidence_score > 90.00` => `OPTIONAL`
- `confidence_score <= 90.00` => `MANDATORY`

Exactly 90.00 is MANDATORY.

## 2. Document Type

A supported class of evidence.

Fields include:

- `document_type_key`
- display name/category/description
- global/default or Tenant scope
- lifecycle status `DRAFT|ACTIVE|RETIRED`; tenant-created types begin DRAFT and first valid Extraction Profile publication activates them automatically

Examples observed in source material include government IDs, booking forms, payment receipts, bank/ledger evidence, invoices, insurance and registration evidence. These examples seed master data only; they are not hard-coded requirements.

A caller may supply `documentTypeKey` as a hint. The hint is not authoritative and does not bypass machine classification verification.

## 3. Canonical Field

Stable output key independent of source label/layout.

Example principle: `VIN`, `Chassis No.` and `Vehicle Identification Number` can map to one canonical key.

Fields include:

- `field_key`
- display name
- datatype
- scope/status

## 4. Extraction Profile

One Document Type can have multiple versions.

Lifecycle:

`DRAFT -> PUBLISHED -> RETIRED`

Rules:

- the service assigns `version_no`; users do not manually type version numbers;
- only DRAFT may be edited;
- a PUBLISHED or RETIRED version is content-immutable;
- publishing a DRAFT atomically changes the prior PUBLISHED version in the same Document-Type/scope to RETIRED and publishes the new version;
- historical Processing Runs continue to reference the exact profile version used.

Each profile field configures:

- canonical field key
- enabled
- expected
- aliases/instruction
- normalization rule references
- validation rule references
- `score_included`
- `score_weight`
- `use_for_subject_matching`
- subject identifier type where used for exact matching
- manual correction allowed
- display sequence

There is deliberately no Phase-1 critical-field override for Human Verification Status.

## 5. Confidence score

For each published profile:

- at least one enabled expected score-bearing field with positive weight is required;
- `FOUND` is the only present state for scoring; `NOT_FOUND|AMBIGUOUS|ERROR` are missing;
- expected missing scored field contributes zero;
- non-expected missing scored field is excluded;
- overall weighted mean yields 0-100 Document `confidence_score` rounded to two decimals;
- provider-native field confidence is normalized to Verigence 0-100 before scoring.

Every confirmed Document snapshots `verification_threshold_applied = 90.00` for lineage even though the Phase-1 threshold is a fixed product rule.

## 6. Requirement Profile

Defines expected evidence for a Subject.

Lifecycle:

`DRAFT -> PUBLISHED -> RETIRED`

Rules:

- the service assigns `version_no`;
- each item contains Document Type, `MANDATORY|OPTIONAL`, minimum count >= 1 and display sequence;
- publishing a new DRAFT atomically retires the previous PUBLISHED version having the same `profile_key`;
- an existing Subject assignment remains pinned to its assigned immutable version until explicitly reassigned;
- a Subject can have zero or one active assignment.

No assignment does not reject uploads. It means completeness cannot be measured against a configured list and the Subject enquiry exposes `REQUIREMENT_PROFILE_NOT_ASSIGNED`.

## 7. Additional documents

A supported Document Type not present in the Subject's assigned Requirement Profile is accepted as `ADDITIONAL` and processed normally. It does not satisfy mandatory/optional counts.

Requirement classification is derived at enquiry time; it is not an authoritative column on the Document.

## 8. Upload Quality Policy

The quality gate is deterministic and configurable without changing document-specific code.

The global `quality_rule_catalog` contains approved implementation keys plus parameter schemas. A Tenant quality policy contains an ordered/non-empty set of:

- `rule_key`
- enabled flag
- rule parameters

The policy is stored as governed Tenant configuration. Every evaluated Document retains individual `document_quality_results` including:

- rule key
- PASS/FAIL/SKIP/ERROR outcome
- exact parameters applied
- measured value/diagnostic payload
- evaluation timestamp

Structural corruption is still determined by MIME/signature/parser/decoder checks and maps to `CORRUPT`. A deterministic quality-rule failure maps to `NOT_FIT` according to the quality service contract.

The actual numeric/algorithm parameters are Tenant calibration values and must be configured before Tenant activation; the architecture never invents them.

## 9. Classification and WhatsApp matching calibration

Required Tenant calibration values:

### `classification_acceptance_score`

Automatic document classification is accepted only when exactly one selected candidate satisfies the configured acceptance score. Otherwise processing ends with a non-retryable classification ambiguity/unclassifiable failure.

### `subject_matching_min_confidence`

An extracted identifier may automatically resolve an unassigned WhatsApp Document to a Subject only when:

1. the Extraction Profile marks the field for Subject matching;
2. the field is found and normalized;
3. applicable deterministic validation passes;
4. field confidence meets the Tenant matching threshold; and
5. exactly one active VERIFIED Subject identifier matches the normalized value.

Otherwise the Document remains UNASSIGNED.

These values are calibration parameters, not unresolved design choices.

## 10. Tenant settings

Required governed settings:

- timezone name
- EOD retry local time
- EOD retry enabled
- document classification acceptance score
- extracted-identifier Subject matching minimum confidence
- upload timeout
- maximum upload size
- allowed MIME types
- non-empty upload Quality Policy
- active retention policy before accepting production uploads
- configured WhatsApp explicit Subject-reference prefix/convention

The Human Verification threshold is intentionally absent because Phase 1 fixes it at 90.00.

## 11. Retention policy

Contains:

- key/name
- retention days
- disposition: `PURGE_CONTENT` or `KEEP_CONTENT`
- active state

At registration, the applicable policy outcome is snapshotted onto the Document so future policy edits do not silently alter historical retention decisions.

## 12. Rule catalogs

Normalization, validation and quality catalogs store stable rule keys, approved implementation keys and parameter schemas.

Arbitrary executable code is prohibited in database configuration.

## 13. Configuration publication validation

Publishing an Extraction Profile fails unless:

- referenced Document Type/canonical fields/rules exist and are visible in scope;
- field datatypes are compatible;
- score weights are non-negative;
- at least one enabled expected score-bearing field has positive weight;
- matching fields have a Subject identifier type when `use_for_subject_matching=true`;
- the target row is DRAFT.

Publishing a Requirement Profile fails unless:

- every referenced Document Type exists and is active/usable for the Tenant;
- minimum counts are >=1;
- the target row is DRAFT.

Publishing performs version supersession atomically, preventing an interval with two published versions or no published replacement.

## 14. Runtime cache

Workers resolve a complete published Extraction Profile once per Processing Run and cache it by immutable profile/version ID. Requirement resolution caches immutable profile versions similarly. Publication invalidates only the effective-resolution cache, not historical version data.
