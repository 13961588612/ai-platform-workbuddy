"""Alembic environment configuration.

Reads the database URL from the application :class:`Settings` so that
migrations use the same connection parameters as the running backend.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure the backend source is importable
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from src.config import get_settings  # noqa: E402
from src.models.base import Base  # noqa: E402

# Import all model modules so that Base.metadata is fully populated
import src.models.agent  # noqa: F401, E402
import src.models.agent_memory  # noqa: F401, E402
import src.models.session  # noqa: F401, E402
import src.models.skill  # noqa: F401, E402
import src.models.user  # noqa: F401, E402

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the SQLAlchemy URL from application settings
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.postgres_dsn_sync)

# Target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect to the database)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
