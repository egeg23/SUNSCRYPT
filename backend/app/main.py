import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings
from app.db import engine

log = logging.getLogger("sunscrypt")
settings = get_settings()

app = FastAPI(
    title="SUNSCRYPT API", version=settings.version, docs_url="/api/docs", openapi_url="/api/openapi.json"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _check_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True
    except Exception as e:  # noqa: BLE001 - health must report, not raise
        log.warning("db health failed: %s", type(e).__name__)
        return False


async def _check_redis() -> bool:
    try:
        r = Redis.from_url(settings.redis_url)
        try:
            return bool(await r.ping())
        finally:
            await r.aclose()
    except Exception as e:  # noqa: BLE001
        log.warning("redis health failed: %s", type(e).__name__)
        return False


@app.get("/api/health")
async def health() -> dict:
    db, redis = await _check_db(), await _check_redis()
    return {
        "status": "ok" if db and redis else "degraded",
        "db": db,
        "redis": redis,
        "version": settings.version,
        "env": settings.env,
    }


@app.get("/api/meta")
async def meta() -> dict:
    """Public, non-secret service flags the web app needs before login."""
    return {
        "name": "SUNSCRYPT",
        "version": settings.version,
        "registration": settings.registration,
        "live_trading_enabled": settings.live_trading_enabled,
    }
