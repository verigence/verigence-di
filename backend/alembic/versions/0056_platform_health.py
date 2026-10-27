"""DI's own platform health tables (SuperAdmin System Health, 2026-10-27).

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-27

DI runs on its own database (the Railway Postgres service), not Audit Core's,
so its health is kept here and read by Audit Core through
GET /v1/platform/health (a ServiceIntegration call), never by giving DI access
to Audit Core's database:

- docintel.service_heartbeats: one row per process start (a "boot"), last_seen
  refreshed every minute, stopped_at stamped on a clean shutdown;
- docintel.service_resource_minutes: the container's CPU (average and 5-second
  peak) and memory per minute, against its limits.

pg_stat_statements is enabled where the server preloads it, so the slowest
queries can be listed; elsewhere the health endpoint says it is unavailable.
"""
from __future__ import annotations

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
        EXCEPTION WHEN OTHERS THEN
          RAISE NOTICE 'pg_stat_statements not available: %', SQLERRM;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS docintel.service_heartbeats (
          boot_id uuid PRIMARY KEY,
          service_name varchar(80) NOT NULL,
          replica_id varchar(120),
          deployment_id varchar(120),
          version varchar(80),
          started_at_utc timestamptz NOT NULL DEFAULT now(),
          last_seen_at_utc timestamptz NOT NULL DEFAULT now(),
          stopped_at_utc timestamptz,
          stop_reason varchar(80)
        );
        CREATE INDEX IF NOT EXISTS ix_di_service_heartbeats_service_started
          ON docintel.service_heartbeats (service_name, started_at_utc DESC);

        CREATE TABLE IF NOT EXISTS docintel.service_resource_minutes (
          boot_id uuid NOT NULL,
          service_name varchar(80) NOT NULL,
          minute_utc timestamptz NOT NULL,
          cpu_cores_avg numeric(8,3),
          cpu_cores_max numeric(8,3),
          cpu_limit_cores numeric(8,3),
          memory_bytes_max bigint,
          memory_limit_bytes bigint,
          PRIMARY KEY (boot_id, minute_utc)
        );
        CREATE INDEX IF NOT EXISTS ix_di_service_resource_minutes_minute
          ON docintel.service_resource_minutes (service_name, minute_utc DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS docintel.service_resource_minutes")
    op.execute("DROP TABLE IF EXISTS docintel.service_heartbeats")
