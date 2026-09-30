"""Bring the published customer_ledger extraction profile in line with its schema.

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-29

The published customer_ledger profile (v2, "Customer Ledger Baseline
Extraction") was authored with its own field names while the Gemini schema
(document_ai/schemas/customer_ledger.py) and Audit Core use another set.
The runtime extracts by the PUBLISHED PROFILE's fields (job_runner sends
each field's extraction_key to the provider), so every ledger was stored
under names Audit Core never reads:

  profile v2                 schema / Audit Core
  total_credits          ->  total_credited
  total_debits           ->  total_debited
  ledger_start_date      ->  period_from
  ledger_end_date        ->  period_to
  ledger_reference       ->  ledger_account_code
  (absent)                   ledger_account_name, booking_reference_number,
                             source_system, cash_credit_total, loan_credit,
                             exchange_credit, line_items

so the ledger controls (cash_credit_total, total_credited, total_debited),
the P2 stage (loan_credit, exchange_credit) and the period dates never saw a
value. The startup check (main._validate_schema_profile_consistency) logged
exactly this as schema_profile_mismatch.

This publishes customer_ledger v3 whose enabled fields equal the schema's
keys exactly, and retires v2 (published profiles are immutable, hence a new
version rather than an edit). From the v2 row of the corresponding old key
each new field keeps its aliases, score flags, fact role, subject-matching
flags, manual-correction flag, normalizers and validators. customer_name and
closing_balance stay expected + scored; total_credited becomes expected +
scored too (the ledger's headline figure for Audit Core). The date
plausibility validator (0042/0048) is wired to period_from / period_to.

Ledgers already read with v2 are re-extracted: each unverified PROCESSED
customer_ledger document is put back to RETRY_PENDING (the only state a
non-INITIAL job runs from -- the worker treats a PROCESSED document as
superseded) and gets a NIGHTLY_REPROCESS job (attempt_no >= 3, per
ck_processing_job_attempt_type; INITIAL/EOD_RETRY attempts already exist for
those documents). Documents with an active job or a human verification are
left alone. Forward-only, like 0016/0036/0038/0046/0048.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

_ACTOR = "migration.0051.customer-ledger-profile-schema-parity"
_TYPE_KEY = "customer_ledger"
_DATE_VALIDATOR_RULE_KEY = "date_plausible_range"

# v3 key -> v2 key it replaces (matched on COALESCE(extraction_key, field_key)).
_OLD_KEY_FOR: dict[str, str] = {
    "total_credited": "total_credits",
    "total_debited": "total_debits",
    "period_from": "ledger_start_date",
    "period_to": "ledger_end_date",
    "ledger_account_code": "ledger_reference",
}

# (field_key, canonical data_type, instruction, expected, display_sequence)
# Snapshot of CUSTOMER_LEDGER_SCHEMA (a migration must not import app code);
# tests/test_customer_ledger_profile_parity.py pins it to the schema.
_FIELDS: tuple[tuple[str, str, str, bool, int], ...] = (
    ('dealer_name', 'STRING', 'Dealership/company name whose books the ledger belongs to, exactly as printed', False, 10),
    ('customer_name', 'STRING', 'Customer/party/account name the ledger is maintained for, exactly as printed', True, 20),
    ('ledger_account_name', 'STRING', 'Ledger/account head name exactly as printed when different from the customer name', False, 30),
    ('ledger_account_code', 'IDENTIFIER', 'Ledger/account/party code or number exactly as printed', False, 40),
    ('booking_reference_number', 'STRING', 'Booking/order/deal reference printed on the ledger, if any', False, 50),
    ('source_system', 'STRING', 'Source system when the document visibly identifies it. Allowed values: DMS, TALLY, DEALER, UNKNOWN', False, 60),
    ('period_from', 'DATE', 'Ledger period start date only when explicitly printed', False, 70),
    ('period_to', 'DATE', 'Ledger period end date only when explicitly printed', False, 80),
    ('opening_balance', 'CURRENCY', 'Opening balance only when explicitly printed; keep the printed sign', False, 90),
    ('total_debited', 'CURRENCY', 'Total of the debit column only when explicitly printed as a total; never sum the rows yourself', False, 100),
    ('total_credited', 'CURRENCY', 'Total of the credit column only when explicitly printed as a total; never sum the rows yourself', True, 110),
    ('closing_balance', 'CURRENCY', 'Closing/running balance at the end of the ledger only when explicitly printed; keep the printed sign', True, 120),
    ('cash_credit_total', 'CURRENCY', 'Total of credit entries whose narration/voucher type is cash, only when the ledger prints such a subtotal; do not derive it', False, 130),
    ('loan_credit', 'CURRENCY', 'Credit entry representing bank/financier loan or finance disbursement, only when a row explicitly identifies it; do not infer from amount', False, 140),
    ('exchange_credit', 'CURRENCY', 'Credit entry representing exchange/trade-in adjustment, only when a row explicitly identifies it', False, 150),
    ('line_items', 'JSON', 'JSON array of visible ledger rows. For each row preserve entry_date (date), particulars_raw, voucher_type, voucher_number, debit_amount, credit_amount and running_balance exactly as printed; do not merge rows or compute missing values', False, 160),)

# Carried per field from the v2 row (columns copied verbatim when it exists).
_CARRY = (
    "aliases::text AS aliases", "score_included", "score_weight", "fact_role_override",
    "use_for_subject_matching", "subject_identifier_type", "manual_correction_allowed",
)


def _ledger_type_id(conn: Any) -> Any:
    return conn.execute(
        sa.text(
            "SELECT document_type_id FROM docintel.document_types "
            "WHERE owner_tenant_id IS NULL AND document_type_key=:key AND status='ACTIVE'"
        ),
        {"key": _TYPE_KEY},
    ).scalar_one_or_none()


def _ensure_canonical_field(conn: Any, field_key: str, data_type: str) -> None:
    display_name = field_key.replace("_", " ").title()
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.canonical_fields (
                canonical_field_id, owner_tenant_id, field_key, display_name,
                data_type, description, status, created_at_utc, updated_at_utc
            )
            SELECT gen_random_uuid(), NULL, :field_key, :display_name,
                   :data_type, NULL, 'ACTIVE', now(), now()
            WHERE NOT EXISTS (
                SELECT 1 FROM docintel.canonical_fields
                WHERE owner_tenant_id IS NULL AND field_key=:field_key
            )
            """
        ),
        {"field_key": field_key, "display_name": display_name, "data_type": data_type},
    )


