"""Platform heartbeat for the SuperAdmin System Health page (2026-10-27): CPU is
kept as the per-minute peak and average, and the heartbeat never stops DI, even
when the database or its tables are not there."""
from __future__ import annotations

import asyncio

import pytest

from verigence.di import platform_heartbeat as hb


def test_peak_and_average_cores_per_minute(monkeypatch):
    readings = iter([
        {"cpu_seconds": 50.0, "memory": 100, "memory_limit": 800, "cpu_limit": 12.0},
        {"cpu_seconds": 60.0, "memory": 300, "memory_limit": 800, "cpu_limit": 12.0},  # 2 cores over 5 s
        {"cpu_seconds": 61.0, "memory": 200, "memory_limit": 800, "cpu_limit": 12.0},  # 0.2 cores
    ])
    monkeypatch.setattr(hb, "read_container_usage", lambda: next(readings))
    beat = hb.PlatformHeartbeat(engine=None, default_service="di-worker-v2")  # type: ignore[arg-type]
    base = 1_800_000_000.0 - (1_800_000_000.0 % 60)
    for offset in (0, 5, 10):
        beat.sample(base + offset)
    [bucket] = beat._minutes.values()
    assert bucket["max"] == pytest.approx(2.0)
    assert bucket["sum"] / bucket["n"] == pytest.approx(1.1)
    assert (bucket["mem"], bucket["mem_limit"], bucket["cpu_limit"]) == (300, 800, 12.0)


def test_usage_is_readable_in_any_container():
    assert hb.read_container_usage()["cpu_seconds"] is not None


async def test_an_unreachable_database_never_stops_the_service():
    stop = asyncio.Event()
    task = asyncio.create_task(hb.run_platform_heartbeat(
        "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none", "di-api", stop, sample_seconds=0.01))
    await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(task, timeout=10)  # finished cleanly, no exception


async def test_a_missing_boot_row_is_written_by_the_next_beat() -> None:
    """The process may start before the tables exist; its first beat after they appear
    writes the boot row, so the page sees it without a restart."""
    executed: list[str] = []

    class _Result:
        def __init__(self, rowcount: int) -> None:
            self.rowcount = rowcount

    class _Conn:
        async def execute(self, statement, params=None):  # type: ignore[no-untyped-def]
            sql = str(statement)
            executed.append(sql.split()[0])
            return _Result(0 if sql.startswith("UPDATE") else 1)

    class _Begin:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return _Conn()

        async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
            return False

    class _Engine:
        def begin(self) -> _Begin:
            return _Begin()

    beat = hb.PlatformHeartbeat(_Engine(), "di-api")  # type: ignore[arg-type]
    await beat.beat()
    assert executed == ["UPDATE", "INSERT"]
