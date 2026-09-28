"""Publish extraction profiles for the four UC03 conditional documents with none.

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-28

Audit Core Phase 2 makes these documents mandatory when the deal's own
evidence calls for them (requirements document, 28 Sep 2026):

  - bank_approval_letter   finance case
  - purchase_order         corporate customer
  - debit_note             insurance / registration through the dealership
  - valuation_report       exchange

A document counts as received once DI has read it, but none of the four had
a published profile (0046's docstring lists them as out of scope then), so
they were classified and never read -- the requirement could never be met.

- bank_approval_letter / valuation_report: publish the reviewed Schema V2
  Wave-1 DRAFT profiles (0020) unchanged in fields, extraction keys and fact
  roles, after promoting three core fields to expected + scored (a profile
  with no scoreable field cannot be published) and wiring the date
  plausibility validator (0042) while still DRAFT. The runtime sends each
  field's extraction_key to the provider (job_runner._provider_field_key),
  the first item of the Wave-1 publication gate.
- debit_note / purchase_order: fresh v1 profiles from their Gemini schemas
  (document_ai/schemas/{debit_note,purchase_order}.py), mirroring 0046.

Then processing is turned on for the four types and documents already
classified as one of them are queued for their first extraction (0046
step 4). Published configuration is immutable: forward-only.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

_ACTOR = "migration.0048.uc03-conditional-document-profiles"
_DATE_VALIDATOR_RULE_KEY = "date_plausible_range"
_WAVE1_PROFILE_NAME = "Schema V2 Wave 1 Draft"

_TYPE_KEYS = ("bank_approval_letter", "valuation_report", "debit_note", "purchase_order")

# Wave-1 drafts: extraction keys promoted to expected + scored.
_WAVE1_PROMOTE: dict[str, tuple[str, ...]] = {
    "bank_approval_letter": ("financier_name", "applicant_name", "sanctioned_amount"),
    "valuation_report": ("registration_number", "valuation_date", "final_offer_value"),
}

_NEW_CANONICAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("dealer_gstin", "Dealer GSTIN", "IDENTIFIER"),
    ("debit_note_number", "Debit Note Number", "IDENTIFIER"),
    ("debit_note_date", "Debit Note Date", "DATE"),
    ("against_invoice_number", "Against Invoice Number", "IDENTIFIER"),
    ("other_charges", "Other Charges", "CURRENCY"),
    ("total_amount", "Total Amount", "CURRENCY"),
    ("particulars", "Particulars", "STRING"),
    ("line_items", "Line Items", "JSON"),
    ("po_number", "Purchase Order Number", "IDENTIFIER"),
    ("po_date", "Purchase Order Date", "DATE"),
    ("buyer_company_name", "Buyer Company Name", "STRING"),
    ("buyer_gstin", "Buyer GSTIN", "IDENTIFIER"),
    ("buyer_address", "Buyer Address", "STRING"),
    ("supplier_name", "Supplier Name", "STRING"),
    ("vehicle_variant", "Vehicle Variant", "STRING"),
    ("sku_code", "SKU Code", "IDENTIFIER"),
    ("quantity", "Quantity", "DECIMAL"),
    ("unit_price", "Unit Price", "CURRENCY"),
    ("po_amount", "Purchase Order Amount", "CURRENCY"),
    ("payment_terms", "Payment Terms", "STRING"),
    ("authorised_by", "Authorised By", "STRING"),
    ("authoriser_signature_present", "Authoriser Signature Present", "BOOLEAN"),
    # Reused when already registered (0036/0046): the existence check decides.
    ("dealer_name", "Dealer Name", "STRING"),
    ("customer_name", "Customer Name", "STRING"),
    ("booking_reference_number", "Booking Reference Number", "STRING"),
    ("insurance_amount", "Insurance Amount", "CURRENCY"),
    ("rto_amount", "RTO Amount", "CURRENCY"),
    ("vehicle_model", "Vehicle Model", "STRING"),
)

# document_type_key -> (profile_name, fields)
# fields: field_key, expected, instruction, aliases, score_included, score_weight, display_sequence
_NEW_PROFILES: dict[str, tuple[str, list[tuple[str, bool, str, list[str], bool, float, int]]]] = {
    "debit_note": (
        "Debit Note Extraction v1",
        [
            ("dealer_name", False, "Issuing dealership/company name exactly as printed.", ["dealer", "from"], False, 0.0, 10),
            ("dealer_gstin", False, "Issuer GSTIN exactly as printed.", ["gstin"], False, 0.0, 20),
            ("debit_note_number", False, "Debit note number/reference exactly as printed.", ["debit note no", "dn no"], False, 0.0, 30),
            ("debit_note_date", False, "Debit note date.", ["date"], False, 0.0, 40),
            ("customer_name", True, "Customer/party the debit note is raised against, exactly as printed.", ["customer", "party", "to"], True, 1.0, 50),
            ("against_invoice_number", False, "Invoice/reference the note is raised against, if printed.", ["against invoice", "ref"], False, 0.0, 60),
            ("booking_reference_number", False, "Booking/order/deal reference printed on the note, if any.", ["booking no", "order no"], False, 0.0, 70),
            ("insurance_amount", False, "Insurance premium charged, only when explicitly shown as an insurance line.", ["insurance", "premium"], False, 0.0, 80),
            ("rto_amount", False, "RTO / registration / road tax charged, only when explicitly shown as such a line.", ["rto", "registration", "road tax"], False, 0.0, 90),
            ("other_charges", False, "Any other charge line explicitly printed that is not insurance or RTO.", ["other charges"], False, 0.0, 100),
            ("total_amount", False, "Debit note total only when printed as a total; never sum the lines.", ["total", "net amount"], False, 0.0, 110),
            ("particulars", False, "Narration/particulars/reason text exactly as printed.", ["particulars", "narration"], False, 0.0, 120),
            ("line_items", False, "JSON array of visible lines; keep particulars_raw and only explicitly printed hsn_sac, quantity, rate and amount.", ["lines"], False, 0.0, 130),
        ],
    ),
    "purchase_order": (
        "Purchase Order Extraction v1",
        [
            ("po_number", False, "Purchase order number/reference exactly as printed.", ["po no", "order no"], False, 0.0, 10),
            ("po_date", False, "Purchase order date.", ["po date", "date"], False, 0.0, 20),
            ("buyer_company_name", True, "Ordering company/organisation name exactly as printed.", ["buyer", "company"], True, 1.0, 30),
            ("buyer_gstin", False, "Buyer GSTIN exactly as printed; leave out when the document says unregistered.", ["gstin"], False, 0.0, 40),
            ("buyer_address", False, "Buyer company address if explicitly printed.", ["address"], False, 0.0, 50),
            ("supplier_name", False, "Dealer/supplier the PO is addressed to, exactly as printed.", ["supplier", "vendor", "to"], False, 0.0, 60),
            ("vehicle_model", False, "Ordered vehicle model exactly as printed.", ["model"], False, 0.0, 70),
            ("vehicle_variant", False, "Ordered vehicle variant/trim exactly as printed.", ["variant"], False, 0.0, 80),
            ("sku_code", False, "Vehicle/product/SKU code only when explicitly printed; never infer.", ["sku", "product code"], False, 0.0, 90),
            ("quantity", False, "Ordered quantity only when explicitly printed.", ["qty", "quantity"], False, 0.0, 100),
            ("unit_price", False, "Per-unit price only when explicitly printed.", ["rate", "unit price"], False, 0.0, 110),
            ("po_amount", False, "Total purchase order value only when printed as a total; never compute it.", ["total", "po value"], False, 0.0, 120),
            ("payment_terms", False, "Payment terms text exactly as printed.", ["payment terms"], False, 0.0, 130),
            ("authorised_by", False, "Name/designation of the person authorising the PO.", ["authorised by", "approved by"], False, 0.0, 140),
            ("authoriser_signature_present", False, "True only when a visible signature/stamp of the authoriser is present.", ["signature"], False, 0.0, 150),
            ("line_items", False, "JSON array of visible lines; keep description_raw and only explicitly printed hsn_sac, quantity, unit_rate and amount.", ["lines"], False, 0.0, 160),
        ],
    ),
}


def _document_type_id(conn: Any, key: str) -> Any:
    return conn.execute(
        sa.text(
            "SELECT document_type_id FROM docintel.document_types "
            "WHERE owner_tenant_id IS NULL AND document_type_key=:key AND status='ACTIVE'"
        ),
        {"key": key},
    ).scalar_one()


def _has_published(conn: Any, document_type_id: Any) -> bool:
    return conn.execute(
        sa.text(
            "SELECT 1 FROM docintel.extraction_profiles "
            "WHERE document_type_id=:dtid AND scope_tenant_id IS NULL AND status='PUBLISHED' LIMIT 1"
        ),
        {"dtid": document_type_id},
    ).scalar_one_or_none() is not None


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str, data_type: str) -> None:
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


def _add_field(conn: Any, profile_id: Any, field_key: str, *, expected: bool, instruction: str,
               aliases: list[str], score_included: bool, score_weight: float, display_sequence: int) -> None:
    canonical_field_id = conn.execute(
        sa.text(
            "SELECT canonical_field_id FROM docintel.canonical_fields "
            "WHERE owner_tenant_id IS NULL AND field_key=:field_key"
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
                true, :expected, :instruction, CAST(:aliases AS jsonb),
                :score_included, :score_weight, false,
                NULL, true, :display_sequence, now(), now(), :field_key, 'UNSPECIFIED'
            )
            """
        ),
        {
            "profile_id": profile_id, "canonical_field_id": canonical_field_id, "expected": expected,
            "instruction": instruction, "aliases": json.dumps(aliases), "score_included": score_included,
            "score_weight": score_weight, "display_sequence": display_sequence, "field_key": field_key,
        },
    )


