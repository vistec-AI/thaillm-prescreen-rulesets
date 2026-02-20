"""Alembic environment — async-aware migration runner.

Uses the synchronous ``get_sync_url()`` helper because Alembic's migration
runner is synchronous.  ``run_migrations_online`` connects via a plain
``Engine`` and applies revisions.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from prescreen_db.config import get_sync_url
from prescreen_db.models.base import Base

# Import all models so Base.metadata knows about their tables.
# Without this, autogenerate would see an empty metadata.
import prescreen_db.models.session  # noqa: F401

# --- Alembic Config ---
config = context.config

# Override the URL placeholder in alembic.ini with the real value from env
config.set_main_option("sqlalchemy.url", get_sync_url())

# Set up Python logging from the ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL without connecting."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connect and apply."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
