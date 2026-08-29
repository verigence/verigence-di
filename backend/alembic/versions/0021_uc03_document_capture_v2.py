"""Add isolated UC03 Document Capture V2 upload/classification state.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-29

The legacy document intake, adapter and processing-job contracts are unchanged.
V2 classifies unknown uploads first, then hands the accepted type to the existing
Schema V2 extraction pipeline as a hint.
"""
from __future__ import annotations

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE docintel.document_capture_v2_uploads (
            tenant_id                   varchar(128) NOT NULL,
            document_id                 uuid NOT NULL,
            audit_storage_context_id    uuid NOT NULL,
            external_context_ref        text NOT NULL,
            phase                       varchar(20) NOT NULL
                                        CHECK (phase IN ('BOOKING','DELIVERY')),
            client_upload_id            varchar(160) NOT NULL,
            logical_object_key          varchar(1000) NOT NULL,
            original_filename           varchar(500) NOT NULL,
            declared_mime_type          varchar(160),
            candidate_document_type_keys jsonb NOT NULL
                                        CHECK (
                                            jsonb_typeof(candidate_document_type_keys)='array'
                                            AND jsonb_array_length(candidate_document_type_keys)>0
                                        ),
            state                       varchar(30) NOT NULL DEFAULT 'RECEIVING'
                                        CHECK (state IN (
                                            'RECEIVING','STORED','CLASSIFYING','CLASSIFIED',
                                            'UNKNOWN','FAILED','DELETED'
                                        )),
            classified_document_type_key varchar(120),
            classification_confidence   numeric(5,2)
                                        CHECK (
                                            classification_confidence IS NULL
                                            OR (classification_confidence >= 0
                                                AND classification_confidence <= 100)
                                        ),
            failure_code                varchar(120),
            failure_detail              text,
            stored_at_utc               timestamptz,
            classified_at_utc           timestamptz,
            created_at_utc              timestamptz NOT NULL DEFAULT now(),
            updated_at_utc              timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, document_id),
            UNIQUE (tenant_id, external_context_ref, phase, client_upload_id),
            FOREIGN KEY (tenant_id, document_id)
                REFERENCES docintel.documents(tenant_id, document_id),
            FOREIGN KEY (tenant_id, audit_storage_context_id)
                REFERENCES docintel.audit_storage_contexts(tenant_id, storage_context_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_capture_v2_uploads_context
        ON docintel.document_capture_v2_uploads
            (tenant_id, external_context_ref, phase, state, created_at_utc)
        """
    )
    op.execute(
        "ALTER TABLE docintel.document_capture_v2_uploads ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY document_capture_v2_uploads_tenant_isolation
        ON docintel.document_capture_v2_uploads
        USING (tenant_id = docintel.current_tenant_id())
        WITH CHECK (tenant_id = docintel.current_tenant_id())
        """
    )

    # This is a global worker queue, deliberately matching the existing
    # processing_jobs pattern. The worker learns tenant_id when it claims a row,
    # therefore tenant RLS must not hide rows before claim.
    op.execute(
        """
        CREATE TABLE docintel.document_capture_v2_classification_jobs (
            tenant_id               varchar(128) NOT NULL,
            classification_job_id   uuid NOT NULL DEFAULT gen_random_uuid(),
            document_id             uuid NOT NULL,
            job_status              varchar(20) NOT NULL DEFAULT 'PENDING'
                                    CHECK (job_status IN (
                                        'PENDING','RUNNING','COMPLETED','FAILED','CANCELLED'
                                    )),
            due_at_utc              timestamptz NOT NULL DEFAULT now(),
            attempt_no              integer NOT NULL DEFAULT 1 CHECK (attempt_no > 0),
            locked_by               varchar(160),
            locked_at_utc           timestamptz,
            started_at_utc          timestamptz,
            completed_at_utc        timestamptz,
            error_code              varchar(120),
            error_detail            text,
            created_at_utc          timestamptz NOT NULL DEFAULT now(),
            updated_at_utc          timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, classification_job_id),
            UNIQUE (tenant_id, document_id),
            FOREIGN KEY (tenant_id, document_id)
                REFERENCES docintel.documents(tenant_id, document_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_document_capture_v2_classification_claim
        ON docintel.document_capture_v2_classification_jobs
            (job_status, due_at_utc, created_at_utc)
        WHERE job_status='PENDING'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS docintel.document_capture_v2_classification_jobs")
    op.execute("DROP TABLE IF EXISTS docintel.document_capture_v2_uploads")
