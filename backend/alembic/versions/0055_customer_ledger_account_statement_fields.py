"""Publish the customer_ledger profile with the dealer account-statement fields.

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-26

The three Mahindra Orissa dealers fill in a printed account-statement form
(Aditya "Accounts Statement", Utkal "Vehicle Account Statement" and the generic
"Account Statement" used by Shivnath and by Utkal's first page). Its headline
figures -- Net Value / Net Receivable (A+B), Gross Value, Less: Discount, Total
Receipts, Short / Excess, Total Cost -- sit in boxes outside the table, so the
ledger schema's line_items never carried them reliably, and the Discount
Details box shares labels (Insurance, Other ...) with the charge rows.

customer_ledger schema 1.1 adds dedicated fields for them (see
document_ai/schemas/customer_ledger.py); this publishes the matching profile
(v4: the v3 fields unchanged -- aliases, score flags, rules carried over --
plus the new ones, all optional) and retires v3. Published profiles are
immutable, hence a new version.

NOTHING IS RE-EXTRACTED here (0051 re-queued every unverified ledger): documents
already read keep what they have until they are read again on purpose.
Forward-only, like 0051.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

_ACTOR = "migration.0055.customer-ledger-account-statement-fields"
_TYPE_KEY = "customer_ledger"
_DATE_VALIDATOR_RULE_KEY = "date_plausible_range"

# (no renames in v4) key -> key it replaces (matched on COALESCE(extraction_key, field_key)).
_OLD_KEY_FOR: dict[str, str] = {}

# (field_key, canonical data_type, instruction, expected, display_sequence)
# Snapshot of CUSTOMER_LEDGER_SCHEMA 1.1 (a migration must not import app code);
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
    ('statement_title', 'STRING', "Title printed at the top of the dealer's own account statement form, verbatim (for example Account Statement, Vehicle Account Statement, Accounts Statement); empty for a DMS or Tally ledger export", False, 160),
    ('vehicle_model', 'STRING', 'Vehicle model printed on the account statement form, exactly as printed', False, 170),
    ('vin_number', 'IDENTIFIER', 'Vehicle VIN / chassis number printed on the account statement form, exactly as printed', False, 180),
    ('invoice_number', 'IDENTIFIER', 'Invoice number printed on the account statement form, exactly as printed', False, 190),
    ('invoice_date', 'DATE', 'Invoice date printed on the account statement form', False, 200),
    ('booking_date', 'DATE', 'Booking date printed on the account statement form', False, 210),
    ('delivery_date', 'DATE', 'Delivery date printed on the account statement form', False, 220),
    ('gross_value', 'CURRENCY', 'The amount printed against Gross Value on the account statement form, before the discount', False, 230),
    ('discount_value', 'CURRENCY', 'The amount printed against Less: Discount on the account statement form', False, 240),
    ('net_value', 'CURRENCY', 'The final amount the customer is to pay, as printed against Net Value, Net Receivable (A+B) or Final Price on the account statement form; never Gross Value, Total Cost or Total (A)', False, 250),
    ('total_cost', 'CURRENCY', 'The amount printed against Total Cost on a Vehicle Account Statement (the figure before the other discount)', False, 260),
    ('total_receipts', 'CURRENCY', 'The amount printed against Total Receipts, Total Receipt or Net Amount Received (E) on the account statement form', False, 270),
    ('balance_amount', 'CURRENCY', 'The amount printed against Short / Excess, Due or Balance Excess/Shortage (C-E) on the account statement form, as printed', False, 280),
    ('discount_details', 'JSON', 'JSON array of the rows of the Discount Details box of the account statement form that carry an amount, each as label (verbatim: Scheme, Loyalty, Accessory, Insurance, Other, MR, Exchange Bonus, Extended Warranty) and amount; empty when the form has no such box', False, 290),
    ('discount_details_total', 'CURRENCY', 'The amount printed against Total in the Discount Details box of the account statement form', False, 300),
    ('line_items', 'JSON', 'JSON array of visible ledger rows. For each row preserve entry_date (date), particulars_raw, voucher_type, voucher_number, debit_amount, credit_amount and running_balance exactly as printed; do not merge rows or compute missing values', False, 310),
)


# Carried per field from the published profile (columns copied verbatim when it exists).
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


def _republish_v4(conn: Any, old: Any) -> Any:
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
    _republish_v4(conn, old)


def downgrade() -> None:
    # Published configuration is immutable; forward-only (as 0016/0036/0038/0046/0048).
    pass