def _new_profile_matches(conn: Any, published_id: Any) -> bool:
    keys = set(conn.execute(
        sa.text(
            """
            SELECT COALESCE(epf.extraction_key, cf.field_key)
            FROM docintel.extraction_profile_fields epf
            JOIN docintel.canonical_fields cf ON cf.canonical_field_id = epf.canonical_field_id
            WHERE epf.profile_id = :pid AND epf.enabled = true
            """
        ),
        {"pid": published_id},
    ).scalars().all())
    return keys == {f[0] for f in _FIELDS}


def _copy_rules(conn: Any, old_field_id: Any, new_field_id: Any) -> None:
    for table, extra in (
        ("profile_field_normalizers", ""),
        ("profile_field_validators", ", severity"),
    ):
        pk = "profile_field_normalizer_id" if table == "profile_field_normalizers" else "profile_field_validator_id"
        conn.execute(
            sa.text(
                f"""
                INSERT INTO docintel.{table} ({pk}, profile_field_id, sequence_no, rule_key, parameters{extra})
                SELECT gen_random_uuid(), :new_id, sequence_no, rule_key, parameters{extra}
                FROM docintel.{table} WHERE profile_field_id = :old_id
                """
            ),
            {"new_id": new_field_id, "old_id": old_field_id},
        )


