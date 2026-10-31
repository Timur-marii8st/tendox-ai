"""Seven-family additive planning and ZP provenance on isolated PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib import import_module
from uuid import uuid4

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from migration_support import assert_direct_downgrade_guard, historical_database
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from test_eis_223_index_pg import counts
from test_eis_223_index_pg import storage as pg_storage
from test_eis_223_regular_kesmbo_pg import DATABASE, OLD_WAVE, seed_old, snapshot

from procurement.storage.eis_223_index import (
    Eis223IndexConflict,
    bind_notice223_window,
    ingest_notice223_window,
    search_notice223_index,
)
from procurement.storage.eis_223_regions import (
    ensure_region_wave,
    read_region_coverage,
    regional_due_windows,
)
from procurement.storage.eis_223_sync import record_attempt, refresh_window_key
from procurement.storage.models import (
    eis_223_notice_versions as versions,
)
from procurement.storage.models import (
    eis_223_region_targets as targets,
)
from procurement.storage.models import (
    eis_223_region_waves as waves,
)
from procurement.storage.repository import PostgresStorage
from test_eis_223_archive import zip_bytes
from test_eis_223_index import URL, responses
from test_eis_223_regions import NOW
from test_eis_223_zpesmbo import FAMILY, NUMBER, REGIONAL, TARGETED, zp_ready, zp_xml

MIGRATION = "20261027_01_eis_223_regular_zpesmbo"


@pytest.fixture(scope="module")
def storage():
    yield from pg_storage.__wrapped__()


@pytest.mark.parametrize("families", [5, 6])
@pytest.mark.parametrize("fresh_first", [False, True])
def test_exact_legacy_scopes_append_once_preserving_frozen_dates_ordinals_history(
    storage, families, fresh_first
):
    company = "zp-wave-" + uuid4().hex
    sha, keys = seed_old(storage, company, families=families)
    before = snapshot(storage, company)

    def ensure(_):
        return ensure_region_wave(storage, company, NOW, actor_id="test", fresh_first=fresh_first)

    with ThreadPoolExecutor(max_workers=3) as executor:
        identities = tuple(executor.map(ensure, range(3)))
    assert len(set(identities)) == 1 and identities[0] != OLD_WAVE
    assert ensure(None) == identities[0]
    assert snapshot(storage, company) == before
    coverage = read_region_coverage(storage, company, now=NOW)
    assert coverage.wave_id == identities[0] and coverage.catalog_sha256 == sha
    assert (coverage.planned, coverage.attempted, coverage.no_data, coverage.unattempted) == (
        1260,
        families * 180,
        families * 180,
        (7 - families) * 180,
    )
    assert coverage.coverage == coverage.freshness == "UNKNOWN"
    due = regional_due_windows(storage, company, NOW, fresh_first=fresh_first)
    allowed = {FAMILY} if families == 6 else {FAMILY, "purchaseNoticeKESMBO"}
    assert len(due) == 32 and all(t.document_type in allowed for t in due)
    assert not set(keys).intersection(refresh_window_key(t) for t in due)
    with storage.transaction(company) as conn:
        rows = conn.execute(select(waves).order_by(waves.c.wave_id)).mappings().all()
        assert len(rows) == 2
        assert len({(r["start_day"], r["end_day"], r["created_at"]) for r in rows}) == 1
    assert read_region_coverage(storage, company + "-other", now=NOW).planned == 0


@pytest.mark.parametrize("families", [5, 6])
def test_partial_scope_is_never_repaired_or_rewritten(storage, families):
    company = "zp-partial-" + uuid4().hex
    seed_old(storage, company, families=families, partial=True, terminal=False)
    before = snapshot(storage, company)
    with pytest.raises(ValueError, match="REGIONAL_FAMILY_SCOPE_UNVERIFIED"):
        ensure_region_wave(storage, company, NOW, actor_id="test")
    assert snapshot(storage, company) == before
    with storage.transaction(company) as conn:
        assert conn.scalar(select(func.count()).select_from(waves)) == 1


@pytest.mark.parametrize("targeted_first", [False, True])
def test_targeted_then_regional_same_xml_preserves_canonical_source_and_search(
    storage, targeted_first
):
    company = "zp-intake-" + uuid4().hex
    targeted = zp_ready(targeted=targeted_first)
    first_key = TARGETED if targeted_first else REGIONAL
    first = ingest_notice223_window(storage, company, targeted, actor_id="test", now=NOW)
    assert first.new_versions == first.record_count == 4
    with storage.transaction(company) as conn:
        before = tuple(conn.execute(select(versions).order_by(versions.c.version_number)))
    assert ingest_notice223_window(storage, company, targeted, actor_id="test", now=NOW).replayed
    regional = zp_ready(targeted=not targeted_first)
    second = ingest_notice223_window(storage, company, regional, actor_id="223-refresh", now=NOW)
    assert second.record_count == 4 and second.new_versions == 0 and not second.replayed
    with storage.transaction(company) as conn:
        after = tuple(conn.execute(select(versions).order_by(versions.c.version_number)))
    assert before == after
    assert all(row.window_key == first_key for row in after)
    assert ingest_notice223_window(storage, company, regional, actor_id="test", now=NOW).replayed
    before_counts = counts(storage, company)
    initial, prepared = responses()
    conflict = bind_notice223_window(
        REGIONAL,
        replace(initial, source_sha256="e" * 64),
        prepared,
        {
            URL: zip_bytes(
                [
                    (
                        "zp-4.xml",
                        zp_xml(version=4).replace(
                            "Поставка бумаги".encode(), "Другая поставка".encode()
                        ),
                    )
                ]
            )
        },
    )
    with pytest.raises(Eis223IndexConflict, match="NOTICE_VERSION_CONFLICT"):
        ingest_notice223_window(storage, company, conflict, actor_id="test", now=NOW)
    assert counts(storage, company) == before_counts
    record_attempt(
        storage,
        company,
        REGIONAL,
        "SYNCED",
        actor_id="223-refresh",
        checked_at=NOW,
        response_sha256=zp_ready().response_sha256,
    )
    with pytest.raises(ValueError, match="ATTEMPT_SCOPE_INVALID"):
        record_attempt(
            storage,
            company,
            TARGETED,
            "SYNCED",
            actor_id="test",
            checked_at=NOW,
            response_sha256=targeted.response_sha256,
        )
    result = search_notice223_index(storage, company, NUMBER, now=NOW)
    assert len(result.matched) == 1
    lead = result.matched[0]
    assert lead.notice.document_type == FAMILY and lead.notice.version_number == 4
    assert lead.source_window == first_key
    assert lead.notice.deadline.value is None and lead.application_status == "UNKNOWN"
    assert result.coverage == result.economics_status == "UNKNOWN"
    assert not search_notice223_index(storage, company + "-other", NUMBER, now=NOW).matched


@pytest.mark.parametrize("kind", ["window", "snapshot", "attempt", "target", "wave-bounds"])
def test_all_new_evidence_and_planned_scope_block_cross_tenant_downgrade(storage, kind):
    with historical_database(expected_database=DATABASE, revision="20261027_03") as db:
        engine = create_engine(db.app_url)
        isolated = PostgresStorage(engine)
        try:
            company = "zp-guard-" + uuid4().hex
            if kind in ("window", "snapshot"):
                ingest_notice223_window(isolated, company, zp_ready(), actor_id="test", now=NOW)
            elif kind == "attempt":
                record_attempt(
                    isolated,
                    company,
                    REGIONAL,
                    "NO_DATA",
                    actor_id="test",
                    checked_at=NOW,
                    response_sha256="a" * 64,
                )
            else:
                sha, _ = seed_old(isolated, company, terminal=False)
                wave_id = str(uuid4())
                with isolated.transaction(company) as conn:
                    conn.execute(
                        insert(waves).values(
                            company_id=company,
                            wave_id=wave_id,
                            catalog_sha256=sha,
                            start_day=NOW.date(),
                            end_day=NOW.date(),
                            target_count=1 if kind == "target" else 1260,
                            created_at=NOW,
                        )
                    )
                    if kind == "target":
                        conn.execute(
                            insert(targets).values(
                                company_id=company,
                                wave_id=wave_id,
                                window_key=REGIONAL,
                                ordinal=0,
                            )
                        )
            # A snapshot has an obligatory FK to a ZP window; both are real here.
            # All five guard predicates are independently checked in the static review.
            assert_direct_downgrade_guard(
                MIGRATION,
                expected_database=db.name,
                expected_revision="20261027_03",
                match="223 ZPESMBO history and planned scope must be preserved",
                tenant_context="unrelated",
            )
        finally:
            engine.dispose()


def test_clean_roundtrip_preserves_old_six_and_all_five_checks_match_metadata(storage):
    from procurement.storage import models

    migration = import_module("migrations.versions." + MIGRATION)
    with historical_database(expected_database=DATABASE, revision="20261026_03") as db:
        admin = create_engine(db.admin_url)
        app = create_engine(db.app_url)
        isolated = PostgresStorage(app)
        try:
            # Early historical migrations bootstrap current metadata, so restore
            # all five pinned V52 preimages before exercising the new upgrade.
            with admin.begin() as conn:
                for table, name in migration.CHECKS:
                    conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                            f"CHECK ({migration.BEFORE[name]})"
                        )
                    )
            company = "zp-roundtrip-" + uuid4().hex
            seed_old(isolated, company, families=6)
            before = snapshot(isolated, company)
            command.upgrade(db.config, "20261027_01")
            assert snapshot(isolated, company) == before
            with admin.begin() as conn:
                for table, name in migration.CHECKS:
                    actual = conn.scalar(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname=:name"
                        ),
                        {"name": name},
                    )
                    check = next(
                        c for c in models.metadata.tables[table].constraints if c.name == name
                    )
                    assert str(check.sqltext) == migration.AFTER[name]
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD CONSTRAINT v54_metadata_check "
                            f"CHECK ({check.sqltext})"
                        )
                    )
                    compiled = conn.scalar(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname='v54_metadata_check'"
                        )
                    )
                    assert actual.removesuffix(" NOT VALID") == compiled
                    assert actual.endswith(" NOT VALID")
                    conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT v54_metadata_check"))
            command.downgrade(db.config, "20261026_03")
            assert snapshot(isolated, company) == before
            with admin.begin() as conn:
                for _table, name in migration.CHECKS:
                    actual = conn.scalar(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname=:name"
                        ),
                        {"name": name},
                    )
                    assert FAMILY not in actual and "1386" not in actual
            command.upgrade(db.config, "20261027_01")
        finally:
            app.dispose()
            admin.dispose()


def test_downgrade_without_all_tenant_visibility_fails_closed(storage):
    migration = import_module("migrations.versions." + MIGRATION)
    original = migration.op
    try:
        with storage._engine.connect() as conn:
            transaction = conn.begin()
            try:
                conn.execute(text("SELECT set_config('app.company_id', 'unrelated', true)"))
                migration.op = Operations(MigrationContext.configure(conn))
                with pytest.raises(DBAPIError, match="row-level security"):
                    migration.downgrade()
            finally:
                transaction.rollback()
    finally:
        migration.op = original


def _restore_validated_preimages(conn, migration):
    for table, name in migration.CHECKS:
        conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
        conn.execute(
            text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({migration.BEFORE[name]})")
        )


def _constraint_state(conn, migration):
    return tuple(
        conn.execute(
            text(
                "SELECT conname,convalidated,connoinherit,pg_get_expr(conbin,conrelid) "
                "FROM pg_constraint WHERE conrelid=to_regclass(:table) AND contype='c' "
                "ORDER BY conname"
            ),
            {"table": table},
        ).all()
        for table, _ in migration.CHECKS
    )


@pytest.mark.parametrize(
    "drift",
    [
        "definition",
        "not-valid",
        "after-not-valid",
        "missing",
        "temp",
        "child",
        "no-inherit",
        "wrong-type",
    ],
)
def test_upgrade_refuses_unproved_old_constraint_and_rolls_back(storage, drift):
    migration = import_module("migrations.versions." + MIGRATION)
    with historical_database(expected_database=DATABASE, revision="20261026_03") as db:
        admin = create_engine(db.admin_url)
        try:
            with admin.begin() as conn:
                _restore_validated_preimages(conn, migration)
                table, name = migration.CHECKS[1]
                if drift == "child":
                    conn.execute(text(f"CREATE TABLE v54_unexpected_child () INHERITS ({table})"))
                elif drift == "temp":
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD CONSTRAINT {name}_v54_before CHECK (true)")
                    )
                else:
                    conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
                    if drift == "wrong-type":
                        conn.execute(
                            text(f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE (company_id)")
                        )
                    elif drift != "missing":
                        expression = (
                            "true"
                            if drift == "definition"
                            else migration.AFTER[name]
                            if drift == "after-not-valid"
                            else migration.BEFORE[name]
                        )
                        suffix = (
                            " NOT VALID"
                            if drift in ("not-valid", "after-not-valid")
                            else " NO INHERIT"
                            if drift == "no-inherit"
                            else ""
                        )
                        conn.execute(
                            text(
                                f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                                f"CHECK ({expression}){suffix}"
                            )
                        )
                before = _constraint_state(conn, migration)
            with pytest.raises(RuntimeError, match="ZP_CHECK_PREIMAGE_UNVERIFIED"):
                command.upgrade(db.config, "20261027_01")
            with admin.connect() as conn:
                assert _constraint_state(conn, migration) == before
                assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261026_03"
        finally:
            admin.dispose()


def test_upgrade_partial_replacement_failure_is_transactional(storage, monkeypatch):
    migration = import_module("migrations.versions." + MIGRATION)
    with historical_database(expected_database=DATABASE, revision="20261026_03") as db:
        admin = create_engine(db.admin_url)
        try:
            with admin.begin() as conn:
                _restore_validated_preimages(conn, migration)
                before = _constraint_state(conn, migration)
            original = migration._replace_validated_check
            completed = []

            def interrupted(table, name):
                original(table, name)
                completed.append(name)
                if len(completed) == 2:
                    raise RuntimeError("injected replacement failure")

            monkeypatch.setattr(migration, "_replace_validated_check", interrupted)
            with admin.begin() as conn:
                transaction = conn.begin_nested()
                original_op = migration.op
                migration.op = Operations(MigrationContext.configure(conn))
                try:
                    with pytest.raises(RuntimeError, match="injected replacement failure"):
                        migration.upgrade()
                finally:
                    transaction.rollback()
                    migration.op = original_op
                assert len(completed) == 2
                assert _constraint_state(conn, migration) == before
                assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "20261026_03"
        finally:
            admin.dispose()


@pytest.mark.parametrize(
    "table,name",
    [
        ("eis_223_windows", "ck_eis_223_window"),
        ("eis_223_notice_versions", "ck_eis_223_snapshot_identity"),
        ("eis_223_sync_attempts", "ck_eis_223_attempt_scope"),
        ("eis_223_region_targets", "ck_eis_223_region_target_scope"),
        ("eis_223_region_waves", "ck_eis_223_region_wave_bounds"),
    ],
)
def test_not_valid_expansion_still_enforces_new_inserts_and_updates(storage, table, name):
    migration = import_module("migrations.versions." + MIGRATION)
    with historical_database(expected_database=DATABASE, revision="20261026_03") as db:
        admin = create_engine(db.admin_url)
        app = create_engine(db.app_url)
        isolated = PostgresStorage(app)
        try:
            with admin.begin() as conn:
                _restore_validated_preimages(conn, migration)
            command.upgrade(db.config, "20261027_01")
            with admin.connect() as conn:
                assert (
                    conn.scalar(
                        text(
                            "SELECT convalidated FROM pg_constraint "
                            "WHERE conrelid=to_regclass(:table) AND conname=:name"
                        ),
                        {"table": table, "name": name},
                    )
                    is False
                )
            company = "zp-enforcement-" + uuid4().hex
            seed_old(isolated, company, families=6)
            ingest_notice223_window(isolated, company, zp_ready(), actor_id="test", now=NOW)
            from procurement.storage import models

            target = models.metadata.tables[table]
            with isolated.transaction(company) as conn:
                row = dict(conn.execute(select(target).limit(1)).mappings().one())
            if table == "eis_223_notice_versions":
                row["version_number"] += 10000
                row["snapshot"] = dict(row["snapshot"], document_type="unsupported")
                change = "version_number = version_number + 10000"
            elif table == "eis_223_region_waves":
                row["wave_id"] = str(uuid4())
                row["target_count"] = 1387
                change = "target_count = 1387"
            else:
                row["window_key"] = "unsupported"
                change = "window_key = 'unsupported'"
                if table == "eis_223_sync_attempts":
                    row["attempt_id"] = str(uuid4())
            # UPDATE is forbidden even to the disposable DB owner by the
            # existing append-only trigger. Preserve that stronger guarantee.
            with pytest.raises(DBAPIError, match="append-only"), admin.begin() as conn:
                conn.execute(
                    text(f"UPDATE {table} SET {change} WHERE company_id=:company"),
                    {"company": company},
                )
            with pytest.raises(DBAPIError, match=name), isolated.transaction(company) as conn:
                conn.execute(insert(target).values(**row))

        finally:
            app.dispose()
            admin.dispose()


def test_exact_validated_after_bootstrap_remains_validated(storage):
    migration = import_module("migrations.versions." + MIGRATION)
    with historical_database(expected_database=DATABASE, revision="20261026_03") as db:
        admin = create_engine(db.admin_url)
        try:
            with admin.begin() as conn:
                for table, name in migration.CHECKS:
                    conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                            f"CHECK ({migration.AFTER[name]})"
                        )
                    )
                before = _constraint_state(conn, migration)
            command.upgrade(db.config, "20261027_01")
            with admin.connect() as conn:
                assert _constraint_state(conn, migration) == before
                assert all(row.convalidated for rows in before for row in rows)
        finally:
            admin.dispose()
