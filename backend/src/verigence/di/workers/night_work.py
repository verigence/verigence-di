"""workers/night_work.py -- what a worker has in hand, read before it rests at night.

One read of the queues (``verigence.di.night_rest``): 0 when work is waiting or
running, the seconds until the earliest retry otherwise, None when there is
nothing at all. The worker rests only on the last two.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_QUEUES_SQL = """
    SELECT
      (EXISTS (SELECT 1 FROM docintel.processing_jobs WHERE job_status = 'RUNNING')
       OR EXISTS (SELECT 1 FROM docintel.document_capture_v2_classification_jobs
                  WHERE job_status = 'RUNNING')) AS running,
      -- a page's link to Audit Core still to be delivered (the legacy lane)
      EXISTS (SELECT 1 FROM docintel.documents
              WHERE upload_status = 'FIT' AND audit_link_status = 'PENDING'
                AND audit_requirement_ref IS NOT NULL) AS link_pending,
      LEAST(
        (SELECT min(due_at_utc) FROM docintel.processing_jobs WHERE job_status = 'PENDING'),
        (SELECT min(due_at_utc) FROM docintel.document_capture_v2_classification_jobs
         WHERE job_status = 'PENDING')
      ) AS next_due_at_utc
"""


def due_in(
    *,
    running: bool,
    link_pending: bool,
    next_due_at_utc: datetime | None,
    eod_retry_in: float | None,
    include_legacy: bool,
    now: datetime,
) -> float | None:
    """What one read of the queues means for a worker about to rest."""
    if running or (include_legacy and link_pending):
        return 0.0
    waits: list[float] = []
    if next_due_at_utc is not None:
        waits.append(max(0.0, (next_due_at_utc - now).total_seconds()))
    if include_legacy and eod_retry_in is not None:
        waits.append(max(0.0, eod_retry_in))
    return min(waits) if waits else None


async def work_due_in(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    include_legacy: bool,
    now: datetime | None = None,
) -> float | None:
    now = now or datetime.now(UTC)
    async with session_factory() as session:
        row = (await session.execute(text(_QUEUES_SQL))).mappings().one()
        eod_retry_in: float | None = None
        if include_legacy:
            # The legacy lane's once-daily retry (scheduler/beat.py) is due by the
            # clock; a worker with such a document waiting is up for it.
            from verigence.di.scheduler.beat import seconds_until_eod_retry  # noqa: PLC0415

            eod_retry_in = await seconds_until_eod_retry(session, now)
    return due_in(
        running=bool(row["running"]),
        link_pending=bool(row["link_pending"]),
        next_due_at_utc=row["next_due_at_utc"],
        eod_retry_in=eod_retry_in,
        include_legacy=include_legacy,
        now=now,
    )
