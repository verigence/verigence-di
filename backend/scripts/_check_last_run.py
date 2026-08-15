"""Diagnostic — check latest pan_card invocation."""
from __future__ import annotations

import asyncio
import json

import asyncpg

DB_URL = (
    "postgresql://neondb_owner:npg_USy5qjMFdRe7"
    "@ep-royal-pond-ayci3m0f.c-5.us-east-2.aws.neon.tech/neondb"
)

async def main() -> None:
    conn = await asyncpg.connect(DB_URL, ssl="require")

    rows = await conn.fetch(
        """
        SELECT
            d.document_id,
            d.processing_status,
            d.confidence_score,
            da.mime_type AS stored_mime,
            pi.capability,
            pi.adapter_key,
            pi.outcome,
            pi.usage_metrics,
            pi.error_code,
            pi.error_detail,
            pi.started_at_utc
        FROM docintel.documents d
        LEFT JOIN docintel.document_artifacts da
          ON da.document_id = d.document_id
        JOIN docintel.processing_runs pr
          ON pr.document_id = d.document_id
        LEFT JOIN docintel.processor_invocations pi
          ON pi.processing_run_id = pr.processing_run_id
        WHERE d.document_type_hint_key = 'pan_card'
          AND pi.capability = 'VISION_EXTRACTION'
        ORDER BY pi.started_at_utc DESC NULLS LAST
        LIMIT 5
        """
    )
    print("=== VISION_EXTRACTION invocations (last 5 pan_card) ===\n")
    for r in rows:
        print(f"doc={str(r['document_id'])[:8]}  proc={r['processing_status']}"
              f"  conf={r['confidence_score']}  mime={r['stored_mime']}"
              f"  started={r['started_at_utc']}")
        print(f"  outcome={r['outcome']}  adapter={r['adapter_key']}")
        if r['error_code']:
            print(f"  ERROR: {r['error_code']} — {r['error_detail']}")
        if r['usage_metrics']:
            u = r['usage_metrics']
            if isinstance(u, str):
                u = json.loads(u)
            print(f"  usage={json.dumps(u, default=str)}")
        print()

    # Check document_field_values for latest doc
    if rows:
        latest_doc_id = rows[0]['document_id']
        print(f"=== document_field_values for doc {str(latest_doc_id)[:8]} ===\n")
        fv = await conn.fetch(
            """
            SELECT cf.field_key, dfv.current_value, dfv.confidence_score
            FROM docintel.document_field_values dfv
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id = dfv.canonical_field_id
            WHERE dfv.document_id = $1 AND dfv.is_current = true
            ORDER BY cf.field_key
            """,
            latest_doc_id,
        )
        for f in fv:
            print(f"  {f['field_key']:<25} value={str(f['current_value']):<30}  conf={f['confidence_score']}")
        if not fv:
            print("  (no rows)")

    await conn.close()

asyncio.run(main())
