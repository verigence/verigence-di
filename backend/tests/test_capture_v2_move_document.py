"""Moving a document DI already read to another Audit Core context (2026-11-24).

Product owner: "no double reading". Audit Core joins a file read on a Journey of
its own to the customer's earlier booking; until now its documents were copied
there and read by the AI a second time. Now DI moves the document: the earlier
booking's context lists it and serves its values, the old context no longer
does, and nothing is read again. Against the real schema.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.api.v2.capture_documents import move_document_to_context
from verigence.di.repositories.database import set_tenant_context
from verigence.di.repositories.tenants import (
    provision_actor,
    provision_retention_policy,
    provision_tenant,
)


async def _context(session: AsyncSession, tenant_id: str, ref: str) -> dict[str, Any]:
    subject_id = uuid.uuid4()
    await session.execute(text(
        """INSERT INTO docintel.subjects (tenant_id, subject_id, subject_type, display_name,
               created_by_actor_id, created_at_utc, updated_at_utc)
           VALUES (:t, :s, 'OTHER', :r, 'test-uploader', now(), now())"""),
        {"t": tenant_id, "s": subject_id, "r": ref})
    context_id = (await session.execute(text(
        """INSERT INTO docintel.audit_storage_contexts (tenant_id, external_context_ref, subject_id, dealer_id,
               dealer_outlet_id, customer_id, project_slug, dealer_slug, dealer_outlet_slug, customer_slug,
               created_by_service_principal)
           VALUES (:t, :r, :s, :d, :o, :c, 'p', 'd', 'o', 'c', 'audit-core') RETURNING storage_context_id"""),
        {"t": tenant_id, "r": ref, "s": subject_id, "d": uuid.uuid4(), "o": uuid.uuid4(), "c": uuid.uuid4()},
    )).scalar_one()
    return {"ref": ref, "subject_id": subject_id, "context_id": context_id}


async def _seed(session: AsyncSession) -> dict[str, Any]:
    tenant_id = f"move-{uuid.uuid4().hex[:10]}"
    await set_tenant_context(session, tenant_id)
    await provision_tenant(session, tenant_id)
    policy_id = await provision_retention_policy(session, tenant_id)
    await provision_actor(session, tenant_id, "test-uploader", "USER")
    source = await _context(session, tenant_id, f"journey-{uuid.uuid4()}")
    target = await _context(session, tenant_id, f"journey-{uuid.uuid4()}")
    document_id = uuid.uuid4()
    await session.execute(text(
        """INSERT INTO docintel.documents (tenant_id, document_id, subject_id, audit_storage_context_id,
               active_retention_policy_id, retention_disposition, source_channel, uploaded_by_actor_type,
               uploaded_by_actor_id, registered_at_utc, correlation_id, created_at_utc, updated_at_utc)
           VALUES (:t, :d, :s, :c, :p, 'PURGE_CONTENT', 'API', 'USER', 'test-uploader', now(), 'c',
                   now(), now())"""),
        {"t": tenant_id, "d": document_id, "s": source["subject_id"], "c": source["context_id"], "p": policy_id})
    await session.execute(text(
        """INSERT INTO docintel.document_capture_v2_uploads (tenant_id, document_id, audit_storage_context_id,
               external_context_ref, phase, client_upload_id, logical_object_key, original_filename,
               candidate_document_type_keys, state, classified_document_type_key)
           VALUES (:t, :d, :c, :r, 'DELIVERY', 'p2-page-1', 'k', 'gate pass.pdf', '["gate_pass"]'::jsonb,
                   'CLASSIFIED', 'gate_pass')"""),
        {"t": tenant_id, "d": document_id, "c": source["context_id"], "r": source["ref"]})
    await session.execute(text(
        """INSERT INTO docintel.document_search_index (tenant_id, document_id, subject_id, document_type_key)
           VALUES (:t, :d, :s, 'gate_pass')"""),
        {"t": tenant_id, "d": document_id, "s": source["subject_id"]})
    return {"tenant_id": tenant_id, "document_id": document_id, "source": source, "target": target}


async def _where(session: AsyncSession, seed: dict[str, Any]) -> dict[str, Any]:
    return dict((await session.execute(text(
        """SELECT u.external_context_ref, u.audit_storage_context_id AS upload_context, u.phase, u.state,
                  d.subject_id, d.audit_storage_context_id AS document_context, si.subject_id AS index_subject
           FROM docintel.document_capture_v2_uploads u
           JOIN docintel.documents d ON d.tenant_id=u.tenant_id AND d.document_id=u.document_id
           JOIN docintel.document_search_index si ON si.tenant_id=u.tenant_id AND si.document_id=u.document_id
           WHERE u.tenant_id=:t AND u.document_id=:d"""),
        {"t": seed["tenant_id"], "d": seed["document_id"]})).mappings().one())


async def test_a_read_document_moves_to_the_other_context_without_being_read_again(
    db_session: AsyncSession,
) -> None:
    seed = await _seed(db_session)
    source, target = seed["source"], seed["target"]
    jobs_before = (await db_session.execute(text(
        "SELECT count(*) FROM docintel.processing_jobs WHERE tenant_id=:t AND document_id=:d"),
        {"t": seed["tenant_id"], "d": seed["document_id"]})).scalar_one()

    outcome = await move_document_to_context(
        db_session, tenant_id=seed["tenant_id"], document_id=seed["document_id"],
        source_ref=source["ref"], target_ref=target["ref"])

    assert outcome == "moved"
    where = await _where(db_session, seed)
    assert where["external_context_ref"] == target["ref"]
    assert where["upload_context"] == where["document_context"] == target["context_id"]
    assert where["subject_id"] == where["index_subject"] == target["subject_id"]
    # What it was read as stays: its phase, its state and type; no new reading.
    assert (where["phase"], where["state"]) == ("DELIVERY", "CLASSIFIED")
    assert (await db_session.execute(text(
        "SELECT count(*) FROM docintel.processing_jobs WHERE tenant_id=:t AND document_id=:d"),
        {"t": seed["tenant_id"], "d": seed["document_id"]})).scalar_one() == jobs_before
    # A retry once moved is answered, not refused; the old context no longer holds it.
    assert await move_document_to_context(
        db_session, tenant_id=seed["tenant_id"], document_id=seed["document_id"],
        source_ref=source["ref"], target_ref=target["ref"]) == "already_there"
    assert await move_document_to_context(
        db_session, tenant_id=seed["tenant_id"], document_id=seed["document_id"],
        source_ref=source["ref"], target_ref=f"journey-{uuid.uuid4()}") == "not_found"


async def test_a_move_to_a_context_not_established_changes_nothing(db_session: AsyncSession) -> None:
    seed = await _seed(db_session)
    outcome = await move_document_to_context(
        db_session, tenant_id=seed["tenant_id"], document_id=seed["document_id"],
        source_ref=seed["source"]["ref"], target_ref=f"journey-{uuid.uuid4()}")
    assert outcome == "target_missing"
    assert (await _where(db_session, seed))["external_context_ref"] == seed["source"]["ref"]
