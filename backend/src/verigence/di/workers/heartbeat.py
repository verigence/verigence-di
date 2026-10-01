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
# Work is due and nothing has been processed for this many heartbeats in a
# row (30 minutes at the default interval): the worker is alive but stalled.
# Logged at ERROR so the log alert fires (decision 2026-10-01).
STALL_HEARTBEATS = 6


def stall_detected(
    *, pending: int, processed_before: int, processed_now: int, idle_beats: int
) -> tuple[bool, int]:
    """Returns (stalled, idle_beats after this beat). Idle beats count only
    while work is due and the processed counter has not moved."""
    if pending <= 0 or processed_now != processed_before:
        return False, 0
    idle_beats += 1
    return idle_beats >= STALL_HEARTBEATS, idle_beats


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
) -> tuple[int, int]:
    """Logs the heartbeat; returns (pending work, processed so far)."""
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
    totals = aggregate_stats(stats())
    logger.info("di_worker_heartbeat", **fields, **totals, **depth)
    pending = int(depth.get("processing_pending", 0)) + int(depth.get("classification_pending", 0))
    return pending, int(totals["processed"])


async def run_heartbeat(
    *,
    stop_event: asyncio.Event,
    session_factory: async_sessionmaker[AsyncSession] | None,
    stats: Callable[[], Iterable[WorkerStats]],
    fields: dict[str, Any],
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    processed_before = 0
    idle_beats = 0
    while not stop_event.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        if stop_event.is_set():
            return
        try:
            pending, processed_now = await emit_heartbeat(
                session_factory=session_factory, stats=stats, fields=fields,
            )
            stalled, idle_beats = stall_detected(
                pending=pending, processed_before=processed_before,
                processed_now=processed_now, idle_beats=idle_beats,
            )
            processed_before = processed_now
            if stalled:
                logger.error(
                    "di_worker_stalled",
                    error_code="WORKER_STALLED",
                    error_category="TECHNICAL",
                    pending_jobs=pending,
                    idle_heartbeats=idle_beats,
                    **fields,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("di_worker_heartbeat_failed", **safe_exception_context(exc))
