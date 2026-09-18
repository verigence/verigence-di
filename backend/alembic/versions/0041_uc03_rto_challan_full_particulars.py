"""Publish UC03 RTO Challan extraction contract Package 4: full particulars.

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-18

0028 published the smallest RTO Challan contract (registration number/state/
territory/district, ex-showroom amount, registration type, HP charges only).
Confirmed live against a real RTO Challan receipt: that contract only ever
surfaces the Hypothecation Addition line -- Chassis No, FinancerName, and
every other Particulars-table row (New Registration, Automation and
Technology Fee, MV Tax, Rebate/Waiver, Grand Total) go unextracted even
though they're printed on the same document. This migration republishes the
profile with the original seven fields plus chassis_number, financer_name,
bank_reference_number, receipt_number, receipt_date, grand_total_amount, and
a line_items JSON array for the full Particulars table -- same shape as the
generalized invoice schema's own line_items (0022), extended with the
rebate/waiver and fine/penalty columns this document's table actually has.
Extraction only; it does not decode registration numbers, infer geography,
or derive amounts.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

_ACTOR = "migration.0041.uc03-rto-full-particulars"
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
            "Extract every visible row of the Particulars/charges table as a JSON array. For "
            "each row preserve description_raw exactly as printed, and extract only explicitly "
            "printed amount, rebate_waiver_amount, fine_penalty_amount and total. Do not merge "
            "separate printed rows into one, and do not invent a row that is not printed "
            "(e.g. New Registration, Hypothecation Addition, Automation and Technology Fee, "
            "MV Tax are typical rows on this document, but extract only what is actually there)."
        ),
        ["particulars", "charges", "fee breakdown", "line items"],
    ),
]


def _ensure_canonical_field(
    conn: Any,
    *,
    field_key: str,
    display_name: str,
    data_type: str,
) -> None:
    existing = conn.execute(
        sa.text(
            """
            SELECT data_type
            FROM docintel.canonical_fields
            WHERE owner_tenant_id IS NULL
              AND field_key=:field_key
            """
        ),
        {"field_key": field_key},
    ).scalar_one_or_none()
    if existing is not None:
        if existing != data_type:
            raise RuntimeError(
                f"Canonical type conflict for {field_key}: "
                f"existing={existing}, requested={data_type}"
            )
        return

    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.canonical_fields (
                canonical_field_id, owner_tenant_id, field_key, display_name,
                data_type, description, status, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), NULL, :field_key, :display_name,
                :data_type, NULL, 'ACTIVE', now(), now()
            )
            """
        ),
        {
            "field_key": field_key,
            "display_name": display_name,
            "data_type": data_type,
        },
    )


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

    # Historical profiles remain immutable, but at most one global profile may be published.
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
    for field_key, display_name, data_type, *_rest in _RTO_FIELDS:
        _ensure_canonical_field(
            conn,
            field_key=field_key,
            display_name=display_name,
            data_type=data_type,
        )
    _publish_rto_profile(conn)


def downgrade() -> None:
    conn = op.get_bind()

    # Preserve historical profile/fact rows; only retire this package's profile.
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
