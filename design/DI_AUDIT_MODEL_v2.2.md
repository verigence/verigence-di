# Verigence Document Intelligence - Tamper-Evident Audit Chain Model

**Baseline:** 2.2  
**Status:** BASELINED

## 1. Change from 2.1

Baseline 2.1 used one `audit_chain_heads` row per Tenant. Every Tenant audit write therefore serialized on one row lock. Baseline 2.2 changes Tenant audit chains to **entity-scoped chains**.

## 2. Chain key

Tenant audit chain head primary key:

`tenant_id + entity_type + entity_id`

An audit event is chained to the same primary audited entity recorded on the event.

Examples:

- Document changes: `DOCUMENT + document_id`
- Subject changes: `SUBJECT + subject_id`
- Extraction Profile changes: `EXTRACTION_PROFILE + profile_id`
- Requirement Profile changes: `REQUIREMENT_PROFILE + profile_id`
- Tenant-wide configuration: `TENANT + tenant_id`

This preserves tamper evidence per audited entity while allowing unrelated entities in the same Tenant to append concurrently.

## 3. Append transaction

For `(tenant_id, entity_type, entity_id)`:

1. `INSERT ... ON CONFLICT DO NOTHING` the chain-head row.
2. `SELECT ... FOR UPDATE` that **entity chain head only**.
3. Read `last_event_hash` as `previous_event_hash`.
4. Canonicalize the event record using the application's versioned audit canonicalization implementation.
5. Calculate SHA-256 `event_hash`.
6. Insert immutable `audit_events` row.
7. Update that entity's chain head.
8. Commit.

Concurrent writes to the **same entity** serialize intentionally; unrelated entities do not.

## 4. Ordering

Baseline 2.2 does not claim one cryptographic total ordering of all Tenant events. Tenant-wide chronological reporting uses `occurred_at_utc` plus `audit_event_id`; cryptographic tamper evidence is entity-scoped.

## 5. Pre-Tenant quarantine

The existing separate system audit chain for pre-Tenant quarantine remains unchanged in Phase 1 because it is outside the Tenant/entity model. It does not block Tenant audit writes.
