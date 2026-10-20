"""Environment and role invariants for the mandatory PostgreSQL gate."""

from __future__ import annotations

import os

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


def _database_url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is not set; PostgreSQL gate checks are skipped")
    return value


def test_postgresql_version_roles_and_migration_head() -> None:
    admin_url = _database_url("DATABASE_ADMIN_URL")
    runtime_url = _database_url("DATABASE_URL")
    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    runtime_engine = create_engine(runtime_url, pool_pre_ping=True)
    try:
        with admin_engine.connect() as connection:
            server_version = int(connection.execute(text("SHOW server_version_num")).scalar_one())
            admin_user = connection.execute(text("SELECT current_user")).scalar_one()
            database_heads = set(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
            runtime_role = connection.execute(
                text(
                    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolbypassrls "
                    "FROM pg_roles WHERE rolname = 'procurement_app'"
                )
            ).one()
            runtime_owned_tables = connection.execute(
                text(
                    "SELECT count(*) FROM pg_class "
                    "WHERE relkind IN ('r', 'p') "
                    "AND relnamespace = 'public'::regnamespace "
                    "AND pg_get_userbyid(relowner) = 'procurement_app'"
                )
            ).scalar_one()

        with runtime_engine.connect() as connection:
            runtime_user = connection.execute(text("SELECT current_user")).scalar_one()

        config = Config("alembic.ini")
        expected_heads = set(ScriptDirectory.from_config(config).get_heads())

        expected_major = int(os.environ.get("POSTGRES_EXPECTED_MAJOR", "16"))
        assert server_version // 10000 == expected_major
        assert admin_user != "procurement_app"
        assert runtime_user == "procurement_app"
        assert tuple(runtime_role) == (False, False, False, False, False)
        assert runtime_owned_tables == 0
        assert database_heads == expected_heads
    finally:
        runtime_engine.dispose()
        admin_engine.dispose()
