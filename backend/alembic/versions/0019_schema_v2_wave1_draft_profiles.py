"""Seed Schema V2 Wave-1 canonical vocabulary and DRAFT profiles.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-29

This migration is configuration-only. It does NOT publish extraction profiles,
so it cannot change the classification candidate set. The frozen semantic map is
read from docs/schema-v2/WAVE1_SEMANTIC_MAPPING_v0.1.md and hash-checked before
any configuration is written. This keeps the migration tied to the reviewed map
without duplicating 100+ mapping rows by hand.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_PROFILE_NAME = "Schema V2 Wave 1 Draft"
_MAPPING_SHA256 = "36ab3f93adebcb75b38d5c4153e53514a090070b95e4982f0a1df6a648eda0ea"

_DOCUMENT_TYPES = (
    ("GST_CERTIFICATE", "gst_certificate", "GST Certificate", "PRINTABLE"),
    ("CORPORATE_ID", "corporate_id", "Corporate ID", "PRINTABLE"),
    ("BANK_APPROVAL_LETTER", "bank_approval_letter", "Bank Approval Letter", "PRINTABLE"),
    ("VALUATION_REPORT", "valuation_report", "Valuation Report", "PRINTABLE"),
)

_STRUCTURED_RULES = {
    ("gst_certificate", "authorised_signatory_names"): {
        "container": "array",
        "item_type": "string",
    },
    ("bank_approval_letter", "conditions_precedent"): {
        "container": "array",
        "item_type": "string",
    },
    ("valuation_report", "condition_parameters"): {
        "container": "array",
        "item_type": "object",
        "properties": {
            "name": ["string", "null"],
            "score_as_printed": ["string", "null"],
            "is_blank": "boolean",
        },
        "required_keys": ["name", "score_as_printed", "is_blank"],
        "allow_extra_keys": False,
    },
    ("valuation_report", "condition_deductions"): {
        "container": "array",
        "item_type": "object",
        "properties": {
            "head": ["string", "null"],
            "amount": ["number", "null"],
            "is_handwritten": "boolean",
        },
        "required_keys": ["head", "amount", "is_handwritten"],
        "allow_extra_keys": False,
    },
    ("valuation_report", "additions"): {
        "container": "array",
        "item_type": "object",
        "properties": {"head": ["string", "null"], "amount": ["number", "null"]},
        "required_keys": ["head", "amount"],
        "allow_extra_keys": False,
    },
}


def _load_frozen_mapping() -> list[tuple[str, str, str, str, str, str]]:
    repo_root = Path(__file__).resolve().parents[3]
    mapping_path = repo_root / "docs" / "schema-v2" / "WAVE1_SEMANTIC_MAPPING_v0.1.md"
    if not mapping_path.exists():
        raise RuntimeError(f"Frozen Wave-1 semantic mapping missing: {mapping_path}")

    raw = mapping_path.read_bytes()
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != _MAPPING_SHA256:
        raise RuntimeError(
            "Frozen Wave-1 semantic mapping hash mismatch; design amendment required "
            f"before migration (expected {_MAPPING_SHA256}, got {actual_hash})"
        )

    text = raw.decode("utf-8")
    rows: list[tuple[str, str, str, str, str, str]] = []
    for heading, document_type_key, _display, _form in _DOCUMENT_TYPES:
        match = re.search(rf"## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)", text, re.S)
        if match is None:
            raise RuntimeError(f"Wave-1 mapping section missing: {heading}")

        for line in match.group(1).splitlines():
            if not line.startswith("| `"):
                continue
            columns = [part.strip() for part in line.strip("|").split("|")]
            extraction_key = columns[0].strip("` ")
            canonical_key = columns[1].strip("` ")
            fact_role = columns[2].strip("` ")
            source_class = columns[3].strip("` ")
            canonical_type = columns[4].strip("` ")
            if source_class in {"REFERENCE", "DERIVED"}:
                continue
            rows.append(
                (
                    document_type_key,
                    extraction_key,
                    canonical_key,
                    fact_role,
                    source_class,
                    canonical_type,
                )
            )

    if len(rows) != 113:
        raise RuntimeError(f"Unexpected Wave-1 extraction mapping row count: {len(rows)} (expected 113)")
    return rows


def _display_name(field_key: str) -> str:
    return field_key.replace("_", " ").title()


def upgrade() -> None:
    bind = op.get_bind()
    profile_fields = _load_frozen_mapping()

    # Rule catalogue needed by DRAFT profiles.
    for rule_key, description, implementation_key in (
        (
            "schema_v2.scalar_literal_parse",
            "Parse a provider scalar literal strictly as number, integer, or boolean.",
            "di.norm.scalar_literal_parse",
        ),
        (
            "schema_v2.date_iso8601",
            "Normalize unambiguous document dates to ISO-8601.",
            "di.norm.date_iso8601",
        ),
        (
            "schema_v2.structured_literal_parse",
            "Parse a provider array/object literal into typed JSON without silent row loss.",
            "di.norm.structured_literal_parse",
        ),
    ):
        bind.execute(
            sa.text("""
                INSERT INTO docintel.normalization_rule_catalog
                    (rule_key, description, implementation_key, parameter_schema, status)
                VALUES (:rk, :descr, :impl, NULL, 'ACTIVE')
                ON CONFLICT (rule_key) DO NOTHING
            """),
            {"rk": rule_key, "descr": description, "impl": implementation_key},
        )

    bind.execute(
        sa.text("""
            INSERT INTO docintel.validation_rule_catalog
                (rule_key, description, implementation_key,
                 parameter_schema, result_scope, status)
            VALUES (
                'schema_v2.structured_shape',
                'Validate Schema V2 structured array/object shape without dropping malformed rows.',
                'di.val.structured_shape', NULL, 'FIELD', 'ACTIVE'
            )
            ON CONFLICT (rule_key) DO NOTHING
        """)
    )

    # Wave-1 document catalogue. DRAFT profiles do not enter classification.
    for _heading, key, display_name, physical_form in _DOCUMENT_TYPES:
        bind.execute(
            sa.text("""
                INSERT INTO docintel.document_types (
                    document_type_id, owner_tenant_id, document_type_key,
                    display_name, description, category, status,
                    created_at_utc, updated_at_utc
                )
                SELECT gen_random_uuid(), NULL, :key, :display_name,
                       'Schema V2 Wave-1 document type', :physical_form, 'ACTIVE',
                       now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM docintel.document_types
                    WHERE owner_tenant_id IS NULL AND document_type_key=:key
                )
            """),
            {"key": key, "display_name": display_name, "physical_form": physical_form},
        )
        bind.execute(
            sa.text("""
                INSERT INTO docintel.tenant_document_types (
                    tenant_id, document_type_id, physical_form_type,
                    requires_processing, is_active, display_order,
                    created_at_utc, updated_at_utc
                )
                SELECT ts.tenant_id, dt.document_type_id, :physical_form,
                       false, true, 100, now(), now()
                FROM docintel.tenant_settings ts
                JOIN docintel.document_types dt
                  ON dt.owner_tenant_id IS NULL AND dt.document_type_key=:key
                ON CONFLICT (tenant_id, document_type_id) DO NOTHING
            """),
            {"key": key, "physical_form": physical_form},
        )

    # Stable global canonical vocabulary. Same canonical key must have one data type.
    canonical_types: dict[str, str] = {}
    for _dt, _extraction, canonical_key, _role, _source, canonical_type in profile_fields:
        previous = canonical_types.setdefault(canonical_key, canonical_type)
        if previous != canonical_type:
            raise RuntimeError(
                f"Canonical type conflict for {canonical_key}: {previous} vs {canonical_type}"
            )

    for field_key, data_type in sorted(canonical_types.items()):
        bind.execute(
            sa.text("""
                INSERT INTO docintel.canonical_fields (
                    canonical_field_id, owner_tenant_id, field_key,
                    display_name, data_type, description, status,
                    created_at_utc, updated_at_utc
                )
                SELECT gen_random_uuid(), NULL, :field_key,
                       :display_name, :data_type,
                       'Schema V2 Wave-1 canonical field', 'ACTIVE', now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM docintel.canonical_fields
                    WHERE owner_tenant_id IS NULL AND field_key=:field_key
                )
            """),
            {
                "field_key": field_key,
                "display_name": _display_name(field_key),
                "data_type": data_type,
            },
        )

    # One isolated DRAFT per type. No existing PUBLISHED profile is retired here.
    for _heading, key, _display, _form in _DOCUMENT_TYPES:
        bind.execute(
            sa.text("""
                INSERT INTO docintel.extraction_profiles (
                    profile_id, document_type_id, scope_tenant_id, version_no,
                    profile_name, status, classification_hint,
                    created_by_actor_id, published_by_actor_id,
                    created_at_utc, published_at_utc, updated_at_utc
                )
                SELECT gen_random_uuid(), dt.document_type_id, NULL,
                       COALESCE((
                           SELECT MAX(ep2.version_no)
                           FROM docintel.extraction_profiles ep2
                           WHERE ep2.document_type_id=dt.document_type_id
                             AND ep2.scope_tenant_id IS NULL
                       ), 0) + 1,
                       :profile_name, 'DRAFT',
                       'Schema V2 Wave-1 draft. Not eligible for classification until explicitly published.',
                       'system.schema_v2', NULL, now(), NULL, now()
                FROM docintel.document_types dt
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key=:key
                  AND NOT EXISTS (
                      SELECT 1 FROM docintel.extraction_profiles ep
                      WHERE ep.document_type_id=dt.document_type_id
                        AND ep.scope_tenant_id IS NULL
                        AND ep.profile_name=:profile_name
                  )
            """),
            {"key": key, "profile_name": _PROFILE_NAME},
        )

    # Provider-native extraction key -> canonical + role. Explicit role is frozen
    # on every Wave-1 field; document default remains a workflow fallback.
    for sequence, (
        document_type_key,
        extraction_key,
        canonical_key,
        fact_role,
        _source_class,
        canonical_type,
    ) in enumerate(profile_fields, 1):
        profile_id = bind.execute(
            sa.text("""
                SELECT ep.profile_id
                FROM docintel.extraction_profiles ep
                JOIN docintel.document_types dt ON dt.document_type_id=ep.document_type_id
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key=:dt_key
                  AND ep.scope_tenant_id IS NULL
                  AND ep.profile_name=:profile_name
                  AND ep.status='DRAFT'
                ORDER BY ep.version_no DESC
                LIMIT 1
            """),
            {"dt_key": document_type_key, "profile_name": _PROFILE_NAME},
        ).scalar_one()
        canonical_id = bind.execute(
            sa.text("""
                SELECT canonical_field_id
                FROM docintel.canonical_fields
                WHERE owner_tenant_id IS NULL AND field_key=:canonical_key
            """),
            {"canonical_key": canonical_key},
        ).scalar_one()

        bind.execute(
            sa.text("""
                INSERT INTO docintel.extraction_profile_fields (
                    profile_field_id, profile_id, canonical_field_id,
                    enabled, expected, extraction_instruction, aliases,
                    score_included, score_weight,
                    use_for_subject_matching, subject_identifier_type,
                    manual_correction_allowed, display_sequence,
                    created_at_utc, updated_at_utc,
                    extraction_key, fact_role_override
                )
                SELECT gen_random_uuid(), :profile_id, :canonical_id,
                       true, false, NULL, CAST('[]' AS jsonb),
                       false, 1.0, false, NULL, true, :sequence,
                       now(), now(), :extraction_key, :fact_role
                WHERE NOT EXISTS (
                    SELECT 1 FROM docintel.extraction_profile_fields
                    WHERE profile_id=:profile_id AND extraction_key=:extraction_key
                )
            """),
            {
                "profile_id": profile_id,
                "canonical_id": canonical_id,
                "sequence": sequence,
                "extraction_key": extraction_key,
                "fact_role": fact_role,
            },
        )
        profile_field_id = bind.execute(
            sa.text("""
                SELECT profile_field_id
                FROM docintel.extraction_profile_fields
                WHERE profile_id=:profile_id AND extraction_key=:extraction_key
            """),
            {"profile_id": profile_id, "extraction_key": extraction_key},
        ).scalar_one()

        # Recover strict typed JSON values at the deterministic rules boundary.
        normalizer_key: str | None = None
        normalizer_params: dict[str, object] | None = None
        structured_params = _STRUCTURED_RULES.get((document_type_key, extraction_key))
        if structured_params is not None:
            normalizer_key = "schema_v2.structured_literal_parse"
            normalizer_params = {"container": structured_params["container"]}
        elif canonical_type in {"CURRENCY", "DECIMAL"}:
            normalizer_key = "schema_v2.scalar_literal_parse"
            normalizer_params = {"type": "number"}
        elif canonical_type == "INTEGER":
            normalizer_key = "schema_v2.scalar_literal_parse"
            normalizer_params = {"type": "integer"}
        elif canonical_type == "BOOLEAN":
            normalizer_key = "schema_v2.scalar_literal_parse"
            normalizer_params = {"type": "boolean"}
        elif canonical_type == "DATE":
            normalizer_key = "schema_v2.date_iso8601"
            normalizer_params = {"locale": "iso"}

        if normalizer_key is not None:
            bind.execute(
                sa.text("""
                    INSERT INTO docintel.profile_field_normalizers (
                        profile_field_normalizer_id, profile_field_id,
                        sequence_no, rule_key, parameters
                    )
                    SELECT gen_random_uuid(), :pfid, 1, :rule_key, CAST(:params AS jsonb)
                    WHERE NOT EXISTS (
                        SELECT 1 FROM docintel.profile_field_normalizers
                        WHERE profile_field_id=:pfid AND sequence_no=1
                    )
                """),
                {
                    "pfid": profile_field_id,
                    "rule_key": normalizer_key,
                    "params": json.dumps(normalizer_params),
                },
            )

        if structured_params is not None:
            bind.execute(
                sa.text("""
                    INSERT INTO docintel.profile_field_validators (
                        profile_field_validator_id, profile_field_id,
                        sequence_no, rule_key, parameters, severity
                    )
                    SELECT gen_random_uuid(), :pfid, 1,
                           'schema_v2.structured_shape', CAST(:params AS jsonb), 'ERROR'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM docintel.profile_field_validators
                        WHERE profile_field_id=:pfid AND sequence_no=1
                    )
                """),
                {"pfid": profile_field_id, "params": json.dumps(structured_params)},
            )


def downgrade() -> None:
    # Canonical fields may already be referenced by immutable facts. A rejected
    # Schema V2 experiment is rolled back by discarding the isolated Neon branch.
    pass
