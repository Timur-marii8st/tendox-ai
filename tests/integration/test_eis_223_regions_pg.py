"""Real PostgreSQL retained regional backlog, RLS, dedup and downgrade guards."""

import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest
from migration_support import assert_direct_downgrade_guard
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from test_eis_223_index_pg import storage as pg_storage

from procurement.sources.eis_223_regions import REGION_SELECTOR_URL
from procurement.storage.eis_223_regions import (
    ensure_region_wave,
    read_region_coverage,
    regional_due_windows,
    register_region_catalog,
)
from procurement.storage.eis_223_sync import record_attempt, refresh_window_key
from procurement.storage.models import (
    eis_223_region_catalogs,
    eis_223_region_targets,
    eis_223_region_waves,
)
from test_eis_223_regions import NOW, catalog_html


@pytest.fixture(scope="module")
def storage():
    yield from pg_storage.__wrapped__()


def seed(storage, company, now=NOW):
    raw = catalog_html()
    register_region_catalog(
        storage,
        company,
        raw,
        source_url=REGION_SELECTOR_URL,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        observed_at=now,
        actor_id="test",
    )
    return ensure_region_wave(storage, company, now, actor_id="test")


def attempt(storage, company, target, now=NOW, outcome="NO_DATA"):
    record_attempt(
        storage,
        company,
        refresh_window_key(target),
        outcome,
        actor_id="test",
        checked_at=now,
        response_sha256="a" * 64,
        reason="SYNTHETIC" if outcome == "FAILED" else None,
    )


def test_catalog_replay_and_rls_immutable_full_wave(storage):
    company = "regions-" + uuid4().hex
    wave = seed(storage, company)
    assert seed(storage, company) == wave
    status = read_region_coverage(storage, company, now=NOW)
    assert (status.catalog_regions, status.planned, status.unattempted) == (3, 30, 30)
    assert status.observation_watermark is None and status.freshness == "UNKNOWN"
    other = read_region_coverage(storage, "other-" + uuid4().hex, now=NOW)
    assert other.planned == 0
    for table in (eis_223_region_catalogs, eis_223_region_waves, eis_223_region_targets):
        for statement in (delete(table), update(table).values(company_id="changed")):
            with pytest.raises(DBAPIError), storage.transaction(company) as conn:
                conn.execute(statement)


def test_midnight_restart_retains_unseen_and_early_retry_survives_partial_batch(storage):
    company = "fair-regions-" + uuid4().hex
    wave = seed(storage, company)
    first = regional_due_windows(storage, company, NOW)
    assert len(first) == 30 and [t.region for t in first[:6:2]] == ["50", "77", "78"]
    attempt(storage, company, first[0], outcome="FAILED")
    later = NOW + timedelta(days=3)
    assert ensure_region_wave(storage, company, later, actor_id="test") == wave
    due = regional_due_windows(storage, company, later, limit=2)
    assert due == (
        first[0],
        first[1],
    )  # retry actually starts before the deadline can truncate batch
    status = read_region_coverage(storage, company, now=later)
    assert (status.failed, status.unattempted, status.source_day_lag) == (1, 29, 3)
    assert status.oldest_gap_day.isoformat() == "2026-10-02"
    with pytest.raises(ValueError, match="REGIONAL_BATCH_INVALID"):
        regional_due_windows(storage, company, later, limit=1)


def test_failed_gap_does_not_freeze_new_wave_and_catchup_does_not_skip_days(storage):
    company = "advance-regions-" + uuid4().hex
    first_wave = seed(storage, company)
    first = regional_due_windows(storage, company, NOW)
    for index, target in enumerate(first):
        attempt(storage, company, target, outcome="FAILED" if index == 0 else "NO_DATA")
    assert regional_due_windows(storage, company, NOW + timedelta(minutes=59)) == ()
    later = NOW + timedelta(days=4)
    second = ensure_region_wave(storage, company, later, actor_id="test")
    assert second != first_wave
    status = read_region_coverage(storage, company, now=later)
    assert (status.start_day.isoformat(), status.end_day.isoformat()) == (
        "2026-10-04",
        "2026-10-05",
    )
    assert (status.old_gaps, status.source_day_lag) == (1, 2)
    assert regional_due_windows(storage, company, later, limit=2)[0] == first[0]


