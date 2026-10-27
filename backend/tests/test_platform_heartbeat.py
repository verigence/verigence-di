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


# --- GET /v1/platform/health (DI's own tables, read by Audit Core) -----------

from datetime import UTC, datetime, timedelta  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from verigence.di.api.v1 import platform_health as ph  # noqa: E402
from verigence.di.auth.service_integration import ServiceIntegrationPrincipal  # noqa: E402
from verigence.di.settings import get_settings  # noqa: E402


def test_only_allowlisted_services_may_read_platform_health():
    assert ph.require_health_reader(ServiceIntegrationPrincipal(service_id="audit-core")).service_id == "audit-core"
    with pytest.raises(HTTPException) as refused:
        ph.require_health_reader(ServiceIntegrationPrincipal(service_id="security"))
    assert refused.value.status_code == 403


async def _engine_or_skip():
    engine = create_async_engine(get_settings().database_url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            ready = (await connection.execute(
                text("SELECT to_regclass('docintel.service_heartbeats') IS NOT NULL"))).scalar_one()
    except Exception:  # noqa: BLE001
        await engine.dispose()
        pytest.skip("no migrated DI database")
    if not ready:
        await engine.dispose()
        pytest.skip("DI migrations not applied")
    return engine


async def test_heartbeat_rows_come_back_through_platform_health(monkeypatch):
    engine = await _engine_or_skip()
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "di-health-test")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "dep-1")
    readings = iter([
        {"cpu_seconds": 10.0, "memory": 1 << 30, "memory_limit": 8 << 30, "cpu_limit": 8.0},
        {"cpu_seconds": 40.0, "memory": 2 << 30, "memory_limit": 8 << 30, "cpu_limit": 8.0},  # 6 cores
    ])
    monkeypatch.setattr(hb, "read_container_usage", lambda: next(readings))
    beat = hb.PlatformHeartbeat(engine, "di-api")
    try:
        # No boot row yet: the beat writes it (self-heal), then the minute.
        minute = (datetime.now(UTC) - timedelta(minutes=2)).timestamp() // 60 * 60
        beat.sample(minute)
        beat.sample(minute + 5)
        await beat.beat()
        async with AsyncSession(engine) as session:
            health = await ph.platform_health(session, 1)
        [boot] = [b for b in health["boots"] if b["bootId"] == beat.boot_id]
        assert (boot["service"], boot["deploymentId"], boot["stoppedAtUtc"]) == ("di-health-test", "dep-1", None)
        [usage] = [r for r in health["resources"] if r["service"] == "di-health-test"]
        assert (usage["cpuMax"], usage["cpuLimit"], usage["memoryMaxGb"], usage["cpuHotMinutes"]) == (6.0, 8.0, 2.0, 0)
        assert {"byStatus", "failures", "leaseReclaims"} <= set(health["queues"])
        assert health["database"]["maxConnections"] > 0
        await beat.stop()
        async with AsyncSession(engine) as session:
            [boot] = [b for b in await ph.boots(session, datetime.now(UTC) - timedelta(hours=1))
                      if b["bootId"] == beat.boot_id]
        assert boot["stoppedAtUtc"] is not None
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM docintel.service_resource_minutes WHERE boot_id = CAST(:b AS uuid)"),
                                     {"b": beat.boot_id})
            await connection.execute(text("DELETE FROM docintel.service_heartbeats WHERE boot_id = CAST(:b AS uuid)"),
                                     {"b": beat.boot_id})
        await engine.dispose()
