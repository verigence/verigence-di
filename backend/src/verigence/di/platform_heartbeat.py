"""Platform heartbeat for the SuperAdmin System Health page (product owner 2026-10-27).

Writes to the shared platform_ops tables that Audit Core's migration 0170 creates:

- one row in platform_ops.service_heartbeats per process start (a "boot"),
  last_seen refreshed every minute, stopped_at stamped on a clean shutdown.
  A new boot in the same Railway deployment is a restart; a boot that went
  quiet without a stop stamp ended unclean (crash, kill);
- container CPU and memory read from the cgroup every 5 seconds, kept as the
  per-minute average and peak against the container's limits, in
  platform_ops.service_resource_minutes.

Best effort throughout: a failed write is logged and dropped. If the tables do
not exist yet it keeps trying quietly; it never stops or slows DI.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = structlog.get_logger(__name__)

SAMPLE_SECONDS = 5.0
BEAT_EVERY_SAMPLES = 12
_CGROUP = Path("/sys/fs/cgroup")


def _minute(now: float) -> datetime:
    return datetime.fromtimestamp(int(now // 60 * 60), UTC)


def _read_int(path: Path) -> int | None:
    try:
        raw = path.read_text().strip()
    except OSError:
        return None
    return None if raw in ("", "max") else int(raw)


def read_container_usage() -> dict[str, float | int | None]:
    """CPU seconds used so far, memory in use and the limits: cgroup v2, then v1, then the process."""
    cpu_seconds: float | None = None
    memory = memory_limit = None
    cpu_limit: float | None = None
    try:
        for line in (_CGROUP / "cpu.stat").read_text().splitlines():
            if line.startswith("usage_usec "):
                cpu_seconds = int(line.split()[1]) / 1_000_000
        memory = _read_int(_CGROUP / "memory.current")
        memory_limit = _read_int(_CGROUP / "memory.max")
        quota, _, period = (_CGROUP / "cpu.max").read_text().strip().partition(" ")
        if quota != "max" and period:
            cpu_limit = int(quota) / int(period)
    except (OSError, ValueError):
        pass
    if cpu_seconds is None:
        usage = _read_int(_CGROUP / "cpuacct" / "cpuacct.usage")
        if usage is not None:
            cpu_seconds = usage / 1_000_000_000
            memory = _read_int(_CGROUP / "memory" / "memory.usage_in_bytes")
            memory_limit = _read_int(_CGROUP / "memory" / "memory.limit_in_bytes")
            quota_us = _read_int(_CGROUP / "cpu" / "cpu.cfs_quota_us")
            period_us = _read_int(_CGROUP / "cpu" / "cpu.cfs_period_us")
            if quota_us and quota_us > 0 and period_us:
                cpu_limit = quota_us / period_us
    if cpu_seconds is None:
        times = os.times()
        cpu_seconds = times.user + times.system
        with suppress(OSError, ValueError, IndexError):
            memory = int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    if memory_limit is not None and memory_limit >= 1 << 60:
        memory_limit = None
    if cpu_limit is None:
        cpu_limit = float(os.cpu_count() or 0) or None
    return {"cpu_seconds": cpu_seconds, "memory": memory, "memory_limit": memory_limit, "cpu_limit": cpu_limit}


class PlatformHeartbeat:
    def __init__(self, engine: AsyncEngine, default_service: str) -> None:
        self.engine = engine
        self.boot_id = str(uuid4())
        self.service = (os.environ.get("RAILWAY_SERVICE_NAME") or default_service)[:80]
        self.replica = os.environ.get("RAILWAY_REPLICA_ID") or None
        self.deployment = os.environ.get("RAILWAY_DEPLOYMENT_ID") or None
        self.version = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:12] or None
        self._last_cpu: tuple[float, float] | None = None
        self._minutes: dict[datetime, dict[str, Any]] = {}

    def sample(self, now: float | None = None) -> None:
        wall = now if now is not None else time.time()
        usage = read_container_usage()
        cores = None
        if self._last_cpu is not None and usage["cpu_seconds"] is not None and wall > self._last_cpu[1]:
            cores = max(float(usage["cpu_seconds"]) - self._last_cpu[0], 0.0) / (wall - self._last_cpu[1])
        if usage["cpu_seconds"] is not None:
            self._last_cpu = (float(usage["cpu_seconds"]), wall)
        bucket = self._minutes.setdefault(_minute(wall), {"sum": 0.0, "n": 0, "max": None, "mem": None,
                                                          "mem_limit": None, "cpu_limit": None})
        if cores is not None:
            bucket["sum"] += cores
            bucket["n"] += 1
            bucket["max"] = max(cores, bucket["max"] or 0.0)
        if usage["memory"] is not None:
            bucket["mem"] = max(int(usage["memory"]), bucket["mem"] or 0)
        bucket["mem_limit"] = usage["memory_limit"]
        bucket["cpu_limit"] = usage["cpu_limit"]

    async def boot(self) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO platform_ops.service_heartbeats (boot_id, service_name, replica_id, deployment_id, "
                    "version) VALUES (CAST(:b AS uuid), :s, :r, :d, :v) "
                    "ON CONFLICT (boot_id) DO UPDATE SET last_seen_at_utc = now()"
                ),
                {"b": self.boot_id, "s": self.service, "r": self.replica, "d": self.deployment, "v": self.version},
            )

    async def beat(self, *, include_current: bool = False) -> None:
        current = _minute(time.time())
        done = {m: self._minutes.pop(m) for m in list(self._minutes) if include_current or m < current}
        async with self.engine.begin() as connection:
            await connection.execute(
                text("UPDATE platform_ops.service_heartbeats SET last_seen_at_utc = now() "
                     "WHERE boot_id = CAST(:b AS uuid)"),
                {"b": self.boot_id},
            )
            for minute, r in done.items():
                await connection.execute(
                    text(
                        """
                        INSERT INTO platform_ops.service_resource_minutes
                          (boot_id, service_name, minute_utc, cpu_cores_avg, cpu_cores_max, cpu_limit_cores,
                           memory_bytes_max, memory_limit_bytes)
                        VALUES (CAST(:b AS uuid), :s, :m, :avg, :max, :cl, :mm, :ml)
                        ON CONFLICT (boot_id, minute_utc) DO UPDATE SET
                          cpu_cores_max = GREATEST(platform_ops.service_resource_minutes.cpu_cores_max,
                                                   EXCLUDED.cpu_cores_max),
                          memory_bytes_max = GREATEST(platform_ops.service_resource_minutes.memory_bytes_max,
                                                      EXCLUDED.memory_bytes_max)
                        """
                    ),
                    {"b": self.boot_id, "s": self.service, "m": minute,
                     "avg": round(r["sum"] / r["n"], 3) if r["n"] else None,
                     "max": round(r["max"], 3) if r["max"] is not None else None,
                     "cl": round(r["cpu_limit"], 3) if r["cpu_limit"] else None,
                     "mm": r["mem"], "ml": r["mem_limit"]},
                )

    async def stop(self, reason: str = "shutdown") -> None:
        with suppress(Exception):
            await self.beat(include_current=True)
        async with self.engine.begin() as connection:
            await connection.execute(
                text("UPDATE platform_ops.service_heartbeats SET stopped_at_utc = now(), last_seen_at_utc = now(), "
                     "stop_reason = :r WHERE boot_id = CAST(:b AS uuid)"),
                {"b": self.boot_id, "r": reason[:80]},
            )


async def _safe(action: str, coro: Any) -> None:
    try:
        await coro
    except Exception as exc:  # noqa: BLE001 - health reporting must never take DI down
        logger.warning("platform_heartbeat_failed", action=action, error=type(exc).__name__, detail=str(exc)[:200])


async def run_platform_heartbeat(
    database_url: str, default_service: str, stop_event: asyncio.Event, *, sample_seconds: float = SAMPLE_SECONDS,
) -> None:
    """Run until ``stop_event`` is set, then stamp a clean stop. Owns a one-connection engine."""
    engine = create_async_engine(database_url, echo=False, pool_size=1, max_overflow=0, pool_pre_ping=True)
    heartbeat = PlatformHeartbeat(engine, default_service)
    try:
        await _safe("boot", heartbeat.boot())
        heartbeat.sample()
        n = 0
        while True:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=sample_seconds)
                break
            except TimeoutError:
                pass
            n += 1
            try:
                heartbeat.sample()
            except Exception as exc:  # noqa: BLE001
                logger.warning("platform_heartbeat_failed", action="sample", error=type(exc).__name__)
            if n % BEAT_EVERY_SAMPLES == 0:
                await _safe("beat", heartbeat.beat())
        await _safe("stop", heartbeat.stop())
    finally:
        with suppress(Exception):
            await engine.dispose()
