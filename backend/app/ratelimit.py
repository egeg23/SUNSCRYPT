"""Ограничение частоты запросов на Redis: окно фиксированной длины."""

import logging

from fastapi import HTTPException

from app.cache import redis

log = logging.getLogger(__name__)


async def hit(key: str, limit: int, window_s: int) -> bool:
    """True — запрос в пределах лимита. Если Redis недоступен, пропускаем:
    вход важнее, а сбой Redis видно в /api/health."""
    try:
        k = f"rl:{key}"
        n = await redis.incr(k)
        if n == 1:
            await redis.expire(k, window_s)
        return n <= limit
    except Exception:
        log.warning("ratelimit: Redis недоступен, лимит не проверен")
        return True


async def enforce(key: str, limit: int, window_s: int) -> None:
    if not await hit(key, limit, window_s):
        raise HTTPException(429, "Слишком много попыток. Подождите и попробуйте снова.")
