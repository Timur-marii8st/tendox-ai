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
from procurement.storage.eis_223_sync import MSK, record_attempt, refresh_window_key
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


def test_shared_fresh_turn_fills_repeat_slots_and_retains_old_history(storage):
    company = "shared-fresh-" + uuid4().hex
    seed(storage, company)
    first = regional_due_windows(storage, company, NOW)
    for target in first:
        attempt(storage, company, target)
    later = NOW + timedelta(hours=6)
    due = regional_due_windows(storage, company, later, limit=32, fresh_first=True, fresh_only=True)
    # All fifteen current-day coordinates are due, not the previous four-slot cap.
    assert len(due) >= 15
    assert all(t.day >= later.astimezone(MSK).date() - timedelta(days=1) for t in due)
    attempt(storage, company, first[0], outcome="FAILED")
    retried = regional_due_windows(
        storage, company, later, limit=32, fresh_first=True, fresh_only=True
    )
    assert retried[0] == first[0]  # A full recheck lane cannot starve a failed coordinate.
    old_keys = {refresh_window_key(t) for t in first}
    ensure_region_wave(
        storage, company, later + timedelta(days=8), actor_id="test", fresh_first=True
    )
    new = regional_due_windows(
        storage, company, later + timedelta(days=8), limit=32, fresh_first=True, fresh_only=True
    )
    assert not old_keys.intersection(refresh_window_key(t) for t in new)
    restart = later + timedelta(days=8)
    for target in new:
        attempt(storage, company, target, now=restart)
    residual = regional_due_windows(storage, company, restart, limit=32, fresh_first=True)
    assert old_keys.intersection(refresh_window_key(t) for t in residual)
    with storage.transaction(company) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_223_region_targets)
                .where(
                    eis_223_region_targets.c.company_id == company,
                    eis_223_region_targets.c.window_key.in_(old_keys),
                )
            )
            == 30
        )


def test_fresh_first_calendar_does_not_wait_for_old_wave_and_retains_date_gaps(storage):
    company = "fresh-regions-" + uuid4().hex
    first_wave = seed(storage, company)
    first = regional_due_windows(storage, company, NOW)
    attempt(storage, company, first[0], outcome="FAILED")
    later = NOW + timedelta(days=8)
    latest_wave = ensure_region_wave(storage, company, later, actor_id="test", fresh_first=True)
    assert latest_wave != first_wave
    coverage = read_region_coverage(storage, company, now=later)
    assert coverage.end_day == later.astimezone(MSK).date()
    due = regional_due_windows(storage, company, later, limit=2, fresh_first=True)
    assert all(t.day == coverage.end_day for t in due)
    # Subsequent bounded calls materialize missing calendar pairs. Creating a
    # historical repair wave must never replace today's current wave.
    for _ in range(4):
        ensure_region_wave(storage, company, later, actor_id="test", fresh_first=True)
        assert read_region_coverage(storage, company, now=later).end_day == coverage.end_day
    with storage.transaction(company) as conn:
        intervals = conn.execute(
            select(eis_223_region_waves.c.start_day, eis_223_region_waves.c.end_day).where(
                eis_223_region_waves.c.company_id == company
            )
        ).all()
        assert (
            conn.scalar(
                select(func.count())
                .select_from(eis_223_region_targets)
                .where(
                    eis_223_region_targets.c.company_id == company,
                    eis_223_region_targets.c.wave_id == first_wave,
                )
            )
            == 30
        )
    covered = {d for start, end in intervals for d in (start, end)}
    assert all((NOW.date() - timedelta(days=1) + timedelta(days=i)) in covered for i in range(10))


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


@pytest.mark.parametrize("outcome", ["NO_DATA", "FAILED"])
def test_outage223_final_day_outside_pair_is_mandatory_and_tenant_scoped(storage, outcome):
    from datetime import UTC, datetime

    company = "mandatory223-" + uuid4().hex
    old = datetime(2026, 10, 9, 10, tzinfo=UTC)
    seed(storage, company, old)
    prior = regional_due_windows(storage, company, old, limit=32, fresh_first=True)
    target = next(t for t in prior if t.day == old.astimezone(MSK).date())
    attempt(storage, company, target, now=old, outcome=outcome)
    now = old + timedelta(days=3)
    ensure_region_wave(storage, company, now, actor_id="test", fresh_first=True)
    current = regional_due_windows(storage, company, now, fresh_first=True, fresh_only=True)
    assert target not in current
    recovery = regional_due_windows(storage, company, now, fresh_first=True, recovery_only=True)
    assert target in recovery
    # Another tenant's terminal evidence cannot acknowledge this coordinate.
    seed(storage, company + "-foreign", old)
    attempt(storage, company + "-foreign", target, now=now)
    assert target in regional_due_windows(
        storage, company, now, fresh_first=True, recovery_only=True
    )
    attempt(storage, company, target, now=now)
    restarted = regional_due_windows(storage, company, now, fresh_first=True, recovery_only=True)
    assert target not in restarted


