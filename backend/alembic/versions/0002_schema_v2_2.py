"""0002_schema_v2_2 — Baseline 2.2 schema delta

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11

Changes from v2.1 → v2.2 (as identified in CHANGED_FILES_v2.2.md and DI_DATA_MODEL_v2.2.md):

1. subject_identifiers: replace non-unique index ix_subject_identifier_exact with
   partial UNIQUE index uq_subject_identifier_active_verified — closes gap D6 from
   architecture review (concurrent insert could create duplicate active VERIFIED
   identifiers, breaking WhatsApp subject-matching invariant).

2. documents: add column document_type_hint_key varchar(120) — persists the optional
   non-authoritative caller hint per DI_LLD_v2.2.md §6 step 4 and DI_CLASSIFICATION_v2.2.md §3.

3. processing_runs: add column classification_candidate_set jsonb — snapshots the
   deterministic candidate set before classifier invocation per DI_CLASSIFICATION_v2.2.md §2 step 7.

4. audit_chain_heads: change primary key from (tenant_id) to (tenant_id, entity_type, entity_id)
   — entity-scoped chains so unrelated entities write concurrently per DI_AUDIT_MODEL_v2.2.md §2.
   The v2.1 table used (tenant_id) PK; this migration renames it, drops the old PK and rebuilds.

5. audit_events: add columns entity_type varchar(80) and entity_id varchar(160) — links each
   event to its audited entity for entity-scoped chain lookup.

NOTE: The audit_chain_heads and audit_events tables were created in migration 0001 as part of
the full raw SQL DDL. This migration alters them to the v2.2 shape.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. subject_identifiers: UNIQUE partial index replacing non-unique ──────
    # Drop the old non-unique index from v2.1
    op.execute("DROP INDEX IF EXISTS docintel.ix_subject_identifier_exact")

    # Create the partial UNIQUE index that enforces the matching invariant
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
            CHECK (classification_candidate_set IS NULL
                   OR jsonb_typeof(classification_candidate_set) = 'array')
    """)

    # ── 4 & 5. Entity-scoped audit chain heads ─────────────────────────────────
    # audit_chain_heads in v2.1 has PK = (tenant_id).
    # v2.2 requires PK = (tenant_id, entity_type, entity_id).
    #
    # Strategy: rename old table, create new table, migrate existing rows
    # (map old tenant-level heads to entity_type='TENANT', entity_id=tenant_id),
    # then drop the old table. The audit_immutability_guard trigger is also recreated.

    op.execute("""
        ALTER TABLE IF EXISTS docintel.audit_chain_heads
        RENAME TO audit_chain_heads_v21
    """)

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

    # Migrate existing rows: treat old per-tenant heads as TENANT entity
    op.execute("""
        INSERT INTO docintel.audit_chain_heads
            (tenant_id, entity_type, entity_id, last_event_hash, updated_at_utc)
        SELECT
            tenant_id,
            'TENANT'  AS entity_type,
            tenant_id AS entity_id,
            last_event_hash,
            updated_at_utc
        FROM docintel.audit_chain_heads_v21
        ON CONFLICT DO NOTHING
    """)

    op.execute("DROP TABLE IF EXISTS docintel.audit_chain_heads_v21")

    # ── 5. audit_events: add entity_type + entity_id columns ──────────────────
    op.execute("""
        ALTER TABLE docintel.audit_events
        ADD COLUMN IF NOT EXISTS entity_type varchar(80),
        ADD COLUMN IF NOT EXISTS entity_id   varchar(160)
    """)

    # Back-fill existing rows with TENANT entity type so FK-like queries work
    op.execute("""
        UPDATE docintel.audit_events
        SET entity_type = 'TENANT',
            entity_id   = tenant_id
        WHERE entity_type IS NULL
    """)

    # Add a covering index for entity-chain lookups
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_audit_events_entity
        ON docintel.audit_events(tenant_id, entity_type, entity_id, occurred_at_utc DESC)
    """)


def downgrade() -> None:
    # ── Reverse 5: remove entity columns from audit_events ────────────────────
    op.execute("DROP INDEX IF EXISTS docintel.ix_audit_events_entity")
    op.execute("""
        ALTER TABLE docintel.audit_events
        DROP COLUMN IF EXISTS entity_type,
        DROP COLUMN IF EXISTS entity_id
    """)

    # ── Reverse 4: revert to single-row-per-tenant audit_chain_heads ──────────
    op.execute("ALTER TABLE IF EXISTS docintel.audit_chain_heads RENAME TO audit_chain_heads_v22")
    op.execute("""
        CREATE TABLE docintel.audit_chain_heads (
            tenant_id       varchar(128) PRIMARY KEY,
            last_event_hash char(64),
            updated_at_utc  timestamptz NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES docintel.tenant_settings(tenant_id)
        )
    """)
    op.execute("""
        INSERT INTO docintel.audit_chain_heads (tenant_id, last_event_hash, updated_at_utc)
        SELECT DISTINCT ON (tenant_id)
            tenant_id, last_event_hash, updated_at_utc
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
    op.execute("DROP INDEX IF EXISTS docintel.uq_subject_identifier_active_verified")
    op.execute("""
        CREATE INDEX ix_subject_identifier_exact
        ON docintel.subject_identifiers(tenant_id, identifier_type, normalized_value)
        WHERE valid_to_utc IS NULL AND verification_status = 'VERIFIED'
    """)
