"""Migration 0051: the published customer_ledger profile matches its schema.

The runtime extracts by the published profile's fields while Audit Core reads
the schema's names, so a profile with different keys silently drops every
ledger value (see the migration docstring). These tests pin the migration's
field snapshot to CUSTOMER_LEDGER_SCHEMA, the resulting DB state, and the
startup check's key comparison for the types this fixed.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.document_ai.schemas import SCHEMA_REGISTRY
from verigence.di.document_ai.schemas.customer_ledger import CUSTOMER_LEDGER_SCHEMA
from verigence.di.document_ai.schemas.dealer_receipt import DEALER_RECEIPT_SCHEMA
from verigence.di.document_ai.schemas.payment_receipt import PAYMENT_RECEIPT_SCHEMA
from verigence.di.repositories.database import set_tenant_context
from verigence.di.repositories.tenants import (
    provision_actor,
    provision_retention_policy,
    provision_tenant,
)

_KEYS = {f.key for f in CUSTOMER_LEDGER_SCHEMA.fields}
_PUBLISHED_KEYS_SQL = """
    SELECT COALESCE(epf.extraction_key, cf.field_key)
    FROM docintel.extraction_profile_fields epf
    JOIN docintel.extraction_profiles ep ON ep.profile_id = epf.profile_id
    JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
    JOIN docintel.canonical_fields cf ON cf.canonical_field_id = epf.canonical_field_id
    WHERE dt.document_type_key = :dtkey AND ep.status = 'PUBLISHED' AND epf.enabled = true