def test_recovery223_keeps_old_unobserved_history_in_original_lane(storage):
    from datetime import UTC, datetime

    company = "old-history223-" + uuid4().hex
    old = datetime(2026, 9, 1, 10, tzinfo=UTC)
    seed(storage, company, old)
    prior = regional_due_windows(storage, company, old, fresh_first=True)
    oldkeys = {refresh_window_key(x) for x in prior}
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    ensure_region_wave(storage, company, now, actor_id="test", fresh_first=True)
    due = regional_due_windows(storage, company, now, fresh_first=True, recovery_only=True)
    assert not oldkeys.intersection(refresh_window_key(x) for x in due)


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"fresh_first": True},
        {"fresh_first": True, "fresh_only": True},
        {"fresh_first": True, "recovery_only": True},
    ],
    ids=["legacy", "fresh-first", "fresh-only", "recovery-only"],
)
def test_materialized_history_preserves_dispatch_order_and_tenant_scope(
    storage, monkeypatch, options
):
    from datetime import UTC, datetime

    from procurement.storage import eis_223_regions as regions

    company = "dispatch-plan-" + uuid4().hex
    now = datetime(2026, 10, 12, 10, tzinfo=UTC)
    old = now - timedelta(days=3)
    seed(storage, company, old)
    history = regional_due_windows(storage, company, old, fresh_first=True)
    for index, target in enumerate(history):
        attempt(storage, company, target, now=old, outcome="FAILED" if index == 0 else "NO_DATA")
    ensure_region_wave(storage, company, now, actor_id="test", fresh_first=True)
    current = regions.plan_targets(
        ("50", "77", "78"),
        now.astimezone(MSK).date() - timedelta(days=1),
        now.astimezone(MSK).date(),
    )
    for target in current[:5]:
        checked = now - timedelta(hours=2)
        attempt(storage, company, target, now=checked)
        attempt(storage, company, target, now=checked, outcome="FAILED")
        attempt(storage, company, target, now=checked)
    seed(storage, company + "-foreign", now)
    for target in current:
        attempt(storage, company + "-foreign", target, now=now)

    actual = regional_due_windows(storage, company, now, limit=32, **options)
    materialized = regions._latest
    # Compare the exact former SELECT on identical persisted evidence, rather
    # than maintaining a second implementation of queue selection in the test.
    with monkeypatch.context() as patch:
        patch.setattr(regions, "_latest", lambda tenant: materialized(tenant).element.subquery())
        previous = regional_due_windows(storage, company, now, limit=32, **options)
    assert actual == previous
    assert actual
    assert len(actual) == len({refresh_window_key(target) for target in actual})


def test_materialized_history_keeps_failure_ties_and_newer_terminal_evidence(storage):
    from procurement.storage import eis_223_regions as regions

    company = "history-ties-" + uuid4().hex
    seed(storage, company)
    planned = regional_due_windows(storage, company, NOW)
    selected = [
        next(target for target in planned if refresh_window_key(target).endswith("/" + family))
        for family in regions.FAMILIES
    ]
    for target in selected:
        attempt(storage, company, target)
        attempt(storage, company, target, outcome="FAILED")
        attempt(storage, company, target)
        attempt(storage, company + "-foreign", target, now=NOW + timedelta(minutes=1))

    def statuses():
        latest = regions._latest(company)
        with storage.transaction(company, consistent_read=True) as conn:
            return dict(conn.execute(select(latest.c.window_key, latest.c.status)).all())

    keys = {refresh_window_key(target) for target in selected}
    assert statuses() == dict.fromkeys(keys, "FAILED")
    for target in selected:
        attempt(storage, company, target, now=NOW + timedelta(minutes=1))
    assert statuses() == dict.fromkeys(keys, "NO_DATA")


def test_recent_daily_reconciliation_is_selected_before_current_day(storage):
    company = "protected-daily-" + uuid4().hex
    seed(storage, company)
    due = regional_due_windows(
        storage, company, NOW, limit=32, fresh_first=True, reconciliation_only=True
    )
    assert due
    assert all(
        NOW.astimezone(MSK).date() - timedelta(days=3) <= t.day < NOW.astimezone(MSK).date()
        for t in due
    )
    current = regional_due_windows(
        storage, company, NOW, limit=32, fresh_first=True, fresh_only=True
    )
    assert any(t.day == NOW.astimezone(MSK).date() for t in current)
    assert (
        regional_due_windows(
            storage, company + "-other", NOW, limit=2, fresh_first=True, reconciliation_only=True
        )
        == ()
    )


def test_host_probe_recent_demand_matches_selection_without_history_scan(storage, monkeypatch):
    from test_eis_223_probe_reconciliation import module

    m = module()
    company = "recent-probe-" + uuid4().hex
    monkeypatch.setattr(m, "COMPANY", company)
    seed(storage, company)
    assert m.recent_reconciliation_due(storage, NOW)
    recent = regional_due_windows(
        storage, company, NOW, limit=32, fresh_first=True, reconciliation_only=True
    )
    assert recent
    for t in recent:
        attempt(storage, company, t)
    assert not m.recent_reconciliation_due(storage, NOW)
    # Empty foreign/catalog state is uncertainty, never an idle declaration.
    monkeypatch.setattr(m, "COMPANY", company + "-foreign")
    with pytest.raises(ValueError, match="OFFICIAL_REGION_CATALOG_MISSING"):
        m.recent_reconciliation_due(storage, NOW)


