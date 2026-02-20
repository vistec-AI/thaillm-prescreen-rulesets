"""Database configuration — reads connection parameters from environment.

Supports two modes:
1. A single ``DATABASE_URL`` env var (takes precedence).
2. Individual ``PG_HOST``, ``PG_PORT``, ``PG_USER``, ``PG_PASSWORD``,
   ``PG_DATABASE`` env vars (convenient for docker-compose).

Both ``sync_url`` (used by Alembic migrations) and ``async_url`` (used by
the async SQLAlchemy engine at runtime) are exposed.
"""

import os


def _build_url_from_parts() -> str:
    """Construct a PostgreSQL connection string from individual env vars."""
    host = os.getenv("PG_HOST", "localhost")
    port = os.getenv("PG_PORT", "5432")
    user = os.getenv("PG_USER", "prescreen")
    password = os.getenv("PG_PASSWORD", "prescreen")
    database = os.getenv("PG_DATABASE", "prescreen")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def get_sync_url() -> str:
    """Return a synchronous (psycopg2 / libpq) connection URL.

    Used by Alembic which runs migrations synchronously.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        # Normalise async driver prefix if the caller set an asyncpg URL
        return url.replace("postgresql+asyncpg://", "postgresql://")
    return _build_url_from_parts()


def get_async_url() -> str:
    """Return an asyncpg connection URL for the async SQLAlchemy engine."""
    url = os.getenv("DATABASE_URL")
    if url:
        # Ensure the asyncpg driver prefix is present
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
    base = _build_url_from_parts()
    return base.replace("postgresql://", "postgresql+asyncpg://", 1)
