from __future__ import annotations

import argparse
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg

PROFILE_NAME = "Schema V2 Wave 1 Draft"


def _sandbox_url(source: str, sandbox_host: str) -> str:
    source = source.replace("postgresql+asyncpg://", "postgresql://", 1)
    source = source.replace("postgres://", "postgresql://", 1)
    parsed = urlsplit(source)
    if not parsed.hostname or "@" not in parsed.netloc:
        raise RuntimeError("DI_DATABASE_URL is not a credentialed PostgreSQL URL")
    userinfo = parsed.netloc.rsplit("@", 1)[0]
    port = f":{parsed.port}" if parsed.port else ""
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop("ssl", None)
    query["sslmode"] = "require"
    return urlunsplit((
        "postgresql",
        f"{userinfo}@{sandbox_host}{port}",
        parsed.path or "/neondb",
        urlencode(query),
        "",
    ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sandbox-host", required=True)
    args = parser.parse_args()

    source_url = os.environ.get("DI_DATABASE_URL", "").strip()
    if not source_url:
        raise SystemExit("DI_DATABASE_URL is missing from the Railway service environment")
    url = _sandbox_url(source_url, args.sandbox_host)

    checks: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(f"{name}={'PASS' if ok else 'FAIL'}" + (f" ({detail})" if detail else ""))

    def rows(cur, sql: str, params=None):
        cur.execute(sql, params)
        return cur.fetchall()

    def scalar(cur, sql: str, params=None):
        cur.execute(sql, params)
        row = cur.fetchone()
        return None if row is None else row[0]

    expected_counts = {
        "gst_certificate": 17,
        "corporate_id": 18,
        "bank_approval_letter": 36,
        "valuation_report": 42,
    }

    with psycopg.connect(url, connect_timeout=20) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                readonly = scalar(cur, "SHOW transaction_read_only")
                record("READ_ONLY_TRANSACTION", readonly == "on", f"value={readonly}")
                record("SANDBOX_HOST_TARGET", conn.info.host == args.sandbox_host, f"host={conn.info.host}")

                profile_rows = rows(cur, """
                    SELECT dt.document_type_key, ep.status, ep.published_at_utc,
                           COUNT(epf.profile_field_id)::int AS field_count
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
                    LEFT JOIN docintel.extraction_profile_fields epf ON epf.profile_id = ep.profile_id
                    WHERE ep.profile_name = %s
                    GROUP BY dt.document_type_key, ep.status, ep.published_at_utc
                    ORDER BY dt.document_type_key
                """, (PROFILE_NAME,))
                actual_counts = {r[0]: r[3] for r in profile_rows}
                record("WAVE1_PROFILE_SET", set(actual_counts) == set(expected_counts), f"profiles={len(profile_rows)}")
                record("WAVE1_PROFILE_FIELD_COUNTS", actual_counts == expected_counts, f"counts={actual_counts}")
                record("WAVE1_PROFILES_DRAFT", all(r[1] == "DRAFT" and r[2] is None for r in profile_rows))

                role_rows = rows(cur, """
                    SELECT dt.document_type_key, cf.field_key,
                           epf.extraction_key, epf.fact_role_override
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
                    JOIN docintel.extraction_profile_fields epf ON epf.profile_id = ep.profile_id
                    JOIN docintel.canonical_fields cf ON cf.canonical_field_id = epf.canonical_field_id
                    WHERE ep.profile_name = %s
                      AND epf.extraction_key = 'chassis_number'
                      AND dt.document_type_key IN ('bank_approval_letter', 'valuation_report')
                    ORDER BY dt.document_type_key
                """, (PROFILE_NAME,))
                role_map = {r[0]: (r[1], r[2], r[3]) for r in role_rows}
                record(
                    "SUBJECT_EXCHANGE_CHASSIS_ROLE_ISOLATION",
                    role_map == {
                        "bank_approval_letter": ("chassis_number", "chassis_number", "SUBJECT_VEHICLE"),
                        "valuation_report": ("chassis_number", "chassis_number", "EXCHANGE_VEHICLE"),
                    },
                    f"rows={len(role_rows)}",
                )

                forbidden = scalar(cur, """
                    SELECT COUNT(*)::int
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.extraction_profile_fields epf ON epf.profile_id = ep.profile_id
                    WHERE ep.profile_name = %s
                      AND epf.extraction_key IN ('financier_type', 'valuation_platform')
                """, (PROFILE_NAME,))
                record("DERIVED_REFERENCE_FIELDS_NOT_EXTRACTED", forbidden == 0, f"violations={forbidden}")

                dupes = scalar(cur, """
                    SELECT COUNT(*)::int FROM (
                        SELECT epf.profile_id, epf.canonical_field_id, epf.fact_role_override, COUNT(*)
                        FROM docintel.extraction_profiles ep
                        JOIN docintel.extraction_profile_fields epf ON epf.profile_id = ep.profile_id
                        WHERE ep.profile_name = %s
                        GROUP BY epf.profile_id, epf.canonical_field_id, epf.fact_role_override
                        HAVING COUNT(*) > 1
                    ) d
                """, (PROFILE_NAME,))
                record("NO_DUPLICATE_CANONICAL_ROLE_MAPPINGS", dupes == 0, f"violations={dupes}")

                n_rules = dict(rows(cur, """
                    SELECT rule_key, status
                    FROM docintel.normalization_rule_catalog
                    WHERE rule_key IN (
                        'schema_v2.scalar_literal_parse',
                        'schema_v2.date_iso8601',
                        'schema_v2.structured_literal_parse'
                    )
                """))
                record("SCHEMA_V2_NORMALIZERS_ACTIVE", n_rules == {
                    "schema_v2.scalar_literal_parse": "ACTIVE",
                    "schema_v2.date_iso8601": "ACTIVE",
                    "schema_v2.structured_literal_parse": "ACTIVE",
                }, f"rules={len(n_rules)}")

                v_rules = dict(rows(cur, """
                    SELECT rule_key, status
                    FROM docintel.validation_rule_catalog
                    WHERE rule_key = 'schema_v2.structured_shape'
                """))
                record("SCHEMA_V2_VALIDATOR_ACTIVE", v_rules.get("schema_v2.structured_shape") == "ACTIVE")

                structured_normalizers = scalar(cur, """
                    SELECT COUNT(*)::int
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.extraction_profile_fields epf ON epf.profile_id=ep.profile_id
                    JOIN docintel.profile_field_normalizers pfn ON pfn.profile_field_id=epf.profile_field_id
                    WHERE ep.profile_name=%s AND pfn.rule_key='schema_v2.structured_literal_parse'
                """, (PROFILE_NAME,))
                structured_validators = scalar(cur, """
                    SELECT COUNT(*)::int
                    FROM docintel.extraction_profiles ep
                    JOIN docintel.extraction_profile_fields epf ON epf.profile_id=ep.profile_id
                    JOIN docintel.profile_field_validators pfv ON pfv.profile_field_id=epf.profile_field_id
                    WHERE ep.profile_name=%s AND pfv.rule_key='schema_v2.structured_shape'
                """, (PROFILE_NAME,))
                record("STRUCTURED_PROFILE_NORMALIZERS_BOUND", structured_normalizers == 5, f"count={structured_normalizers}")
                record("STRUCTURED_PROFILE_VALIDATORS_BOUND", structured_validators == 5, f"count={structured_validators}")

                di_expected = {
                    ("documents", "default_fact_role"),
                    ("extraction_profile_fields", "extraction_key"),
                    ("extraction_profile_fields", "fact_role_override"),
                    ("extracted_facts", "fact_role"),
                    ("document_field_values", "fact_role"),
                }
                di_columns = set(rows(cur, """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema='docintel'
                      AND (table_name, column_name) IN (
                        ('documents','default_fact_role'),
                        ('extraction_profile_fields','extraction_key'),
                        ('extraction_profile_fields','fact_role_override'),
                        ('extracted_facts','fact_role'),
                        ('document_field_values','fact_role')
                      )
                """))
                record("DI_ROLE_COLUMNS_PRESENT", di_columns == di_expected, f"count={len(di_columns)}")

                audit_expected = {
                    "fact_role", "di_value_version_no", "di_extracted_fact_id",
                    "di_processing_run_id", "di_extraction_profile_id",
                    "di_extraction_profile_version", "di_invocation_id", "di_pipeline_version",
                }
                audit_columns = {r[0] for r in rows(cur, """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='auditcore' AND table_name='evidence_facts'
                      AND column_name IN (
                        'fact_role','di_value_version_no','di_extracted_fact_id',
                        'di_processing_run_id','di_extraction_profile_id',
                        'di_extraction_profile_version','di_invocation_id','di_pipeline_version'
                      )
                """)}
                record("AUDIT_LINEAGE_COLUMNS_PRESENT", audit_columns == audit_expected, f"count={len(audit_columns)}")

                di_indexes_expected = {
                    "uq_extraction_profile_field_key",
                    "uq_extraction_profile_canonical_role",
                    "uq_document_current_field_value",
                    "ix_extracted_facts_doc_field_role",
                }
                di_indexes = {r[0] for r in rows(cur, """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname='docintel'
                      AND indexname IN (
                        'uq_extraction_profile_field_key',
                        'uq_extraction_profile_canonical_role',
                        'uq_document_current_field_value',
                        'ix_extracted_facts_doc_field_role'
                      )
                """)}
                record("DI_ROLE_INDEXES_PRESENT", di_indexes == di_indexes_expected, f"count={len(di_indexes)}")

                audit_indexes_expected = {"ix_evidence_facts_role_current", "ix_evidence_facts_di_lineage"}
                audit_indexes = {r[0] for r in rows(cur, """
                    SELECT indexname FROM pg_indexes
                    WHERE schemaname='auditcore'
                      AND indexname IN ('ix_evidence_facts_role_current','ix_evidence_facts_di_lineage')
                """)}
                record("AUDIT_LINEAGE_INDEXES_PRESENT", audit_indexes == audit_indexes_expected, f"count={len(audit_indexes)}")

                triggers = {r[0] for r in rows(cur, """
                    SELECT trigger_name
                    FROM information_schema.triggers
                    WHERE trigger_schema='docintel'
                      AND trigger_name IN ('trg_set_extracted_fact_role','trg_set_document_field_value_role')
                """)}
                record("ROLE_PROPAGATION_TRIGGERS_PRESENT", triggers == {
                    "trg_set_extracted_fact_role", "trg_set_document_field_value_role"
                }, f"count={len(triggers)}")

                current_dupes = scalar(cur, """
                    SELECT COUNT(*)::int FROM (
                        SELECT tenant_id, document_id, canonical_field_id, fact_role, COUNT(*)
                        FROM docintel.document_field_values
                        WHERE is_current = true
                        GROUP BY tenant_id, document_id, canonical_field_id, fact_role
                        HAVING COUNT(*) > 1
                    ) x
                """)
                record("NO_CURRENT_VALUE_ROLE_COLLISIONS", current_dupes == 0, f"violations={current_dupes}")

                di_version = scalar(cur, "SELECT version_num FROM docintel.alembic_version")
                record("DI_MIGRATION_VERSION_0020", di_version == "0020", f"version={di_version}")

                public_alembic = scalar(cur, "SELECT to_regclass('public.alembic_version')::text")
                audit_version = scalar(cur, "SELECT version_num FROM public.alembic_version") if public_alembic else None
                record("AUDIT_MIGRATION_VERSION_0035", audit_version == "0035_schema_v2_fact_lineage", f"version={audit_version}")

                lineage_bad = scalar(cur, """
                    SELECT COUNT(*)::int
                    FROM auditcore.evidence_facts
                    WHERE di_extracted_fact_id IS NOT NULL
                      AND (
                        di_processing_run_id IS NULL OR
                        di_extraction_profile_id IS NULL OR
                        di_extraction_profile_version IS NULL OR
                        di_invocation_id IS NULL OR
                        di_pipeline_version IS NULL
                      )
                """)
                lineage_rows = scalar(cur, """
                    SELECT COUNT(*)::int FROM auditcore.evidence_facts
                    WHERE di_extracted_fact_id IS NOT NULL
                """)
                record("AUDIT_LINEAGE_ROWS_CONSISTENT", lineage_bad == 0, f"lineage_rows={lineage_rows}, violations={lineage_bad}")

    failed = [name for name, ok, _ in checks if not ok]
    print(f"TOTAL_CHECKS={len(checks)}")
    print(f"FAILED_CHECKS={len(failed)}")
    if failed:
        print("FAILED_NAMES=" + ",".join(failed))
        print("OVERALL_SQL_GATE=FAIL")
        return 1
    print("OVERALL_SQL_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
