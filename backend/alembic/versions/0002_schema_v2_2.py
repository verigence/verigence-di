"""0002_schema_v2_2 — Baseline 2.2 schema delta

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11

Precise delta from live Neon state (0001/v2.1) to v2.2.

Verified live column names via DI_POSTGRESQL_SCHEMA_v2.1.sql:
  - audit_chain_heads: columns are (tenant_id PK, last_event_hash, last_event_at_utc)
  - audit_events: already has entity_type + entity_id columns + ix_audit_entity index (no change needed)
  - subject_identifiers: has ix_subject_identifier_exact (non-unique)

Changes applied:

1. subject_identifiers:
   Drop non-unique ix_subject_identifier_exact.
   Create UNIQUE partial index uq_subject_identifier_active_verified.
   Closes architecture gap D6 — concurrent inserts can no longer create two
   active VERIFIED identifiers for different Subjects in the same Tenant.

2. documents:
   Add column document_type_hint_key varchar(120).
   Persists the non-authoritative caller hint per DI_LLD_v2.2 §6 step 4.

3. processing_runs:
   Add column classification_candidate_set jsonb with array-type CHECK.
   Snapshots the deterministic candidate set before classification per
   DI_CLASSIFICATION_v2.2 §2 step 7.

4. audit_chain_heads:
   Rebuild from single-tenant-row design to entity-scoped chain heads.
   The old table has PK=(tenant_id). The new design needs PK=(tenant_id, entity_type, entity_id).
   Strategy:
     a. Rename old table to _v21 backup.
     b. Create new table with correct PK and column names.
        Column name used is 'updated_at_utc' (v2.2 convention; v2.1 used 'last_event_at_utc').
     c. Migrate existing rows → entity_type='TENANT', entity_id=tenant_id.
     d. Drop backup.

   NOTE: audit_events entity_type/entity_id columns and ix_audit_entity index
   already exist in v2.1 — no change needed for that table.
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. subject_identifiers: non-unique → UNIQUE partial index ─────────────
    op.execute(
        "DROP INDEX IF EXISTS docintel.ix_subject_identifier_exact"
    )
    op.execute("""
        CREATE UNIQUE INDEX uq_subject_identifier_active_verified
            ON docintel.subject_identifiers(tenant_id, identifier_type, normalized_value)
            WHERE valid_to_utc IS NULL AND verification_status = 'VERIFIED'
    """)

    # ── 2. documents: add document_type_hint_key ──────────────────────────────
    op.execute("""
        ALTER TABLE docintel.documents
            ADD COLUMN IF NOT EXISTS document_type_hint_key varchar(120)
    """)

    # ── 3. processing_runs: add classification_candidate_set ──────────────────
    op.execute("""
        ALTER TABLE docintel.processing_runs
            ADD COLUMN IF NOT EXISTS classification_candidate_set jsonb
                CHECK (
                    classification_candidate_set IS NULL
                    OR jsonb_typeof(classification_candidate_set) = 'array'
                )
    """)

    # ── 4. audit_chain_heads: rebuild for entity-scoped chains ────────────────
    # The live v2.1 table: PK=(tenant_id), columns: last_event_hash, last_event_at_utc
    # The v2.2 table needs: PK=(tenant_id, entity_type, entity_id), column: updated_at_utc

    # Step 4a: save old data
    op.execute("""
        ALTER TABLE docintel.audit_chain_heads
            RENAME TO audit_chain_heads_v21
    """)

    # Step 4b: create new entity-scoped table
    op.execute("""
        CREATE TABLE docintel.audit_chain_heads (
            tenant_id       varchar(128) NOT NULL,
            entity_type     varchar(80)  NOT NULL,
            entity_id       varchar(160) NOT NULL,
            last_event_hash char(64),
            updated_at_utc  timestamptz  NOT NULL,
            PRIMARY KEY (tenant_id, entity_type, entity_id),
            FOREIGN KEY (tenant_id)
                REFERENCES docintel.tenant_settings(tenant_id)
        )
    """)

    # Step 4c: migrate old per-tenant rows → TENANT entity entries
    op.execute("""
        INSERT INTO docintel.audit_chain_heads
            (tenant_id, entity_type, entity_id, last_event_hash, updated_at_utc)
        SELECT
            tenant_id,
            'TENANT'                                     AS entity_type,
            tenant_id                                    AS entity_id,
            last_event_hash,
            COALESCE(last_event_at_utc, NOW() AT TIME ZONE 'UTC') AS updated_at_utc
        FROM docintel.audit_chain_heads_v21
        ON CONFLICT DO NOTHING
    """)

    # Step 4d: drop backup
    op.execute("DROP TABLE docintel.audit_chain_heads_v21")


def downgrade() -> None:
    # ── Reverse 4: restore single-row-per-tenant audit_chain_heads ────────────
    op.execute(
        "ALTER TABLE IF EXISTS docintel.audit_chain_heads "
        "RENAME TO audit_chain_heads_v22"
    )
    op.execute("""
        CREATE TABLE docintel.audit_chain_heads (
            tenant_id       varchar(128) PRIMARY KEY,
            last_event_hash char(64),
            last_event_at_utc timestamptz,
            FOREIGN KEY (tenant_id) REFERENCES docintel.tenant_settings(tenant_id)
        )
    """)
    op.execute("""
        INSERT INTO docintel.audit_chain_heads
            (tenant_id, last_event_hash, last_event_at_utc)
        SELECT DISTINCT ON (tenant_id)
            tenant_id,
            last_event_hash,
            updated_at_utc AS last_event_at_utc
        FROM docintel.audit_chain_heads_v22
        WHERE entity_type = 'TENANT'
        ORDER BY tenant_id, updated_at_utc DESC
        ON CONFLICT DO NOTHING
    """)
    op.execute("DROP TABLE IF EXISTS docintel.audit_chain_heads_v22")

    # ── Reverse 3: drop classification_candidate_set ──────────────────────────
    op.execute("""
        ALTER TABLE docintel.processing_runs
            DROP COLUMN IF EXISTS classification_candidate_set
    """)

    # ── Reverse 2: drop document_type_hint_key ────────────────────────────────
    op.execute("""
        ALTER TABLE docintel.documents
            DROP COLUMN IF EXISTS document_type_hint_key
    """)

    # ── Reverse 1: restore old non-unique index ───────────────────────────────
    op.execute(
        "DROP INDEX IF EXISTS docintel.uq_subject_identifier_active_verified"
    )
    op.execute("""
        CREATE INDEX ix_subject_identifier_exact
            ON docintel.subject_identifiers(tenant_id, identifier_type, normalized_value)
            WHERE valid_to_utc IS NULL AND verification_status = 'VERIFIED'
    """)
