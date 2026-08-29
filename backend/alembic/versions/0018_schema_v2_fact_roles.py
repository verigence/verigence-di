"""Schema V2 fact-role and profile extraction-key foundation.

Additive foundation for role-safe document extraction. Before any V2 changes are
applied, the migration takes a one-time data snapshot of every V1 table touched
by the Schema V2 migrations into the separate ``docintel_v1_backup`` schema.
The operational ``docintel`` tables remain the runtime source of truth while the
V2 implementation is validated; the snapshot provides a deterministic rollback
and comparison baseline without renaming or deleting existing tables.

A canonical field keeps one business meaning (for example
``vehicle_registration_number``) while a new extraction-profile field may use
document-native output wording and an effective fact role (for example
SUBJECT_VEHICLE vs EXCHANGE_VEHICLE).

Existing published extraction-profile children are immutable by design. For that
reason historical rows are NOT backfilled or edited: ``extraction_key`` remains
NULL on them and runtime code must fall back to the canonical field key. All new
Schema V2 profile fields set ``extraction_key`` explicitly.

Effective role is stamped at persistence time. A profile-field override wins;
otherwise the document-level default is used. A second trigger copies the exact
role from the immutable extracted fact to the accepted/current value. This lets
existing worker inserts remain backward compatible while role propagation is
introduced safely and gives the sandbox an end-to-end collision test before the
more complex multi-role-in-one-document extraction-key work begins.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-29
"""
from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_ALLOWED_ROLES_SQL = """
'UNSPECIFIED',
'SUBJECT_VEHICLE',
'EXCHANGE_VEHICLE',
'SUBJECT_TRANSACTION',
'CUSTOMER',
'PAYER',
'TRANSFEROR',
'TRANSFEREE',
'ORGANISATION'
"""


