"""Migration 0059: the form_21 and delivery_receipt document types.

Each type needs a global ACTIVE row (with its classifier definition), a
dedicated schema, a published profile whose keys and expected flags are the
schema's (D25), and a tenant_document_types row so the classifier offers it.
These tests pin the migration's profile snapshot to the schemas, the field
names to the vocabulary other schemas use, and the resulting DB state.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.document_ai.schemas import FALLBACK_SCHEMA, SCHEMA_REGISTRY, get_schema
from verigence.di.document_ai.schemas.delivery_receipt import DELIVERY_RECEIPT_SCHEMA
from verigence.di.document_ai.schemas.form_21 import FORM_21_SCHEMA
from verigence.di.document_ai.type_definitions import GLOBAL_DOCUMENT_TYPE_DEFINITIONS
from verigence.di.repositories.database import set_tenant_context
from verigence.di.repositories.tenants import provision_tenant, provision_tenant_document_types

_TYPES = ("form_21", "delivery_receipt")
_PUBLISHED_KEYS_SQL = """
    SELECT COALESCE(epf.extraction_key, cf.field_key), epf.expected
    FROM docintel.extraction_profile_fields epf
    JOIN docintel.extraction_profiles ep ON ep.profile_id = epf.profile_id
    JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
    JOIN docintel.canonical_fields cf ON cf.canonical_field_id = epf.canonical_field_id
    WHERE dt.document_type_key = :dtkey AND dt.owner_tenant_id IS NULL
      AND ep.status = 'PUBLISHED' AND ep.scope_tenant_id IS NULL AND epf.enabled = true
