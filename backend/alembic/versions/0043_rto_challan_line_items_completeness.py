"""Strengthen RTO Challan line_items extraction to cover every printed row.

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-21

Reported live: the RTO Challan's line_items array (0041) only ever
extracts one row of the Particulars/fee table, even though these
challans routinely print 5-15 separate charge lines (Registration Fee,
Road Tax, Hypothecation Charges, Smart Card Fee, Fitness Fee, Fancy/
Choice Number Fee, Form Fee, Postal Charges, Agent Fee, Cess, ...).
0041's instruction already said "extract every visible row" but never
told the model how many rows to expect or asked it to verify its own
count against the printed table -- both of which this republish adds,
matching the same wording now also updated in the Python schema
definition (rto_challan.py) for future profile republishes.

extraction_profile_fields are guarded immutable once PUBLISHED
(guard_extraction_profile_child, 0001_initial_schema.py), so this
republishes the whole profile from the same fixed field list 0041 used,
changing only the line_items instruction -- same wholesale-republish
shape 0041 itself used, not the clone-existing-fields shape 0042 used
for a single validator addition (this profile has no normalizers/
validators of its own to preserve).
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

_ACTOR = "migration.0043.rto-challan-line-items-completeness"
_PROFILE_NAME = "UC03 RTO Final Report Contract v2"

# field_key, display_name, data_type, display_sequence, instruction, aliases
F = tuple[str, str, str, int, str, list[str]]

_RTO_FIELDS: list[F] = [
    (
        "registration_number",
        "Registration Number",
        "IDENTIFIER",
        10,
        "Extract the vehicle registration number only when explicitly printed or labelled on the RTO paper/challan. Never reconstruct or decode it.",
        ["registration no", "registration number", "regn no", "vehicle registration no"],
    ),
    (
        "registration_state",
        "Registration State",
        "STRING",
        20,
        "Extract the Registration/RTO State only when explicitly printed. Return null when not stated; never infer State from registration number, RTO code, district, PIN code, or outside geography knowledge.",
        ["state", "registration state", "rto state"],
    ),
    (
        "registration_territory",
        "Registration Territory",
        "STRING",
        30,
        "Extract Territory or Union Territory only when explicitly printed. Return null when not stated; never derive it from State, registration number, RTO code, or outside geography knowledge.",
        ["territory", "union territory", "ut", "registration territory"],
    ),
    (
        "registration_district",
        "Registration District",
        "STRING",
        40,
        "Extract the Registration/RTO District only when explicitly printed. Return null when not stated; never infer it from RTO code, city, State, registration number, or outside geography knowledge.",
        ["district", "registration district", "rto district"],
    ),
    (
        "ex_showroom_amount",
        "Ex Showroom Amount",
        "CURRENCY",
        50,
        "Extract the ex-showroom monetary amount only when explicitly labelled and printed on the RTO paper/challan. Never calculate it from taxable value, invoice value, taxes, registration fees, or totals.",
        ["ex showroom", "ex-showroom", "ex showroom price", "ex-showroom price"],
    ),
    (
        "registration_type",
        "Registration Type",
        "STRING",
        60,
        "Extract registration type/category exactly as printed. Return null when absent; never classify or infer it from vehicle, customer, finance, tax, usage, or registration-number context.",
        ["registration type", "regn type", "type of registration", "registration category"],
    ),
    (
        "hp_charges_amount",
        "HP Charges Amount",
        "CURRENCY",
        70,
        "Extract hypothecation/HP charges only when explicitly labelled and printed. Never calculate or derive the amount from finance details, loan amount, registration fee, or another charge.",
        ["hp charges", "hypothecation charges", "hypothecation fee", "hp fee"],
    ),
    (
        "chassis_number",
        "Chassis Number",
        "IDENTIFIER",
        80,
        "Extract the vehicle chassis number exactly as printed on the RTO paper/challan. Never derive it from a registration number or VIN.",
        ["chassis no", "chassis number", "chasis no", "chassis no."],
    ),
    (
        "financer_name",
        "Financer Name",
        "STRING",
        90,
        "Extract the financer/bank name exactly as printed (e.g. against 'FinancerName' or 'Financed By'). Return null when the document shows no financer, never infer one from a cash/self-financed sale.",
        ["financer name", "financer", "financed by", "finance company", "bank name"],
    ),
    (
        "bank_reference_number",
        "Bank Reference Number",
        "STRING",
        100,
        "Extract the bank reference number exactly as printed (e.g. against 'Bank Ref No'). Return null when not stated.",
        ["bank ref no", "bank reference no", "bank reference number"],
    ),
    (
        "receipt_number",
        "Receipt Number",
        "IDENTIFIER",
        110,
        "Extract the receipt/application number exactly as printed (e.g. against 'RECEIPT/APPL No'). Preserve it verbatim, including any slash-separated parts.",
        ["receipt no", "appl no", "receipt/appl no", "application number"],
    ),
    (
        "receipt_date",
        "Receipt Date",
        "DATE",
        120,
        "Extract the receipt date exactly as printed. Never confuse it with the 'Printed On' timestamp when the two differ.",
        ["receipt date", "date"],
    ),
    (
        "grand_total_amount",
        "Grand Total Amount",
        "CURRENCY",
        130,
        "Extract the final grand total amount exactly as printed; never recompute it by summing the Particulars table yourself.",
        ["grand total", "total amount", "grand total (in rs)"],
    ),
    (
        "line_items",
        "RTO Particulars Line Items",
        "JSON",
        140,
        (
            "Return a JSON array with ONE ENTRY PER PRINTED ROW of the Particulars/charges "
            "table -- an RTO Challan's fee break-up routinely lists many separate rows "
            "(for example: Registration Fee, Road Tax, Hypothecation/HPA Charges, Smart Card "
            "Fee, Fitness Fee, Fancy/Choice Number Fee, Form Fee, Postal/Speed Post Charges, "
            "Agent Fee, Cess), each with its own amount -- return every one of them as its own "
            "array element, never a single summarized or totaled entry. Scan the ENTIRE table "
            "from its first printed row to its last before answering; a table with N printed "
            "rows must produce an array of exactly N items, never fewer. Before finalizing, "
            "re-count the printed rows and confirm the array length matches -- a one-element "
            "array is correct ONLY if the printed table itself genuinely shows just one row. "
            "For each row preserve description_raw exactly as printed, and extract only "
            "explicitly printed amount, rebate_waiver_amount, fine_penalty_amount and total. "
            "Never merge two or more printed rows into one array element, never invent a row "
            "that is not printed, and never collapse the table down to only its total/"
            "grand-total row."
        ),
        ["particulars", "charges", "fee breakdown", "line items"],
    ),
]


def _add_profile_field(conn: Any, *, profile_id: Any, field: F) -> None:
    field_key, _display_name, _data_type, sequence, instruction, aliases = field
    canonical_field_id = conn.execute(
        sa.text(
            """
            SELECT canonical_field_id
            FROM docintel.canonical_fields
            WHERE owner_tenant_id IS NULL
              AND field_key=:field_key
            """
        ),
        {"field_key": field_key},
    ).scalar_one()

    conn.execute(
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
                gen_random_uuid(), :profile_id, :canonical_field_id,
                true, false, :instruction, CAST(:aliases AS jsonb),
                false, 0.0, false, NULL, true,
                :sequence, now(), now(), :field_key, 'UNSPECIFIED'
            )
            """
        ),
        {
            "profile_id": profile_id,
            "canonical_field_id": canonical_field_id,
            "instruction": instruction,
            "aliases": json.dumps(aliases),
            "sequence": sequence,
            "field_key": field_key,
        },
    )


