"""Add AI-assisted DI configuration authoring proposal store.

Additive only. Existing document intake, extraction, fields and analyse tables/APIs
are not changed.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-24
"""
from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS docintel.configuration_proposals (
            tenant_id                       varchar(128) NOT NULL,
            proposal_id                     uuid NOT NULL,
            status                          varchar(20) NOT NULL DEFAULT 'PROPOSED'
                                              CHECK (status IN (
                                                'PROPOSED','DRAFT','TESTED','APPROVED',
                                                'PUBLISHED','RETIRED','REJECTED'
                                              )),
            sample_storage_key              text NOT NULL,
            sample_filename                 varchar(500) NOT NULL,
            sample_mime_type                varchar(160) NOT NULL,
            sample_size_bytes               bigint NOT NULL CHECK (sample_size_bytes > 0),
            proposed_document_type_key      varchar(120) NOT NULL,
            proposed_display_name           varchar(240) NOT NULL,
            physical_form_type              varchar(20) NOT NULL
                                              CHECK (physical_form_type IN (
                                                'GOVT_ID','PRINTABLE','HANDWRITTEN','ADDITIONAL'
                                              )),
            proposal_payload                jsonb NOT NULL,
            latest_test_result              jsonb,
            generated_by_model              varchar(120),
            prompt_tokens                   integer NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
            response_tokens                 integer NOT NULL DEFAULT 0 CHECK (response_tokens >= 0),
            created_by_actor_id             varchar(160) NOT NULL,
            approved_by_actor_id            varchar(160),
            published_by_actor_id           varchar(160),
            materialized_document_type_id   uuid,
            materialized_profile_id         uuid,
            created_at_utc                  timestamptz NOT NULL,
            updated_at_utc                  timestamptz NOT NULL,
            approved_at_utc                 timestamptz,
            published_at_utc                timestamptz,
            PRIMARY KEY (tenant_id, proposal_id),
            FOREIGN KEY (tenant_id) REFERENCES docintel.tenant_settings(tenant_id),
            FOREIGN KEY (materialized_document_type_id)
              REFERENCES docintel.document_types(document_type_id),
            FOREIGN KEY (materialized_profile_id)
              REFERENCES docintel.extraction_profiles(profile_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_configuration_proposals_tenant_status
        ON docintel.configuration_proposals(tenant_id, status, created_at_utc DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_configuration_proposals_document_type
        ON docintel.configuration_proposals(tenant_id, proposed_document_type_key)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS docintel.configuration_proposals")
