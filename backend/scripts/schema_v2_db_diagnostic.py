from __future__ import annotations

import argparse
import os
from urllib.parse import urlsplit

import psycopg


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-host", required=True)
    args = parser.parse_args()

    url = os.environ.get("DI_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DI_DATABASE_URL is required")
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1).replace("postgres://", "postgresql://", 1)

    parsed = urlsplit(url)
    print(f"EXPECTED_HOST={args.expected_host}")
    print(f"URL_HOST_MATCH={'PASS' if parsed.hostname == args.expected_host else 'FAIL'}")

    with psycopg.connect(url, connect_timeout=20) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SHOW transaction_read_only")
                print(f"READ_ONLY_TRANSACTION={'PASS' if cur.fetchone()[0] == 'on' else 'FAIL'}")
                print(f"CONNECTED_HOST={conn.info.host}")

                cur.execute("SELECT to_regclass('docintel.alembic_version')::text")
                if cur.fetchone()[0]:
                    cur.execute("SELECT version_num FROM docintel.alembic_version")
                    print(f"DI_ALEMBIC_VERSION={cur.fetchone()[0]}")
                else:
                    print("DI_ALEMBIC_VERSION=MISSING")

                cur.execute("SELECT to_regclass('public.alembic_version')::text")
                if cur.fetchone()[0]:
                    cur.execute("SELECT version_num FROM public.alembic_version")
                    print(f"AUDIT_ALEMBIC_VERSION={cur.fetchone()[0]}")
                else:
                    print("AUDIT_ALEMBIC_VERSION=MISSING")

                for schema, table in (
                    ("docintel", "documents"),
                    ("docintel", "extraction_profile_fields"),
                    ("docintel", "extracted_facts"),
                    ("docintel", "document_field_values"),
                    ("docintel", "normalization_rule_catalog"),
                    ("docintel", "validation_rule_catalog"),
                    ("docintel", "extraction_profiles"),
                    ("auditcore", "evidence_facts"),
                ):
                    cur.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema=%s AND table_name=%s
                        ORDER BY ordinal_position
                        """,
                        (schema, table),
                    )
                    cols = [r[0] for r in cur.fetchall()]
                    print(f"TABLE={schema}.{table} EXISTS={'YES' if cols else 'NO'} COLUMN_COUNT={len(cols)}")
                    if table in {
                        "documents", "extraction_profile_fields", "extracted_facts",
                        "document_field_values", "evidence_facts"
                    }:
                        print(f"COLUMNS_{schema}_{table}=" + ",".join(cols))

                cur.execute(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname='docintel'
                      AND indexname IN (
                        'uq_extraction_profile_field_key',
                        'uq_extraction_profile_canonical_role',
                        'uq_document_current_field_value',
                        'ix_extracted_facts_doc_field_role'
                      )
                    ORDER BY indexname
                    """
                )
                print("DI_SCHEMA_V2_INDEXES=" + ",".join(r[0] for r in cur.fetchall()))

                cur.execute(
                    """
                    SELECT trigger_name
                    FROM information_schema.triggers
                    WHERE trigger_schema='docintel'
                      AND trigger_name IN (
                        'trg_set_extracted_fact_role',
                        'trg_set_document_field_value_role'
                      )
                    ORDER BY trigger_name
                    """
                )
                print("DI_SCHEMA_V2_TRIGGERS=" + ",".join(r[0] for r in cur.fetchall()))

                cur.execute(
                    """
                    SELECT rule_key, status
                    FROM docintel.normalization_rule_catalog
                    WHERE rule_key LIKE 'schema_v2.%'
                    ORDER BY rule_key
                    """
                )
                print("DI_SCHEMA_V2_NORMALIZERS=" + ";".join(f"{r[0]}:{r[1]}" for r in cur.fetchall()))

                cur.execute(
                    """
                    SELECT rule_key, status
                    FROM docintel.validation_rule_catalog
                    WHERE rule_key LIKE 'schema_v2.%'
                    ORDER BY rule_key
                    """
                )
                print("DI_SCHEMA_V2_VALIDATORS=" + ";".join(f"{r[0]}:{r[1]}" for r in cur.fetchall()))

                cur.execute(
                    """
                    SELECT dt.document_type_key, ep.profile_name, ep.version_no, ep.status,
                           COUNT(epf.profile_field_id)::int
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.document_types dt ON dt.document_type_id=ep.document_type_id
                    LEFT JOIN docintel.extraction_profile_fields epf ON epf.profile_id=ep.profile_id
                    WHERE dt.document_type_key IN (
                        'gst_certificate','corporate_id','bank_approval_letter','valuation_report'
                    )
                    GROUP BY dt.document_type_key, ep.profile_name, ep.version_no, ep.status
                    ORDER BY dt.document_type_key, ep.version_no
                    """
                )
                for row in cur.fetchall():
                    print("PROFILE=" + "|".join(str(x) for x in row))

    print("DIAGNOSTIC=COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