"""


def _migration() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0051_customer_ledger_profile_schema_parity.py"
    spec = importlib.util.spec_from_file_location("mig_0051", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.no_docker
def test_migration_field_snapshot_equals_the_schema() -> None:
    fields = _migration()._FIELDS
    assert [f[0] for f in fields] == [f.key for f in CUSTOMER_LEDGER_SCHEMA.fields]
    by_key = {f[0]: f for f in fields}
    for spec in CUSTOMER_LEDGER_SCHEMA.fields:
        assert by_key[spec.key][2].startswith(spec.description), spec.key
    assert {k for k, *_rest in fields if by_key[k][3]} == {"customer_name", "closing_balance", "total_credited"}


@pytest.mark.no_docker
@pytest.mark.parametrize("schema", [PAYMENT_RECEIPT_SCHEMA, DEALER_RECEIPT_SCHEMA])
def test_receipt_schemas_declare_booking_reference_number(schema) -> None:  # type: ignore[no-untyped-def]
    spec = {f.key: f for f in schema.fields}["booking_reference_number"]
    assert spec.field_type == "string"
    assert spec.required is False
    assert SCHEMA_REGISTRY[schema.document_type_key] is schema


@pytest.mark.asyncio
async def test_published_ledger_profile_matches_schema(db_session: AsyncSession) -> None:
    rows = (await db_session.execute(text(
        """
        SELECT ep.version_no, ep.status FROM docintel.extraction_profiles ep
        JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
        WHERE dt.document_type_key = 'customer_ledger' AND ep.scope_tenant_id IS NULL
        """
    ))).all()
    published = [v for v, s in rows if s == "PUBLISHED"]
    assert len(published) == 1
    assert all(s == "RETIRED" for v, s in rows if v != published[0])
    assert published[0] >= 3

    keys = set((await db_session.execute(text(_PUBLISHED_KEYS_SQL), {"dtkey": "customer_ledger"})).scalars())
    assert keys == _KEYS

    scored = set((await db_session.execute(text(
        """
        SELECT epf.extraction_key FROM docintel.extraction_profile_fields epf
        JOIN docintel.extraction_profiles ep ON ep.profile_id = epf.profile_id
        JOIN docintel.document_types dt ON dt.document_type_id = ep.document_type_id
        WHERE dt.document_type_key = 'customer_ledger' AND ep.status = 'PUBLISHED'
          AND epf.expected = true AND epf.score_included = true AND epf.score_weight > 0
        """
    ))).scalars())
    assert scored == {"customer_name", "closing_balance", "total_credited"}

    dated = set((await db_session.execute(text(
        """
        SELECT epf.extraction_key FROM docintel.extraction_profile_fields epf
        JOIN docintel.extraction_profiles ep ON ep.profile_id = epf.profile_id
        JOIN docintel.profile_field_validators v ON v.profile_field_id = epf.profile_field_id
        WHERE ep.status = 'PUBLISHED' AND v.rule_key = 'date_plausible_range'
          AND epf.extraction_key IN ('period_from', 'period_to')
        """
    ))).scalars())
    assert dated == {"period_from", "period_to"}


@pytest.mark.asyncio
@pytest.mark.parametrize("dtkey", ["customer_ledger", "payment_receipt"])
async def test_startup_check_reports_no_mismatch(db_session: AsyncSession, dtkey: str) -> None:
    # Same comparison as main._validate_schema_profile_consistency.
    profile_keys = set((await db_session.execute(text(_PUBLISHED_KEYS_SQL), {"dtkey": dtkey})).scalars())
    schema_keys = {f.key for f in SCHEMA_REGISTRY[dtkey].fields}
    assert profile_keys, f"no published {dtkey} profile"
    assert schema_keys - profile_keys == set()
    assert profile_keys - schema_keys == set()


@pytest.mark.asyncio
async def test_requeue_resets_processed_unverified_ledgers_once(db_session: AsyncSession) -> None:
    tenant_id = f"t-{uuid.uuid4().hex[:12]}"
    await set_tenant_context(db_session, tenant_id)
    await provision_tenant(db_session, tenant_id)
    policy_id = await provision_retention_policy(db_session, tenant_id)
    await provision_actor(db_session, tenant_id, "test-uploader", "USER")
    dtid = (await db_session.execute(text(
        "SELECT document_type_id FROM docintel.document_types "
        "WHERE owner_tenant_id IS NULL AND document_type_key='customer_ledger'"
    ))).scalar_one()

    async def make(verified: bool) -> uuid.UUID:
        doc = uuid.uuid4()
        await db_session.execute(text(
            """
            INSERT INTO docintel.documents (
                tenant_id, document_id, document_type_id, active_retention_policy_id, upload_status,
                retention_disposition, source_channel, uploaded_by_actor_type, uploaded_by_actor_id,
                registered_at_utc, correlation_id, created_at_utc, updated_at_utc,
                processing_status, confirmation_status, confidence_score,
                verification_threshold_applied, human_verification_status, verification_state)
            VALUES (:t, :d, :dt, :p, 'FIT', 'PURGE_CONTENT', 'WEB', 'USER', 'test-uploader',
                    now(), 'corr-1', now(), now(), 'PROCESSED', 'CONFIRMED', 95, 90, 'OPTIONAL', :vs)
            """
        ), {"t": tenant_id, "d": doc, "dt": dtid, "p": policy_id,
            "vs": "VERIFIED" if verified else "NOT_VERIFIED"})
        return doc

    fresh, verified = await make(False), await make(True)
    mig = _migration()
    await db_session.run_sync(lambda s: mig._requeue_processed_ledgers(s.connection(), dtid))
    await db_session.run_sync(lambda s: mig._requeue_processed_ledgers(s.connection(), dtid))  # idempotent

    status = {
        d: (ps, cs)
        for d, ps, cs in (await db_session.execute(text(
            "SELECT document_id, processing_status, confirmation_status FROM docintel.documents "
            "WHERE tenant_id=:t"), {"t": tenant_id})).all()
    }
    assert status[fresh] == ("RETRY_PENDING", "PENDING")
    assert status[verified] == ("PROCESSED", "CONFIRMED")
    jobs = (await db_session.execute(text(
        "SELECT document_id, job_type, attempt_no, job_status FROM docintel.processing_jobs WHERE tenant_id=:t"),
        {"t": tenant_id})).all()
    assert [tuple(j) for j in jobs] == [(fresh, "NIGHTLY_REPROCESS", 3, "PENDING")]
