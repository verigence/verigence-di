"""GET /v1/platform/health -- DI's health for Audit Core's SuperAdmin System Health
page (product owner 2026-10-27).

DI runs on its own database, so Audit Core asks DI rather than reading it. A
ServiceIntegration token is required and only the services named in
DI_PLATFORM_HEALTH_SERVICE_IDS (default "audit-core") may call. The answer is
counts, codes and timings only -- never document, field or customer data:

- boots: DI processes' starts in the window (and any still running), from
  docintel.service_heartbeats, for Audit Core to tell restarts from deploys;
- resources: CPU and memory peaks and averages per service against limits;
- queues: classification and extraction jobs per Project and status, those in
  flight past 30 minutes, and failures by error code; lease reclaims (a worker
  died holding a job);
- schedulerProblems: end-of-day runs that errored or never finished;
- database: DI's own database -- connections, held-open transactions, deadlocks,
  rollbacks, the slowest queries when pg_stat_statements is loaded.

GET /v1/platform/ai-usage (product owner 2026-11-16: "capture the cost") answers what
the AI provider calls cost, per day, Project, kind of call, document type, model and
service tier: calls, tokens and US$ at list price. Same callers, same rule: counts and
amounts only.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.auth.service_integration import (
    ServiceIntegrationPrincipal,
    require_service_integration,
)
from verigence.di.document_ai.gemini_cost import PRICES_USD_PER_MTOK, cost_usd
from verigence.di.errors import ErrorCode, http_exception
from verigence.di.repositories.database import AsyncSessionFactory
from verigence.di.settings import get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Platform health"])

_QUEUES = {
    "classification": "docintel.document_capture_v2_classification_jobs",
    "extraction": "docintel.processing_jobs",
}
_IN_FLIGHT = ("PENDING", "RUNNING")


def allowed_services() -> set[str]:
    return {s.strip() for s in get_settings().platform_health_service_ids.split(",") if s.strip()}


def require_health_reader(
    service: Annotated[ServiceIntegrationPrincipal, Depends(require_service_integration)],
) -> ServiceIntegrationPrincipal:
    if service.service_id not in allowed_services():
        logger.warning("platform_health_refused", service_id=service.service_id)
        raise http_exception(ErrorCode.FORBIDDEN, detail="This service may not read DI's platform health.")
    return service


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def _num(value: Any) -> float | None:
    return None if value is None else round(float(value), 3)


def _gb(value: Any) -> float | None:
    return None if value is None else round(float(value) / (1024 ** 3), 3)


async def _rows(session: AsyncSession, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(r) for r in (await session.execute(text(sql), params or {})).mappings().all()]


async def boots(session: AsyncSession, since: datetime) -> list[dict[str, Any]]:
    return [{
        "bootId": str(r["boot_id"]), "service": r["service_name"], "replicaId": r["replica_id"],
        "deploymentId": r["deployment_id"], "version": r["version"], "startedAtUtc": _iso(r["started_at_utc"]),
        "lastSeenAtUtc": _iso(r["last_seen_at_utc"]), "stoppedAtUtc": _iso(r["stopped_at_utc"]),
    } for r in await _rows(session, """
        SELECT boot_id, service_name, replica_id, deployment_id, version, started_at_utc, last_seen_at_utc,
               stopped_at_utc
        FROM docintel.service_heartbeats
        WHERE last_seen_at_utc >= :since OR stopped_at_utc IS NULL
        ORDER BY service_name, started_at_utc
    """, {"since": since})]


async def resources(session: AsyncSession, since: datetime) -> list[dict[str, Any]]:
    peaks = {r["service_name"]: r for r in await _rows(session, """
        SELECT service_name, max(cpu_cores_max) AS cpu_max, avg(cpu_cores_avg) AS cpu_avg,
               max(cpu_limit_cores) AS cpu_limit, max(memory_bytes_max) AS mem_max,
               avg(memory_bytes_max) AS mem_avg, max(memory_limit_bytes) AS mem_limit,
               (array_agg(minute_utc ORDER BY cpu_cores_max DESC NULLS LAST))[1] AS cpu_peak_at,
               (array_agg(minute_utc ORDER BY memory_bytes_max DESC NULLS LAST))[1] AS mem_peak_at,
               count(*) FILTER (WHERE cpu_limit_cores > 0 AND cpu_cores_max >= 0.8 * cpu_limit_cores) AS hot
        FROM docintel.service_resource_minutes
        WHERE minute_utc >= :since
        GROUP BY 1
    """, {"since": since})}
    hourly: dict[str, list[dict[str, Any]]] = {}
    for r in await _rows(session, """
        SELECT service_name, date_trunc('hour', minute_utc) AS hour, max(cpu_cores_max) AS cpu_max,
               avg(cpu_cores_avg) AS cpu_avg, max(memory_bytes_max) AS mem_max
        FROM docintel.service_resource_minutes
        WHERE minute_utc >= :since
        GROUP BY 1, 2 ORDER BY 2
    """, {"since": since}):
        hourly.setdefault(r["service_name"], []).append({
            "hour": _iso(r["hour"]), "cpuMax": _num(r["cpu_max"]), "cpuAvg": _num(r["cpu_avg"]),
            "memoryMaxGb": _gb(r["mem_max"])})
    return [{
        "service": name, "cpuMax": _num(p["cpu_max"]), "cpuAvg": _num(p["cpu_avg"]), "cpuLimit": _num(p["cpu_limit"]),
        "cpuPeakAtUtc": _iso(p["cpu_peak_at"]), "cpuHotMinutes": int(p["hot"] or 0),
        "memoryMaxGb": _gb(p["mem_max"]), "memoryAvgGb": _gb(p["mem_avg"]), "memoryLimitGb": _gb(p["mem_limit"]),
        "memoryPeakAtUtc": _iso(p["mem_peak_at"]), "hourly": hourly.get(name, []),
    } for name, p in sorted(peaks.items())]


async def queues(session: AsyncSession, since: datetime) -> dict[str, Any]:
    by_status: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for queue, table in _QUEUES.items():
        for r in await _rows(session, f"""
            SELECT tenant_id, job_status, count(*) AS n,
                   count(*) FILTER (WHERE job_status IN ('PENDING','RUNNING')
                                    AND created_at_utc < now() - interval '30 minutes') AS over_30m,
                   min(created_at_utc) FILTER (WHERE job_status IN ('PENDING','RUNNING')) AS oldest
            FROM {table}
            WHERE created_at_utc >= :since OR job_status IN ('PENDING','RUNNING')
            GROUP BY 1, 2
        """, {"since": since}):
            by_status.append({"queue": queue, "tenantId": r["tenant_id"], "status": r["job_status"],
                              "count": int(r["n"]), "over30m": int(r["over_30m"]), "oldestInFlightAtUtc": _iso(r["oldest"])})
        for r in await _rows(session, f"""
            SELECT tenant_id, COALESCE(error_code, 'unknown') AS error_code, count(*) AS n
            FROM {table}
            WHERE job_status = 'FAILED' AND created_at_utc >= :since
            GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 25
        """, {"since": since}):
            failures.append({"queue": queue, "tenantId": r["tenant_id"], "errorCode": r["error_code"],
                             "count": int(r["n"])})
    reclaims = (await session.execute(text("""
        SELECT COALESCE(sum(lease_reclaim_count), 0) FROM docintel.processing_jobs WHERE created_at_utc >= :since
    """), {"since": since})).scalar_one()
    return {"byStatus": by_status, "failures": failures, "leaseReclaims": int(reclaims or 0)}


async def scheduler_problems(session: AsyncSession, since: datetime) -> list[dict[str, Any]]:
    return [{
        "runName": r["run_name"], "runDate": _iso(r["run_date"]), "startedAtUtc": _iso(r["started_at_utc"]),
        "completedAtUtc": _iso(r["completed_at_utc"]), "errorCode": r["error_code"],
    } for r in await _rows(session, """
        SELECT run_name, run_date, started_at_utc, completed_at_utc, error_code
        FROM docintel.scheduler_runs
        WHERE started_at_utc >= :since
          AND (error_code IS NOT NULL OR (completed_at_utc IS NULL AND started_at_utc < now() - interval '1 hour'))
        ORDER BY started_at_utc DESC LIMIT 20
    """, {"since": since})]


async def database(session: AsyncSession) -> dict[str, Any]:
    [base] = await _rows(session, """
        SELECT d.datname AS database, pg_database_size(d.datname) AS size_bytes,
               current_setting('max_connections')::int AS max_connections,
               d.xact_commit AS commits, d.xact_rollback AS rollbacks, d.deadlocks, d.conflicts,
               d.temp_files, d.stats_reset,
               (SELECT count(*) FROM pg_stat_activity a WHERE a.datname = d.datname
                  AND a.state LIKE 'idle in transaction%%' AND a.state_change < now() - interval '5 minutes')
                 AS idle_in_tx_5m,
               (SELECT count(*) FROM pg_stat_activity a WHERE a.datname = d.datname AND a.state = 'active'
                  AND a.backend_type = 'client backend' AND a.query_start < now() - interval '1 minute') AS active_1m,
               (SELECT count(*) FROM pg_stat_activity a WHERE a.datname = d.datname
                  AND a.wait_event_type = 'Lock') AS waiting_on_locks
        FROM pg_stat_database d WHERE d.datname = current_database()
    """)
    connections = {r["state"]: int(r["n"]) for r in await _rows(session, """
        SELECT COALESCE(state, 'unknown') AS state, count(*) AS n FROM pg_stat_activity
        WHERE datname = current_database() AND backend_type = 'client backend' GROUP BY 1
    """)}
    slow: list[dict[str, Any]] | None = None
    note: str | None = None
    has_pss = (await session.execute(text("SELECT to_regclass('public.pg_stat_statements') IS NOT NULL"))).scalar_one()
    if not has_pss:
        note = "pg_stat_statements is not installed"
    else:
        try:
            async with session.begin_nested():
                slow = [{
                    "query": r["query"], "calls": int(r["calls"]), "meanMs": float(r["mean_ms"]),
                    "maxMs": float(r["max_ms"]), "totalMs": float(r["total_ms"]),
                } for r in await _rows(session, r"""
                    SELECT left(regexp_replace(query, '\s+', ' ', 'g'), 300) AS query, calls,
                           round(mean_exec_time::numeric, 1) AS mean_ms, round(max_exec_time::numeric, 1) AS max_ms,
                           round(total_exec_time::numeric, 0) AS total_ms
                    FROM public.pg_stat_statements s
                    WHERE s.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
                      AND s.query NOT ILIKE '%%pg_stat_statements%%'
                    ORDER BY s.mean_exec_time DESC LIMIT 10
                """)]
        except Exception as exc:  # noqa: BLE001 - not preloaded on this server
            note = f"pg_stat_statements is not loaded ({type(exc).__name__})"
    return {
        "database": base["database"], "sizeBytes": int(base["size_bytes"]), "maxConnections": base["max_connections"],
        "commits": int(base["commits"]), "rollbacks": int(base["rollbacks"]), "deadlocks": int(base["deadlocks"]),
        "conflicts": int(base["conflicts"]), "tempFiles": int(base["temp_files"]),
        "statsResetAtUtc": _iso(base["stats_reset"]), "connections": connections,
        "idleInTransactionOver5m": int(base["idle_in_tx_5m"]), "activeOver1m": int(base["active_1m"]),
        "waitingOnLocks": int(base["waiting_on_locks"]), "slowQueries": slow, "slowQueriesNote": note,
    }


async def platform_health(session: AsyncSession, hours: int) -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    return {
        "generatedAtUtc": now.isoformat(), "windowHours": hours,
        "boots": await boots(session, since),
        "resources": await resources(session, since),
        "queues": await queues(session, since),
        "schedulerProblems": await scheduler_problems(session, since),
        "database": await database(session),
    }


@router.get("/v1/platform/health")
async def get_platform_health(
    _service: Annotated[ServiceIntegrationPrincipal, Depends(require_health_reader)],
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
) -> dict[str, Any]:
    async with AsyncSessionFactory() as session:
        return await platform_health(session, hours)


# --- GET /v1/platform/ai-usage -------------------------------------------------

_EXTRACTION_USAGE_SQL = """
    WITH calls AS (
        SELECT (i.started_at_utc AT TIME ZONE :tz)::date AS day, i.tenant_id, i.outcome,
               COALESCE(i.usage_metrics->>'document_type_key', 'unknown') AS document_type_key,
               COALESCE(i.usage_metrics->>'model', 'unknown') AS model,
               -- A read made before the tier was kept on the call takes its upload's tier.
               COALESCE(i.usage_metrics->>'service_tier', u.gemini_tier, 'STANDARD') AS tier,
               (i.usage_metrics ? 'billed_prompt_tokens') AS has_tokens,
               COALESCE((i.usage_metrics->>'billed_prompt_tokens')::bigint, 0) AS prompt_tokens,
               GREATEST(
                   COALESCE((i.usage_metrics->>'response_tokens')::bigint, 0)
                     + COALESCE((i.usage_metrics->>'thoughts_tokens')::bigint, 0),
                   COALESCE((i.usage_metrics->>'total_tokens')::bigint, 0)
                     - COALESCE((i.usage_metrics->>'billed_prompt_tokens')::bigint, 0),
                   0) AS output_tokens,
               COALESCE((i.usage_metrics->>'cached_tokens')::bigint, 0) AS cached_tokens,
               (i.usage_metrics->>'cost_usd')::numeric AS cost_usd
        FROM docintel.processor_invocations i
        LEFT JOIN docintel.processing_runs pr
          ON pr.tenant_id = i.tenant_id AND pr.processing_run_id = i.processing_run_id
        LEFT JOIN docintel.document_capture_v2_uploads u
          ON u.tenant_id = pr.tenant_id AND u.document_id = pr.document_id
        WHERE i.capability = 'VISION_EXTRACTION' AND i.started_at_utc >= :since
    )
    SELECT day, tenant_id, document_type_key, model, tier,
           count(*) AS calls,
           count(*) FILTER (WHERE outcome = 'FAILED') AS failed_calls,
           count(*) FILTER (WHERE NOT has_tokens AND cost_usd IS NULL) AS calls_without_usage,
           sum(prompt_tokens) AS prompt_tokens, sum(output_tokens) AS output_tokens,
           COALESCE(sum(cost_usd), 0) AS recorded_cost_usd,
           COALESCE(sum(prompt_tokens) FILTER (WHERE cost_usd IS NULL AND has_tokens), 0) AS unpriced_prompt_tokens,
           COALESCE(sum(output_tokens) FILTER (WHERE cost_usd IS NULL AND has_tokens), 0) AS unpriced_output_tokens,
           -- Input the provider served from its cache is billed at a tenth of the price.
           COALESCE(sum(cached_tokens) FILTER (WHERE cost_usd IS NULL AND has_tokens), 0) AS unpriced_cached_tokens
    FROM calls
    GROUP BY 1, 2, 3, 4, 5
    ORDER BY 1, 2, 3