def _wire_date_plausibility_validator(conn: Any, profile_id: Any) -> None:
    # Next free sequence per field: a Wave-1 draft field may already carry one.
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


def _publish(conn: Any, profile_id: Any) -> None:
    scoreable = conn.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1 FROM docintel.extraction_profile_fields
                WHERE profile_id=:pid AND enabled=true AND expected=true
                  AND score_included=true AND score_weight > 0
            )
            """
        ),
        {"pid": profile_id},
    ).scalar_one()
    if not scoreable:
        raise RuntimeError(f"Profile {profile_id} has no scoreable field; refusing to publish")
    conn.execute(
        sa.text(
            """
            UPDATE docintel.extraction_profiles
            SET status='PUBLISHED', published_by_actor_id=:actor_id,
                published_at_utc=now(), updated_at_utc=now()
            WHERE profile_id=:pid AND status='DRAFT'
            """
        ),
        {"actor_id": _ACTOR, "pid": profile_id},
    )


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Wave-1 drafts: promote core fields, wire date validators, publish.
    for document_type_key, promoted in _WAVE1_PROMOTE.items():
        document_type_id = _document_type_id(conn, document_type_key)
        if _has_published(conn, document_type_id):
            continue
        profile_id = conn.execute(
            sa.text(
                """
                SELECT profile_id FROM docintel.extraction_profiles
                WHERE document_type_id=:dtid AND scope_tenant_id IS NULL
                  AND profile_name=:name AND status='DRAFT'
                ORDER BY version_no DESC LIMIT 1
                """
            ),
            {"dtid": document_type_id, "name": _WAVE1_PROFILE_NAME},
        ).scalar_one()
        conn.execute(
            sa.text(
                """
                UPDATE docintel.extraction_profile_fields
                SET expected=true, score_included=true, score_weight=1.0, updated_at_utc=now()
                WHERE profile_id=:pid AND extraction_key = ANY(:keys)
                """
            ),
            {"pid": profile_id, "keys": list(promoted)},
        )
        _wire_date_plausibility_validator(conn, profile_id)
        _publish(conn, profile_id)

    # 2. debit_note / purchase_order: fresh v1 profiles.
    for field_key, display_name, data_type in _NEW_CANONICAL_FIELDS:
        _ensure_canonical_field(conn, field_key, display_name, data_type)
    for document_type_key, (profile_name, fields) in _NEW_PROFILES.items():
        document_type_id = _document_type_id(conn, document_type_key)
        if _has_published(conn, document_type_id):
            continue
        profile_id = conn.execute(
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
                       :profile_name, 'DRAFT', :hint, :actor_id, now(), now()
                RETURNING profile_id
                """
            ),
            {"dtid": document_type_id, "profile_name": profile_name, "hint": document_type_key, "actor_id": _ACTOR},
        ).scalar_one()
        for field_key, expected, instruction, aliases, score_included, score_weight, seq in fields:
            _add_field(conn, profile_id, field_key, expected=expected, instruction=instruction, aliases=aliases,
                       score_included=score_included, score_weight=score_weight, display_sequence=seq)
        _wire_date_plausibility_validator(conn, profile_id)
        _publish(conn, profile_id)

    # 3. Every tenant has the four types, with processing on.
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.tenant_document_types (
                tenant_id, document_type_id, physical_form_type,
                requires_processing, is_active, display_order,
                created_at_utc, updated_at_utc
            )
            SELECT ts.tenant_id, dt.document_type_id, dt.category, true, true, 100, now(), now()
            FROM docintel.tenant_settings ts
            JOIN docintel.document_types dt
              ON dt.owner_tenant_id IS NULL AND dt.status='ACTIVE'
             AND dt.document_type_key = ANY(:keys)
            ON CONFLICT (tenant_id, document_type_id) DO NOTHING
            """
        ),
        {"keys": list(_TYPE_KEYS)},
    )
    conn.execute(
        sa.text(
            """
            UPDATE docintel.tenant_document_types tdt
            SET requires_processing=true, updated_at_utc=now()
            FROM docintel.document_types dt
            WHERE dt.document_type_id=tdt.document_type_id
              AND dt.owner_tenant_id IS NULL
              AND dt.document_type_key = ANY(:keys)
              AND tdt.requires_processing=false
            """
        ),
        {"keys": list(_TYPE_KEYS)},
    )

    # 4. Documents already classified as one of them get their first extraction.
    stuck_rows = conn.execute(
        sa.text(
            """
            SELECT d.tenant_id, d.document_id
            FROM docintel.documents d
            WHERE d.document_type_hint_key = ANY(:keys)
              AND d.processing_status NOT IN ('PROCESSED', 'FAILED')
              AND NOT EXISTS (
                  SELECT 1 FROM docintel.processing_jobs pj
                  WHERE pj.tenant_id = d.tenant_id AND pj.document_id = d.document_id
              )
            """
        ),
        {"keys": list(_TYPE_KEYS)},
    ).all()
    for tenant_id, document_id in stuck_rows:
        conn.execute(
            sa.text(
                "UPDATE docintel.documents SET requires_processing=true, updated_at_utc=now() "
                "WHERE tenant_id=:tid AND document_id=:did"
            ),
            {"tid": tenant_id, "did": document_id},
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO docintel.processing_jobs
                    (tenant_id, processing_job_id, document_id, correlation_id,
                     job_type, job_status, due_at_utc, attempt_no, created_at_utc)
                VALUES (:tid, gen_random_uuid(), :did, :corr, 'INITIAL', 'PENDING', now(), 1, now())
                ON CONFLICT (tenant_id, document_id, job_type, attempt_no) DO NOTHING
                """
            ),
            {"tid": tenant_id, "did": document_id, "corr": f"backfill.0048.{document_id}"},
        )
    if stuck_rows:
        conn.execute(sa.text("SELECT pg_notify('di_processing_jobs', 'backfill_0048')"))


def downgrade() -> None:
    # Published configuration is immutable; forward-only (as 0016/0036/0038/0046).
    pass
