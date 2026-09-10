"""Close four Delivery document-classification/extraction gaps found live.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-10

Found by direct review of real uploaded Delivery documents on one journey:

1. payment_receipt (Delivery's receipt type, registered in 0016) has NEVER
   had a published extraction profile -- it silently fell back to a generic,
   receipt-unaware Gemini prompt (document_ai/schemas' FALLBACK_SCHEMA).
   Fixed by cloning dealer_receipt's already-published profile fields (the
   same real-world document, Booking's side of this exact gap already
   closed) plus one Delivery-specific field: a receipt is raised against an
   invoice at delivery, not a booking.
2. customer_kyc (also registered in 0016, also never profiled) gets its own
   fresh profile matching document_ai/schemas/customer_kyc.py.
3. gst_declaration is a genuinely new document type: a real uploaded
   "Declaration of GST (for Sales Department)" form had nowhere correct to
   land, so DI's classifier confidently misfiled it as customer_kyc instead
   of surfacing it as unrecognized -- there was no better bucket available.
4. credit_note is also a genuinely new document type: a real uploaded
   Credit Note had no registered type at all and could not be classified as
   anything. Its field shape is identical to Delivery's existing invoice
   family (VIN, dealer GSTIN, taxable value, CGST/SGST, grand total), so its
   profile clones customer_invoice_dms's current published fields rather
   than redefining an equivalent field set from scratch.

Every field-set here matches document_ai/schemas/{payment_receipt,
customer_kyc, gst_declaration}.py and invoice.py's CREDIT_NOTE_SCHEMA exactly
-- the DB profile (what fields exist to score/store) and the Python schema
(what prompt asks Gemini to fill them) must agree on field_key naming.
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

_ACTOR = "migration.0036.delivery-document-type-gaps"

# key, display name, physical form
_NEW_DOCUMENT_TYPES = (
    ("credit_note", "Credit Note", "PRINTABLE"),
    ("gst_declaration", "GST Declaration", "HANDWRITTEN"),
)

# field_key, display_name, data_type -- only genuinely new canonical fields.
# customer_name/dealer_name/receipt_number/etc. already exist (dealer_receipt,
# 0014) and are reused as-is via _ensure_canonical_field's idempotent lookup.
_NEW_CANONICAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("invoice_reference_number", "Invoice Reference Number", "IDENTIFIER"),
    ("evidence_format", "Evidence Format", "STRING"),
    ("relation_name", "Relation Name (S/O, W/O, D/O)", "STRING"),
    ("id_type", "ID Type", "STRING"),
    ("id_number", "ID Number", "IDENTIFIER"),
    ("date_of_birth", "Date of Birth", "DATE"),
    ("address", "Address", "STRING"),
    ("pin_code", "PIN Code", "STRING"),
    ("phone_number", "Phone Number", "STRING"),
    ("document_date", "Document Date", "DATE"),
    ("photo_present", "Photo Present", "BOOLEAN"),
    ("signature_present", "Signature Present", "BOOLEAN"),
    ("is_photocopy", "Is Photocopy", "BOOLEAN"),
    ("vehicle_model", "Vehicle Model", "STRING"),
    ("purchase_date", "Purchase Date", "DATE"),
    ("has_gst_number", "Has GST Number", "BOOLEAN"),
    ("gstin", "GSTIN", "IDENTIFIER"),
    ("customer_signature_present", "Customer Signature Present", "BOOLEAN"),
    ("sales_personnel_name", "Sales Personnel Name", "STRING"),
    ("sales_personnel_signature_present", "Sales Personnel Signature Present", "BOOLEAN"),
)


def _ensure_canonical_field(conn: Any, field_key: str, display_name: str, data_type: str) -> None:
    existing = conn.execute(
        sa.text(
            "SELECT 1 FROM docintel.canonical_fields WHERE owner_tenant_id IS NULL AND field_key=:field_key"
        ),
        {"field_key": field_key},
    ).scalar_one_or_none()
    if existing is not None:
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
        {"field_key": field_key, "display_name": display_name, "data_type": data_type},
    )


def _document_type_id(conn: Any, document_type_key: str) -> Any:
    return conn.execute(
        sa.text(
            """
            SELECT document_type_id FROM docintel.document_types
            WHERE owner_tenant_id IS NULL AND document_type_key=:key AND status='ACTIVE'
            """
        ),
        {"key": document_type_key},
    ).scalar_one()


def _current_published_profile_id(conn: Any, document_type_id: Any) -> Any:
    return conn.execute(
        sa.text(
            """
            SELECT profile_id FROM docintel.extraction_profiles
            WHERE document_type_id=:dtid AND scope_tenant_id IS NULL AND status='PUBLISHED'
            ORDER BY version_no DESC LIMIT 1
            """
        ),
        {"dtid": document_type_id},
    ).scalar_one()


def _new_profile_id(conn: Any, document_type_id: Any, profile_name: str, classification_hint: str) -> Any:
    version_no = conn.execute(
        sa.text(
            "SELECT COALESCE(MAX(version_no), 0) + 1 FROM docintel.extraction_profiles "
            "WHERE document_type_id=:dtid AND scope_tenant_id IS NULL"
        ),
        {"dtid": document_type_id},
    ).scalar_one()
    return conn.execute(
        sa.text(
            """
            INSERT INTO docintel.extraction_profiles (
                profile_id, document_type_id, scope_tenant_id, version_no,
                profile_name, status, classification_hint,
                created_by_actor_id, created_at_utc, updated_at_utc
            ) VALUES (
                gen_random_uuid(), :dtid, NULL, :version_no,
                :profile_name, 'DRAFT', :hint, :actor_id, now(), now()
            ) RETURNING profile_id
            """
        ),
        {
            "dtid": document_type_id,
            "version_no": version_no,
            "profile_name": profile_name,
            "hint": classification_hint,
            "actor_id": _ACTOR,
        },
    ).scalar_one()


def _publish(conn: Any, profile_id: Any) -> None:
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


def _clone_profile_fields(conn: Any, source_profile_id: Any, target_profile_id: Any) -> None:
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
            )
            SELECT
                gen_random_uuid(), :target_profile_id, epf.canonical_field_id,
                epf.enabled, epf.expected, epf.extraction_instruction, epf.aliases,
                epf.score_included, epf.score_weight, epf.use_for_subject_matching,
                epf.subject_identifier_type, epf.manual_correction_allowed,
                epf.display_sequence, now(), now(),
                COALESCE(epf.extraction_key, cf.field_key),
                COALESCE(epf.fact_role_override, 'UNSPECIFIED')
            FROM docintel.extraction_profile_fields epf
            JOIN docintel.canonical_fields cf ON cf.canonical_field_id=epf.canonical_field_id
            WHERE epf.profile_id=:source_profile_id
            ORDER BY epf.display_sequence, epf.profile_field_id
            """
        ),
        {"target_profile_id": target_profile_id, "source_profile_id": source_profile_id},
    )