"""


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "0059_form_21_and_delivery_receipt_types.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0059", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.no_docker
def test_registry_resolves_the_dedicated_schemas() -> None:
    assert get_schema("form_21") is FORM_21_SCHEMA is SCHEMA_REGISTRY["form_21"]
    assert get_schema("delivery_receipt") is DELIVERY_RECEIPT_SCHEMA
    names = {key: name for key, name, _ in _migration()._NEW_DOCUMENT_TYPES}
    for key in _TYPES:
        schema = get_schema(key)
        assert schema is not FALLBACK_SCHEMA
        assert schema.document_type_key == key
        assert schema.display_name == names[key]
        assert schema.system_prompt and schema.prompt_notes
    assert names == {"form_21": "Form 21 (Sale Certificate)",
                     "delivery_receipt": "Vehicle Delivery Receipt"}


@pytest.mark.no_docker
@pytest.mark.parametrize("key", _TYPES)
def test_profile_snapshot_matches_the_schema(key: str) -> None:
    _, fields = _migration()._PROFILES[key]
    profile = {f[0]: f[1] for f in fields}
    assert len(profile) == len(fields)
    assert profile == {f.key: f.required for f in get_schema(key).fields}
    # expected fields are the scored ones, so the profile can be published
    for field_key, expected, _, aliases, scored, weight, _ in fields:
        assert scored is expected and (weight > 0) is expected, field_key
        assert aliases, field_key
    assert [f[6] for f in fields] == sorted(f[6] for f in fields)


@pytest.mark.no_docker
def test_every_profile_field_has_a_canonical_field_of_the_right_type() -> None:
    module = _migration()
    canonical = {key: data_type for key, _, data_type in module._CANONICAL_FIELDS}
    for key in _TYPES:
        for field in get_schema(key).fields:
            assert field.key in canonical, field.key
            if field.field_type == "date":
                assert canonical[field.key] == "DATE", field.key


@pytest.mark.no_docker
def test_fields_use_the_names_other_schemas_give_the_same_facts() -> None:
    form = {f.key: f for f in FORM_21_SCHEMA.fields}
    receipt = {f.key: f for f in DELIVERY_RECEIPT_SCHEMA.fields}
    # Form 21: the invoice family's names for the buyer and the financier.
    assert {"certificate_number", "invoice_number", "sale_date", "buyer_name", "buyer_address",
            "dealer_name", "vin_number", "engine_number", "vehicle_make", "vehicle_model",
            "vehicle_color", "vehicle_manufacture_month_year", "financed_by"} == set(form)
    assert {"receipt_number", "delivery_date", "customer_name", "vehicle_model", "vin_number",
            "engine_number", "financed_by"} == set(receipt)
    assert {k for k, f in form.items() if f.required} == {"buyer_name", "vin_number"}
    assert {k for k, f in receipt.items() if f.required} == {"customer_name", "vin_number"}
    for fields in (form, receipt):
        for key, field in fields.items():
            assert field.field_type in ("string", "date"), key
            if key.endswith("_date"):
                assert field.field_type == "date" and field.normalization == "date_dd_mm_yyyy", key
        # neither page bills anything: no amount is asked for
        assert not any(k.endswith(("_amount", "_price", "_total")) for k in fields)


@pytest.mark.asyncio
async def test_global_rows_are_active_with_their_definitions(db_session: AsyncSession) -> None:
    rows = {
        r["document_type_key"]: r
        for r in (await db_session.execute(text(
            "SELECT document_type_key, display_name, description, category, status "
            "FROM docintel.document_types "
            "WHERE owner_tenant_id IS NULL AND document_type_key = ANY(:keys)"
        ), {"keys": list(_TYPES)})).mappings().all()
    }
    assert set(rows) == set(_TYPES)
    for key in _TYPES:
        assert rows[key]["status"] == "ACTIVE"
        assert rows[key]["category"] == "PRINTABLE"
        assert rows[key]["display_name"] == get_schema(key).display_name
        assert rows[key]["description"] == GLOBAL_DOCUMENT_TYPE_DEFINITIONS[key]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", _TYPES)
async def test_published_profile_is_the_schema(db_session: AsyncSession, key: str) -> None:
    # Same comparison as main._validate_schema_profile_consistency, plus the flags.
    published = dict((await db_session.execute(text(_PUBLISHED_KEYS_SQL), {"dtkey": key})).all())
    assert published == {f.key: f.required for f in get_schema(key).fields}

    hint, version = (await db_session.execute(text(
        "SELECT ep.classification_hint, ep.version_no FROM docintel.extraction_profiles ep "
        "JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id "
        "WHERE dt.document_type_key = :k AND dt.owner_tenant_id IS NULL AND ep.status = 'PUBLISHED'"
    ), {"k": key})).one()
    assert (hint, version) == (key, 1)

    dated = set((await db_session.execute(text(
        """
        SELECT epf.extraction_key FROM docintel.extraction_profile_fields epf
        JOIN docintel.extraction_profiles ep ON ep.profile_id = epf.profile_id
        JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
        JOIN docintel.profile_field_validators v ON v.profile_field_id = epf.profile_field_id
        WHERE dt.document_type_key = :k AND ep.status = 'PUBLISHED'
          AND v.rule_key = 'date_plausible_range'
        """
    ), {"k": key})).scalars())
    assert dated == {f.key for f in get_schema(key).fields if f.field_type == "date"}


async def _tenant_rows(db_session: AsyncSession, tenant_id: str) -> dict[str, tuple[bool, bool, str]]:
    rows = (await db_session.execute(text(
        """
        SELECT dt.document_type_key, tdt.is_active, tdt.requires_processing, tdt.physical_form_type
        FROM docintel.tenant_document_types tdt
        JOIN docintel.document_types dt ON dt.document_type_id = tdt.document_type_id
        WHERE tdt.tenant_id = :t AND dt.document_type_key = ANY(:keys)
        """
    ), {"t": tenant_id, "keys": list(_TYPES)})).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


@pytest.mark.asyncio
async def test_migration_enables_both_for_an_existing_tenant(db_session: AsyncSession) -> None:
    tenant_id = f"t-{uuid.uuid4().hex[:12]}"
    await set_tenant_context(db_session, tenant_id)
    await provision_tenant(db_session, tenant_id)
    assert await _tenant_rows(db_session, tenant_id) == {}

    enable = _migration().enable_for_every_tenant
    await db_session.run_sync(lambda session: enable(session.connection()))
    enabled = await _tenant_rows(db_session, tenant_id)
    assert enabled == {key: (True, True, "PRINTABLE") for key in _TYPES}

    # A tenant's own choice stands when it runs again.
    await db_session.execute(text(
        "UPDATE docintel.tenant_document_types SET is_active = false "
        "WHERE tenant_id = :t AND document_type_id = (SELECT document_type_id "
        "FROM docintel.document_types WHERE owner_tenant_id IS NULL "
        "AND document_type_key = 'delivery_receipt')"
    ), {"t": tenant_id})
    await db_session.run_sync(lambda session: enable(session.connection()))
    assert (await _tenant_rows(db_session, tenant_id))["delivery_receipt"][0] is False


@pytest.mark.asyncio
async def test_a_new_tenant_is_provisioned_with_both(db_session: AsyncSession) -> None:
    # tenant_session() runs this on every session: a tenant created after the
    # migration gets both types with processing on.
    tenant_id = f"t-{uuid.uuid4().hex[:12]}"
    await set_tenant_context(db_session, tenant_id)
    await provision_tenant(db_session, tenant_id)
    await provision_tenant_document_types(db_session, tenant_id)
    assert await _tenant_rows(db_session, tenant_id) == {key: (True, True, "PRINTABLE") for key in _TYPES}
