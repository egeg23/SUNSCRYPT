from collections.abc import AsyncIterator

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.models import SystemFlag

_s = get_settings()
engine = (
    create_async_engine(_s.database_url, poolclass=NullPool)
    if _s.db_nullpool
    else create_async_engine(_s.database_url, pool_pre_ping=True, pool_size=5)
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def db_alive() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def read_flags(session: AsyncSession) -> dict[str, bool]:
    rows = await session.execute(select(SystemFlag.key, SystemFlag.value))
    return {key: value for key, value in rows.all()}
