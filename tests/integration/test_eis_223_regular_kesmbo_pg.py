"""Additive regional KES admission and retained five-family history on isolated PG."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from alembic import command
from migration_support import assert_direct_downgrade_guard, historical_database
from sqlalchemy import create_engine, func, insert, select, text
from test_eis_223_index_pg import counts
from test_eis_223_index_pg import storage as pg_storage

from procurement.sources.eis_223_regions import REGION_SELECTOR_URL
from procurement.storage.eis_223_index import (
    Eis223IndexConflict,
    ingest_notice223_window,
    search_notice223_index,
)
from procurement.storage.eis_223_regions import (
    ensure_region_wave,
    plan_targets,
    read_region_coverage,
    regional_due_windows,
    register_region_catalog,
)
from procurement.storage.eis_223_sync import record_attempt, refresh_window_key
from procurement.storage.models import (
    audit_events,
    eis_223_event_sync_attempts,
    eis_223_lot_event_sync_attempts,
    eis_223_sync_attempts,
)
from procurement.storage.models import (
    eis_223_region_targets as targets,
)
from procurement.storage.models import (
    eis_223_region_waves as waves,
)
from procurement.storage.repository import PostgresStorage
from test_eis_223_archive import zip_bytes
from test_eis_223_regions import NOW, catalog_html
from test_eis_223_regular_kesmbo import REGIONAL_KEY, regional_window
from test_eis_223_targeted_kesmbo import kesmbo_xml

OLD_WAVE = "ffffffff-ffff-4fff-bfff-ffffffffffff"
MIGRATION = "20261026_03_eis_223_regular_kesmbo"
DATABASE = "procurement_eis_test_20261005_s209"


@pytest.fixture(scope="module")
def storage():
    yield from pg_storage.__wrapped__()


def seed_old(storage, company, *, partial=False, terminal=True, families=5):
    regions = tuple(f"{i:02}" for i in range(1, 91))
    raw = catalog_html(regions)
    sha = register_region_catalog(
        storage,
        company,
        raw,
        source_url=REGION_SELECTOR_URL,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        observed_at=NOW,
        actor_id="test",
    )
    keys = tuple(
        refresh_window_key(t)
        for t in plan_targets(regions, NOW.date() - timedelta(days=1), NOW.date())
        if t.document_type != "purchaseNoticeZPESMBO"
        and (families == 6 or t.document_type != "purchaseNoticeKESMBO")
    )
    assert families in (5, 6) and len(keys) == 180 * families
    if partial:
        keys = keys[:-1]
    with storage.transaction(company) as conn:
        conn.execute(
            insert(waves).values(
                company_id=company,
                wave_id=OLD_WAVE,
                catalog_sha256=sha,
                start_day=NOW.date() - timedelta(days=1),
                end_day=NOW.date(),
                target_count=len(keys),
                created_at=NOW,
            )
        )
        # Different valid ordinals must not make exact set recognition fail.
        conn.execute(
            insert(targets),
            [
                dict(company_id=company, wave_id=OLD_WAVE, window_key=k, ordinal=i)
                for i, k in enumerate(reversed(keys))
            ],
        )
        if terminal:
            for table, family in (
                (eis_223_sync_attempts, None),
                (eis_223_event_sync_attempts, "purchaseRejection"),
                (eis_223_lot_event_sync_attempts, "purchaseLotCancellation"),
            ):
                selected = [
                    k
                    for k in keys
                    if (
                        k.endswith("/" + family)
                        if family
                        else not k.endswith(("/purchaseRejection", "/purchaseLotCancellation"))
                    )
                ]
                conn.execute(
                    insert(table),
                    [
                        dict(
                            company_id=company,
                            attempt_id=str(uuid4()),
                            window_key=k,
                            status="NO_DATA",
                            response_sha256="a" * 64,
                            checkpoint_response_sha256=None,
                            reason=None,
                            checked_at=NOW,
                        )
                        for k in selected
                    ],
                )
    return sha, keys


def snapshot(storage, company):
    with storage.transaction(company) as conn:
        old = tuple(
            conn.execute(
                select(targets.c.window_key, targets.c.ordinal)
                .where(targets.c.wave_id == OLD_WAVE)
                .order_by(targets.c.ordinal)
            )
        )
        attempts = tuple(
            tuple(conn.execute(select(t).order_by(t.c.attempt_id)))
            for t in (
                eis_223_sync_attempts,
                eis_223_event_sync_attempts,
                eis_223_lot_event_sync_attempts,
            )
        )
    return old, attempts


@pytest.mark.parametrize("fresh_first", [False, True])
def test_old900_append1080_same_now_concurrent_idempotent_history_reuse(storage, fresh_first):
    company = "kes-wave-" + uuid4().hex
    sha, keys = seed_old(storage, company)
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
        900,
        900,
        360,
    )
    assert coverage.coverage == coverage.freshness == "UNKNOWN"
    due = regional_due_windows(storage, company, NOW, fresh_first=fresh_first)
    assert len(due) == 32 and all(
        t.document_type in ("purchaseNoticeKESMBO", "purchaseNoticeZPESMBO") for t in due
    )
    assert not set(keys).intersection(refresh_window_key(t) for t in due)
    with storage.transaction(company) as conn:
        assert conn.scalar(select(func.count()).select_from(waves)) == 2
        event = conn.execute(
            select(audit_events.c.basis).where(
                audit_events.c.event_type == "EIS_223_REGIONAL_WAVE_CREATED"
            )
        ).scalar_one()
        assert event["predecessor_wave_id"] == OLD_WAVE
        assert event["previous_target_count"] == 900
    assert read_region_coverage(storage, company + "-other", now=NOW).planned == 0


@pytest.mark.parametrize("invalid", ["partial", "changed-catalog"])
def test_unverified_old_scope_never_silently_repairs_or_appends(storage, invalid):
    company = "kes-unverified-" + uuid4().hex
    seed_old(storage, company, partial=invalid == "partial", terminal=False)
    if invalid == "changed-catalog":
        raw = catalog_html(("01", "02"))
        register_region_catalog(
            storage,
            company,
            raw,
            source_url=REGION_SELECTOR_URL,
            response_sha256=hashlib.sha256(raw).hexdigest(),
            observed_at=NOW + timedelta(seconds=1),
            actor_id="test",
        )
    before = snapshot(storage, company)
    with pytest.raises(ValueError, match="REGIONAL_FAMILY_SCOPE_UNVERIFIED"):
        ensure_region_wave(storage, company, NOW, actor_id="test", fresh_first=True)
    assert snapshot(storage, company) == before
    with storage.transaction(company) as conn:
        assert conn.scalar(select(func.count()).select_from(waves)) == 1


def test_regular_authenticated_intake_replay_conflict_checkpoint_search_and_rls(storage):
    company = "kes-intake-" + uuid4().hex
    ready = regional_window()
    report = ingest_notice223_window(storage, company, ready, actor_id="test", now=NOW)
    assert report.new_versions == report.record_count == 1
    before = counts(storage, company)
    assert ingest_notice223_window(storage, company, ready, actor_id="test", now=NOW).replayed
    assert counts(storage, company) == before
    with pytest.raises(Eis223IndexConflict):
        ingest_notice223_window(
            storage,
            company,
            ready.model_copy(
                update={
                    "archives": (
                        zip_bytes(
                            [
                                (
                                    "kesmbo.xml",
                                    kesmbo_xml().replace(
                                        "Поставка бумаги".encode(),
                                        "Другая поставка бумаги".encode(),
                                    ),
                                )
                            ]
                        ),
                    )
                }
            ),
            actor_id="test",
            now=NOW,
        )
    assert counts(storage, company) == before
    record_attempt(
        storage,
        company,
        REGIONAL_KEY,
        "SYNCED",
        actor_id="test",
        checked_at=NOW,
        response_sha256=ready.response_sha256,
    )
    result = search_notice223_index(storage, company, "бумага", now=NOW)
    assert len(result.matched) == 1
    assert result.matched[0].notice.document_type == "purchaseNoticeKESMBO"
    assert result.matched[0].notice.deadline.value is None
    assert result.coverage == result.economics_status == "UNKNOWN"
    assert not search_notice223_index(storage, company + "-other", "бумага", now=NOW).matched


@pytest.mark.parametrize("kind", ["window", "attempt", "target", "wave-bounds"])
def test_new_regular_history_blocks_cross_tenant_downgrade(storage, kind):
    with historical_database(expected_database=DATABASE, revision="20261027_03") as db:
        engine = create_engine(db.app_url)
        isolated = PostgresStorage(engine)
        try:
            company = "kes-guard-" + uuid4().hex
            if kind == "window":
                ingest_notice223_window(
                    isolated, company, regional_window(), actor_id="test", now=NOW
                )
            elif kind == "attempt":
                record_attempt(
                    isolated,
                    company,
                    REGIONAL_KEY,
                    "NO_DATA",
                    actor_id="test",
                    checked_at=NOW,
                    response_sha256="a" * 64,
                )
            else:
                sha, _ = seed_old(isolated, company, terminal=False)
                if kind == "target":
                    # Test historical03 policy independently of the current planner.
                    wave_id = str(uuid4())
                    with isolated.transaction(company) as conn:
                        conn.execute(
                            insert(waves).values(
                                company_id=company,
                                wave_id=wave_id,
                                catalog_sha256=sha,
                                start_day=NOW.date(),
                                end_day=NOW.date(),
                                target_count=1,
                                created_at=NOW,
                            )
                        )
                        conn.execute(
                            insert(targets).values(
                                company_id=company,
                                wave_id=wave_id,
                                window_key=REGIONAL_KEY,
                                ordinal=0,
                            )
                        )
                else:
                    with isolated.transaction(company) as conn:
                        conn.execute(
                            insert(waves).values(
                                company_id=company,
                                wave_id=str(uuid4()),
                                catalog_sha256=sha,
                                start_day=NOW.date() - timedelta(days=1),
                                end_day=NOW.date(),
                                target_count=1080,
                                created_at=NOW,
                            )
                        )
            assert_direct_downgrade_guard(
                MIGRATION,
                expected_database=db.name,
                expected_revision="20261027_03",
                match="223 regular KESMBO history must be preserved",
                tenant_context="unrelated",
            )
        finally:
            engine.dispose()


def test_migration_clean_roundtrip_and_additive_metadata_constraints(storage):
    from procurement.storage import models

    migration = import_module("migrations.versions." + MIGRATION)
    accepted_v52 = import_module("migrations.versions.20261027_01_eis_223_regular_zpesmbo")
    with historical_database(expected_database=DATABASE, revision="20261026_02") as db:
        # Historical bootstrap migrations copy current metadata. Restore the
        # captured pre-V52 CHECKs explicitly before testing this upgrade.
        schema_engine = create_engine(db.admin_url)
        try:
            with schema_engine.begin() as conn:
                for table, name in migration.CHECKS:
                    conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                            f"CHECK ({migration.BEFORE[name]})"
                        )
                    )
        finally:
            schema_engine.dispose()
        old_engine = create_engine(db.app_url)
        old_storage = PostgresStorage(old_engine)
        company = "old-migration-" + uuid4().hex
        try:
            seed_old(old_storage, company)
            before = snapshot(old_storage, company)
            command.upgrade(db.config, "20261026_03")
            assert snapshot(old_storage, company) == before
        finally:
            old_engine.dispose()
        engine = create_engine(db.admin_url)
        try:
            with engine.begin() as conn:
                names = (
                    "ck_eis_223_window",
                    "ck_eis_223_attempt_scope",
                    "ck_eis_223_region_target_scope",
                    "ck_eis_223_region_wave_bounds",
                )
                for name in names:
                    actual = conn.scalar(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname=:name"
                        ),
                        {"name": name},
                    )
                    assert actual is not None
                    if name == names[-1]:
                        assert "1188" in actual
                    else:
                        assert "purchaseNoticeKESMBO" in actual
                    metadata_check = next(
                        c
                        for t in models.metadata.tables.values()
                        for c in t.constraints
                        if c.name == name
                    )
                    table = metadata_check.table.name
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD CONSTRAINT v52_metadata_check "
                            f"CHECK ({accepted_v52.BEFORE[name]})"
                        )
                    )
                    compiled = conn.scalar(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname='v52_metadata_check'"
                        )
                    )
                    assert actual == compiled
                    conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT v52_metadata_check"))
            command.downgrade(db.config, "20261026_02")
            command.upgrade(db.config, "20261026_03")
        finally:
            engine.dispose()
