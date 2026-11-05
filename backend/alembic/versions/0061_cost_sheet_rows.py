"""Publish the cost_sheet profile with its rows and title (cost_sheet schema 1.1).

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-05

The cost sheet's profile (0046) read four headline figures and the on-road
total. Its other priced rows -- TCS, extended warranty, RSA, FASTag, handling,
others -- were never read, so the total could not be checked against its rows
(product owner 2026-11-05: "NDC rows should add up and so does cost sheet";
live, 165 of 198 Utkal cost sheets print a total above the four figures read).
Before the classifier's definitions (0058), Utkal's Vehicle Account Statement
was often filed as a cost sheet; the printed title tells one from a quotation.

cost_sheet schema 1.1 adds ``document_title`` and ``line_items`` (both
optional); this publishes the matching profile (the next version: the
published fields carried over unchanged -- instruction, aliases, score flags,
normalizers and validators -- plus the two new ones) and retires the old one.
Published profiles are immutable, hence a new version.

NOTHING IS RE-EXTRACTED here: cost sheets already read keep what they have
until they are read again on purpose. Forward-only, like 0055.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

_ACTOR = "migration.0061.cost-sheet-rows"
_TYPE_KEY = "cost_sheet"
_DATE_VALIDATOR_RULE_KEY = "date_plausible_range"

# (no renames) key -> key it replaces.
_OLD_KEY_FOR: dict[str, str] = {}

# (field_key, canonical data_type, instruction, expected, display_sequence)
# Snapshot of COST_SHEET_SCHEMA 1.1 (a migration must not import app code);
# tests/test_cost_sheet_rows_profile.py pins it to the schema. A field the
# published profile already has keeps its published instruction.
_FIELDS: tuple[tuple[str, str, str, bool, int], ...] = (
    ('customer_name', 'STRING', 'Customer name exactly as printed/written.', True, 10),
    ('vehicle_model', 'STRING', 'Vehicle model and variant exactly as printed.', True, 20),
    ('ex_showroom_price', 'CURRENCY', 'Ex-showroom price.', True, 30),
    ('rto_amount', 'CURRENCY', 'RTO / registration / road-tax amount (the total of the registration charges if itemised).', False, 40),
    ('insurance_amount', 'CURRENCY', 'Insurance amount.', False, 50),
    ('accessories_amount', 'CURRENCY', 'Accessories amount (the accessories total if itemised).', False, 60),
    ('discount_amount', 'CURRENCY', 'Total discount / bonus / offer amount deducted, as a positive number.', False, 70),
    ('total_on_road_price', 'CURRENCY', 'Total on-road price / grand total payable.', True, 80),
    ('cost_sheet_date', 'DATE', 'Date of the cost sheet.', False, 90),
    ('document_title', 'STRING', 'Title printed at the top of the page, verbatim (for example Quotation, Cost Sheet, Quotation cum Proforma Invoice, Vehicle Account Statement).', False, 100),
    ('line_items', 'JSON', 'JSON array of every priced row of the sheet in printed order, each as particulars_raw (the row\'s label verbatim), amount (as printed) and deduction (true when the row is subtracted: a discount, offer, scheme or Less row); never the total, on-road, net or grand-total rows.', False, 110),
)


# Carried per field from the published profile (columns copied verbatim when it exists).
_CARRY = (
    "aliases::text AS aliases", "score_included", "score_weight", "fact_role_override",
    "use_for_subject_matching", "subject_identifier_type", "manual_correction_allowed",
)


def _type_id(conn: Any) -> Any:
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


def _republish(conn: Any, old: Any) -> Any:
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
                       epf.extraction_instruction, epf.expected,
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
            "pid": new_profile_id, "cfid": canonical_field_id,
            "expected": bool(prev["expected"]) if prev else expected,
            "instruction": prev["extraction_instruction"] if prev else instruction, "seq": seq, "key": field_key,
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
    document_type_id = _type_id(conn)
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
    _republish(conn, old)


def downgrade() -> None:
    # Published configuration is immutable; forward-only (as 0055).
    pass
