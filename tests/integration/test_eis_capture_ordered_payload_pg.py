"""Isolated PostgreSQL equivalence for narrow-key, late-payload capture SQL."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import (
    Column,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    create_engine,
    insert,
    text,
)
from sqlalchemy.engine import make_url

from procurement.sources.eis_search_capture import encode_row, load_capture_plan
from procurement.storage import eis_search_capture as capture

ROOT = Path(__file__).resolve().parents[2]


def test_lateral_payload_keeps_rls_unicode_versions_bytes_and_repeatable_snapshot(
    monkeypatch, record_property
):
    app_url, admin_url = os.environ.get("DATABASE_URL"), os.environ.get("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL acceptance requires both gate database URLs")
    app_identity, admin_identity = make_url(app_url), make_url(admin_url)
    assert app_identity.database == admin_identity.database
    assert "procurement_eis_test_" in (app_identity.database or "")
    app, admin = create_engine(app_url), create_engine(admin_url)
    schema = "capture_lateral_" + uuid4().hex
    tenant, foreign = "lateral-own", "lateral-foreign"
    plan, _ = load_capture_plan(ROOT / "scripts/benchmarks/eis-search-capture-plan.v3.json")
    spec = next(r for r in plan.relations if r.name == "eis_notice_versions")
    source_table = capture._table(spec.name)
    metadata = MetaData(schema=schema)
    table = Table(
        spec.name,
        metadata,
        *[
            Column(
                c.name,
                Text()
                if c.name in spec.primary_key and c.kind == "TEXT"
                else source_table.c[c.name].type.copy(),
                nullable=c.nullable,
            )
            for c in spec.columns
        ],
        PrimaryKeyConstraint(*spec.primary_key),
    )
    quote = admin.dialect.identifier_preparer.quote
    qualified = quote(schema) + "." + quote(spec.name)
    created = False
    try:
        with app.connect() as connection:
            role, superuser, bypass = connection.execute(
                text(
                    "SELECT current_user,r.rolsuper,r.rolbypassrls FROM pg_roles r "
                    "WHERE r.rolname=current_user"
                )
            ).one()
            assert not superuser and not bypass
        with admin.begin() as connection:
            assert connection.scalar(text("SELECT current_user")) == "procurement_owner"
            # Alpine supplies ICU locales; glibc installations may supply libc locales.
            # Require a real non-C English locale, never silently weaken the fixture to C.
            collation = connection.scalar(
                text(
                    "SELECT c.collname FROM pg_collation c "
                    "JOIN pg_namespace n ON n.oid=c.collnamespace "
                    "WHERE n.nspname='pg_catalog' "
                    "AND c.collisdeterministic AND c.collencoding IN (-1,6) "
                    "AND c.collname IN ('en_US.utf8','en-US-x-icu') "
                    "ORDER BY CASE c.collname WHEN 'en_US.utf8' THEN 0 ELSE 1 END LIMIT 1"
                )
            )
            assert collation in {"en_US.utf8", "en-US-x-icu"}
            for column in spec.columns:
                if column.name in spec.primary_key and column.kind == "TEXT":
                    table.c[column.name].type.collation = collation
            record_property("fixture_collation", collation)
            record_property("postgres_version", connection.scalar(text("SHOW server_version")))
            connection.exec_driver_sql("CREATE SCHEMA " + quote(schema))
            created = True
            metadata.create_all(connection)
            connection.exec_driver_sql("ALTER TABLE " + qualified + " ENABLE ROW LEVEL SECURITY")
            connection.exec_driver_sql("ALTER TABLE " + qualified + " FORCE ROW LEVEL SECURITY")
            connection.exec_driver_sql(
                "CREATE POLICY tenant_rows ON "
                + qualified
                + " USING (company_id=current_setting('app.company_id',true)) "
                "WITH CHECK (company_id=current_setting('app.company_id',true))"
            )
            connection.exec_driver_sql(
                "GRANT USAGE ON SCHEMA " + quote(schema) + " TO " + quote(role)
            )
            connection.exec_driver_sql("GRANT SELECT ON " + qualified + " TO " + quote(role))
        numbers = ["a", "A", "\u0451", "\u0435", "\u00e9", "e\u0301", "\u0411", "\U0001f600"]
        expected_keys = sorted(
            [(number, version) for number in numbers for version in (1, 2)],
            key=lambda key: (key[0].encode("utf8"), key[1]),
        )
        for company in (tenant, foreign):
            rows = []
            for number, version in expected_keys:
                row = {}
                for column in spec.columns:
                    row[column.name] = (
                        None
                        if column.nullable
                        else {"text": "Ð±ÑƒÐ¼Ð°Ð³Ð°ðŸ˜€\n", "dense": [0] * 20000}
                        if column.kind == "JSON"
                        else version
                        if column.kind == "INTEGER"
                        else Decimal("1.20")
                        if column.kind == "DECIMAL"
                        else datetime(2026, 10, 8, tzinfo=UTC)
                        if column.kind == "DATETIME"
                        else "a" * 64
                        if "sha256" in column.name
                        else "synthetic"
                    )
                row.update(company_id=company, purchase_number=number, version_number=version)
                rows.append(row)
            with admin.begin() as connection:
                connection.execute(
                    text("SELECT set_config('app.company_id',:tenant,true)"), {"tenant": company}
                )
                connection.execute(insert(table), rows)
        monkeypatch.setattr(
            capture, "_table", lambda name: table if name == spec.name else source_table
        )
        selection = capture._selection(spec, tenant)
        old = capture._ordered_capture_statement(spec, selection, version3=False)
        new = capture._ordered_capture_statement(spec, selection, version3=True)

        def read(connection, statement):
            with connection.execution_options(stream_results=True, yield_per=2).execute(
                statement
            ) as result:
                return [capture._normalize_row(spec, row) for row in result.mappings()]

        with (
            app.connect().execution_options(isolation_level="REPEATABLE READ") as connection,
            connection.begin(),
        ):
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql("SET LOCAL statement_timeout='30000ms'")
            connection.exec_driver_sql("SET LOCAL lock_timeout='1000ms'")
            connection.execute(
                text("SELECT set_config('app.company_id',:tenant,true)"), {"tenant": tenant}
            )
            baseline = read(connection, old)
            locale_order = read(
                connection, selection.order_by(*(table.c[name] for name in spec.primary_key))
            )
            assert [
                (r["purchase_number"], r["version_number"]) for r in locale_order
            ] != expected_keys
            # A committed later update must not change this capture transaction.
            with admin.begin() as later:
                later.execute(
                    text("SELECT set_config('app.company_id',:tenant,true)"), {"tenant": tenant}
                )
                later.execute(
                    table.update().where(table.c.company_id == tenant).values(title="later")
                )
            candidate = read(connection, new)
            assert len(candidate) == len(baseline) == 16
            assert [(r["purchase_number"], r["version_number"]) for r in candidate] == expected_keys
            assert all(r["company_id"] == tenant and r["title"] != "later" for r in candidate)
            old_bytes = [encode_row(spec, row) for row in baseline]
            new_bytes = [encode_row(spec, row) for row in candidate]
            assert old_bytes == new_bytes
            record_property("ordered_rows", len(candidate))
            record_property(
                "ordered_canonical_sha256", hashlib.sha256(b"".join(new_bytes)).hexdigest()
            )
            assert (
                hashlib.sha256(b"".join(old_bytes)).digest()
                == hashlib.sha256(b"".join(new_bytes)).digest()
            )
            # Timeout statements must not open portals or alter the live payload cursor.
            nonstream = {"stream_results": False, "yield_per": None}

            def portal_count():
                with connection.execute(
                    text("SELECT count(*) FROM pg_cursors"), execution_options=nonstream
                ) as portals:
                    return portals.scalar_one()

            budget = capture._PackageBudget(plan, time.monotonic())
            with connection.execution_options(stream_results=True, yield_per=2).execute(
                new
            ) as live:
                options = dict(connection.get_execution_options())
                assert options["stream_results"] and options["yield_per"] == 2
                assert portal_count() == 1
                iterator = iter(live.mappings())
                observed_rows = []
                for _ in range(3):
                    capture._bound_statement_timeout(connection, budget)
                    assert dict(connection.get_execution_options()) == options
                    assert not live.closed and portal_count() == 1
                    with connection.execute(
                        text("SELECT current_setting('statement_timeout')"),
                        execution_options=nonstream,
                    ) as timeout_setting:
                        assert timeout_setting.scalar_one() == "30s"
                    observed_rows.append(capture._normalize_row(spec, next(iterator)))
                observed_rows.extend(capture._normalize_row(spec, row) for row in iterator)
                assert [encode_row(spec, row) for row in observed_rows] == old_bytes
            assert portal_count() == 0
            record_property("timeout_calls_with_live_cursor", 3)
            record_property("portals_during_payload", 1)
            record_property("portals_after_payload_close", 0)
            connection.execution_options(stream_results=False, yield_per=None)
            for difference in (
                old.order_by(None).except_all(new.order_by(None)),
                new.order_by(None).except_all(old.order_by(None)),
            ):
                with connection.execute(difference.limit(1)) as result:
                    assert result.first() is None
            # Even a forged explicit foreign selection is blocked by RLS.
            with connection.execute(capture._selection(spec, foreign)) as result:
                assert result.first() is None
        with app.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.company_id',:tenant,true)"), {"tenant": tenant}
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM " + qualified + " WHERE title='later'")
                )
                == 16
            )
    finally:
        if created:
            assert schema.startswith("capture_lateral_") and schema != "public"
            with admin.begin() as connection:
                connection.exec_driver_sql("DROP SCHEMA " + quote(schema) + " CASCADE")
        app.dispose()
        admin.dispose()