def _snapshot_v1_tables() -> None:
    """Take an idempotent pre-V2 data snapshot outside the operational schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS docintel_v1_backup")
    op.execute("""
        DO $$
        DECLARE
            table_name text;
        BEGIN
            FOREACH table_name IN ARRAY ARRAY[
                'documents',
                'extraction_profile_fields',
                'extracted_facts',
                'document_field_values',
                'normalization_rule_catalog',
                'validation_rule_catalog',
                'document_types',
                'tenant_document_types',
                'canonical_fields',
                'extraction_profiles',
                'profile_field_normalizers',
                'profile_field_validators'
            ]
            LOOP
                IF to_regclass('docintel.' || table_name) IS NOT NULL
                   AND to_regclass('docintel_v1_backup.' || table_name) IS NULL THEN
                    EXECUTE format(
                        'CREATE TABLE docintel_v1_backup.%I AS TABLE docintel.%I WITH DATA',
                        table_name,
                        table_name
                    );
                END IF;
            END LOOP;
        END
        $$
    """)


def upgrade() -> None:
    # Never begin V2 mutation without a recoverable V1 baseline. The snapshot is
    # idempotent and lives in a separate schema so normal runtime queries cannot
    # accidentally hit backup tables.
    _snapshot_v1_tables()

    # Document-level default. Individual profile fields may override this.
    op.execute("""
        ALTER TABLE docintel.documents
        ADD COLUMN IF NOT EXISTS default_fact_role varchar(40)
            NOT NULL DEFAULT 'UNSPECIFIED'
    """)

    # Separate the provider-facing extraction key from the canonical business
    # field. Existing published profile rows remain NULL here so their immutable
    # child rows are never mutated. Runtime falls back to cf.field_key.
    op.execute("""
        ALTER TABLE docintel.extraction_profile_fields
        ADD COLUMN IF NOT EXISTS extraction_key varchar(160)
    """)
    op.execute("""
        ALTER TABLE docintel.extraction_profile_fields
        ADD COLUMN IF NOT EXISTS fact_role_override varchar(40)
            NOT NULL DEFAULT 'UNSPECIFIED'
    """)

    # Persist the effective role on immutable machine facts and accepted/current
    # values so downstream consumers never need to reconstruct role from today's
    # profile configuration.
    op.execute("""
        ALTER TABLE docintel.extracted_facts
        ADD COLUMN IF NOT EXISTS fact_role varchar(40)
            NOT NULL DEFAULT 'UNSPECIFIED'
    """)
    op.execute("""
        ALTER TABLE docintel.document_field_values
        ADD COLUMN IF NOT EXISTS fact_role varchar(40)
            NOT NULL DEFAULT 'UNSPECIFIED'
    """)

    # Controlled vocabulary. Null is never a role; unknown context is the
    # explicit UNSPECIFIED value so joins and uniqueness remain deterministic.
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_documents_default_fact_role'
                  AND conrelid = 'docintel.documents'::regclass
            ) THEN
                ALTER TABLE docintel.documents
                ADD CONSTRAINT ck_documents_default_fact_role
                CHECK (default_fact_role IN ({_ALLOWED_ROLES_SQL}));
            END IF;
        END $$
    """)
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_extraction_profile_fields_fact_role'
                  AND conrelid = 'docintel.extraction_profile_fields'::regclass
            ) THEN
                ALTER TABLE docintel.extraction_profile_fields
                ADD CONSTRAINT ck_extraction_profile_fields_fact_role
                CHECK (fact_role_override IN ({_ALLOWED_ROLES_SQL}));
            END IF;
        END $$
    """)
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_extracted_facts_fact_role'
                  AND conrelid = 'docintel.extracted_facts'::regclass
            ) THEN
                ALTER TABLE docintel.extracted_facts
                ADD CONSTRAINT ck_extracted_facts_fact_role
                CHECK (fact_role IN ({_ALLOWED_ROLES_SQL}));
            END IF;
        END $$
    """)
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_document_field_values_fact_role'
                  AND conrelid = 'docintel.document_field_values'::regclass
            ) THEN
                ALTER TABLE docintel.document_field_values
                ADD CONSTRAINT ck_document_field_values_fact_role
                CHECK (fact_role IN ({_ALLOWED_ROLES_SQL}));
            END IF;
        END $$
    """)

    # Existing uniqueness assumed one canonical field per profile. Schema V2
    # permits the same canonical fact in two roles, while every explicit
    # provider-facing extraction key remains unique inside its profile.
    op.execute("""
        ALTER TABLE docintel.extraction_profile_fields
        DROP CONSTRAINT IF EXISTS extraction_profile_fields_profile_id_canonical_field_id_key
    """)
    op.execute("""
        DROP INDEX IF EXISTS docintel.extraction_profile_fields_profile_id_canonical_field_id_key
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_extraction_profile_field_key
        ON docintel.extraction_profile_fields(profile_id, extraction_key)
        WHERE extraction_key IS NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_extraction_profile_canonical_role
        ON docintel.extraction_profile_fields(
            profile_id, canonical_field_id, fact_role_override
        )
    """)

    # Current accepted values are unique per document + canonical + effective
    # role. This prevents exchange facts from overwriting subject-vehicle facts.
    op.execute("DROP INDEX IF EXISTS docintel.uq_document_current_field_value")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_document_current_field_value
        ON docintel.document_field_values(
            tenant_id, document_id, canonical_field_id, fact_role
        )
        WHERE is_current = true
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_extracted_facts_doc_field_role
        ON docintel.extracted_facts(
            tenant_id, document_id, canonical_field_id, fact_role, created_at_utc DESC
        )
    """)

    # Derive and freeze the effective role when an immutable extracted fact is
    # inserted. No published profile child is edited.
    op.execute("""
        CREATE OR REPLACE FUNCTION docintel.set_extracted_fact_role()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_override varchar(40);
            v_default varchar(40);
        BEGIN
            SELECT epf.fact_role_override
              INTO v_override
              FROM docintel.extraction_profile_fields epf
             WHERE epf.profile_field_id = NEW.profile_field_id;

            SELECT d.default_fact_role
              INTO v_default
              FROM docintel.documents d
             WHERE d.tenant_id = NEW.tenant_id
               AND d.document_id = NEW.document_id;

            NEW.fact_role := CASE
                WHEN COALESCE(v_override, 'UNSPECIFIED') <> 'UNSPECIFIED'
                    THEN v_override
                ELSE COALESCE(v_default, 'UNSPECIFIED')
            END;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_set_extracted_fact_role ON docintel.extracted_facts")
    op.execute("""
        CREATE TRIGGER trg_set_extracted_fact_role
        BEFORE INSERT ON docintel.extracted_facts
        FOR EACH ROW EXECUTE FUNCTION docintel.set_extracted_fact_role()
    """)

    # The accepted/current value must carry the exact immutable fact role rather
    # than re-resolving profile/document configuration at a later point in time.
    op.execute("""
        CREATE OR REPLACE FUNCTION docintel.set_document_field_value_role()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_fact_role varchar(40);
        BEGIN
            IF NEW.source_extracted_fact_id IS NOT NULL THEN
                SELECT ef.fact_role
                  INTO v_fact_role
                  FROM docintel.extracted_facts ef
                 WHERE ef.tenant_id = NEW.tenant_id
                   AND ef.extracted_fact_id = NEW.source_extracted_fact_id;
                NEW.fact_role := COALESCE(v_fact_role, NEW.fact_role, 'UNSPECIFIED');
            ELSE
                NEW.fact_role := COALESCE(NEW.fact_role, 'UNSPECIFIED');
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_set_document_field_value_role ON docintel.document_field_values")
    op.execute("""
        CREATE TRIGGER trg_set_document_field_value_role
        BEFORE INSERT ON docintel.document_field_values
        FOR EACH ROW EXECUTE FUNCTION docintel.set_document_field_value_role()
    """)


def downgrade() -> None:
    # Role-bearing evidence cannot safely be collapsed automatically. Restore or
    # compare against docintel_v1_backup (or the pre-V2 database snapshot) instead.
    raise RuntimeError(
        "0018 is safety-nonreversible in place; restore the docintel_v1_backup baseline"
    )
