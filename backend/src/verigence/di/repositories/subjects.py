"""repositories/subjects.py — Subject repository (async SQLAlchemy)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from verigence.di.domain.enums import SubjectStatus, SubjectType


async def create_subject(
    session: AsyncSession,
    *,
    tenant_id: str,
    subject_type: SubjectType,
    display_name: str | None,
    created_by_actor_id: str,
    created_by_actor_type: str = "USER",
) -> dict:  # type: ignore[type-arg]
    """Insert a Subject after ensuring its creating actor exists."""
    from verigence.di.repositories.tenants import provision_actor  # noqa: PLC0415

    await provision_actor(
        session,
        tenant_id,
        created_by_actor_id,
        actor_type=created_by_actor_type,
    )
    now = datetime.now(UTC)
    subject_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO docintel.subjects
                (tenant_id, subject_id, subject_type, display_name, status,
                 created_by_actor_id, created_at_utc, updated_at_utc)
            VALUES
                (:tenant_id, :subject_id, :subject_type, :display_name, 'ACTIVE',
                 :actor_id, :now, :now)
        """),
        {
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "subject_type": subject_type.value,
            "display_name": display_name,
            "actor_id": created_by_actor_id,
            "now": now,
        },
    )
    await session.commit()
    return {
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "subject_type": subject_type,
        "display_name": display_name,
        "status": SubjectStatus.ACTIVE,
        "created_at_utc": now,
        "updated_at_utc": now,
    }


async def get_subject(
    session: AsyncSession,
    *,
    tenant_id: str,
    subject_id: uuid.UUID,
) -> dict | None:  # type: ignore[type-arg]
    row = (
        await session.execute(
            text("""
                SELECT tenant_id, subject_id, subject_type, display_name, status,
                       created_at_utc, updated_at_utc
                FROM docintel.subjects
                WHERE tenant_id = :tenant_id AND subject_id = :subject_id
            """),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        )
    ).mappings().one_or_none()
    if row is None:
        return None
    return {
        "tenant_id": row["tenant_id"],
        "subject_id": row["subject_id"],
        "subject_type": SubjectType(row["subject_type"]),
        "display_name": row["display_name"],
        "status": SubjectStatus(row["status"]),
        "created_at_utc": row["created_at_utc"],
        "updated_at_utc": row["updated_at_utc"],
    }


async def list_subjects(
    session: AsyncSession,
    *,
    tenant_id: str,
    status: SubjectStatus | None = None,
    query: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:  # type: ignore[type-arg]
    conditions = ["tenant_id = :tenant_id"]
    params: dict = {"tenant_id": tenant_id, "limit": limit + 1}  # type: ignore[type-arg]
    if status is not None:
        conditions.append("status = :status")
        params["status"] = status.value
    if query:
        conditions.append("display_name ILIKE :query")
        params["query"] = f"%{query}%"
    if cursor:
        conditions.append("subject_id > :cursor")
        params["cursor"] = cursor
    where_clause = " AND ".join(conditions)
    sql = text(f"""
        SELECT tenant_id, subject_id, subject_type, display_name, status,
               created_at_utc, updated_at_utc
        FROM docintel.subjects
        WHERE {where_clause}
        ORDER BY created_at_utc DESC, subject_id
        LIMIT :limit
    """)
    rows = (await session.execute(sql, params)).mappings().all()
    return [
        {
            "tenant_id": r["tenant_id"],
            "subject_id": r["subject_id"],
            "subject_type": SubjectType(r["subject_type"]),
            "display_name": r["display_name"],
            "status": SubjectStatus(r["status"]),
            "created_at_utc": r["created_at_utc"],
            "updated_at_utc": r["updated_at_utc"],
        }
        for r in rows
    ]


async def subject_exists(
    session: AsyncSession,
    *,
    tenant_id: str,
    subject_id: uuid.UUID,
) -> bool:
    row = (
        await session.execute(
            text("""
                SELECT 1 FROM docintel.subjects
                WHERE tenant_id = :tenant_id AND subject_id = :subject_id AND status = 'ACTIVE'
                LIMIT 1
            """),
            {"tenant_id": tenant_id, "subject_id": subject_id},
        )
    ).one_or_none()
    return row is not None
