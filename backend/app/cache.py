from redis.asyncio import Redis

from app.config import get_settings

redis = Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2)


async def redis_alive() -> bool:
    try:
        return bool(await redis.ping())
    except Exception:
        return False