def test_host_probe_recent_failure_keeps_existing_one_hour_cooldown(storage, monkeypatch):
    from test_eis_223_probe_reconciliation import module

    m = module()
    company = "recent-retry-" + uuid4().hex
    monkeypatch.setattr(m, "COMPANY", company)
    seed(storage, company)
    recent = regional_due_windows(
        storage, company, NOW, limit=32, fresh_first=True, reconciliation_only=True
    )
    assert recent
    for t in recent[1:]:
        attempt(storage, company, t)
    attempt(storage, company, recent[0], now=NOW - timedelta(minutes=59), outcome="FAILED")
    assert not m.recent_reconciliation_due(storage, NOW)
    assert m.recent_reconciliation_due(storage, NOW + timedelta(minutes=1))


@pytest.mark.parametrize("limit", [2, 32])
@pytest.mark.parametrize("mode", ["recovery_only", "reconciliation_only"])
def test_dispatch_filters_keep_retry_and_final_day_debt_tenant_scoped(storage, limit, mode):
    from datetime import UTC, datetime

    from procurement.storage import eis_223_regions as regions

    company = "dispatch-fence-" + uuid4().hex
    now = datetime(2026, 10, 24, 12, tzinfo=UTC)
    prior = now - timedelta(days=2)
    seed(storage, company, prior)
    targets = regions.plan_targets(
        ("50", "77", "78"),
        prior.astimezone(MSK).date() - timedelta(days=1),
        prior.astimezone(MSK).date(),
    )
    # All historical windows are final except one failed retry and one early
    # terminal response. Foreign later successes must not discharge either debt.
    retry, early = targets[:2]
    for target in targets:
        checked = prior - timedelta(days=1) if target == early else now - timedelta(hours=2)
        attempt(
            storage,
            company,
            target,
            now=checked,
            outcome="FAILED" if target == retry else "NO_DATA",
        )
        attempt(storage, company + "-foreign", target, now=now)
    ensure_region_wave(storage, company, now, actor_id="test", fresh_first=True)
    for target in regions.plan_targets(
        ("50", "77", "78"),
        now.astimezone(MSK).date() - timedelta(days=1),
        now.astimezone(MSK).date(),
    ):
        attempt(storage, company, target, now=now - timedelta(hours=1))
    result = regional_due_windows(
        storage, company, now, limit=limit, fresh_first=True, **{mode: True}
    )
    assert result == (retry, early)
    assert (
        regional_due_windows(
            storage, company + "-foreign", now, limit=limit, fresh_first=True, **{mode: True}
        )
        == ()
    )
    attempt(storage, company, retry, now=now)
    attempt(storage, company, early, now=now)
    assert (
        regional_due_windows(storage, company, now, limit=limit, fresh_first=True, **{mode: True})
        == ()
    )


@pytest.mark.parametrize(
    "family", ["purchaseNoticeAESMBO", "purchaseRejection", "purchaseLotCancellation"]
)
@pytest.mark.parametrize("phase", ["INITIAL", "PREPARED", "WSDL", "SOAP", "ARCHIVE"])
def test_source_error_codes_persist_with_audit_and_tenant_scope(storage, family, phase):
    from procurement.sources.eis_feed_sync import EisSourceError
    from procurement.storage.models import (
        audit_events,
        eis_223_event_sync_attempts,
        eis_223_lot_event_sync_attempts,
        eis_223_sync_attempts,
    )

    company = "source-code-" + uuid4().hex
    table = {
        "purchaseNoticeAESMBO": eis_223_sync_attempts,
        "purchaseRejection": eis_223_event_sync_attempts,
        "purchaseLotCancellation": eis_223_lot_event_sync_attempts,
    }[family]
    service = phase in {"INITIAL", "PREPARED"}
    detail = (
        EisSourceError(phase, service_code=13)
        if service
        else EisSourceError(phase, http_status=503, category="HTTP_STATUS")
    )
    reason = detail.persisted_reason("SERVICE_ERROR" if service else "SOURCE_RESPONSE_REJECTED")
    record_attempt(
        storage,
        company,
        f"getDocsIP/RI223/50/2026-10-01+03:00/{family}",
        "SERVICE_ERROR" if service else "FAILED",
        actor_id="test",
        checked_at=NOW,
        response_sha256="a" * 64 if service else None,
        reason=reason,
    )
    with storage.transaction(company) as conn:
        assert conn.scalar(select(table.c.reason).where(table.c.company_id == company)) == reason
        basis = conn.scalar(
            select(audit_events.c.basis).where(audit_events.c.company_id == company)
        )
        assert basis["reason"] == reason
    with storage.transaction("foreign-" + uuid4().hex) as conn:
        assert (
            conn.scalar(
                select(func.count()).select_from(table).where(table.c.company_id == company)
            )
            == 0
        )