"""

_CLASSIFICATION_USAGE_SQL = """
    SELECT (j.created_at_utc AT TIME ZONE :tz)::date AS day, j.tenant_id,
           COALESCE(j.usage_metrics->>'model', 'unknown') AS model,
           COALESCE(j.usage_metrics->>'service_tier', 'unknown') AS tier,
           (j.usage_metrics IS NOT NULL) AS has_usage,
           -- Usage is kept from the first job that has it; an earlier job's call was never recorded.
           (CAST(:recorded_since AS timestamptz) IS NULL
            OR j.created_at_utc < CAST(:recorded_since AS timestamptz)) AS before_recording,
           count(*) AS jobs,
           count(*) FILTER (WHERE j.job_status = 'FAILED') AS failed_jobs,
           COALESCE(sum((j.usage_metrics->>'provider_calls')::int), 0) AS calls,
           COALESCE(sum((j.usage_metrics->>'billed_prompt_tokens')::bigint), 0) AS prompt_tokens,
           COALESCE(sum((j.usage_metrics->>'billed_output_tokens')::bigint), 0) AS output_tokens,
           COALESCE(sum((j.usage_metrics->>'cost_usd')::numeric), 0) AS recorded_cost_usd,
           count(*) FILTER (WHERE j.usage_metrics IS NOT NULL AND j.usage_metrics->>'cost_usd' IS NULL)
             AS jobs_without_price
    FROM docintel.document_capture_v2_classification_jobs j
    WHERE j.created_at_utc >= :since
    GROUP BY 1, 2, 3, 4, 5, 6
    ORDER BY 1, 2