def test_exact_terminal_scope_has_oldest_watermark_but_never_full_eis_claim(storage):
    company = "complete-regions-" + uuid4().hex
    seed(storage, company)
    for index, target in enumerate(regional_due_windows(storage, company, NOW)):
        attempt(storage, company, target, now=NOW + timedelta(seconds=index))
    result = read_region_coverage(storage, company, now=NOW + timedelta(minutes=1))
    assert result.scope_status == "COMPLETE" and result.no_data == 30
    assert result.regions_terminal == 3 and result.observation_watermark == NOW
    assert result.first_sweep_finished and result.coverage == result.freshness == "UNKNOWN"


def test_same_notice_across_regions_deduplicates_business_version_preserves_source_receipts(
    storage,
):
    from procurement.storage.eis_223_index import ingest_notice223_window
    from procurement.storage.models import (
        eis_223_archive_sources,
        eis_223_notice_versions,
        eis_223_windows,
    )
    from test_eis_223_index import window

    company = "dedup-regions-" + uuid4().hex
    first = window()
    second = first.model_copy(
        update={
            "window_key": first.window_key.replace("/50/", "/77/"),
            "response_sha256": "c" * 64,
        }
    )
    assert ingest_notice223_window(storage, company, first, actor_id="test").new_versions == 1
    assert ingest_notice223_window(storage, company, second, actor_id="test").new_versions == 0
    for ready in (first, second):
        record_attempt(
            storage,
            company,
            ready.window_key,
            "SYNCED",
            actor_id="test",
            checked_at=NOW,
            response_sha256=ready.response_sha256,
        )
    with storage.transaction(company) as conn:
        counts = tuple(
            conn.scalar(select(func.count()).select_from(t))
            for t in (eis_223_notice_versions, eis_223_windows, eis_223_archive_sources)
        )
    assert counts == (1, 2, 2)


def test_regional_history_blocks_downgrade_even_outside_current_tenant(storage):
    company = "regions-downgrade-" + uuid4().hex
    seed(storage, company)
    before = read_region_coverage(storage, company, now=NOW)
    assert_direct_downgrade_guard(
        "20261003_04_eis_223_regions",
        expected_database="procurement_eis_test_20261005_s209",
        match="region plan or non-50 source history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    assert read_region_coverage(storage, company, now=NOW) == before


def test_early_fresh_and_retry_slots_precede_unseen_without_duplicates(storage):
    company = "fresh-lane-" + uuid4().hex
    seed(storage, company)
    first = regional_due_windows(storage, company, NOW)
    attempt(storage, company, first[0])
    attempt(storage, company, first[1], outcome="FAILED")
    later = NOW + timedelta(hours=6)
    due = regional_due_windows(storage, company, later, limit=3)
    assert due == (first[0], first[1], first[2])
    assert regional_due_windows(storage, company, later, limit=2) == (first[1], first[2])
    all_due = regional_due_windows(storage, company, later)
    assert len(all_due) == len(set(refresh_window_key(t) for t in all_due)) == 30


def test_finished_wave_advances_at_moscow_midnight_before_24h_without_skipping(storage):
    company = "midnight-fresh-" + uuid4().hex
    first_wave = seed(storage, company)
    for target in regional_due_windows(storage, company, NOW):
        attempt(storage, company, target)
    later = NOW + timedelta(hours=3)  # 00:00 MSK, only three hours since creation.
    second = ensure_region_wave(storage, company, later, actor_id="test")
    assert second != first_wave
    state = read_region_coverage(storage, company, now=later)
    assert state.start_day.isoformat() == "2026-10-03" and state.end_day.isoformat() == "2026-10-04"
    assert (
        ensure_region_wave(storage, company, later + timedelta(minutes=1), actor_id="test")
        == second
    )
