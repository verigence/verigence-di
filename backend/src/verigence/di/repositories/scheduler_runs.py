"""repositories/scheduler_runs.py — once-per-day markers for scheduled runs.

The scheduler ticks every 60 seconds on every API/worker replica, and a daily
trigger window spans several ticks. Claiming ``(run_name, run_date)`` with an
INSERT ... ON CONFLICT DO NOTHING lets exactly one tick on one replica perform
(and report) a daily run; every other tick sees the marker and does nothing.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def claim_scheduler_run(
    session: AsyncSession,
    *,
    run_name: str,
    run_date: date,
    claimed_by: str,
    now: datetime,
    error_code: str | None = None,
) -> bool:
    """True when this caller is the first to claim ``run_name`` for ``run_date``.

    The claim belongs to the caller's transaction: if that transaction rolls
    back, the run is unclaimed again and a later tick may retry it.
    """
    claimed = (
        await session.execute(
            text("""
                INSERT INTO docintel.scheduler_runs
                    (run_name, run_date, claimed_by, started_at_utc, error_code)
                VALUES (:run_name, :run_date, :claimed_by, :now, :error_code)
                ON CONFLICT (run_name, run_date) DO NOTHING
                RETURNING run_name
            """),
            {
                "run_name": run_name,
                "run_date": run_date,
                "claimed_by": claimed_by[:160],
                "now": now,
                "error_code": error_code,
            },
        )
    ).scalar_one_or_none()
    return claimed is not None


async def complete_scheduler_run(
    session: AsyncSession,
    *,
    run_name: str,
    run_date: date,
    items_queued: int,
    now: datetime,
) -> None:
    await session.execute(
        text("""
            UPDATE docintel.scheduler_runs
            SET completed_at_utc = :now, items_queued = :items_queued
            WHERE run_name = :run_name AND run_date = :run_date
        """),
        {"run_name": run_name, "run_date": run_date, "items_queued": items_queued, "now": now},
    )
