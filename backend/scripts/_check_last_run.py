"""Quick diagnostic — show Gemini invocation outcome for the last pan_card run."""
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

    # 1. Last 3 pan_card documents
    rows = await conn.fetch(
        """
        SELECT
            d.document_id,
            d.processing_status,
            d.confidence_score,
            da.mime_type AS stored_mime,
            da.logical_object_key,
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
        ORDER BY pi.started_at_utc DESC NULLS LAST
        LIMIT 5
        """
    )
    print("=== PROCESSOR INVOCATIONS (last 5 pan_card) ===\n")
    for r in rows:
        print(f"doc={str(r['document_id'])[:8]}  proc={r['processing_status']}"
              f"  conf={r['confidence_score']}  mime={r['stored_mime']}")
        print(f"  capability={r['capability']}  adapter={r['adapter_key']}"
              f"  outcome={r['outcome']}")
        if r['error_code']:
            print(f"  ERROR: {r['error_code']} — {r['error_detail']}")
        if r['usage_metrics']:
            print(f"  usage={json.dumps(r['usage_metrics'], default=str)}")
        print()

    # 2. extracted_facts for the most recent pan_card doc
    print("=== EXTRACTED FACTS (most recent pan_card) ===\n")
    facts = await conn.fetch(
        """
        SELECT
            d.document_id,
            ef.field_key,
            ef.raw_value,
            ef.normalized_value,
            ef.confidence_score,
            ef.found_status
        FROM docintel.documents d
        JOIN docintel.extracted_facts ef ON ef.document_id = d.document_id
        WHERE d.document_type_hint_key = 'pan_card'
        ORDER BY ef.created_at_utc DESC NULLS LAST
        LIMIT 10
        """
    )
    for f in facts:
        print(f"doc={str(f['document_id'])[:8]}  key={f['field_key']:<25}"
              f"  status={f['found_status']}  raw={str(f['raw_value'])[:40]}"
              f"  norm={str(f['normalized_value'])[:40]}  conf={f['confidence_score']}")
    if not facts:
        print("  (no extracted_facts rows)")

    await conn.close()

asyncio.run(main())
