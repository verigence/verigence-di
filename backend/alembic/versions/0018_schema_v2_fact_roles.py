"""Schema V2 fact-role and profile extraction-key foundation.

Additive foundation for role-safe document extraction.  A canonical field keeps
one business meaning (for example ``vehicle_registration_number``) while an
extraction-profile field may use document-native output wording and an effective
fact role (for example SUBJECT_VEHICLE vs EXCHANGE_VEHICLE).

The migration is intentionally idempotent because the Schema V2 sandbox may be
exercised before the parent environment has been brought through the complete
existing Alembic chain.  Production promotion still happens through normal
Alembic ordering after revision 0017.

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


def upgrade() -> None:
    # Document-level default.  Individual profile fields may override this.
    op.execute("""
        ALTER TABLE docintel.documents
        ADD COLUMN IF NOT EXISTS default_fact_role varchar(40)
            NOT NULL DEFAULT 'UNSPECIFIED'
    """)

    # Separate the provider-facing extraction key from the canonical business
    # field.  This is required for documents such as a Cost Sheet that can carry
    # two instances of the same canonical fact in different roles.
    op.execute("""
        ALTER TABLE docintel.extraction_profile_fields
        ADD COLUMN IF NOT EXISTS extraction_key varchar(160)
    """)
    op.execute("""
        ALTER TABLE docintel.extraction_profile_fields
        ADD COLUMN IF NOT EXISTS fact_role_override varchar(40)
            NOT NULL DEFAULT 'UNSPECIFIED'
    """)
    op.execute("""
        UPDATE docintel.extraction_profile_fields epf
        SET extraction_key = cf.field_key
        FROM docintel.canonical_fields cf
        WHERE epf.canonical_field_id = cf.canonical_field_id
          AND epf.extraction_key IS NULL
    """)
    op.execute("""
        ALTER TABLE docintel.extraction_profile_fields
        ALTER COLUMN extraction_key SET NOT NULL
    """)

    # Persist the effective role on immutable machine facts and accepted/current
    # values so downstream consumers never need to reconstruct role from today’s
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

    # Controlled vocabulary.  Null is never a role; UNKNOWN context is the
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

    # Existing uniqueness assumed one canonical field per profile.  Schema V2
    # permits the same canonical fact in two roles, while still requiring every
    # provider-facing extraction key to be unique inside a profile.
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
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_extraction_profile_canonical_role
        ON docintel.extraction_profile_fields(
            profile_id, canonical_field_id, fact_role_override
        )
    """)

    # Current accepted values are unique per document + canonical + effective
    # role.  This prevents exchange facts from overwriting subject-vehicle facts.
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


def downgrade() -> None:
    # Downgrade is intentionally conservative.  Role-bearing evidence may have
    # been created after upgrade; collapsing it back to a role-less uniqueness
    # model could silently merge subject and exchange facts.  A rollback must be
    # performed by restoring the pre-Schema-V2 database branch/snapshot.
    raise RuntimeError(
        "0018 is safety-nonreversible in place; restore the pre-schema-v2 Neon branch"
    )
