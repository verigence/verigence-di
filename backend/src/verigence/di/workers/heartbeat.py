"""workers/heartbeat.py — periodic liveness event for the standalone worker.

A silent worker is otherwise indistinguishable from a dead one: an idle queue
logs nothing. Every interval the worker process emits ``di_worker_heartbeat``
with its loop/job counters and the current queue depth. A failing depth query
is logged and skipped; it never stops the heartbeat or the workers.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from verigence.di.runtime_errors import safe_exception_context

logger = structlog.get_logger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 300.0


@dataclass
class WorkerStats:
    """Monotonic counters one worker loop updates; read by the heartbeat."""

    cycles: int = 0
    processed: int = 0
    failed: int = 0

    def record(self, outcome: str) -> None:
        self.processed += 1
        if outcome == "failed":
            self.failed += 1


def aggregate_stats(stats: Iterable[WorkerStats]) -> dict[str, int]:
    totals = {"cycles": 0, "processed": 0, "failed": 0}
    for item in stats:
        totals["cycles"] += item.cycles
        totals["processed"] += item.processed
        totals["failed"] += item.failed
    return totals


async def queue_depth(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            text(
                """
                SELECT 'processing' AS queue, job_status, COUNT(*) AS n
                FROM docintel.processing_jobs
                WHERE job_status IN ('PENDING', 'RUNNING')
                GROUP BY job_status
                UNION ALL
                SELECT 'classification' AS queue, job_status, COUNT(*) AS n
                FROM docintel.document_capture_v2_classification_jobs
                WHERE job_status IN ('PENDING', 'RUNNING')
                GROUP BY job_status
                """
            )
        )
    ).all()
    depth = {
        "processing_pending": 0,
        "processing_running": 0,
        "classification_pending": 0,
        "classification_running": 0,
    }
    for queue, status, count in rows:
        depth[f"{queue}_{str(status).lower()}"] = int(count)
    return depth


async def emit_heartbeat(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None,
    stats: Callable[[], Iterable[WorkerStats]],
    fields: dict[str, Any],
) -> None:
    depth: dict[str, int] = {}
    if session_factory is not None:
        try:
            async with session_factory() as session:
                depth = await queue_depth(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "di_worker_heartbeat_queue_depth_failed",
                error_code="DATABASE_UNAVAILABLE",
                **safe_exception_context(exc),
            )
    logger.info("di_worker_heartbeat", **fields, **aggregate_stats(stats()), **depth)


async def run_heartbeat(
    *,
    stop_event: asyncio.Event,
    session_factory: async_sessionmaker[AsyncSession] | None,
    stats: Callable[[], Iterable[WorkerStats]],
    fields: dict[str, Any],
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    while not stop_event.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        if stop_event.is_set():
            return
        try:
            await emit_heartbeat(session_factory=session_factory, stats=stats, fields=fields)
        except Exception as exc:  # noqa: BLE001
            logger.warning("di_worker_heartbeat_failed", **safe_exception_context(exc))
