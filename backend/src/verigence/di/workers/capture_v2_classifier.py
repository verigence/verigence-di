"""Async classification worker for UC03 Document Capture V2.

This queue is deliberately separate from the legacy processing worker. Once a V2
upload is classified, the accepted type is written as the document hint and the
existing INITIAL processing job is created. The existing worker then performs the
already-deployed Schema V2 extraction/lineage pipeline unchanged.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from verigence.di.application.intake import _detect_mime
from verigence.di.document_ai.v2_classifier import classify_document_v2
from verigence.di.domain.enums import UploadStatus
from verigence.di.quality.validator import validate_upload
from verigence.di.repositories.database import tenant_session
from verigence.di.repositories.documents import update_document_upload_complete
from verigence.di.repositories.processing_jobs import create_initial_job
from verigence.di.settings import get_settings
from verigence.di.storage.adapter import get_storage_adapter

logger = structlog.get_logger(__name__)
_NOTIFY_CHANNEL = "di_capture_v2_jobs"


def _worker_id() -> str:
    try:
        host = socket.gethostname()
    except Exception:
        host = "unknown"
    return f"capture-v2.{host}.{os.getpid()}"


def _asyncpg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgresql://"
    )


class CaptureV2ClassificationWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._notify_conn: Any | None = None

    def start(self) -> None:
        self._stop.clear()
        self._wake.clear()
        self._task = asyncio.create_task(self._run(), name="capture-v2-classifier")
        logger.info("capture_v2_classifier_started")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=15)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        if self._notify_conn is not None:
            with contextlib.suppress(Exception):
                await self._notify_conn.close()
            self._notify_conn = None
        logger.info("capture_v2_classifier_stopped")

    async def _open_notify(self, database_url: str) -> bool:
        try:
            import asyncpg
            conn = await asyncpg.connect(_asyncpg_url(database_url))

            def _on_notify(connection: object, pid: int, channel: str, payload: str) -> None:
                del connection, pid, channel, payload
                self._wake.set()

            await conn.add_listener(_NOTIFY_CHANNEL, _on_notify)
            self._notify_conn = conn
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("capture_v2_notify_unavailable", error=str(exc))
            return False

    async def _run(self) -> None:
        settings = get_settings()
        database_url = str(settings.database_url)
        engine = create_async_engine(database_url, echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        notify_url = getattr(settings, "worker_notify_db_url", "") or database_url
        notify_active = await self._open_notify(str(notify_url))
        worker_id = _worker_id()
        try:
            while not self._stop.is_set():
                did_work = False
                try:
                    job = await self._claim(factory, worker_id)
                    if job is not None:
                        did_work = True
                        await self._process(job)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("capture_v2_worker_error", error=str(exc))
                if not did_work:
                    self._wake.clear()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            asyncio.shield(self._wake.wait()),
                            timeout=1.0 if notify_active else 0.25,
                        )
        finally:
            await engine.dispose()

    async def _claim(
        self,
        factory: async_sessionmaker[AsyncSession],
        worker_id: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        async with factory() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        """
                        SELECT tenant_id, classification_job_id, document_id, attempt_no
                        FROM docintel.document_capture_v2_classification_jobs
                        WHERE job_status='PENDING' AND due_at_utc <= :now
                        ORDER BY due_at_utc, created_at_utc
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {"now": now},
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            await session.execute(
                text(
                    """
                    UPDATE docintel.document_capture_v2_classification_jobs
                    SET job_status='RUNNING', locked_by=:worker_id,
                        locked_at_utc=:now, started_at_utc=:now, updated_at_utc=:now
                    WHERE tenant_id=:tenant_id AND classification_job_id=:job_id
                    """
                ),
                {
                    "worker_id": worker_id,
                    "now": now,
                    "tenant_id": row["tenant_id"],
                    "job_id": row["classification_job_id"],
                },
            )
            return dict(row)

    async def _process(self, job: dict[str, Any]) -> None:
        tenant_id = str(job["tenant_id"])
        document_id = uuid.UUID(str(job["document_id"]))
        job_id = uuid.UUID(str(job["classification_job_id"]))
        try:
            await self._classify(tenant_id, document_id, job_id)
        except Exception as exc:  # noqa: BLE001
            await self._fail_job(
                tenant_id=tenant_id,
                job_id=job_id,
                document_id=document_id,
                attempt_no=int(job["attempt_no"]),
                error=str(exc),
            )

    async def _classify(self, tenant_id: str, document_id: uuid.UUID, job_id: uuid.UUID) -> None:
        storage = get_storage_adapter()
        async with tenant_session(tenant_id) as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT u.logical_object_key, u.candidate_document_type_keys,
                               u.declared_mime_type, u.state,
                               d.original_filename, d.correlation_id
                        FROM docintel.document_capture_v2_uploads u
                        JOIN docintel.documents d
                          ON d.tenant_id=u.tenant_id AND d.document_id=u.document_id
                        WHERE u.tenant_id=:tenant_id AND u.document_id=:document_id
                        FOR UPDATE OF u, d
                        """
                    ),
                    {"tenant_id": tenant_id, "document_id": document_id},
                )
            ).mappings().one()
            await session.execute(
                text(
                    """
                    UPDATE docintel.document_capture_v2_uploads
                    SET state='CLASSIFYING', updated_at_utc=now()
                    WHERE tenant_id=:tenant_id AND document_id=:document_id
                    """
                ),
                {"tenant_id": tenant_id, "document_id": document_id},
            )
            await session.commit()

        stream = await storage.get_stream(str(row["logical_object_key"]))
        document_bytes = stream.read()
        detected_mime = _detect_mime(document_bytes, str(row["original_filename"] or ""))
        sha256_hex = hashlib.sha256(document_bytes).hexdigest()

        async with tenant_session(tenant_id) as session:
            validation = await validate_upload(
                session=session,
                tenant_id=tenant_id,
                document_id=document_id,
                data=document_bytes,
                declared_mime=row["declared_mime_type"],
                filename=row["original_filename"],
            )
            await update_document_upload_complete(
                session,
                tenant_id=tenant_id,
                document_id=document_id,
                file_size_bytes=len(document_bytes),
                content_hash_sha256=sha256_hex,
                detected_mime_type=validation.detected_mime or detected_mime,
                upload_status=validation.upload_status,
                upload_issue_code=validation.upload_issue_code,
                upload_issue_detail=validation.upload_issue_detail,
            )
            await session.execute(
                text(
                    """
                    UPDATE docintel.document_artifacts
                    SET mime_type=:mime_type, file_size_bytes=:size,
                        content_hash_sha256=:sha256
                    WHERE tenant_id=:tenant_id AND document_id=:document_id
                      AND artifact_type='ORIGINAL'
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "mime_type": validation.detected_mime or detected_mime,
                    "size": len(document_bytes),
                    "sha256": sha256_hex,
                },
            )
            if validation.upload_status != UploadStatus.FIT:
                await self._finish_failed(
                    session,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    document_id=document_id,
                    code=validation.upload_issue_code or "UPLOAD_NOT_FIT",
                    detail=validation.upload_issue_detail or "Uploaded document failed quality checks",
                )
                await session.commit()
                return

            candidate_keys = [str(value) for value in row["candidate_document_type_keys"]]
            candidates = (
                await session.execute(
                    text(
                        """
                        SELECT dt.document_type_key, dt.display_name
                        FROM docintel.document_types dt
                        JOIN docintel.tenant_document_types tdt
                          ON tdt.document_type_id=dt.document_type_id
                         AND tdt.tenant_id=:tenant_id
                         AND tdt.is_active=true
                        WHERE dt.document_type_key = ANY(:candidate_keys)
                          AND dt.status IN ('ACTIVE','DRAFT')
                        ORDER BY array_position(:candidate_keys, dt.document_type_key)
                        """
                    ),
                    {"tenant_id": tenant_id, "candidate_keys": candidate_keys},
                )
            ).mappings().all()
            threshold = (
                await session.execute(
                    text(
                        "SELECT classification_acceptance_score "
                        "FROM docintel.tenant_settings WHERE tenant_id=:tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
            ).scalar_one()
            await session.commit()

        result = await classify_document_v2(
            document_bytes=document_bytes,
            mime_type=validation.detected_mime or detected_mime,
            candidates=[(r["document_type_key"], r["display_name"]) for r in candidates],
        )
        accepted = (
            result.document_type_key
            if result.document_type_key is not None
            and result.confidence >= Decimal(str(threshold))
            else None
        )

        async with tenant_session(tenant_id) as session:
            now = datetime.now(UTC)
            if accepted is None:
                await session.execute(
                    text(
                        """
                        UPDATE docintel.document_capture_v2_uploads
                        SET state='UNKNOWN', classification_confidence=:confidence,
                            classified_document_type_key=NULL, classified_at_utc=:now,
                            updated_at_utc=:now
                        WHERE tenant_id=:tenant_id AND document_id=:document_id
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "document_id": document_id,
                        "confidence": result.confidence,
                        "now": now,
                    },
                )
                await self._complete_job(session, tenant_id, job_id, now)
                await session.commit()
                return

            type_row = (
                await session.execute(
                    text(
                        """
                        SELECT dt.document_type_id, tdt.physical_form_type,
                               tdt.requires_processing,
                               EXISTS (
                                   SELECT 1 FROM docintel.extraction_profiles ep
                                   WHERE ep.document_type_id=dt.document_type_id
                                     AND ep.status='PUBLISHED'
                                     AND (ep.scope_tenant_id IS NULL OR ep.scope_tenant_id=:tenant_id)
                               ) AS has_published_profile
                        FROM docintel.document_types dt
                        JOIN docintel.tenant_document_types tdt
                          ON tdt.document_type_id=dt.document_type_id
                         AND tdt.tenant_id=:tenant_id
                        WHERE dt.document_type_key=:document_type_key
                          AND tdt.is_active=true
                        LIMIT 1
                        """
                    ),
                    {"tenant_id": tenant_id, "document_type_key": accepted},
                )
            ).mappings().one()

            await session.execute(
                text(
                    """
                    UPDATE docintel.documents
                    SET document_type_id=:document_type_id,
                        document_type_hint_key=:document_type_key,
                        physical_form_type=:physical_form_type,
                        requires_processing=:requires_processing,
                        updated_at_utc=:now
                    WHERE tenant_id=:tenant_id AND document_id=:document_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "document_type_id": type_row["document_type_id"],
                    "document_type_key": accepted,
                    "physical_form_type": type_row["physical_form_type"],
                    "requires_processing": type_row["requires_processing"],
                    "now": now,
                },
            )
            await session.execute(
                text(
                    """
                    UPDATE docintel.document_capture_v2_uploads
                    SET state='CLASSIFIED', classified_document_type_key=:document_type_key,
                        classification_confidence=:confidence, classified_at_utc=:now,
                        updated_at_utc=:now, failure_code=NULL, failure_detail=NULL
                    WHERE tenant_id=:tenant_id AND document_id=:document_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "document_type_key": accepted,
                    "confidence": result.confidence,
                    "now": now,
                },
            )

            if type_row["requires_processing"] and type_row["has_published_profile"]:
                processing_job_id = await create_initial_job(
                    session,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    correlation_id=str(row["correlation_id"]),
                )
                await session.execute(
                    text("SELECT pg_notify('di_processing_jobs', :payload)"),
                    {"payload": str(processing_job_id)},
                )

            await self._complete_job(session, tenant_id, job_id, now)
            await session.commit()

    async def _complete_job(
        self,
        session: AsyncSession,
        tenant_id: str,
        job_id: uuid.UUID,
        now: datetime,
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE docintel.document_capture_v2_classification_jobs
                SET job_status='COMPLETED', completed_at_utc=:now, updated_at_utc=:now
                WHERE tenant_id=:tenant_id AND classification_job_id=:job_id
                """
            ),
            {"tenant_id": tenant_id, "job_id": job_id, "now": now},
        )

    async def _finish_failed(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        job_id: uuid.UUID,
        document_id: uuid.UUID,
        code: str,
        detail: str,
    ) -> None:
        now = datetime.now(UTC)
        await session.execute(
            text(
                """
                UPDATE docintel.document_capture_v2_uploads
                SET state='FAILED', failure_code=:code, failure_detail=:detail,
                    updated_at_utc=:now
                WHERE tenant_id=:tenant_id AND document_id=:document_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "document_id": document_id,
                "code": code[:120],
                "detail": detail[:2000],
                "now": now,
            },
        )
        await session.execute(
            text(
                """
                UPDATE docintel.document_capture_v2_classification_jobs
                SET job_status='FAILED', completed_at_utc=:now,
                    error_code=:code, error_detail=:detail, updated_at_utc=:now
                WHERE tenant_id=:tenant_id AND classification_job_id=:job_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "job_id": job_id,
                "code": code[:120],
                "detail": detail[:2000],
                "now": now,
            },
        )

    async def _fail_job(
        self,
        *,
        tenant_id: str,
        job_id: uuid.UUID,
        document_id: uuid.UUID,
        attempt_no: int,
        error: str,
    ) -> None:
        async with tenant_session(tenant_id) as session:
            now = datetime.now(UTC)
            if attempt_no < 2:
                await session.execute(
                    text(
                        """
                        UPDATE docintel.document_capture_v2_classification_jobs
                        SET job_status='PENDING', attempt_no=attempt_no+1,
                            due_at_utc=:due, locked_by=NULL, locked_at_utc=NULL,
                            error_code='CLASSIFICATION_RETRY', error_detail=:detail,
                            updated_at_utc=:now
                        WHERE tenant_id=:tenant_id AND classification_job_id=:job_id
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "job_id": job_id,
                        "due": now + timedelta(seconds=1),
                        "detail": error[:2000],
                        "now": now,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE docintel.document_capture_v2_uploads
                        SET state='STORED', updated_at_utc=:now
                        WHERE tenant_id=:tenant_id AND document_id=:document_id
                        """
                    ),
                    {"tenant_id": tenant_id, "document_id": document_id, "now": now},
                )
            else:
                await self._finish_failed(
                    session,
                    tenant_id=tenant_id,
                    job_id=job_id,
                    document_id=document_id,
                    code="CLASSIFICATION_FAILED",
                    detail=error,
                )
            await session.commit()


_worker = CaptureV2ClassificationWorker()


def get_capture_v2_classifier_worker() -> CaptureV2ClassificationWorker:
    return _worker
