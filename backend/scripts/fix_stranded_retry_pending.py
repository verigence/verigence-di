"""
One-shot script: move pre-D24 RETRY_PENDING documents to FAILED/NOT_CONFIRMED
and insert backout_jobs rows for them.

Run:
    DI_DATABASE_URL="postgresql://..." python scripts/fix_stranded_retry_pending.py
"""
import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg

TTL_HOURS = 12

DB_URL = (
    os.environ.get("DI_DATABASE_URL", "")
    .replace("postgresql+asyncpg://", "postgresql://")
    .replace("?ssl=require", "")
    .replace("?sslmode=require", "")
)


async def fix() -> None:
    conn = await asyncpg.connect(DB_URL, ssl="require")

    docs = await conn.fetch(
        """
        SELECT d.tenant_id, d.document_id,
               pj.processing_job_id, pj.error_code, pj.error_detail
        FROM docintel.documents d
        JOIN docintel.processing_jobs pj
          ON pj.tenant_id = d.tenant_id AND pj.document_id = d.document_id
        WHERE d.processing_status = 'RETRY_PENDING'
          AND pj.job_status       = 'FAILED'
        ORDER BY d.registered_at_utc
        """
    )

    print(f"Found {len(docs)} stranded RETRY_PENDING documents to fix")
    if not docs:
        await conn.close()
        return

    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=TTL_HOURS)

    async with conn.transaction():
        for doc in docs:
            tenant_id    = doc["tenant_id"]
            document_id  = doc["document_id"]
            job_id       = doc["processing_job_id"]
            error_code   = doc["error_code"] or "PRE_D24_STRANDED"
            error_detail = (
                doc["error_detail"]
                or "Document was RETRY_PENDING before backout queue was deployed"
            )
            backout_id   = uuid.uuid4()

            # 1. Move document to FAILED / NOT_CONFIRMED
            await conn.execute(
                """
                UPDATE docintel.documents
                SET processing_status         = 'FAILED',
                    confirmation_status       = 'NOT_CONFIRMED',
                    processing_failure_code   = $1,
                    processing_failure_detail = $2,
                    updated_at_utc            = $3
                WHERE tenant_id       = $4
                  AND document_id     = $5
                  AND processing_status = 'RETRY_PENDING'
                """,
                error_code,
                error_detail,
                now,
                tenant_id,
                document_id,
            )

            # 2. Insert backout row with explicit cast for uuid columns
            await conn.execute(
                """
                INSERT INTO docintel.backout_jobs AS bj
                    (tenant_id, backout_job_id, document_id, processing_job_id,
                     processing_run_id, error_class, error_code, error_detail,
                     expires_at_utc, created_at_utc)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (tenant_id, document_id) DO UPDATE
                    SET backout_job_id    = EXCLUDED.backout_job_id,
                        processing_job_id = EXCLUDED.processing_job_id,
                        processing_run_id = EXCLUDED.processing_run_id,
                        error_class       = EXCLUDED.error_class,
                        error_code        = EXCLUDED.error_code,
                        error_detail      = EXCLUDED.error_detail,
                        expires_at_utc    = EXCLUDED.expires_at_utc,
                        created_at_utc    = EXCLUDED.created_at_utc
                """,
                tenant_id,
                backout_id,
                document_id,
                job_id,
                None,          # processing_run_id — nullable
                "RETRYABLE",
                error_code,
                error_detail,
                expires_at,
                now,
            )

            print(
                f"  Fixed: tenant={tenant_id}  "
                f"doc={document_id}  code={error_code}"
            )

    # Verify
    retry_remaining = await conn.fetchval(
        "SELECT COUNT(*) FROM docintel.documents WHERE processing_status = 'RETRY_PENDING'"
    )
    failed_count = await conn.fetchval(
        "SELECT COUNT(*) FROM docintel.documents "
        "WHERE processing_status = 'FAILED' AND upload_status = 'FIT'"
    )
    backout_count = await conn.fetchval(
        "SELECT COUNT(*) FROM docintel.backout_jobs"
    )

    print()
    print("=== Verification ===")
    print(f"  RETRY_PENDING remaining : {retry_remaining}  (should be 0)")
    print(f"  FAILED FIT documents    : {failed_count}")
    print(f"  backout_jobs rows       : {backout_count}")

    await conn.close()


asyncio.run(fix())
