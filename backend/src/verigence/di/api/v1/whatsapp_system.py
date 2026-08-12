"""api/v1/whatsapp_system.py — System-scoped WhatsApp routes (stubs for Phase 2).

OAS operations (5):
  POST /v1/system/whatsapp/routes
       → putWhatsappRoute            (platform:whatsapp:admin, systemBearer)
  POST /v1/integrations/whatsapp/webhook
       → whatsappWebhook             (no JWT — provider HMAC only)
  GET  /v1/system/whatsapp/quarantine
       → getWhatsappQuarantine       (platform:whatsapp:admin, systemBearer)
  POST /v1/system/whatsapp/quarantine/{quarantineId}/replay
       → replayWhatsappQuarantine    (platform:whatsapp:admin, systemBearer)
  POST /v1/system/whatsapp/quarantine/{quarantineId}/discard
       → discardWhatsappQuarantine   (platform:whatsapp:admin, systemBearer)

Phase-1 status: correct HTTP routing + auth enforcement. Full business logic
(HMAC verification, media download, replay processing) is in Step 14 (Phase 2).
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text

from verigence.di.auth.dependencies import require_system_actor
from verigence.di.auth.permissions import Permission
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.errors import ErrorCode, problem

router = APIRouter(tags=["WhatsApp"])


# ── POST /v1/system/whatsapp/routes ──────────────────────────────────────────

@router.post("/v1/system/whatsapp/routes")
async def put_whatsapp_route(
    body: dict[str, Any],
    actor: ActorPrincipal = Depends(require_system_actor),
) -> dict[str, Any]:
    """Configure a WhatsApp destination/account route to Tenant and SYSTEM actor.

    Phase 1: stores route row. Full webhook dispatch is Phase 2.
    """
    # Permission check — system actor must carry platform:whatsapp:admin
    if not actor.can(Permission.PLATFORM_WHATSAPP_ADMIN):
        raise problem(403, "Requires platform:whatsapp:admin permission",
                      ErrorCode.FORBIDDEN)

    destination_id: str = body.get("destinationId", "")
    tenant_id: str = body.get("tenantId", "")
    system_actor_id: str = body.get("systemActorId", "")
    if not destination_id or not tenant_id:
        raise problem(422, "destinationId and tenantId are required",
                      ErrorCode.VALIDATION_ERROR)

    from datetime import UTC, datetime
    now = datetime.now(UTC)
    route_id = uuid.uuid4()

    # Use a raw non-tenant session (system scope has no app.tenant_id)
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from verigence.di.repositories.database import get_engine
    engine = get_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        await session.execute(
            text("""
                    INSERT INTO docintel.whatsapp_routes
                        (route_id, destination_id, tenant_id, system_actor_id,
                         status, created_at_utc, updated_at_utc)
                    VALUES (:rid, :dest, :tid, :said, 'ACTIVE', :now, :now)
                    ON CONFLICT (destination_id) DO UPDATE
                    SET tenant_id = EXCLUDED.tenant_id,
                        system_actor_id = EXCLUDED.system_actor_id,
                        status = 'ACTIVE',
                        updated_at_utc = EXCLUDED.updated_at_utc
                """),
            {
                "rid": route_id, "dest": destination_id,
                "tid": tenant_id, "said": system_actor_id or None,
                "now": now,
            },
        )

    return {
        "routeId": str(route_id),
        "destinationId": destination_id,
        "tenantId": tenant_id,
        "systemActorId": system_actor_id or None,
        "status": "ACTIVE",
    }


# ── POST /v1/integrations/whatsapp/webhook ────────────────────────────────────

@router.post("/v1/integrations/whatsapp/webhook")
async def whatsapp_webhook(request: Request) -> Response:
    """Receive inbound WhatsApp message/media webhook.

    Phase 1: acknowledge 200. HMAC verification + media intake is Phase 2.
    Provider signature verification replaces JWT — no auth dependency here.
    """
    # TODO (Phase 2): verify provider HMAC signature before processing
    return Response(status_code=200)


# ── GET /v1/system/whatsapp/quarantine ────────────────────────────────────────

@router.get("/v1/system/whatsapp/quarantine")
async def get_whatsapp_quarantine(
    page: int = 1,
    page_size: int = 50,
    actor: ActorPrincipal = Depends(require_system_actor),
) -> dict[str, Any]:
    """List WhatsApp intake events for which Tenant routing failed."""
    if not actor.can(Permission.PLATFORM_WHATSAPP_ADMIN):
        raise problem(403, "Requires platform:whatsapp:admin permission",
                      ErrorCode.FORBIDDEN)

    offset = (max(1, page) - 1) * min(200, page_size)
    limit = min(200, page_size)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from verigence.di.repositories.database import get_engine
    engine = get_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.execute(
                text("""
                    SELECT quarantine_id, destination_id, sender_phone_number,
                           status, received_at_utc, created_at_utc
                    FROM docintel.whatsapp_quarantine
                    WHERE status = 'PENDING'
                    ORDER BY received_at_utc DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"limit": limit, "offset": offset},
            )
        ).mappings().all()
        total = (
            await session.execute(
                text("""
                    SELECT COUNT(*) FROM docintel.whatsapp_quarantine
                    WHERE status = 'PENDING'
                """),
            )
        ).scalar()

    return {
        "items": [
            {
                "quarantineId": str(r["quarantine_id"]),
                "destinationId": r["destination_id"],
                "senderPhoneNumber": r["sender_phone_number"],
                "status": r["status"],
                "receivedAt": r["received_at_utc"].isoformat() if r.get("received_at_utc") else None,
            }
            for r in rows
        ],
        "page": page,
        "pageSize": page_size,
        "total": total or 0,
    }


