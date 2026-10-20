"""Fail-closed helpers for historical migration checks on disposable PostgreSQL."""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
HISTORICAL_DATABASE_PREFIX = "procurement_migration_test_"


@dataclass(frozen=True)
class HistoricalDatabase:
    name: str
    admin_url: str
    app_url: str
    config: Config


def _render(url: URL) -> str:
    return url.render_as_string(hide_password=False)


def _validated_gate_urls(expected_database: str) -> tuple[URL, URL]:
    if os.environ.get("QUALITY_GATE_DISPOSABLE_POSTGRES") != "1":
        pytest.fail("historical migration checks require QUALITY_GATE_DISPOSABLE_POSTGRES=1")
    values = []
    for variable in ("DATABASE_URL", "DATABASE_ADMIN_URL"):
        raw = os.environ.get(variable)
        if not raw:
            pytest.fail(f"historical migration checks require {variable}")
        url = make_url(raw)
        if (
            url.drivername not in {"postgresql", "postgresql+psycopg"}
            or url.host not in LOCAL_HOSTS
            or url.port is None
            or url.database != expected_database
            or url.query
        ):
            pytest.fail(
                f"{variable} must target the exact local disposable database "
                f"{expected_database!r} without query overrides"
            )
        values.append(url)
    app_url, admin_url = values
    if (app_url.host, app_url.port, app_url.database) != (
        admin_url.host,
        admin_url.port,
        admin_url.database,
    ):
        pytest.fail("historical migration URLs must target the same local endpoint")
    if app_url.username != "procurement_app" or admin_url.username != "procurement_owner":
        pytest.fail("historical migration checks require the dedicated gate roles")
    return app_url, admin_url


def _latest_head() -> str:
    config = Config("alembic.ini")
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        pytest.fail("Alembic migration history has no head")
    return head


def assert_direct_downgrade_guard(
    migration_stem: str,
    *,
    expected_database: str,
    match: str,
    tenant_context: str | None = None,
) -> None:
    """Execute one old downgrade guard without traversing newer irreversible revisions."""

    _, admin_url = _validated_gate_urls(expected_database)
    module = importlib.import_module(f"migrations.versions.{migration_stem}")
    engine = create_engine(admin_url, pool_pre_ping=True)
    declared_head = _latest_head()
    original_op = module.op
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                original_revision = connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                assert original_revision == declared_head
                if tenant_context is not None:
                    connection.execute(
                        text("SELECT set_config('app.company_id', :company, true)"),
                        {"company": tenant_context},
                    )
                module.op = Operations(MigrationContext.configure(connection))
                with pytest.raises(DBAPIError, match=match):
                    module.downgrade()
            finally:
                module.op = original_op
                transaction.rollback()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                original_revision
            )
    finally:
        module.op = original_op
        engine.dispose()


def _generated_database(revision: str) -> str:
    suffix = re.sub(r"[^a-z0-9]+", "_", revision.lower()).strip("_")
    name = f"{HISTORICAL_DATABASE_PREFIX}{suffix}_{uuid4().hex[:10]}"
    if len(name) > 63 or not re.fullmatch(r"[a-z0-9_]+", name):
        pytest.fail("generated historical database name is unsafe")
    return name


def _assert_owned_database_name(database: str) -> None:
    if (
        not database.startswith(HISTORICAL_DATABASE_PREFIX)
        or len(database) > 63
        or not re.fullmatch(r"[a-z0-9_]+", database)
    ):
        pytest.fail("historical database name is outside the task-owned prefix")


@contextmanager
def historical_database(
    *,
    expected_database: str,
    revision: str,
) -> Iterator[HistoricalDatabase]:
    """Create a unique DB migrated only to ``revision`` and drop that exact DB afterward."""

    app_url, admin_url = _validated_gate_urls(expected_database)
    database = _generated_database(revision)
    _assert_owned_database_name(database)
    historical_admin = admin_url.set(database=database)
    historical_app = app_url.set(database=database)
    maintenance = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    created = False
    previous = {
        variable: os.environ.get(variable)
        for variable in ("DATABASE_URL", "DATABASE_ADMIN_URL")
    }
    primary_error: BaseException | None = None
    try:
        with maintenance.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == "procurement_owner"
            connection.execute(text(f'CREATE DATABASE "{database}" OWNER procurement_owner'))
        created = True
        os.environ["DATABASE_URL"] = _render(historical_app)
        os.environ["DATABASE_ADMIN_URL"] = _render(historical_admin)
        config = Config("alembic.ini")
        command.upgrade(config, revision)
        engine = create_engine(historical_admin)
        try:
            with engine.connect() as connection:
                assert (
                    connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
                )
        finally:
            engine.dispose()
        yield HistoricalDatabase(
            name=database,
            admin_url=_render(historical_admin),
            app_url=_render(historical_app),
            config=config,
        )
    except BaseException as error:
        primary_error = error
        raise
    finally:
        for variable, value in previous.items():
            if value is None:
                os.environ.pop(variable, None)
            else:
                os.environ[variable] = value
        try:
            if created:
                _assert_owned_database_name(database)
                try:
                    with maintenance.connect() as connection:
                        connection.execute(
                            text(
                                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                                "WHERE datname=:database AND pid <> pg_backend_pid()"
                            ),
                            {"database": database},
                        )
                        connection.execute(text(f'DROP DATABASE "{database}"'))
                except BaseException as cleanup_error:
                    if primary_error is None:
                        raise
                    primary_error.add_note(
                        f"historical database cleanup also failed: {cleanup_error!r}"
                    )
        finally:
            maintenance.dispose()
