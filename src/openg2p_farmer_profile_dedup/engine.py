from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None
_service_engine: AsyncEngine | None = None
_service_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.resolved_db_datasource, echo=False, pool_pre_ping=True)
    return _engine


def get_service_engine() -> AsyncEngine:
    global _service_engine
    if _service_engine is None:
        settings = get_settings()
        _service_engine = create_async_engine(
            settings.resolved_service_db_datasource,
            echo=False,
            pool_pre_ping=True,
        )
    return _service_engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_maker


def get_service_session_maker() -> async_sessionmaker[AsyncSession]:
    global _service_session_maker
    if _service_session_maker is None:
        _service_session_maker = async_sessionmaker(
            bind=get_service_engine(),
            expire_on_commit=False,
        )
    return _service_session_maker


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    session_maker = get_session_maker()
    async with session_maker() as session:
        yield session


@asynccontextmanager
async def get_service_session() -> AsyncIterator[AsyncSession]:
    session_maker = get_service_session_maker()
    async with session_maker() as session:
        yield session