def _publish_rto_profile(conn: Any) -> None:
    document_type_id = conn.execute(
        sa.text(
            """
            SELECT document_type_id
            FROM docintel.document_types
            WHERE owner_tenant_id IS NULL
              AND document_type_key='rto_challan'
              AND status='ACTIVE'
            """
        )
    ).scalar_one()

    version_no = conn.execute(
        sa.text(
            """
            SELECT COALESCE(MAX(version_no), 0) + 1
            FROM docintel.extraction_profiles
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
            """
        ),
        {"document_type_id": document_type_id},
    ).scalar_one()

    profile_id = conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profiles (
                profile_id, document_type_id, scope_tenant_id, version_no,
                profile_name, status, classification_hint,
                created_by_actor_id, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), :document_type_id, NULL, :version_no,
                :profile_name, 'DRAFT',
                'Automobile RTO Challan or RTO registration/fee paper.',
                :actor, now(), now()
            )
            RETURNING profile_id
            """
        ),
        {
            "document_type_id": document_type_id,
            "version_no": version_no,
            "profile_name": _PROFILE_NAME,
            "actor": _ACTOR,
        },
    ).scalar_one()

    for field in _RTO_FIELDS:
        _add_profile_field(conn, profile_id=profile_id, field=field)

    # 0042 attached date_plausible_range to every published DATE field
    # (receipt_date here). This migration rebuilds the RTO profile's fields
    # wholesale from _RTO_FIELDS -- same shape 0041 itself used -- rather
    # than cloning the retiring profile's own children, so without this it
    # would silently retire the old receipt_date field (validator and all)
    # and publish a new one with no validator attached at all.
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_validators (
                profile_field_validator_id, profile_field_id,
                sequence_no, rule_key, parameters, severity
            )
            SELECT
                gen_random_uuid(),
                epf.profile_field_id,
                1,
                'date_plausible_range',
                '{}'::jsonb,
                'ERROR'
            FROM docintel.extraction_profile_fields epf
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id = epf.canonical_field_id
            WHERE epf.profile_id = :profile_id
              AND cf.data_type = 'DATE'
              AND epf.enabled = true
            """
        ),
        {"profile_id": profile_id},
    )

    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='RETIRED', updated_at_utc=now()
            WHERE document_type_id=:document_type_id
              AND scope_tenant_id IS NULL
              AND status='PUBLISHED'
              AND profile_id<>:profile_id
            """
        ),
        {"document_type_id": document_type_id, "profile_id": profile_id},
    )

    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED',
                published_by_actor_id=:actor,
                published_at_utc=now(),
                updated_at_utc=now()
            WHERE profile_id=:profile_id
              AND status='DRAFT'
            """
        ),
        {"profile_id": profile_id, "actor": _ACTOR},
    )


def upgrade() -> None:
    conn = op.get_bind()
    _publish_rto_profile(conn)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles ep
            SET status='RETIRED', updated_at_utc=now()
            FROM docintel.document_types dt
            WHERE ep.document_type_id=dt.document_type_id
              AND dt.owner_tenant_id IS NULL
              AND dt.document_type_key='rto_challan'
              AND ep.scope_tenant_id IS NULL
              AND ep.created_by_actor_id=:actor
              AND ep.status IN ('DRAFT','PUBLISHED')
            """
        ),
        {"actor": _ACTOR},
    )
