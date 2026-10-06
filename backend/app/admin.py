"""Раздел владельца: приглашения, пользователи, ссылки сброса пароля.

Только для администратора с включённой 2FA. Позже то же самое будет доступно
из Telegram-бота (этап 9)."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import Current, Db, new_invite, new_reset_link, require_2fa
from app.cache import redis
from app.db import read_flags
from app.models import EngineEvent, Invite, SystemFlag, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


async def require_admin(cur: Annotated[Current, Depends(require_2fa)]) -> Current:
    if not cur.user.is_admin:
        raise HTTPException(403, "Только для владельца")
    return cur


Admin = Annotated[Current, Depends(require_admin)]


class InviteIn(BaseModel):
    note: str | None = Field(default=None, max_length=120)


@router.post("/invites")
async def create_invite(body: InviteIn, cur: Admin, db: Db) -> dict:
    link = await new_invite(db, cur.user, body.note)
    await db.commit()
    return {"link": link, "expires_in_days": 7}


@router.get("/invites")
async def list_invites(cur: Admin, db: Db) -> list[dict]:
    rows = (
        await db.execute(
            select(Invite, User.email)
            .outerjoin(User, User.id == Invite.used_by)
            .order_by(Invite.created_at.desc())
            .limit(100)
        )
    ).all()
    now = datetime.now(UTC)
    return [
        {
            "note": inv.note,
            "created_at": inv.created_at.isoformat(),
            "status": "used" if inv.used_at else ("expired" if inv.expires_at < now else "active"),
            "used_by": email,
        }
        for inv, email in rows
    ]


@router.get("/users")
async def list_users(cur: Admin, db: Db) -> list[dict]:
    users = await db.scalars(select(User).order_by(User.created_at))
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "is_admin": u.is_admin,
            "totp_enabled": u.totp_enabled_at is not None,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@router.post("/users/{user_id}/reset-link")
async def reset_link(user_id: uuid.UUID, cur: Admin, db: Db) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Нет такого пользователя")
    link = await new_reset_link(db, user)
    await db.commit()
    return {"link": link, "expires_in_hours": 1}


class GlobalStopIn(BaseModel):
    stopped: bool


@router.get("/flags")
async def flags(cur: Admin, db: Db) -> dict[str, bool]:
    return await read_flags(db)


@router.post("/global-stop")
async def global_stop(body: GlobalStopIn, cur: Admin, db: Db) -> dict[str, bool]:
    """Общая аварийная остановка: все кабинеты закрывают позиции и встают."""
    flag = await db.get(SystemFlag, "global_stop")
    flag.value = body.stopped
    db.add(
        EngineEvent(
            kind="global_stop",
            message="Общая аварийная остановка" if body.stopped else "Общая остановка снята",
        )
    )
    await db.commit()
    try:
        await redis.set("stop:global", "1" if body.stopped else "0")
    except Exception:  # Redis недоступен — диспетчер подхватит флаг из базы
        log.warning("Redis недоступен")
    return await read_flags(db)