"""


def usage_window(days: int, tz: ZoneInfo, now: datetime) -> tuple[date, datetime]:
    """The first day of a window of ``days`` whole days ending today in ``tz``,
    and the UTC instant that day starts."""
    first_day = now.astimezone(tz).date() - timedelta(days=days - 1)
    return first_day, datetime.combine(first_day, time.min, tzinfo=tz).astimezone(UTC)


def _money(value: Any) -> float:
    return round(float(value or 0), 6)


def extraction_usage_row(r: dict[str, Any]) -> dict[str, Any]:
    """One day / Project / document type of reads. A read that kept its tokens but
    no cost (every read before 2026-11-16) is priced here from those tokens at the
    list price of its model and tier; a model with no price leaves it uncosted."""
    recorded = _money(r["recorded_cost_usd"])
    from_tokens: float | None = 0.0
    if int(r["unpriced_prompt_tokens"]) or int(r["unpriced_output_tokens"]):
        output = int(r["unpriced_output_tokens"])
        from_tokens = cost_usd(
            str(r["model"]), str(r["tier"]), prompt_tokens=int(r["unpriced_prompt_tokens"]),
            response_tokens=output, total_tokens=0, cached_tokens=int(r.get("unpriced_cached_tokens") or 0))
    return {
        "date": _iso(r["day"]), "tenantId": r["tenant_id"], "capability": "EXTRACTION",
        "documentTypeKey": r["document_type_key"], "model": r["model"], "tier": r["tier"],
        "calls": int(r["calls"]), "failedCalls": int(r["failed_calls"]),
        "callsWithoutUsage": int(r["calls_without_usage"]),
        "promptTokens": int(r["prompt_tokens"]), "outputTokens": int(r["output_tokens"]),
        "costUsd": None if from_tokens is None else round(recorded + from_tokens, 6),
        "costFromTokensUsd": from_tokens,
    }


def classification_usage_row(r: dict[str, Any]) -> dict[str, Any]:
    """One day / Project of classification jobs. A job with no usage made no provider
    call (its single candidate was trusted) -- or, before usage began to be kept,
    made one that was never recorded: those are counted apart, never costed."""
    has_usage = bool(r["has_usage"])
    before_recording = not has_usage and bool(r["before_recording"])
    unpriced = int(r["jobs_without_price"])
    return {
        "date": _iso(r["day"]), "tenantId": r["tenant_id"], "capability": "CLASSIFICATION",
        "documentTypeKey": None, "model": r["model"] if has_usage else None, "tier": r["tier"] if has_usage else None,
        "calls": int(r["calls"]) if has_usage else (int(r["jobs"]) if before_recording else 0),
        "failedCalls": int(r["failed_jobs"]),
        "callsWithoutUsage": int(r["jobs"]) if before_recording else 0,
        "promptTokens": int(r["prompt_tokens"]), "outputTokens": int(r["output_tokens"]),
        "costUsd": None if (before_recording or unpriced) else _money(r["recorded_cost_usd"]),
        "costFromTokensUsd": 0.0,
    }


async def ai_usage(session: AsyncSession, days: int, tz_name: str, now: datetime | None = None) -> dict[str, Any]:
    tz = ZoneInfo(tz_name)
    moment = now or datetime.now(UTC)
    first_day, since = usage_window(days, tz, moment)
    recorded_since = (await session.execute(text(
        "SELECT min(created_at_utc) FROM docintel.document_capture_v2_classification_jobs "
        "WHERE usage_metrics IS NOT NULL"))).scalar_one_or_none()
    params = {"tz": tz_name, "since": since}
    rows = [extraction_usage_row(r) for r in await _rows(session, _EXTRACTION_USAGE_SQL, params)]
    rows += [classification_usage_row(r) for r in await _rows(
        session, _CLASSIFICATION_USAGE_SQL, {**params, "recorded_since": recorded_since})]
    return {
        "generatedAtUtc": moment.isoformat(), "days": days, "timezone": tz_name,
        "firstDay": first_day.isoformat(), "currency": "USD",
        "prices": [{"model": model, "tier": tier, "inputPerMTok": float(price[0]), "outputPerMTok": float(price[1])}
                   for model, tiers in sorted(PRICES_USD_PER_MTOK.items()) for tier, price in sorted(tiers.items())],
        "classificationRecordedSinceUtc": _iso(recorded_since),
        "rows": rows,
    }


@router.get("/v1/platform/ai-usage")
async def get_ai_usage(
    _service: Annotated[ServiceIntegrationPrincipal, Depends(require_health_reader)],
    days: Annotated[int, Query(ge=1, le=92)] = 30,
    tz: Annotated[str, Query(max_length=64)] = "Asia/Kolkata",
) -> dict[str, Any]:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise http_exception(ErrorCode.VALIDATION_ERROR, detail="Unknown time zone.") from exc
    async with AsyncSessionFactory() as session:
        return await ai_usage(session, days, tz)