# ── POST /v1/system/whatsapp/quarantine/{quarantineId}/replay ─────────────────

@router.post("/v1/system/whatsapp/quarantine/{quarantine_id}/replay", status_code=202)
async def replay_whatsapp_quarantine(
    quarantine_id: uuid.UUID,
    actor: ActorPrincipal = Depends(require_system_actor),
) -> Response:
    """Replay a quarantined WhatsApp intake item after route is corrected.

    Phase 1: validates item exists + is PENDING; sets REPLAYING. Full replay logic is Phase 2.
    """
    if not actor.can(Permission.PLATFORM_WHATSAPP_ADMIN):
        raise problem(403, "Requires platform:whatsapp:admin permission",
                      ErrorCode.FORBIDDEN)

    from datetime import UTC, datetime
    now = datetime.now(UTC)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from verigence.di.repositories.database import get_engine
    engine = get_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = (
            await session.execute(
                text("""
                        SELECT status FROM docintel.whatsapp_quarantine
                        WHERE quarantine_id = :qid
                    """),
                {"qid": quarantine_id},
            )
        ).one_or_none()
        if row is None:
            raise problem(404, "Quarantine item not found",
                          ErrorCode.QUARANTINE_ITEM_NOT_FOUND)
        if row[0] != "PENDING":
            raise problem(409, f"Quarantine item is {row[0]}, not PENDING",
                          ErrorCode.INVALID_DOCUMENT_STATE)

        await session.execute(
            text("""
                    UPDATE docintel.whatsapp_quarantine
                    SET status = 'REPLAYING', updated_at_utc = :now
                    WHERE quarantine_id = :qid
                """),
            {"qid": quarantine_id, "now": now},
        )

    return Response(status_code=202)


# ── POST /v1/system/whatsapp/quarantine/{quarantineId}/discard ────────────────

@router.post("/v1/system/whatsapp/quarantine/{quarantine_id}/discard")
async def discard_whatsapp_quarantine(
    quarantine_id: uuid.UUID,
    actor: ActorPrincipal = Depends(require_system_actor),
) -> dict[str, Any]:
    """Discard a quarantined item — deletes temporary media + marks DISCARDED."""
    if not actor.can(Permission.PLATFORM_WHATSAPP_ADMIN):
        raise problem(403, "Requires platform:whatsapp:admin permission",
                      ErrorCode.FORBIDDEN)

    from datetime import UTC, datetime
    now = datetime.now(UTC)

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from verigence.di.repositories.database import get_engine
    engine = get_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = (
            await session.execute(
                text("""
                        SELECT status FROM docintel.whatsapp_quarantine
                        WHERE quarantine_id = :qid
                    """),
                {"qid": quarantine_id},
            )
        ).one_or_none()
        if row is None:
            raise problem(404, "Quarantine item not found",
                          ErrorCode.QUARANTINE_ITEM_NOT_FOUND)
        if row[0] not in ("PENDING", "REPLAYING"):
            raise problem(409, f"Cannot discard item in state {row[0]}",
                          ErrorCode.INVALID_DOCUMENT_STATE)

        await session.execute(
            text("""
                    UPDATE docintel.whatsapp_quarantine
                    SET status = 'DISCARDED', updated_at_utc = :now
                    WHERE quarantine_id = :qid
                """),
            {"qid": quarantine_id, "now": now},
        )

    return {"quarantineId": str(quarantine_id), "status": "DISCARDED"}
