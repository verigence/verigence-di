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
    include_legacy: bool,
    now: datetime,
) -> float | None:
    """What one read of the queues means for a worker about to rest."""
    if running or (include_legacy and link_pending):
        return 0.0
    if next_due_at_utc is None:
        return None
    return max(0.0, (next_due_at_utc - now).total_seconds())


async def work_due_in(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    include_legacy: bool,
    now: datetime | None = None,
) -> float | None:
    now = now or datetime.now(UTC)
    async with session_factory() as session:
        row = (await session.execute(text(_QUEUES_SQL))).mappings().one()
    return due_in(
        running=bool(row["running"]),
        link_pending=bool(row["link_pending"]),
        next_due_at_utc=row["next_due_at_utc"],
        include_legacy=include_legacy,
        now=now,
    )