def _add_field(
    conn: Any,
    profile_id: Any,
    field_key: str,
    *,
    expected: bool,
    instruction: str,
    aliases: list[str],
    score_included: bool,
    score_weight: float,
    display_sequence: int,
) -> None:
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
            "profile_id": profile_id,
            "canonical_field_id": canonical_field_id,
            "expected": expected,
            "instruction": instruction,
            "aliases": json.dumps(aliases),
            "score_included": score_included,
            "score_weight": score_weight,
            "display_sequence": display_sequence,
            "field_key": field_key,
        },
    )


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Register the two genuinely new document types (mirrors 0016) ──────
    for key, display_name, physical_form in _NEW_DOCUMENT_TYPES:
        safe_name = display_name.replace("'", "''")
        conn.execute(
            sa.text(
                f"""
                INSERT INTO docintel.document_types (
                    document_type_id, owner_tenant_id, document_type_key,
                    display_name, description, category, status,
                    created_at_utc, updated_at_utc
                )
                SELECT gen_random_uuid(), NULL, '{key}', '{safe_name}', NULL,
                       '{physical_form}', 'ACTIVE', now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM docintel.document_types
                    WHERE owner_tenant_id IS NULL AND document_type_key = '{key}'
                )
                """
            )
        )
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.tenant_document_types (
                tenant_id, document_type_id, physical_form_type,
                requires_processing, is_active, display_order,
                created_at_utc, updated_at_utc
            )
            SELECT ts.tenant_id, dt.document_type_id, dt.category,
                   true, true, 100, now(), now()
            FROM docintel.tenant_settings ts
            JOIN docintel.document_types dt
              ON dt.owner_tenant_id IS NULL AND dt.status='ACTIVE'
             AND dt.document_type_key IN ('credit_note', 'gst_declaration')
            ON CONFLICT (tenant_id, document_type_id) DO NOTHING
            """
        )
    )

    # ── 2. Ensure every genuinely new canonical field exists ────────────────
    for field_key, display_name, data_type in _NEW_CANONICAL_FIELDS:
        _ensure_canonical_field(conn, field_key, display_name, data_type)

    # ── 3. payment_receipt: clone dealer_receipt's published fields + one
    #        Delivery-specific addition (never had a profile at all before) ──
    dealer_receipt_dtid = _document_type_id(conn, "dealer_receipt")
    dealer_receipt_profile_id = _current_published_profile_id(conn, dealer_receipt_dtid)
    payment_receipt_dtid = _document_type_id(conn, "payment_receipt")
    payment_receipt_profile_id = _new_profile_id(
        conn, payment_receipt_dtid, "Payment Receipt Extraction v1", "payment_receipt",
    )
    _clone_profile_fields(conn, dealer_receipt_profile_id, payment_receipt_profile_id)
    _add_field(
        conn, payment_receipt_profile_id, "invoice_reference_number",
        expected=False,
        instruction="Extract the invoice/bill number this receipt is raised against, exactly as printed, if stated.",
        aliases=["against bill no", "invoice no", "bill no", "against invoice"],
        score_included=False, score_weight=0.0, display_sequence=999,
    )
    _publish(conn, payment_receipt_profile_id)

    # ── 4. customer_kyc: fresh profile (never had one at all before) ────────
    customer_kyc_dtid = _document_type_id(conn, "customer_kyc")
    customer_kyc_profile_id = _new_profile_id(
        conn, customer_kyc_dtid, "Customer KYC Extraction v1", "customer_kyc",
    )
    _kyc_fields = [
        ("evidence_format", False, "Identify the evidence format: PAN_CARD, AADHAAR, VOTER_ID, PASSPORT, DRIVING_LICENSE, KYC_FORM, or OTHER.", ["id type", "document type"], False, 0.0, 10),
        ("customer_name", True, "Extract the customer's name exactly as printed.", ["name", "customer name"], True, 1.0, 20),
        ("relation_name", False, "Extract father's/husband's/guardian's name if printed (S/O, W/O, D/O, C/O).", ["s/o", "w/o", "d/o", "c/o"], False, 0.0, 30),
        ("id_type", False, "Extract the identity document type only when this is a printed ID.", ["id type"], False, 0.0, 40),
        ("id_number", False, "Extract the identity/document number exactly as printed.", ["id no", "document no"], False, 0.0, 50),
        ("date_of_birth", False, "Extract date of birth if printed.", ["dob", "date of birth"], False, 0.0, 60),
        ("address", False, "Extract the full address exactly as printed.", ["address"], False, 0.0, 70),
        ("pin_code", False, "Extract the PIN/postal code exactly as printed.", ["pin", "pincode", "pin code"], False, 0.0, 80),
        ("phone_number", False, "Extract the phone number exactly as printed.", ["phone", "mobile", "contact"], False, 0.0, 90),
        ("document_date", False, "Extract the date the KYC form/declaration was signed or issued, if printed.", ["date"], False, 0.0, 100),
        ("photo_present", False, "True when a person photo is clearly present, false when clearly absent, null when uncertain.", ["photo"], False, 0.0, 110),
        ("signature_present", False, "True when the customer's signature is clearly present, false when clearly absent, null when uncertain.", ["signature"], False, 0.0, 120),
        ("is_photocopy", False, "True when clearly a photocopy/scan, false when clearly an original, null when uncertain.", ["photocopy", "scan"], False, 0.0, 130),
    ]
    for field_key, expected, instruction, aliases, score_included, score_weight, seq in _kyc_fields:
        _add_field(
            conn, customer_kyc_profile_id, field_key,
            expected=expected, instruction=instruction, aliases=aliases,
            score_included=score_included, score_weight=score_weight, display_sequence=seq,
        )
    _publish(conn, customer_kyc_profile_id)

    # ── 5. gst_declaration: fresh profile, brand new type ────────────────────
    gst_declaration_dtid = _document_type_id(conn, "gst_declaration")
    gst_declaration_profile_id = _new_profile_id(
        conn, gst_declaration_dtid, "GST Declaration Extraction v1", "gst_declaration",
    )
    _gst_declaration_fields = [
        ("customer_name", True, "Extract the declarant/customer name exactly as printed or handwritten.", ["name"], True, 1.0, 10),
        ("relation_name", False, "Extract father's/husband's/guardian's name if stated (S/O, W/O, D/O).", ["s/o", "w/o", "d/o"], False, 0.0, 20),
        ("address", False, "Extract the customer address exactly as stated.", ["address"], False, 0.0, 30),
        ("pin_code", False, "Extract the PIN/postal code exactly as stated.", ["pin"], False, 0.0, 40),
        ("vehicle_model", False, "Extract the vehicle model purchased, exactly as stated.", ["model"], False, 0.0, 50),
        ("purchase_date", False, "Extract the date of purchase stated in the declaration.", ["date"], False, 0.0, 60),
        ("has_gst_number", True, "True when the declarant states they hold a GST number, false when they explicitly declare no GST number, null when not clearly stated.", ["gst number", "gstin"], True, 1.0, 70),
        ("gstin", False, "Extract the declared GSTIN, only when has_gst_number is true and a number is actually written.", ["gstin", "gst no"], False, 0.0, 80),
        ("customer_signature_present", False, "True when the customer/owner's signature is clearly present.", ["signature"], False, 0.0, 90),
        ("sales_personnel_name", False, "Extract the sales personnel name if printed/signed.", ["sales personnel"], False, 0.0, 100),
        ("sales_personnel_signature_present", False, "True when the sales personnel's signature is clearly present.", ["signature"], False, 0.0, 110),
        ("document_date", False, "Extract the date the declaration itself was signed, if separately stated from purchase_date.", ["date"], False, 0.0, 120),
    ]
    for field_key, expected, instruction, aliases, score_included, score_weight, seq in _gst_declaration_fields:
        _add_field(
            conn, gst_declaration_profile_id, field_key,
            expected=expected, instruction=instruction, aliases=aliases,
            score_included=score_included, score_weight=score_weight, display_sequence=seq,
        )
    _publish(conn, gst_declaration_profile_id)

    # ── 6. credit_note: clone customer_invoice_dms's published fields --
    #        identical field superset by design (invoice.py's _build_schema,
    #        extension="vehicle" for both), never had a profile before ──────
    customer_invoice_dms_dtid = _document_type_id(conn, "customer_invoice_dms")
    customer_invoice_dms_profile_id = _current_published_profile_id(conn, customer_invoice_dms_dtid)
    credit_note_dtid = _document_type_id(conn, "credit_note")
    credit_note_profile_id = _new_profile_id(
        conn, credit_note_dtid, "Credit Note Extraction v1", "credit_note",
    )
    _clone_profile_fields(conn, customer_invoice_dms_profile_id, credit_note_profile_id)
    _publish(conn, credit_note_profile_id)

    # ── 7. Turn processing ON for payment_receipt/customer_kyc now that both
    #        have a published profile -- 0016 deliberately left
    #        requires_processing=false for exactly this reason ("until an
    #        Admin publishes a matching extraction profile"). Without this,
    #        every future upload of either type would still never queue
    #        extraction despite the profile now existing. ────────────────────
    conn.execute(
        sa.text(
            """
            UPDATE docintel.tenant_document_types tdt
            SET requires_processing=true, updated_at_utc=now()
            FROM docintel.document_types dt
            WHERE dt.document_type_id=tdt.document_type_id
              AND dt.owner_tenant_id IS NULL
              AND dt.document_type_key IN ('payment_receipt', 'customer_kyc')
              AND tdt.requires_processing=false
            """
        )
    )

    # ── 8. Backfill already-stuck documents: a Capture V2 upload never knows
    #        its type until classification, so intake never queued a job for
    #        these (requires_processing was false at every gate it passed
    #        through); nothing will retroactively notice the type now has a
    #        profile on its own. Queue their first-ever extraction directly. ─
    stuck_rows = conn.execute(
        sa.text(
            """
            SELECT d.tenant_id, d.document_id
            FROM docintel.documents d
            WHERE d.document_type_hint_key IN ('payment_receipt', 'customer_kyc')
              AND d.processing_status NOT IN ('PROCESSED', 'FAILED')
              AND NOT EXISTS (
                  SELECT 1 FROM docintel.processing_jobs pj
                  WHERE pj.tenant_id = d.tenant_id AND pj.document_id = d.document_id
              )
            """
        )
    ).all()
    for tenant_id, document_id in stuck_rows:
        conn.execute(
            sa.text(
                """
                UPDATE docintel.documents
                SET requires_processing=true, updated_at_utc=now()
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
                VALUES
                    (:tid, gen_random_uuid(), :did, :corr,
                     'INITIAL', 'PENDING', now(), 1, now())
                ON CONFLICT (tenant_id, document_id, job_type) DO NOTHING
                """
            ),
            {"tid": tenant_id, "did": document_id, "corr": f"backfill.0036.{document_id}"},
        )
    if stuck_rows:
        conn.execute(sa.text("SELECT pg_notify('di_processing_jobs', 'backfill_0036')"))


def downgrade() -> None:
    # Published configuration is immutable; a forward-only design (same as
    # every other profile-publishing migration in this repo, e.g. 0016/0034).
    pass
