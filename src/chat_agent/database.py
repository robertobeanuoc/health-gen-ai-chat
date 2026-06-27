import os

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def _get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        uri = os.getenv("MYSQL_ALCHEMY_URI", "")
        if not uri:
            raise RuntimeError("MYSQL_ALCHEMY_URI environment variable is not set.")
        async_uri = uri.replace("mysql+pymysql://", "mysql+aiomysql://", 1)
        _engine = create_async_engine(async_uri, echo=False, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def init_db() -> None:
    from . import models  # noqa: F401 — register models before create_all

    async with _get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    if _session_factory is None:
        _get_engine()
    async with _session_factory() as session:
        yield session
