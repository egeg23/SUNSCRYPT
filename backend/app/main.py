"""SUNSCRYPT API. Все пути — под /api: gateway отдаёт /api сюда, остальное —
сайту."""

import logging
from contextlib import asynccontextmanager
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import admin, auth, safety
from app.cache import redis_alive
from app.config import get_settings
from app.db import SessionLocal, db_alive, get_session, read_flags


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        async with SessionLocal() as db:
            await auth.ensure_owner(db)
    except Exception as e:  # база ещё не готова — повторим при следующем запуске
        logging.getLogger(__name__).warning("владелец не создан: %s", type(e).__name__)
    yield


app = FastAPI(
    title="SUNSCRYPT API",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.include_router(auth.router)
app.include_router(admin.router)


@app.middleware("http")
async def same_origin_only(request: Request, call_next):
    """Защита от CSRF вдобавок к SameSite=Lax: изменяющие запросы из
    браузера принимаем только со своего сайта."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Чужой источник запроса"}, status_code=403)
    return await call_next(request)


async def get_flags(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, bool]:
    return await read_flags(session)


@app.get("/api/health")
async def health(response: Response) -> dict:
    db, cache = await db_alive(), await redis_alive()
    ok = db and cache
    if not ok:
        response.status_code = 503
    return {
        "status": "ok" if ok else "degraded",
        "db": db,
        "redis": cache,
        "commit": get_settings().git_commit,
    }


@app.get("/api/status")
async def status(flags: Annotated[dict[str, bool], Depends(get_flags)]) -> dict:
    """Публичный режим сервиса: что разрешено прямо сейчас."""
    real_enabled = flags.get("real_trading_enabled", False)
    global_stop = flags.get("global_stop", False)
    return {
        "default_mode": safety.DEFAULT_MODE,
        "real_trading_allowed": safety.real_mode_allowed(real_enabled, global_stop),
        "global_stop": global_stop,
        "max_leverage": safety.MAX_LEVERAGE,
        "default_leverage": safety.DEFAULT_LEVERAGE,
    }