def _wire_date_plausibility_validator(conn: Any, profile_id: Any) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_validators (
                profile_field_validator_id, profile_field_id,
                sequence_no, rule_key, parameters, severity
            )
            SELECT gen_random_uuid(), epf.profile_field_id,
                   COALESCE((SELECT MAX(v.sequence_no) FROM docintel.profile_field_validators v
                             WHERE v.profile_field_id = epf.profile_field_id), 0) + 1,
                   :rule_key, '{}'::jsonb, 'ERROR'
            FROM docintel.extraction_profile_fields epf
            JOIN docintel.canonical_fields cf ON cf.canonical_field_id = epf.canonical_field_id
            WHERE epf.profile_id = :profile_id AND cf.data_type = 'DATE' AND epf.enabled = true
              AND NOT EXISTS (
                  SELECT 1 FROM docintel.profile_field_validators v
                  WHERE v.profile_field_id = epf.profile_field_id AND v.rule_key = :rule_key
              )
            """
        ),
        {"profile_id": profile_id, "rule_key": _DATE_VALIDATOR_RULE_KEY},
    )


def _republish_v3(conn: Any, old: Any) -> Any:
    new_profile_id = conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profiles (
                profile_id, document_type_id, scope_tenant_id, version_no,
                profile_name, status, classification_hint,
                created_by_actor_id, created_at_utc, updated_at_utc
            )
            SELECT gen_random_uuid(), :dtid, NULL,
                   COALESCE((SELECT MAX(version_no) FROM docintel.extraction_profiles
                             WHERE document_type_id=:dtid AND scope_tenant_id IS NULL), 0) + 1,
                   :name, 'DRAFT', :hint, :actor, now(), now()
            RETURNING profile_id
            """
        ),
        {"dtid": old["document_type_id"], "name": old["profile_name"],
         "hint": old["classification_hint"], "actor": _ACTOR},
    ).scalar_one()

    old_rows = {
        r["old_key"]: r
        for r in conn.execute(
            sa.text(
                f"""
                SELECT epf.profile_field_id, COALESCE(epf.extraction_key, cf.field_key) AS old_key,
                       {', '.join('epf.' + c for c in _CARRY)}
                FROM docintel.extraction_profile_fields epf
                JOIN docintel.canonical_fields cf ON cf.canonical_field_id = epf.canonical_field_id
                WHERE epf.profile_id = :pid
                """
            ),
            {"pid": old["profile_id"]},
        ).mappings().all()
    }

    for field_key, data_type, instruction, expected, seq in _FIELDS:
        _ensure_canonical_field(conn, field_key, data_type)
        canonical_field_id = conn.execute(
            sa.text(
                "SELECT canonical_field_id FROM docintel.canonical_fields "
                "WHERE owner_tenant_id IS NULL AND field_key=:k"
            ),
            {"k": field_key},
        ).scalar_one()
        prev = old_rows.get(_OLD_KEY_FOR.get(field_key, field_key))
        params: dict[str, Any] = {
            "pid": new_profile_id, "cfid": canonical_field_id, "expected": expected,
            "instruction": instruction, "seq": seq, "key": field_key,
            "aliases": prev["aliases"] if prev else json.dumps([]),
            "score_included": expected or bool(prev and prev["score_included"]),
            "score_weight": float(prev["score_weight"]) if prev and prev["score_weight"] else (1.0 if expected else 0.0),
            "role": prev["fact_role_override"] if prev else "UNSPECIFIED",
            "subj": bool(prev["use_for_subject_matching"]) if prev else False,
            "sit": prev["subject_identifier_type"] if prev else None,
            "manual": bool(prev["manual_correction_allowed"]) if prev else True,
        }
        new_field_id = conn.execute(
            sa.text(
                """
                INSERT INTO docintel.extraction_profile_fields (
                    profile_field_id, profile_id, canonical_field_id,
                    enabled, expected, extraction_instruction, aliases,
                    score_included, score_weight, use_for_subject_matching,
                    subject_identifier_type, manual_correction_allowed,
                    display_sequence, created_at_utc, updated_at_utc,
                    extraction_key, fact_role_override
                ) VALUES (
                    gen_random_uuid(), :pid, :cfid,
                    true, :expected, :instruction, CAST(:aliases AS jsonb),
                    :score_included, :score_weight, :subj,
                    :sit, :manual, :seq, now(), now(), :key, :role
                )
                RETURNING profile_field_id
                """
            ),
            params,
        ).scalar_one()
        if prev:
            _copy_rules(conn, prev["profile_field_id"], new_field_id)
    _wire_date_plausibility_validator(conn, new_profile_id)

    # Retire old, then publish new (uq_extraction_profile_published); only
    # status/updated_at_utc change on retire (guard_extraction_profile_header).
    conn.execute(
        sa.text("UPDATE docintel.extraction_profiles SET status='RETIRED', updated_at_utc=now() "
                "WHERE profile_id=:pid"),
        {"pid": old["profile_id"]},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED', published_by_actor_id=:actor,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:pid AND status='DRAFT'
            """
        ),
        {"pid": new_profile_id, "actor": _ACTOR},
    )
    return new_profile_id


def _requeue_processed_ledgers(conn: Any, document_type_id: Any) -> None:
    rows = conn.execute(
        sa.text(
            """
            SELECT d.tenant_id, d.document_id, d.correlation_id,
                   COALESCE((SELECT MAX(pj.attempt_no) FROM docintel.processing_jobs pj
                             WHERE pj.tenant_id = d.tenant_id AND pj.document_id = d.document_id
                               AND pj.job_type = 'NIGHTLY_REPROCESS'), 2) + 1 AS next_attempt_no
            FROM docintel.documents d
            WHERE (d.document_type_id = :dtid OR d.document_type_hint_key = :key)
              AND d.upload_status = 'FIT'
              AND d.processing_status = 'PROCESSED'
              AND d.verification_state = 'NOT_VERIFIED'
              AND NOT EXISTS (
                  SELECT 1 FROM docintel.processing_jobs a
                  WHERE a.tenant_id = d.tenant_id AND a.document_id = d.document_id
                    AND a.job_status IN ('PENDING', 'RUNNING')
              )
            """
        ),
        {"dtid": document_type_id, "key": _TYPE_KEY},
    ).all()
    for tenant_id, document_id, correlation_id, next_attempt_no in rows:
        # Old MACHINE values must not shadow the re-extraction (the worker
        # inserts is_current values with ON CONFLICT DO NOTHING); HUMAN and
        # EXTERNAL values are untouched.
        conn.execute(
            sa.text(
                "UPDATE docintel.document_field_values SET is_current=false "
                "WHERE tenant_id=:tid AND document_id=:did AND is_current=true AND value_source='MACHINE'"
            ),
            {"tid": tenant_id, "did": document_id},
        )
        conn.execute(
            sa.text(
                """
                UPDATE docintel.documents
                SET processing_status='RETRY_PENDING', confirmation_status='PENDING',
                    confidence_score=NULL, verification_threshold_applied=NULL,
                    human_verification_status=NULL, requires_processing=true,
                    updated_at_utc=now()
                WHERE tenant_id=:tid AND document_id=:did
                """
            ),
            {"tid": tenant_id, "did": document_id},
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO docintel.processing_jobs
                    (tenant_id, processing_job_id, document_id, correlation_id,
                     job_type, job_status, due_at_utc, attempt_no, created_at_utc)
                VALUES (:tid, gen_random_uuid(), :did, :corr, 'NIGHTLY_REPROCESS', 'PENDING',
                        now(), :attempt, now())
                ON CONFLICT (tenant_id, document_id, job_type, attempt_no) DO NOTHING
                """
            ),
            {"tid": tenant_id, "did": document_id,
             "corr": correlation_id or f"backfill.0051.{document_id}", "attempt": next_attempt_no},
        )
    if rows:
        conn.execute(sa.text("SELECT pg_notify('di_processing_jobs', 'backfill_0051')"))


def upgrade() -> None:
    conn = op.get_bind()
    document_type_id = _ledger_type_id(conn)
    if document_type_id is None:
        return
    old = conn.execute(
        sa.text(
            """
            SELECT profile_id, document_type_id, profile_name, classification_hint
            FROM docintel.extraction_profiles
            WHERE document_type_id=:dtid AND scope_tenant_id IS NULL AND status='PUBLISHED'
            """
        ),
        {"dtid": document_type_id},
    ).mappings().one_or_none()
    if old is None or _new_profile_matches(conn, old["profile_id"]):
        return
    _republish_v3(conn, old)
    _requeue_processed_ledgers(conn, document_type_id)


def downgrade() -> None:
    # Published configuration is immutable; forward-only (as 0016/0036/0038/0046/0048).
    pass
