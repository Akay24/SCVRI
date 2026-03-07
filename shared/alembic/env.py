"""Alembic migration environment.

Supports both offline (--sql) and online modes.
Database URL is always sourced from pydantic Settings — never hardcoded.

Running migrations::

    # Apply all pending migrations
    cd shared && alembic upgrade head

    # Generate a new migration (after model changes)
    cd shared && alembic revision --autogenerate -m "describe_change"

    # Show current revision
    cd shared && alembic current
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# ---------------------------------------------------------------------------
# Load pydantic settings — this also loads .env if present
# ---------------------------------------------------------------------------
from scvri_shared.config import settings

# ---------------------------------------------------------------------------
# Import ALL models so Alembic's autogenerate sees them
# ---------------------------------------------------------------------------
from scvri_shared.models import Base  # noqa: F401 – imports trigger model registration

# ---------------------------------------------------------------------------
# Alembic boilerplate
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Override the sqlalchemy.url with the value from our settings rather than
# reading it from alembic.ini — this ensures .env is the single source of truth.
config.set_main_option("sqlalchemy.url", settings.database_url)


def include_object(object, name, type_, reflected, compare_to):  # noqa: A002
    """Filter — skip Citus-internal tables that appear during reflection."""
    if type_ == "table" and name.startswith("pg_"):
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL script, no live DB needed)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (requires live DB connection)."""
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,       # single-use connection for migrations
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
            # Transactional DDL — all migration steps are one atomic transaction
            transaction_per_migration=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
