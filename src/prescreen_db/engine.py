"""Async SQLAlchemy engine and session factory.

The engine is created lazily on first call and reused across the process
lifetime.  Call ``dispose_engine()`` during graceful shutdown.
"""

import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from prescreen_db.config import get_async_url

# Connection pool tuning — overridable via PG_POOL_SIZE / PG_MAX_OVERFLOW
# env vars so operators can scale the pool without code changes.
_POOL_SIZE = int(os.getenv("PG_POOL_SIZE", "5"))
_MAX_OVERFLOW = int(os.getenv("PG_MAX_OVERFLOW", "10"))

# Module-level singleton so the entire app shares one connection pool.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return (and lazily create) the singleton async engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_async_url(),
            echo=False,
            pool_size=_POOL_SIZE,
            max_overflow=_MAX_OVERFLOW,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return (and lazily create) the async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def dispose_engine() -> None:
    """Dispose the engine's connection pool (call on app shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
