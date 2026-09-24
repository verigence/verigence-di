"""Publish extraction profiles for the remaining UC03 catalog types with none.

Revision ID: 0046
Revises: 0045
Create Date: 2026-09-24

Direct user correction (2026-09-24): "all types of schemas which are
registered in DI should be there ... its not about one or other document."
Migration 0016 (Add the UC03 Booking/Delivery business document catalogue)
registered 19 document types with requires_processing=false, its own
docstring saying explicitly: "Some already have extraction profiles; the
remaining document types are valid manual-review evidence until an Admin
publishes an extraction profile for them." Later migrations (0022, 0026,
0028, 0036, 0038) closed most of that gap one type at a time as each was
reported broken -- this migration closes the entire remaining gap for the
UC03 Booking/Delivery catalog in one pass, rather than waiting for each of
the remaining types to be individually reported stuck:

  - minimum_booking_payment_proof
  - vehicle_rc                  (Journey Documents checklist label: "Trade-In RC")
  - transfer_letter             ("Trade-In Transfer Letter")
  - authorization_letter        ("Trade-In Authorization...")
  - cost_sheet
  - value_added_service_document
  - no_dues_certificate

(debit_note, purchase_order, bank_approval_letter, valuation_report also
have no published profile, but are not referenced anywhere in Audit
Core's UC03 Booking/Delivery requirement catalog -- out of scope here.)

Mirrors 0038's structure (fresh profiles) and 0036's steps 7-8 (turn
requires_processing on, backfill already-stuck documents that classified
before this profile existed and so never got an INITIAL job queued at
all).
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

_ACTOR = "migration.0046.uc03-delivery-extraction-profile-gaps"
# Same rule migration 0042 registered and wires onto every DATE field of
# every published, tenant-agnostic profile -- 0042 could only retrofit
# profiles that already existed at the time; a brand new profile has to
# wire this itself. Cheap to do here directly (INSERT while still DRAFT)
# rather than 0042's clone-and-republish dance, which exists only because
# profile_field_validators is guarded immutable once PUBLISHED (see
# 0042's own docstring) -- these fields have never been published yet.
_DATE_VALIDATOR_RULE_KEY = "date_plausible_range"

_GAP_TYPE_KEYS = (
    "minimum_booking_payment_proof",
    "vehicle_rc",
    "transfer_letter",
    "authorization_letter",
    "cost_sheet",
    "value_added_service_document",
    "no_dues_certificate",
)

_NEW_CANONICAL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("owner_name", "Owner Name", "STRING"),
    ("registration_date", "Registration Date", "DATE"),
    ("registering_authority", "Registering Authority (RTO)", "STRING"),
    ("vehicle_class", "Vehicle Class", "STRING"),
    ("vehicle_fuel_type", "Vehicle Fuel Type", "STRING"),
    ("vehicle_seating_capacity", "Vehicle Seating Capacity", "INTEGER"),
    ("transferor_name", "Transferor Name", "STRING"),
    ("transferee_name", "Transferee Name", "STRING"),
    ("transfer_date", "Transfer Date", "DATE"),
    ("sale_consideration_amount", "Sale Consideration Amount", "CURRENCY"),
    ("authorizer_name", "Authorizer Name", "STRING"),
    ("authorized_person_name", "Authorized Person Name", "STRING"),
    ("authorization_purpose", "Authorization Purpose", "STRING"),
    ("authorization_date", "Authorization Date", "DATE"),
    ("rto_amount", "RTO Amount", "CURRENCY"),
    ("cost_sheet_date", "Cost Sheet Date", "DATE"),
    ("service_amount", "Service Amount", "CURRENCY"),
    ("financer_name", "Financer Name", "STRING"),
    ("certificate_date", "Certificate Date", "DATE"),
    ("closure_date", "Closure Date", "DATE"),
    # Already registered by earlier migrations (dealer_receipt, insurance_cover,
    # loan_statement, supporting_document, booking commercial components) --
    # listed here too so _ensure_canonical_field's own existence check is the
    # single source of truth for what's actually new, not this comment.
    ("dealer_name", "Dealer Name", "STRING"),
    ("receipt_number", "Receipt Number", "IDENTIFIER"),
    ("receipt_date", "Receipt Date", "DATE"),
    ("customer_name", "Customer Name", "STRING"),
    ("amount_paid", "Amount Paid", "CURRENCY"),
    ("payment_mode", "Payment Mode", "STRING"),
    ("payment_reference_no", "Payment Reference Number", "IDENTIFIER"),
    ("booking_reference_number", "Booking Reference Number", "STRING"),
    ("vehicle_registration_number", "Vehicle Registration Number", "IDENTIFIER"),
    ("vehicle_model", "Vehicle Model", "STRING"),
    ("chassis_number", "Chassis Number", "IDENTIFIER"),
    ("engine_number", "Engine Number", "IDENTIFIER"),
    ("ex_showroom_price", "Ex-Showroom Price", "CURRENCY"),
    ("insurance_amount", "Insurance Amount", "CURRENCY"),
    ("accessories_amount", "Accessories Amount", "CURRENCY"),
    ("discount_amount", "Discount Amount", "CURRENCY"),
    ("total_on_road_price", "Total On-Road Price", "CURRENCY"),
    ("borrower_name", "Borrower Name", "STRING"),
    ("loan_account_number", "Loan Account Number", "IDENTIFIER"),
    ("document_title", "Document Title", "STRING"),
    ("issuing_entity", "Issuing Entity", "STRING"),
    ("reference_number", "Reference Number", "IDENTIFIER"),
    ("document_date", "Document Date", "DATE"),
    ("subject_name", "Subject Name", "STRING"),
)

# document_type_key -> (profile_name, classification_hint, fields)
# fields: field_key, expected, instruction, aliases, score_included, score_weight, display_sequence
_PROFILES: dict[str, tuple[str, str, list[tuple[str, bool, str, list[str], bool, float, int]]]] = {
    "minimum_booking_payment_proof": (
        "Minimum Booking Amount Payment Proof Extraction v1",
        "minimum_booking_payment_proof",
        [
            ("dealer_name", False, "Extract dealership name if shown.", ["dealer", "dealership"], False, 0.0, 10),
            ("receipt_number", True, "Extract receipt/voucher number.", ["receipt no", "voucher no"], True, 1.0, 20),
            ("receipt_date", True, "Extract receipt/payment date.", ["receipt date", "date"], True, 1.0, 30),
            ("customer_name", True, "Extract payer/customer name.", ["customer", "received from"], True, 1.0, 40),
            ("amount_paid", True, "Extract the amount paid toward the minimum booking amount.", ["amount", "amount received", "booking amount"], True, 1.0, 50),
            ("payment_mode", False, "Extract cash/card/UPI/cheque/NEFT/RTGS or other mode.", ["payment mode", "mode"], False, 0.0, 60),
            ("payment_reference_no", False, "Extract transaction/UTR/cheque/payment reference if present.", ["utr", "transaction id", "reference no", "cheque no"], False, 0.0, 70),
            ("booking_reference_number", False, "Extract linked booking/order/reference number if present.", ["booking no", "order no"], False, 0.0, 80),
        ],
    ),
    "vehicle_rc": (
        "Vehicle Registration Certificate Extraction v1",
        "vehicle_rc",
        [
            ("vehicle_registration_number", True, "Extract the vehicle's registration number exactly as printed.", ["registration no", "reg no", "regn no"], True, 1.0, 10),
            ("owner_name", True, "Extract the registered owner's name.", ["owner", "registered owner", "name of owner"], True, 1.0, 20),
            ("chassis_number", True, "Extract the chassis number exactly as printed.", ["chassis no"], True, 1.0, 30),
            ("engine_number", True, "Extract the engine number exactly as printed.", ["engine no"], True, 1.0, 40),
            ("vehicle_model", False, "Extract the vehicle's Make/Model exactly as printed.", ["maker model", "model"], False, 0.0, 50),
            ("vehicle_class", False, "Extract the vehicle class exactly as printed.", ["class", "vehicle class"], False, 0.0, 60),
            ("vehicle_fuel_type", False, "Extract the fuel type exactly as printed.", ["fuel", "fuel type"], False, 0.0, 70),
            ("vehicle_seating_capacity", False, "Extract the seating capacity exactly as printed.", ["seating capacity", "seat capacity"], False, 0.0, 80),
            ("registration_date", False, "Extract the date of registration.", ["registration date", "regn date", "date of registration"], False, 0.0, 90),
            ("registering_authority", False, "Extract the registering RTO/authority name.", ["registering authority", "rto"], False, 0.0, 100),
        ],
    ),
    "transfer_letter": (
        "Vehicle Transfer Letter Extraction v1",
        "transfer_letter",
        [
            ("transferor_name", True, "Extract the transferor's (current owner/seller's) name.", ["transferor", "seller", "from"], True, 1.0, 10),
            ("transferee_name", True, "Extract the transferee's (buyer/dealer's) name.", ["transferee", "buyer", "to"], True, 1.0, 20),
            ("vehicle_registration_number", True, "Extract the vehicle's registration number exactly as printed.", ["registration no", "reg no"], True, 1.0, 30),
            ("chassis_number", False, "Extract the chassis number if present.", ["chassis no"], False, 0.0, 40),
            ("transfer_date", True, "Extract the date of transfer.", ["transfer date", "date"], True, 1.0, 50),
            ("sale_consideration_amount", False, "Extract the sale consideration/amount if stated.", ["consideration", "amount", "sale value"], False, 0.0, 60),
        ],
    ),
    "authorization_letter": (
        "Authorization Letter Extraction v1",
        "authorization_letter",
        [
            ("authorizer_name", True, "Extract the name of the person granting authorization.", ["authorizer", "i,", "signed by"], True, 1.0, 10),
            ("authorized_person_name", True, "Extract the name of the person/entity being authorized.", ["authorized person", "hereby authorize"], True, 1.0, 20),
            ("vehicle_registration_number", False, "Extract the vehicle's registration number if this authorization references a specific vehicle.", ["registration no", "reg no"], False, 0.0, 30),
            ("authorization_purpose", False, "Extract what the authorized person is being permitted to do.", ["purpose", "for the purpose of"], False, 0.0, 40),
            ("authorization_date", False, "Extract the date the authorization was signed.", ["date"], False, 0.0, 50),
        ],
    ),
    "cost_sheet": (
        "Cost Sheet Extraction v1",
        "cost_sheet",
        [
            ("customer_name", True, "Extract the customer's name.", ["customer", "name"], True, 1.0, 10),
            ("vehicle_model", True, "Extract the vehicle model/variant.", ["model", "variant"], True, 1.0, 20),
            ("ex_showroom_price", True, "Extract the ex-showroom price.", ["ex-showroom", "ex showroom price"], True, 1.0, 30),
            ("rto_amount", False, "Extract the RTO/registration amount.", ["rto", "registration charges"], False, 0.0, 40),
            ("insurance_amount", False, "Extract the insurance amount.", ["insurance"], False, 0.0, 50),
            ("accessories_amount", False, "Extract the accessories amount if listed.", ["accessories"], False, 0.0, 60),
            ("discount_amount", False, "Extract the total discount/bonus amount if listed.", ["discount", "bonus"], False, 0.0, 70),
            ("total_on_road_price", True, "Extract the total on-road price.", ["on-road price", "total price", "grand total"], True, 1.0, 80),
            ("cost_sheet_date", False, "Extract the cost sheet's own date.", ["date"], False, 0.0, 90),
        ],
    ),
    "value_added_service_document": (
        "Value Added Service Document Extraction v1",
        "value_added_service_document",
        [
            ("document_title", True, "Extract the document's visible title/type.", ["title", "document type"], True, 1.0, 10),
            ("issuing_entity", False, "Extract the organisation/authority issuing the document.", ["issued by", "issuer"], False, 0.0, 20),
            ("reference_number", False, "Extract the primary reference/certificate/document number if present.", ["reference no", "document no"], False, 0.0, 30),
            ("document_date", False, "Extract the primary issue/document date if present.", ["date", "issued on"], False, 0.0, 40),
            ("subject_name", False, "Extract the person/entity the document relates to.", ["name", "subject"], False, 0.0, 50),
            ("service_amount", False, "Extract the service's cost/amount if stated.", ["amount", "cost", "price"], False, 0.0, 60),
        ],
    ),
    "no_dues_certificate": (
        "No Dues Certificate Extraction v1",
        "no_dues_certificate",
        [
            ("financer_name", True, "Extract the financer/bank/NBFC name issuing the certificate.", ["financer", "bank", "lender"], True, 1.0, 10),
            ("borrower_name", True, "Extract the borrower/customer name.", ["borrower", "customer", "name of borrower"], True, 1.0, 20),
            ("loan_account_number", True, "Extract the loan account/reference number.", ["loan account no", "loan no", "loan id"], True, 1.0, 30),
            ("vehicle_registration_number", False, "Extract the financed vehicle's registration number if present.", ["registration no", "reg no"], False, 0.0, 40),
            ("certificate_date", False, "Extract the date the certificate was issued.", ["date", "issued on"], False, 0.0, 50),
            ("closure_date", False, "Extract the date the loan was actually closed, if different from the certificate date.", ["closure date", "date of closure"], False, 0.0, 60),
        ],
    ),
}


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


def _wire_date_plausibility_validator(conn: Any, profile_id: Any) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO docintel.profile_field_validators (
                profile_field_validator_id, profile_field_id,
                sequence_no, rule_key, parameters, severity
            )
            SELECT gen_random_uuid(), epf.profile_field_id, 1, :rule_key, '{}'::jsonb, 'ERROR'
            FROM docintel.extraction_profile_fields epf
            JOIN docintel.canonical_fields cf
              ON cf.canonical_field_id = epf.canonical_field_id
            WHERE epf.profile_id = :profile_id
              AND cf.data_type = 'DATE'
              AND epf.enabled = true
            """
        ),
        {"profile_id": profile_id, "rule_key": _DATE_VALIDATOR_RULE_KEY},
    )


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Canonical fields (idempotent -- reused keys already exist and are
    #        left untouched; only genuinely new ones get inserted). ──────────
    for field_key, display_name, data_type in _NEW_CANONICAL_FIELDS:
        _ensure_canonical_field(conn, field_key, display_name, data_type)

    # ── 2. A fresh, published profile per gap type. ─────────────────────────
    published_document_type_ids: list[Any] = []
    for document_type_key, (profile_name, classification_hint, fields) in _PROFILES.items():
        document_type_id = conn.execute(
            sa.text(
                """
                SELECT document_type_id FROM docintel.document_types
                WHERE owner_tenant_id IS NULL AND document_type_key=:key AND status='ACTIVE'
                """
            ),
            {"key": document_type_key},
        ).scalar_one()
        already_published = conn.execute(
            sa.text(
                """
                SELECT 1 FROM docintel.extraction_profiles
                WHERE document_type_id=:dtid AND scope_tenant_id IS NULL AND status='PUBLISHED'
                """
            ),
            {"dtid": document_type_id},
        ).scalar_one_or_none()
        if already_published is not None:
            continue

        profile_id = conn.execute(
            sa.text(
                """
                INSERT INTO docintel.extraction_profiles (
                    profile_id, document_type_id, scope_tenant_id, version_no,
                    profile_name, status, classification_hint,
                    created_by_actor_id, created_at_utc, updated_at_utc
                ) VALUES (
                    gen_random_uuid(), :dtid, NULL, 1,
                    :profile_name, 'DRAFT', :hint, :actor_id, now(), now()
                ) RETURNING profile_id
                """
            ),
            {"dtid": document_type_id, "profile_name": profile_name, "hint": classification_hint, "actor_id": _ACTOR},
        ).scalar_one()

        for field_key, expected, instruction, aliases, score_included, score_weight, seq in fields:
            _add_field(
                conn, profile_id, field_key,
                expected=expected, instruction=instruction, aliases=aliases,
                score_included=score_included, score_weight=score_weight, display_sequence=seq,
            )

        _wire_date_plausibility_validator(conn, profile_id)

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
        published_document_type_ids.append(document_type_id)

    # ── 3. Turn processing ON now that every gap type has a published
    #        profile -- 0016 deliberately left requires_processing=false for
    #        exactly this reason. Without this, every future upload of any
    #        of these types would still never queue extraction despite the
    #        profile now existing. ──────────────────────────────────────────
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
        {"keys": list(_GAP_TYPE_KEYS)},
    )

    # ── 4. Backfill already-stuck documents (mirrors 0036 steps 7-8): a
    #        Capture V2 upload never knows its type until classification, so
    #        intake never queued a job for these (requires_processing was
    #        false at every gate it passed through); nothing will
    #        retroactively notice the type now has a profile on its own.
    #        Queue their first-ever extraction directly. ────────────────────
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
        {"keys": list(_GAP_TYPE_KEYS)},
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
            {"tid": tenant_id, "did": document_id, "corr": f"backfill.0046.{document_id}"},
        )
    if stuck_rows:
        conn.execute(sa.text("SELECT pg_notify('di_processing_jobs', 'backfill_0046')"))


def downgrade() -> None:
    # Published configuration is immutable; forward-only (same as every
    # other profile-publishing migration in this repo, e.g. 0016/0036/0038).
    pass
