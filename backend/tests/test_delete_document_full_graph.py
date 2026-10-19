"""delete_document against the real schema.

On 2026-10-19 every Audit Core request to delete a merged page's DI document failed:
the DELETE of its processing runs was refused by Postgres because
document_classifications (and other tables) still pointed at those runs, and the API
reported the resulting IntegrityError as DATABASE_UNAVAILABLE. delete_document must
leave no row behind that references the document or its runs, and must not touch any
other document.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.repositories.database import set_tenant_context
from verigence.di.repositories.documents import delete_document
from verigence.di.repositories.tenants import (
    provision_actor,
    provision_retention_policy,
    provision_tenant,
)


class _Storage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


async def _scalar(session: AsyncSession, sql: str, **params: Any) -> Any:
    return (await session.execute(text(sql), params)).scalar_one()


async def _tenant(session: AsyncSession) -> tuple[str, Any, Any]:
    tenant_id = f"del-graph-{uuid.uuid4().hex[:10]}"
    await set_tenant_context(session, tenant_id)
    await provision_tenant(session, tenant_id)
    policy_id = await provision_retention_policy(session, tenant_id)
    await provision_actor(session, tenant_id, "test-uploader", "USER")
    subject_id = uuid.uuid4()
    await session.execute(text(
        """INSERT INTO docintel.subjects (tenant_id, subject_id, subject_type, display_name,
               created_by_actor_id, created_at_utc, updated_at_utc)
           VALUES (:t, :s, 'OTHER', 'Graph subject', 'test-uploader', now(), now())"""),
        {"t": tenant_id, "s": subject_id})
    return tenant_id, policy_id, subject_id


async def _catalog(session: AsyncSession, tenant_id: str) -> tuple[Any, Any]:
    """One project field and its profile field (what facts and field values point at)."""
    suffix = uuid.uuid4().hex[:8]
    document_type_id = await _scalar(
        session,
        """INSERT INTO docintel.document_types (document_type_id, owner_tenant_id, document_type_key,
               display_name, category, status, created_at_utc, updated_at_utc)
           VALUES (gen_random_uuid(), :t, :k, 'Graph Type', 'PRINTABLE', 'DRAFT', now(), now())
           RETURNING document_type_id""",
        t=tenant_id, k=f"graph_type_{suffix}",
    )
    canonical_field_id = await _scalar(
        session,
        """INSERT INTO docintel.canonical_fields (canonical_field_id, owner_tenant_id, field_key,
               display_name, data_type, status, created_at_utc, updated_at_utc)
           VALUES (gen_random_uuid(), :t, :k, 'Graph Field', 'STRING', 'ACTIVE', now(), now())
           RETURNING canonical_field_id""",
        t=tenant_id, k=f"graph_field_{suffix}",
    )
    profile_id = await _scalar(
        session,
        """INSERT INTO docintel.extraction_profiles (profile_id, document_type_id, scope_tenant_id, version_no,
               profile_name, status, created_by_actor_id, created_at_utc, updated_at_utc)
           VALUES (gen_random_uuid(), :d, :t, 1, 'Graph Profile', 'DRAFT', 'test-admin', now(), now())
           RETURNING profile_id""",
        d=document_type_id, t=tenant_id,
    )
    profile_field_id = await _scalar(
        session,
        """INSERT INTO docintel.extraction_profile_fields (profile_field_id, profile_id, canonical_field_id,
               enabled, expected, aliases, score_included, score_weight, use_for_subject_matching,
               manual_correction_allowed, display_sequence, created_at_utc, updated_at_utc,
               extraction_key, fact_role_override)
           VALUES (gen_random_uuid(), :p, :c, true, false, '[]'::jsonb, false, 0, false, true, 10, now(), now(),
                   :k, 'UNSPECIFIED') RETURNING profile_field_id""",
        p=profile_id, c=canonical_field_id, k=f"graph_{uuid.uuid4().hex[:6]}",
    )
    return canonical_field_id, profile_field_id


async def _document_graph(
    session: AsyncSession,
    tenant_id: str,
    policy_id: Any,
    canonical_field_id: Any,
    profile_field_id: Any,
    *,
    subject_id: Any,
) -> dict[str, Any]:
    """A classified, extracted document with one row in every table that references it."""
    ids = {k: uuid.uuid4() for k in (
        "doc", "job", "run", "invocation", "fact", "verification", "artifact", "intake", "link")}
    p = {"t": tenant_id, **ids}
    await session.execute(text(
        """INSERT INTO docintel.documents (tenant_id, document_id, subject_id, active_retention_policy_id,
               retention_disposition, source_channel, uploaded_by_actor_type, uploaded_by_actor_id,
               registered_at_utc, correlation_id, created_at_utc, updated_at_utc)
           VALUES (:t, :doc, :sid, :pol, 'PURGE_CONTENT', 'WEB', 'USER', 'test-uploader', now(), 'c', now(), now())"""),
        {**p, "sid": subject_id, "pol": policy_id})
    await session.execute(text(
        """INSERT INTO docintel.processing_jobs (tenant_id, processing_job_id, document_id, correlation_id,
               job_type, job_status, due_at_utc, attempt_no, created_at_utc)
           VALUES (:t, :job, :doc, 'c', 'INITIAL', 'COMPLETED', now(), 1, now())"""), p)
    await session.execute(text(
        """INSERT INTO docintel.processing_runs (tenant_id, processing_run_id, processing_job_id, document_id,
               correlation_id, run_type, run_status, pipeline_version, started_at_utc, created_at_utc)
           VALUES (:t, :run, :job, :doc, 'c', 'INITIAL', 'COMPLETED', 'test', now(), now())"""), p)
    await session.execute(text(
        "UPDATE docintel.documents SET current_processing_run_id=:run WHERE tenant_id=:t AND document_id=:doc"), p)
    await session.execute(text(
        """INSERT INTO docintel.document_classifications (tenant_id, classification_id, processing_run_id,
               document_id, classification_method, created_at_utc)
           VALUES (:t, gen_random_uuid(), :run, :doc, 'GEMINI', now())"""), p)
    await session.execute(text(
        """INSERT INTO docintel.processor_invocations (tenant_id, invocation_id, processing_run_id,
               correlation_id, capability, adapter_key, outcome, started_at_utc)
           VALUES (:t, :invocation, :run, 'c', 'OTHER', 'test', 'SUCCESS', now())"""), p)
    await session.execute(text(
        """INSERT INTO docintel.extracted_facts (tenant_id, extracted_fact_id, processing_run_id, document_id,
               profile_field_id, canonical_field_id, found_status, created_at_utc, invocation_id)
           VALUES (:t, :fact, :run, :doc, :pf, :cf, 'FOUND', now(), :invocation)"""),
        {**p, "pf": profile_field_id, "cf": canonical_field_id})
    await session.execute(text(
        """INSERT INTO docintel.validation_results (tenant_id, validation_result_id, processing_run_id,
               document_id, rule_key, result, severity, created_at_utc)
           VALUES (:t, gen_random_uuid(), :run, :doc, 'schema_v2.structured_shape', 'PASS', 'INFO', now())"""), p)
    await session.execute(text(
        """INSERT INTO docintel.human_verifications (tenant_id, verification_id, document_id,
               human_verification_status_at_time, machine_confidence_score, verified_by_actor_id,
               verified_at_utc, created_at_utc)
           VALUES (:t, :verification, :doc, 'MANDATORY', 50, 'test-uploader', now(), now())"""), p)
    await session.execute(text(
        """INSERT INTO docintel.document_field_values (tenant_id, document_field_value_id, document_id,
               canonical_field_id, value_source, accepted_by_actor_id, accepted_at_utc, version_no,
               created_at_utc, source_extracted_fact_id, source_verification_id)
           VALUES (:t, gen_random_uuid(), :doc, :cf, 'MACHINE', 'test-uploader', now(), 1, now(),
                   :fact, NULL)"""), {**p, "cf": canonical_field_id})
    await session.execute(text(
        """INSERT INTO docintel.document_field_values (tenant_id, document_field_value_id, document_id,
               canonical_field_id, value_source, accepted_by_actor_id, accepted_at_utc, version_no,
               created_at_utc, source_extracted_fact_id, source_verification_id, fact_role)
           VALUES (:t, gen_random_uuid(), :doc, :cf, 'HUMAN', 'test-uploader', now(), 2, now(),
                   NULL, :verification, 'CUSTOMER')"""), {**p, "cf": canonical_field_id})
    await session.execute(text(
        """INSERT INTO docintel.document_artifacts (tenant_id, artifact_id, document_id, storage_id,
               logical_object_key, artifact_type, created_at_utc, processing_run_id)
           VALUES (:t, :artifact, :doc, gen_random_uuid(), :key, 'OCR_RAW', now(), :run)"""),
        {**p, "key": f"graph/{ids['doc']}/ocr.txt"})
    await session.execute(text(
        """INSERT INTO docintel.document_quality_results (tenant_id, quality_result_id, document_id, rule_key,
               outcome, evaluated_at_utc) VALUES (:t, gen_random_uuid(), :doc, 'di.quality.file_not_empty', 'PASS', now())"""), p)
    await session.execute(text(
        """INSERT INTO docintel.document_search_index (tenant_id, document_id, indexed_fields, created_at_utc,
               updated_at_utc) VALUES (:t, :doc, '{}'::jsonb, now(), now())"""), p)
    await session.execute(text(
        """INSERT INTO docintel.entity_links (tenant_id, entity_link_id, document_id, source_system, entity_type,
               entity_id, link_status, link_method, linked_by_actor_id, linked_at_utc)
           VALUES (:t, :link, :doc, 'AUDIT', 'JOURNEY', 'j1', 'CONFIRMED', 'SYSTEM', 'test-uploader', now())"""), p)
    await session.execute(text(
        """INSERT INTO docintel.integration_intake_events (tenant_id, intake_event_id, correlation_id,
               source_channel, source_event_id, status, received_at_utc, document_id)
           VALUES (:t, :intake, 'c', 'WHATSAPP', :ev, 'DOCUMENT_CREATED', now(), :doc)"""),
        {**p, "ev": f"ev-{ids['doc']}"})
    await session.execute(text(
        """INSERT INTO docintel.backout_jobs (tenant_id, backout_job_id, document_id, processing_job_id,
               error_class, expires_at_utc, created_at_utc)
           VALUES (:t, gen_random_uuid(), :doc, :job, 'RETRYABLE', now() + interval '1 day', now())"""), p)
    await session.flush()
    return ids


_CHILD_TABLES = (
    "processing_jobs", "processing_runs", "document_classifications", "extracted_facts",
    "validation_results", "human_verifications", "document_field_values", "document_artifacts",
    "document_quality_results", "document_search_index", "entity_links", "backout_jobs",
)


async def _counts(session: AsyncSession, tenant_id: str, document_id: Any) -> dict[str, int]:
    counts = {"documents": await _scalar(
        session, "SELECT count(*) FROM docintel.documents WHERE tenant_id=:t AND document_id=:d",
        t=tenant_id, d=document_id)}
    for table in _CHILD_TABLES:
        counts[table] = await _scalar(
            session, f"SELECT count(*) FROM docintel.{table} WHERE tenant_id=:t AND document_id=:d",  # noqa: S608
            t=tenant_id, d=document_id)
    return counts


@pytest.mark.asyncio
async def test_a_classified_extracted_document_is_deleted_with_everything_that_points_at_it(
    db_session: AsyncSession,
) -> None:
    tenant_id, policy_id, subject_id = await _tenant(db_session)
    canonical_field_id, profile_field_id = await _catalog(db_session, tenant_id)
    gone = await _document_graph(db_session, tenant_id, policy_id, canonical_field_id, profile_field_id,
                                 subject_id=subject_id)
    kept = await _document_graph(db_session, tenant_id, policy_id, canonical_field_id, profile_field_id,
                                 subject_id=subject_id)
    kept_before = await _counts(db_session, tenant_id, kept["doc"])
    assert all(n >= 1 for n in kept_before.values()), kept_before

    storage = _Storage()
    await delete_document(db_session, tenant_id=tenant_id, document_id=gone["doc"],
                          subject_id=subject_id, storage=storage)  # type: ignore[arg-type]
    await db_session.flush()

    assert all(n == 0 for n in (await _counts(db_session, tenant_id, gone["doc"])).values())
    assert storage.deleted == [f"graph/{gone['doc']}/ocr.txt"]
    # the intake event is a record of what arrived: it stays, no longer pointing at the document
    assert await _scalar(
        db_session, "SELECT count(*) FROM docintel.integration_intake_events "
        "WHERE tenant_id=:t AND intake_event_id=:i AND document_id IS NULL", t=tenant_id, i=gone["intake"]) == 1
    # the other document of the same tenant is untouched, children included
    assert await _counts(db_session, tenant_id, kept["doc"]) == kept_before
    assert await _scalar(
        db_session, "SELECT count(*) FROM docintel.integration_intake_events "
        "WHERE tenant_id=:t AND intake_event_id=:i AND document_id=:d",
        t=tenant_id, i=kept["intake"], d=kept["doc"]) == 1


@pytest.mark.asyncio
async def test_a_document_other_documents_point_to_can_still_be_deleted(db_session: AsyncSession) -> None:
    tenant_id, policy_id, subject_id = await _tenant(db_session)
    canonical_field_id, profile_field_id = await _catalog(db_session, tenant_id)
    gone = await _document_graph(db_session, tenant_id, policy_id, canonical_field_id, profile_field_id,
                                 subject_id=subject_id)
    other = await _document_graph(db_session, tenant_id, policy_id, canonical_field_id, profile_field_id,
                                  subject_id=subject_id)
    await db_session.execute(text(
        """UPDATE docintel.documents SET duplicate_of_document_id=:g, replaces_document_id=:g,
               replaced_by_document_id=:g WHERE tenant_id=:t AND document_id=:o"""),
        {"t": tenant_id, "g": gone["doc"], "o": other["doc"]})
    await db_session.flush()

    await delete_document(db_session, tenant_id=tenant_id, document_id=gone["doc"],
                          subject_id=subject_id, storage=_Storage())  # type: ignore[arg-type]
    await db_session.flush()

    row = (await db_session.execute(text(
        "SELECT duplicate_of_document_id, replaces_document_id, replaced_by_document_id "
        "FROM docintel.documents WHERE tenant_id=:t AND document_id=:o"),
        {"t": tenant_id, "o": other["doc"]})).one()
    assert tuple(row) == (None, None, None)
    assert (await _counts(db_session, tenant_id, other["doc"]))["documents"] == 1


@pytest.mark.asyncio
async def test_another_tenants_document_with_the_same_id_is_not_touched(db_session: AsyncSession) -> None:
    tenant_a, policy_a, subject_a = await _tenant(db_session)
    canonical_a, profile_a = await _catalog(db_session, tenant_a)
    mine = await _document_graph(db_session, tenant_a, policy_a, canonical_a, profile_a, subject_id=subject_a)
    tenant_b, policy_b, subject_b = await _tenant(db_session)
    canonical_b, profile_b = await _catalog(db_session, tenant_b)
    theirs = await _document_graph(db_session, tenant_b, policy_b, canonical_b, profile_b, subject_id=subject_b)
    theirs_before = await _counts(db_session, tenant_b, theirs["doc"])

    await set_tenant_context(db_session, tenant_a)
    await delete_document(db_session, tenant_id=tenant_a, document_id=mine["doc"],
                          subject_id=subject_a, storage=_Storage())  # type: ignore[arg-type]
    await db_session.flush()

    assert await _counts(db_session, tenant_b, theirs["doc"]) == theirs_before


@pytest.mark.asyncio
async def test_every_table_that_references_a_document_or_its_runs_is_handled(db_session: AsyncSession) -> None:
    """A table added later that points at documents, processing runs or jobs would make the delete
    fail again (as document_classifications did). Add it to delete_document and to this list."""
    handled = {
        "backout_jobs", "document_artifacts", "document_capture_v2_classification_jobs",
        "document_capture_v2_uploads", "document_classifications", "document_field_values",
        "document_quality_results", "document_search_index", "documents", "entity_links",
        "extracted_facts", "human_verifications", "integration_intake_events", "processing_jobs",
        "processing_runs", "processor_invocations", "validation_results",
    }
    referencing = {
        r[0] for r in (await db_session.execute(text(
            """SELECT DISTINCT c.conrelid::regclass::text
               FROM pg_constraint c
               WHERE c.contype='f' AND c.confrelid IN (
                   'docintel.documents'::regclass, 'docintel.processing_runs'::regclass,
                   'docintel.processing_jobs'::regclass, 'docintel.processor_invocations'::regclass,
                   'docintel.extracted_facts'::regclass, 'docintel.human_verifications'::regclass)"""))).all()
    }
    unhandled = {name.split(".", 1)[1] for name in referencing} - handled
    assert not unhandled, f"delete_document does not handle: {sorted(unhandled)}"
