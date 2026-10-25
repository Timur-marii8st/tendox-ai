"""Read-only fairness gate on an explicitly isolated PostgreSQL database."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.exc import IntegrityError

from procurement.sources.eis_corpus import eligible_windows
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.models import (
    audit_events,
    eis_feed_windows,
    eis_sync_attempts,
    eis_sync_targets,
)
from procurement.storage.repository import PostgresStorage

NOW = datetime(2026, 10, 3, 9, tzinfo=UTC)  # 12:00 in Europe/Moscow.


@pytest.fixture(scope="module")
def storage() -> PostgresStorage:
    app_url, admin_url = os.getenv("DATABASE_URL"), os.getenv("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL credentials required")
    if "procurement_eis_test_" not in app_url or "procurement_eis_test_" not in admin_url:
        pytest.fail("corpus fairness gate requires explicitly isolated test database")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", admin_url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(app_url, pool_pre_ping=True)
    try:
        yield PostgresStorage(engine)
    finally:
        engine.dispose()


def _key(region: int, day: str, kind: str = "epNotificationEF2020") -> str:
    suffix = "" if kind == "epNotificationEF2020" else f"/{kind}"
    return f"getDocsIP/PRIZ/{region:02d}/{day}+03:00{suffix}"


def _target(company: str, key: str) -> dict[str, object]:
    return {
        "company_id": company,
        "window_key": key,
        "planned_by": "test",
        "planned_at": NOW - timedelta(days=30),
        "coverage": "UNKNOWN",
    }


def _attempt(
    company: str,
    key: str,
    outcome: str,
    at: datetime,
) -> dict[str, object]:
    return {
        "company_id": company,
        "attempt_id": str(uuid.uuid4()),
        "window_key": key,
        "actor_id": "test",
        "outcome": outcome,
        "reason_code": "SOURCE_FAILURE" if outcome == "FAILED" else None,
        "source_response_sha256": "a" * 64 if outcome == "NO_DATA" else None,
        "attempted_at": at,
    }


def _counts(storage: PostgresStorage, company: str) -> tuple[int, ...]:
    with storage.transaction(company, consistent_read=True) as connection:
        return tuple(
            connection.scalar(
                select(func.count()).select_from(table).where(table.c.company_id == company)
            )
            for table in (eis_sync_targets, eis_sync_attempts, eis_feed_windows, audit_events)
        )


def test_history_admission_order_and_concurrent_persisted_request(storage, monkeypatch, tmp_path):
    import asyncio
    import fcntl
    import hashlib
    import time
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import AsyncMock, Mock

    from procurement import eis_freshness_dispatch_cli as dispatch
    from procurement.sources import eis_corpus
    from procurement.sources.eis_223_regions import REGION_SELECTOR_URL
    from procurement.storage.eis_223_regions import register_region_catalog
    from procurement.storage.eis_freshness_requests import (
        EisRefreshRequestPayload,
        plan_refresh_request,
    )
    from test_eis_223_regions import catalog_html

    now = datetime.now(UTC)
    company, other = ("admission-" + uuid.uuid4().hex for _ in range(2))
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
    # Isolate the real persisted foreground lane; no baseline/regional work in this scenario.
    monkeypatch.setattr(dispatch, "resource_gate", lambda *_a, **_k: None)
    monkeypatch.setattr(dispatch, "read_due_freshness", lambda *_a, **_k: ())
    monkeypatch.setattr(dispatch, "_regional_demand", lambda *_a, **_k: (0, False))
    payload = EisRefreshRequestPayload(query="test", regions=("50",))
    plan_refresh_request(storage, other, payload, actor_id="test", now=now)
    journal = EisSyncJournal(storage, company, "test")
    before = _counts(storage, company)
    source = AsyncMock()
    monkeypatch.setattr(eis_corpus, "sync_eis_window", source)
    selected = []

    def selection(*_a, **_k):
        # Reached only if the other tenant's persisted request did not block admission.
        selected.append(True)
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(
                plan_refresh_request, storage, company, payload, actor_id="concurrent", now=now
            ).result(timeout=10)
        return (_key(50, "2026-10-02"),)

    monkeypatch.setattr(eis_corpus, "eligible_windows", selection)
    lease = tmp_path / "import.lock"
    with lease.open("ab") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with lease.open("ab") as contender, pytest.raises(BlockingIOError):
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = asyncio.run(
            eis_corpus.run_corpus(
                journal, "no-source", now=now, mandatory_fresh_first=True, transport=object()
            )
        )
    assert selected == [True]
    assert report["reason"] == "MANDATORY_FRESH_WORK_READY" and report["attempted"] == 0
    source.assert_not_awaited()
    after = _counts(storage, company)
    assert after[:3] == before[:3] and after[3] == before[3] + 1  # Concurrent request audit only.

    expensive = Mock(side_effect=AssertionError("existing debt must precede history selection"))
    monkeypatch.setattr(eis_corpus, "eligible_windows", expensive)
    started = time.monotonic()
    with lease.open("ab") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        report = asyncio.run(
            eis_corpus.run_corpus(
                journal, "no-source", now=now, mandatory_fresh_first=True, transport=object()
            )
        )
    blocked_seconds = time.monotonic() - started
    print(f"existing_debt_lease_hold_seconds={blocked_seconds:.6f}")
    assert blocked_seconds < 2  # The previous ~30s eligibility work must be excluded.
    expensive.assert_not_called()
    assert report["selected"] == report["attempted"] == 0
    assert report["reason"] == "MANDATORY_FRESH_WORK_READY"
    assert _counts(storage, company) == after
    with lease.open("ab") as contender:
        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)  # A waiting fresh worker can proceed.


def test_recent_failure_lane_is_bounded_due_latest_tenant_scoped_and_read_only(
    storage: PostgresStorage,
) -> None:
    company = f"corpus-fair-{uuid.uuid4().hex}"
    other = f"corpus-fair-{uuid.uuid4().hex}"
    backlog = tuple(
        _key(
            (index % 99) + 1,
            f"2026-{7 + index // 99:02d}-{index % 28 + 1:02d}",
        )
        for index in range(140)
    )
    recent = tuple(_key(index + 1, "2026-10-02") for index in range(15))
    latest_not_failed = _key(30, "2026-10-01")
    cooling_down = _key(31, "2026-10-01")
    completed = _key(32, "2026-10-01")
    old_failed = _key(33, "2026-09-25")
    other_failed = _key(34, "2026-10-02")
    future_latest = _key(35, "2026-10-01")
    tenant_keys = (
        *backlog,
        *recent,
        latest_not_failed,
        cooling_down,
        completed,
        old_failed,
        future_latest,
    )

    with storage.transaction(company) as connection:
        connection.execute(insert(eis_sync_targets), [_target(company, key) for key in tenant_keys])
        attempts = [
            _attempt(company, key, "FAILED", NOW - timedelta(hours=40 - index))
            for index, key in enumerate(recent)
        ]
        attempts.extend(
            (
                _attempt(company, latest_not_failed, "FAILED", NOW - timedelta(hours=50)),
                _attempt(company, latest_not_failed, "NO_DATA", NOW - timedelta(hours=30)),
                _attempt(company, cooling_down, "FAILED", NOW - timedelta(hours=23)),
                _attempt(company, completed, "FAILED", NOW - timedelta(hours=30)),
                _attempt(company, old_failed, "FAILED", NOW - timedelta(hours=60)),
                _attempt(company, future_latest, "FAILED", NOW - timedelta(hours=50)),
                _attempt(company, future_latest, "NO_DATA", NOW + timedelta(hours=1)),
            )
        )
        connection.execute(insert(eis_sync_attempts), attempts)
        connection.execute(
            insert(eis_feed_windows).values(
                company_id=company,
                window_key=completed,
                response_sha256="b" * 64,
                manifest_sha256="c" * 64,
                archive_count=1,
                notice_count=0,
                coverage="UNKNOWN",
                ingested_at=NOW - timedelta(hours=29),
            )
        )
    with storage.transaction(other) as connection:
        connection.execute(
            insert(eis_sync_targets),
            [_target(other, other_failed), _target(other, backlog[0])],
        )
        connection.execute(
            insert(eis_sync_attempts),
            [
                _attempt(other, other_failed, "FAILED", NOW - timedelta(hours=40)),
                _attempt(other, backlog[0], "NO_DATA", NOW + timedelta(hours=2)),
            ],
        )

    journal = EisSyncJournal(storage, company, "worker")
    before = _counts(storage, company)
    selected = eligible_windows(journal, now=NOW, limit=10)
    selected_again = eligible_windows(journal, now=NOW, limit=10)

    # Two repair slots: one evidenced empty recheck, then one failed repair.
    assert selected[:2] == (latest_not_failed, recent[0])
    assert selected == selected_again and len(selected) == 10 and len(set(selected)) == 10
    assert all(key in backlog for key in selected[2:])
    assert not {cooling_down, completed, old_failed, other_failed} & set(selected[:2])
    assert _counts(storage, company) == before

    one = eligible_windows(journal, now=NOW, limit=1)
    assert len(one) == 1 and one[0] in backlog

    capped = eligible_windows(journal, now=NOW, limit=100)
    assert capped[:12] == (latest_not_failed, *recent[:11])
    assert all(key in backlog for key in capped[12:])
    assert len(capped) == len(set(capped)) == 100
    assert _counts(storage, company) == before

    complete_queue = eligible_windows(journal, now=NOW, limit=1000)
    assert backlog[0] in complete_queue  # Other tenant's future attempt cannot affect this tenant.
    assert latest_not_failed in complete_queue and old_failed in complete_queue
    assert not {cooling_down, completed, future_latest, other_failed} & set(complete_queue)
    assert len(complete_queue) == 157
    assert _counts(storage, company) == before


@pytest.mark.parametrize("active", [False, True])
def test_no_data_recheck_reserve_does_not_starve_failure_history_or_new_dates(storage, active):
    company = f"empty-fair-{uuid.uuid4().hex}"
    old = tuple(_key(i, "2026-08-01") for i in range(1, 80))
    new = tuple(_key(i, "2026-10-02", "epNotificationEOK2020") for i in range(1, 80))
    failed = tuple(_key(i, "2026-10-02") for i in range(1, 16))
    empty = tuple(_key(i, "2026-09-30", "epNotificationCancel") for i in range(1, 9))
    retry = tuple(_key(i, "2026-09-20") for i in range(1, 7))
    with storage.transaction(company) as conn:
        keys = (*old, *failed, *empty, *retry, *(new if active else ()))
        conn.execute(insert(eis_sync_targets), [_target(company, k) for k in keys])
        conn.execute(
            insert(eis_sync_attempts),
            [
                *[_attempt(company, k, "FAILED", NOW - timedelta(hours=30)) for k in failed],
                *[
                    _attempt(company, k, "NO_DATA", NOW - timedelta(hours=50 - i))
                    for i, k in enumerate(empty)
                ],
                *[_attempt(company, k, "SERVICE_ERROR", NOW - timedelta(hours=40)) for k in retry],
            ],
        )
    before = _counts(storage, company)
    selected = eligible_windows(EisSyncJournal(storage, company, "test"), now=NOW, limit=60)
    assert len(selected) == len(set(selected)) == 60
    assert tuple(k for k in selected if k in empty) == empty[:3]
    assert tuple(k for k in selected if k in failed) == failed[:9]
    assert tuple(k for k in selected if k in retry) == retry[:3]
    assert len(set(selected) & set(old)) == (9 if active else 45)
    if active:
        assert selected[:2] == (old[0], new[0])
        assert selected[:6] == (old[0], *new[:4], empty[0])
        assert len(set(selected) & set(new)) == 36
    else:
        assert selected[:3] == empty[:3]
    assert _counts(storage, company) == before


def test_no_data_latest_tie_proof_canonical_and_completed_moscow_date_gates(storage):
    company, other = (f"empty-gates-{uuid.uuid4().hex}" for _ in range(2))
    old = tuple(_key(i, "2026-08-01") for i in range(1, 80))
    good = _key(1, "2026-10-02")
    replaced = _key(2, "2026-10-02")
    future = _key(3, "2026-10-02")
    cooling = _key(4, "2026-10-02")
    boundary = _key(5, "2026-10-02")
    canonical = _key(6, "2026-10-02")
    transport = _key(7, "2026-10-02")
    unproved = _key(8, "2026-10-02")
    bad_sha = _key(9, "2026-10-02")
    missing_plan = _key(10, "2026-10-02")
    outside = _key(11, "2026-09-25")
    current = _key(12, "2026-10-03")
    other_key = _key(13, "2026-10-02")
    tied_failed = _key(14, "2026-10-02")
    tied_empty = _key(15, "2026-10-02")
    malformed_date = _key(16, "2026-02-30")
    with storage.transaction(company) as conn:
        keys = (
            good,
            replaced,
            future,
            cooling,
            boundary,
            canonical,
            transport,
            unproved,
            bad_sha,
            outside,
            current,
            tied_failed,
            tied_empty,
            malformed_date,
        )
        conn.execute(insert(eis_sync_targets), [_target(company, k) for k in (*old, *keys)])
        attempts = [_attempt(company, k, "NO_DATA", NOW - timedelta(hours=30)) for k in keys]
        attempts[0]["attempted_at"] = NOW - timedelta(hours=55)
        attempts[2]["attempted_at"] = NOW + timedelta(hours=1)
        attempts[3]["attempted_at"] = NOW - timedelta(hours=24) + timedelta(microseconds=1)
        attempts[4]["attempted_at"] = NOW - timedelta(hours=24)
        attempts[6]["attempted_at"] = NOW - timedelta(hours=50)
        # DB constraints forbid unproved NO_DATA. Other source states remain unresolved.
        for index in (7, 8):
            attempts[index]["outcome"] = "PREPARING"
            attempts[index]["attempted_at"] = NOW
            attempts[index]["source_response_sha256"] = None
        for k in (tied_failed, tied_empty):
            item = next(a for a in attempts if a["window_key"] == k)
            item["attempt_id"] = (
                "00000000-0000-0000-0000-000000000001"
                if k == tied_failed
                else "00000000-0000-0000-0000-000000000004"
            )
        tie = _attempt(company, tied_failed, "FAILED", NOW - timedelta(hours=30))
        tie["attempt_id"] = "00000000-0000-0000-0000-000000000002"
        replace_tie = _attempt(company, tied_empty, "FAILED", NOW - timedelta(hours=30))
        replace_tie["attempt_id"] = "00000000-0000-0000-0000-000000000003"
        attempts.extend(
            [
                tie,
                replace_tie,
                _attempt(company, replaced, "SYNCED", NOW - timedelta(hours=29)),
            ]
        )
        conn.execute(insert(eis_sync_attempts), attempts)
        for k, kind in ((canonical, "LEGACY_CANONICAL"), (transport, "VARIANT_TRANSPORT")):
            conn.execute(
                insert(eis_feed_windows).values(
                    company_id=company,
                    window_key=k,
                    response_sha256="b" * 64,
                    manifest_sha256="c" * 64,
                    archive_count=1,
                    notice_count=0,
                    coverage="UNKNOWN",
                    intake_kind=kind,
                    ingested_at=NOW - timedelta(hours=31),
                )
            )
    with storage.transaction(other) as conn:
        conn.execute(insert(eis_sync_targets), [_target(other, good), _target(other, other_key)])
        conn.execute(
            insert(eis_sync_attempts),
            [
                _attempt(other, good, "NO_DATA", NOW + timedelta(hours=1)),
                _attempt(other, other_key, "NO_DATA", NOW - timedelta(hours=70)),
            ],
        )
    journal = EisSyncJournal(storage, company, "test")
    for sha in (None, "INVALID"):
        unproved_attempt = _attempt(company, unproved, "NO_DATA", NOW - timedelta(hours=60))
        unproved_attempt["source_response_sha256"] = sha
        with pytest.raises(IntegrityError), storage.transaction(company) as conn:
            conn.execute(insert(eis_sync_attempts), [unproved_attempt])
    with pytest.raises(IntegrityError), storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_attempts),
            [
                _attempt(company, missing_plan, "NO_DATA", NOW - timedelta(hours=60)),
            ],
        )
    before = _counts(storage, company)
    selected = eligible_windows(journal, now=NOW, limit=60)
    # The old NO_DATA now has its own early slot; the recent reserve remains three.
    assert selected[:4] == (outside, good, transport, tied_empty)
    assert selected[4] == tied_failed
    assert len(set(selected)) == len(selected) == 60
    assert not {
        replaced,
        future,
        cooling,
        canonical,
        unproved,
        bad_sha,
        missing_plan,
        current,
        other_key,
        malformed_date,
    } & set(selected[1:4])
    assert _counts(storage, company) == before
    # Boundary becomes third slot once the older transport observation cools down.
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_attempts),
            [_attempt(company, k, "NO_DATA", NOW) for k in (outside, good, transport, tied_empty)],
        )
    assert eligible_windows(journal, now=NOW, limit=60)[0] == boundary


def test_no_data_recheck_outcome_resets_cooldown_and_canonical_stops_further_rechecks(storage):
    company = f"empty-transition-{uuid.uuid4().hex}"
    key = _key(77, "2026-10-02")
    old = tuple(_key(i, "2026-08-01") for i in range(1, 80))
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_sync_targets), [_target(company, k) for k in (*old, key)])
        conn.execute(
            insert(eis_sync_attempts),
            [
                _attempt(company, key, "NO_DATA", NOW - timedelta(hours=30)),
            ],
        )
    journal = EisSyncJournal(storage, company, "test")
    assert eligible_windows(journal, now=NOW, limit=60)[0] == key
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_sync_attempts), [_attempt(company, key, "NO_DATA", NOW)])
    assert key not in eligible_windows(
        journal, now=NOW + timedelta(hours=24, microseconds=-1), limit=60
    )
    assert eligible_windows(journal, now=NOW + timedelta(hours=24), limit=60)[0] == key
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_feed_windows).values(
                company_id=company,
                window_key=key,
                response_sha256="b" * 64,
                manifest_sha256="c" * 64,
                archive_count=1,
                notice_count=0,
                coverage="UNKNOWN",
                ingested_at=NOW + timedelta(hours=24),
            )
        )
    assert key not in eligible_windows(journal, now=NOW + timedelta(hours=48), limit=60)


@pytest.mark.parametrize(
    "limit,empty_cap,failed_cap",
    [(1, 0, 0), (2, 0, 1), (5, 0, 1), (6, 1, 1), (10, 1, 1), (20, 1, 3), (60, 3, 9), (100, 3, 9)],
)
def test_no_data_quota_uses_existing_repair_capacity_and_reserves_failure_slot(
    storage, limit, empty_cap, failed_cap
):
    company = f"empty-small-{uuid.uuid4().hex}"
    old = tuple(
        _key(
            i % 99 + 1, "2026-08-01", "epNotificationCancel" if i >= 99 else "epNotificationEF2020"
        )
        for i in range(149)
    )
    empty = tuple(_key(i, "2026-10-02") for i in range(1, 8))
    failed = tuple(_key(i, "2026-10-01") for i in range(1, 16))
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_targets), [_target(company, k) for k in (*old, *empty, *failed)]
        )
        conn.execute(
            insert(eis_sync_attempts),
            [
                *[_attempt(company, k, "NO_DATA", NOW - timedelta(hours=30)) for k in empty],
                *[_attempt(company, k, "FAILED", NOW - timedelta(hours=30)) for k in failed],
            ],
        )
    selected = eligible_windows(EisSyncJournal(storage, company, "test"), now=NOW, limit=limit)
    assert len(selected) == len(set(selected)) == limit
    assert len(set(selected) & set(empty)) == empty_cap
    assert len(set(selected) & set(failed)) == failed_cap


def test_zero_and_insufficient_reserve_fill_with_moscow_boundary_and_stable_tie(
    storage: PostgresStorage,
) -> None:
    midnight_moscow = datetime(2026, 10, 2, 21, tzinfo=UTC)
    zero_company = f"corpus-zero-{uuid.uuid4().hex}"
    zero_backlog = tuple(_key(index + 1, "2026-08-01") for index in range(8))
    with storage.transaction(zero_company) as connection:
        connection.execute(
            insert(eis_sync_targets),
            [_target(zero_company, key) for key in zero_backlog],
        )
    zero = eligible_windows(
        EisSyncJournal(storage, zero_company, "worker"),
        now=midnight_moscow,
        limit=5,
    )
    assert zero == zero_backlog[:5]

    company = f"corpus-partial-{uuid.uuid4().hex}"
    backlog = tuple(_key(index + 1, "2026-08-02") for index in range(25))
    # 2026-09-26 is the inclusive lower boundary at 2026-10-03 00:00 Moscow.
    tied = tuple(sorted((_key(92, "2026-09-26"), _key(91, "2026-09-26"))))
    outside = _key(93, "2026-09-25")
    with storage.transaction(company) as connection:
        connection.execute(
            insert(eis_sync_targets),
            [_target(company, key) for key in (*backlog, *tied, outside)],
        )
        same_attempted_at = midnight_moscow - timedelta(hours=30)
        connection.execute(
            insert(eis_sync_attempts),
            [
                _attempt(company, key, "FAILED", same_attempted_at)
                for key in (*reversed(tied), outside)
            ],
        )

    before = _counts(storage, company)
    selected = eligible_windows(
        EisSyncJournal(storage, company, "worker"),
        now=midnight_moscow,
        limit=20,
    )

    # Four slots are available, only two qualify; the old lane fills all 18 remaining slots.
    assert selected[:2] == tied
    assert len(selected) == 20 and all(key in backlog for key in selected[2:])
    assert outside not in selected
    assert _counts(storage, company) == before


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("limit", [29, 30, 31, 32, 60])
def test_older_empty_reserve_preserves_all_lanes_and_total_budget(storage, active, limit):
    company = f"older-empty-share-{uuid.uuid4().hex}"
    old = tuple(_key(i, "2026-08-01") for i in range(1, 80))
    new = (
        tuple(_key(i, "2026-10-02", "epNotificationEOK2020") for i in range(1, 80))
        if active
        else ()
    )
    older_empty = tuple(_key(i, "2026-09-20", "epNotificationCancel") for i in range(1, 8))
    recent_empty = tuple(_key(i, "2026-10-02") for i in range(1, 8))
    failed = tuple(_key(i, "2026-10-01") for i in range(1, 16))
    retries = tuple(_key(i, "2026-09-19") for i in range(1, 7))
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_targets),
            [
                _target(company, k)
                for k in (*old, *new, *older_empty, *recent_empty, *failed, *retries)
            ],
        )
        conn.execute(
            insert(eis_sync_attempts),
            [
                *[
                    _attempt(company, k, "NO_DATA", NOW - timedelta(hours=50 - i))
                    for i, k in enumerate(older_empty)
                ],
                *[_attempt(company, k, "NO_DATA", NOW - timedelta(hours=30)) for k in recent_empty],
                *[_attempt(company, k, "FAILED", NOW - timedelta(hours=30)) for k in failed],
                *[
                    _attempt(company, k, "SERVICE_ERROR", NOW - timedelta(hours=30))
                    for k in retries
                ],
            ],
        )
    before = _counts(storage, company)
    selected = eligible_windows(EisSyncJournal(storage, company, "test"), now=NOW, limit=limit)
    repair = min((limit + 4) // 5, 12, limit - 1)
    recent_cap = min((limit + 19) // 20, 3, repair - 1)
    assert len(selected) == len(set(selected)) == limit
    assert len(set(selected) & set(recent_empty)) == recent_cap
    assert len(set(selected) & set(failed)) == repair - recent_cap
    assert len(set(selected) & set(retries)) == min((limit + 19) // 20, 3)
    assert tuple(k for k in selected if k in older_empty) == (
        older_empty[:1] if limit >= 30 else ()
    )
    if active:
        assert selected[:2] == (old[0], new[0])
        assert len(set(selected) & set(new)) == (3 * limit + 4) // 5
        if limit >= 30:
            assert selected[:6] == (old[0], *new[:4], older_empty[0])
    elif limit >= 30:
        assert selected[0] == older_empty[0]
    assert _counts(storage, company) == before


def test_older_empty_latest_tie_tenant_dates_canonical_cooldown_and_reset(storage):
    company, other = (f"older-empty-gates-{uuid.uuid4().hex}" for _ in range(2))
    old = tuple(_key(i, "2026-08-01") for i in range(1, 80))
    keys = tuple(_key(i, "2026-09-25") for i in range(1, 9))
    good, transport, canonical, replaced, cooling, future, tied_empty, tied_failed = keys
    malformed = _key(20, "2026-02-30")
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_targets), [_target(company, k) for k in (*old, *keys, malformed)]
        )
        attempts = [
            _attempt(company, k, "NO_DATA", NOW - timedelta(hours=60 - i))
            for i, k in enumerate(keys)
        ]
        attempts[4]["attempted_at"] = NOW - timedelta(hours=24) + timedelta(microseconds=1)
        attempts[5]["attempted_at"] = NOW + timedelta(hours=1)
        attempts[6]["attempted_at"] = NOW - timedelta(hours=24)
        for i in (6, 7):
            attempts[i]["attempt_id"] = str(uuid.UUID(int=1 if i == 6 else 4))
            tie = _attempt(company, keys[i], "FAILED", attempts[i]["attempted_at"])
            tie["attempt_id"] = str(uuid.UUID(int=0 if i == 6 else 5))
            attempts.append(tie)
        attempts.extend(
            [
                _attempt(company, replaced, "FAILED", NOW - timedelta(hours=25)),
                _attempt(company, malformed, "NO_DATA", NOW - timedelta(hours=100)),
            ]
        )
        conn.execute(insert(eis_sync_attempts), list(reversed(attempts)))
        for key, kind in ((canonical, "LEGACY_CANONICAL"), (transport, "VARIANT_TRANSPORT")):
            conn.execute(
                insert(eis_feed_windows).values(
                    company_id=company,
                    window_key=key,
                    response_sha256="b" * 64,
                    manifest_sha256="c" * 64,
                    archive_count=1,
                    notice_count=0,
                    coverage="UNKNOWN",
                    intake_kind=kind,
                    ingested_at=NOW,
                )
            )
    with storage.transaction(other) as conn:
        conn.execute(insert(eis_sync_targets), [_target(other, good), _target(other, old[0])])
        conn.execute(
            insert(eis_sync_attempts),
            [
                _attempt(other, good, "NO_DATA", NOW),
                _attempt(other, old[0], "NO_DATA", NOW - timedelta(hours=100)),
            ],
        )
    journal = EisSyncJournal(storage, company, "test")
    before = _counts(storage, company)
    selected = eligible_windows(journal, now=NOW, limit=60)
    assert selected[0] == good
    assert not {cooling, future, canonical, replaced, tied_failed, malformed} & set(selected)
    assert _counts(storage, company) == before
    # Repeatempty restarts cooldown; variant transport still cannot complete the next key.
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_sync_attempts), [_attempt(company, good, "NO_DATA", NOW)])
    assert eligible_windows(journal, now=NOW, limit=60)[0] == transport
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_feed_windows).values(
                company_id=company,
                window_key=transport,
                response_sha256="d" * 64,
                manifest_sha256="e" * 64,
                archive_count=1,
                notice_count=0,
                coverage="UNKNOWN",
                intake_kind="LEGACY_CANONICAL",
                ingested_at=NOW,
            )
        )
    assert eligible_windows(journal, now=NOW, limit=60)[0] == tied_empty


def test_daily_older_empty_anchor_counts_toward_single_reserve(storage):
    company = f"older-anchor-{uuid.uuid4().hex}"
    old = tuple(_key(i, "2026-09-20") for i in (1, 2))
    new = tuple(_key(i, "2026-10-02") for i in range(1, 80))
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_sync_targets), [_target(company, k) for k in (*old, *new)])
        conn.execute(
            insert(eis_sync_attempts),
            [
                _attempt(company, k, "NO_DATA", NOW - timedelta(hours=50 - i))
                for i, k in enumerate(old)
            ],
        )
    selected = eligible_windows(EisSyncJournal(storage, company, "test"), now=NOW, limit=60)
    assert selected[:6] == (old[0], *new[:5])
    assert selected.count(old[0]) == selected.count(old[1]) == 1
    assert len(selected) == len(set(selected)) == 60
    # Second old empty is ordinary fill after 36 new, not a second reserved prefix slot.
    assert selected.index(old[1]) == 37


def test_older_empty_seven_day_rollover_uses_source_date_not_attempt_age(storage):
    company = f"older-date-rollover-{uuid.uuid4().hex}"
    old = tuple(_key(i, "2026-08-01") for i in range(1, 80))
    older, boundary = _key(90, "2026-09-25"), _key(91, "2026-09-26")
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_targets), [_target(company, k) for k in (*old, older, boundary)]
        )
        conn.execute(
            insert(eis_sync_attempts),
            [
                _attempt(company, older, "NO_DATA", NOW - timedelta(hours=50)),
                _attempt(company, boundary, "NO_DATA", NOW - timedelta(hours=60)),
            ],
        )
    journal = EisSyncJournal(storage, company, "test")
    assert eligible_windows(journal, now=NOW, limit=60)[:2] == (older, boundary)
    # Once Sep26 leaves the last seven completed MSK dates, its older attempt wins.
    assert (
        eligible_windows(journal, now=datetime(2026, 10, 3, 21, tzinfo=UTC), limit=60)[0]
        == boundary
    )


def test_historical_transient_lane_survives_large_null_backlog_and_remains_read_only(
    storage: PostgresStorage,
) -> None:
    company = f"historic-fair-{uuid.uuid4().hex}"
    other = f"historic-other-{uuid.uuid4().hex}"
    backlog = tuple(_key(index % 80 + 1, f"2026-08-{index // 80 + 1:02d}") for index in range(400))
    recent = tuple(_key(index + 1, "2026-10-02") for index in range(15))
    transient = tuple(_key(index + 1, "2026-09-20") for index in range(5))
    excluded = tuple(_key(index + 20, "2026-09-20") for index in range(10))
    missing_target = _key(70, "2026-09-20")
    with storage.transaction(company) as connection:
        connection.execute(
            insert(eis_sync_targets),
            [_target(company, key) for key in (*backlog, *recent, *transient, *excluded)],
        )
        attempts = [_attempt(company, key, "FAILED", NOW - timedelta(hours=50)) for key in recent]
        for index, key in enumerate(transient):
            outcome = ("FAILED", "FAILED", "SERVICE_ERROR", "PREPARING", "FAILED")[index]
            item = _attempt(company, key, outcome, NOW - timedelta(hours=80 - index * 5))
            if outcome == "FAILED":
                item["reason_code"] = (
                    "SOURCE_TRANSPORT_FAILED" if index != 1 else "SOURCE_WSDL_UNAVAILABLE"
                )
            if index == 4:
                # Same timestamp: larger UUID wins; the earlier NO_DATA cannot mask retry.
                item["attempt_id"] = "00000000-0000-0000-0000-000000000002"
                old = _attempt(company, key, "NO_DATA", item["attempted_at"])
                old["attempt_id"] = "00000000-0000-0000-0000-000000000001"
                attempts.append(old)
            attempts.append(item)
        for index, code in enumerate(
            (
                "MEMBER_UNSUPPORTED",
                "DATABASE_BUDGET_REACHED",
                "NOTICE_VERSION_CONFLICT",
                "SOURCE_FAILURE",
            )
        ):
            item = _attempt(company, excluded[index], "FAILED", NOW - timedelta(hours=100))
            item["reason_code"] = code
            attempts.append(item)
        attempts.append(_attempt(company, excluded[4], "NO_DATA", NOW - timedelta(hours=100)))
        for index in (5, 6, 7, 8, 9):
            item = _attempt(company, excluded[index], "FAILED", NOW - timedelta(hours=100))
            item["reason_code"] = "SOURCE_TRANSPORT_FAILED"
            if index == 7:
                item["attempt_id"] = "00000000-0000-0000-0000-000000000003"
            attempts.append(item)
        attempts.append(_attempt(company, excluded[5], "SYNCED", NOW - timedelta(hours=30)))
        attempts.append(_attempt(company, excluded[6], "PREPARING", NOW - timedelta(hours=23)))
        tie = _attempt(company, excluded[7], "NO_DATA", NOW - timedelta(hours=100))
        tie["attempt_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        attempts.append(tie)
        attempts.append(_attempt(company, excluded[8], "SERVICE_ERROR", NOW + timedelta(hours=1)))
        extra = _attempt(company, missing_target, "SERVICE_ERROR", NOW - timedelta(hours=200))
        # Attempt FK requires a planned target; other-tenant-only cases are seeded below.
        connection.execute(insert(eis_sync_attempts), attempts)
        for key, kind in ((excluded[9], "LEGACY_CANONICAL"), (transient[0], "VARIANT_TRANSPORT")):
            connection.execute(
                insert(eis_feed_windows).values(
                    company_id=company,
                    window_key=key,
                    response_sha256="b" * 64,
                    manifest_sha256="c" * 64,
                    archive_count=1,
                    notice_count=0,
                    coverage="UNKNOWN",
                    intake_kind=kind,
                    ingested_at=NOW - timedelta(hours=90),
                )
            )
    with storage.transaction(other) as connection:
        connection.execute(
            insert(eis_sync_targets), [_target(other, missing_target), _target(other, transient[0])]
        )
        extra["company_id"] = other
        connection.execute(
            insert(eis_sync_attempts), [extra, _attempt(other, transient[0], "NO_DATA", NOW)]
        )
    journal = EisSyncJournal(storage, company, "worker")
    before = _counts(storage, company)
    selected = eligible_windows(journal, now=NOW, limit=60)
    assert len(selected) == len(set(selected)) == 60
    assert selected[0] == excluded[4]  # NO_DATA excluded from transients, now reserved separately.
    assert selected[1:13] == recent[:12]
    assert selected[13:16] == transient[:3]
    assert all(key in backlog for key in selected[16:])
    assert selected == eligible_windows(journal, now=NOW, limit=60)
    assert set(excluded) & set(selected) == {excluded[4]}
    assert missing_target not in selected
    assert eligible_windows(journal, now=NOW, limit=1)[0] in backlog
    two = eligible_windows(journal, now=NOW, limit=2)
    assert two[0] == recent[0] and two[1] in backlog
    three = eligible_windows(journal, now=NOW, limit=3)
    assert three[:2] == (recent[0], transient[0]) and three[2] in backlog
    assert _counts(storage, company) == before


def test_historical_latest_tie_and_unused_slots_fill_normal_backlog(
    storage: PostgresStorage,
) -> None:
    company = f"historic-tie-{uuid.uuid4().hex}"
    backlog = tuple(_key(index + 1, "2026-08-01") for index in range(90))
    retry, superseded = _key(91, "2026-09-25"), _key(92, "2026-09-25")
    at = NOW - timedelta(hours=24)
    with storage.transaction(company) as connection:
        connection.execute(
            insert(eis_sync_targets), [_target(company, k) for k in (*backlog, retry, superseded)]
        )
        attempts = []
        for key, last in ((retry, "SERVICE_ERROR"), (superseded, "NO_DATA")):
            first = _attempt(company, key, "PREPARING", at)
            first["attempt_id"] = "00000000-0000-0000-0000-00000000000" + (
                "1" if key == retry else "3"
            )
            latest = _attempt(company, key, last, at)
            latest["attempt_id"] = "00000000-0000-0000-0000-00000000000" + (
                "2" if key == retry else "4"
            )
            attempts.extend((first, latest))
        connection.execute(insert(eis_sync_attempts), list(reversed(attempts)))
    before = _counts(storage, company)
    selected = eligible_windows(EisSyncJournal(storage, company, "worker"), now=NOW, limit=60)
    assert selected[:2] == (superseded, retry)
    assert len(selected) == 60 and all(key in backlog for key in selected[2:])
    assert _counts(storage, company) == before


def test_historical_retry_clause_excludes_invalid_source_date_without_cast_error(
    storage: PostgresStorage,
) -> None:
    from sqlalchemy import literal, union_all

    from procurement.sources.eis_corpus import historical_source_retry_clause

    rows = union_all(
        *[
            select(
                literal(key).label("window_key"),
                literal("SERVICE_ERROR").label("outcome"),
                literal(None).label("reason_code"),
                literal(NOW - timedelta(hours=24)).label("attempted_at"),
            )
            for key in (
                _key(50, "2026-09-25"),
                _key(51, "2026-09-26"),
                _key(52, "2026-99-99"),
                _key(53, "2026-10-03"),
            )
        ]
    ).cte("synthetic_latest")
    with storage.transaction(
        f"historic-date-{uuid.uuid4().hex}", consistent_read=True
    ) as connection:
        selected = tuple(
            connection.execute(
                select(rows.c.window_key).where(historical_source_retry_clause(rows, NOW))
            ).scalars()
        )
    assert selected == (_key(50, "2026-09-25"),)


def test_limit_two_reuses_unused_recent_capacity_but_reserves_normal_slot(
    storage: PostgresStorage,
) -> None:
    for has_recent in (False, True):
        company = f"historic-small-{uuid.uuid4().hex}"
        retry = _key(50, "2026-09-20")
        recent = _key(50, "2026-10-02")
        backlog = _key(50, "2026-08-01")
        with storage.transaction(company) as connection:
            keys = (retry, backlog, recent) if has_recent else (retry, backlog)
            connection.execute(insert(eis_sync_targets), [_target(company, key) for key in keys])
            attempts = [_attempt(company, retry, "SERVICE_ERROR", NOW - timedelta(hours=24))]
            if has_recent:
                attempts.append(_attempt(company, recent, "FAILED", NOW - timedelta(hours=24)))
            connection.execute(insert(eis_sync_attempts), attempts)
        journal = EisSyncJournal(storage, company, "worker")
        before = _counts(storage, company)
        assert eligible_windows(journal, now=NOW, limit=2) == (
            recent if has_recent else retry,
            backlog,
        )
        assert eligible_windows(journal, now=NOW, limit=1) == (backlog,)
        assert _counts(storage, company) == before


def test_daily_new_dates_preserve_old_anchor_hard_share_and_retry_caps(storage):
    company = f"daily-fair-{uuid.uuid4().hex}"
    other = f"daily-other-{uuid.uuid4().hex}"
    old = tuple(_key(i, "2026-08-01") for i in range(1, 80))
    new = tuple(_key(i, "2026-10-02", "epNotificationEOK2020") for i in range(1, 80))
    failed = tuple(_key(i, "2026-10-02") for i in range(1, 16))
    retries = tuple(_key(i, "2026-09-20") for i in range(1, 7))
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_targets), [_target(company, k) for k in (*old, *new, *failed, *retries)]
        )
        conn.execute(
            insert(eis_sync_attempts),
            [
                *[_attempt(company, k, "FAILED", NOW - timedelta(hours=30)) for k in failed],
                *[
                    _attempt(company, k, "SERVICE_ERROR", NOW - timedelta(hours=40))
                    for k in retries
                ],
            ],
        )
    with storage.transaction(other) as conn:
        conn.execute(insert(eis_sync_targets), [_target(other, old[0]), _target(other, new[0])])
        conn.execute(
            insert(eis_sync_attempts),
            [_attempt(other, k, "NO_DATA", NOW) for k in (old[0], new[0])],
        )
    journal = EisSyncJournal(storage, company, "test")
    before = _counts(storage, company)
    # No activation at limit1: exact legacy NULL/date-desc/key order.
    assert eligible_windows(journal, now=NOW, limit=1) == (new[0],)
    assert eligible_windows(journal, now=NOW, limit=2) == (old[0], new[0])
    selected = eligible_windows(journal, now=NOW, limit=60)
    assert selected[:2] == (old[0], new[0])
    assert selected[:6] == (old[0], *new[:4], failed[0])
    assert tuple(k for k in selected if k in failed) == failed[:12]
    assert tuple(k for k in selected if k in retries) == retries[:3]
    assert len(selected) == len(set(selected)) == 60
    assert len(set(selected) & set(new)) == 36
    assert len(set(selected) & set(old)) == 9
    assert _counts(storage, company) == before


@pytest.mark.parametrize(
    ("old_count", "new_count", "limit", "expected_new"),
    [
        (50, 2, 10, 2),
        (50, 50, 10, 6),
        (2, 50, 10, 8),
        (1, 50, 60, 50),
    ],
)
def test_daily_share_is_work_conserving_only_after_ordinary_old_exhausted(
    storage, old_count, new_count, limit, expected_new
):
    company = f"daily-fill-{uuid.uuid4().hex}"
    old = tuple(_key(i, "2026-08-01") for i in range(1, old_count + 1))
    new = tuple(_key(i, "2026-10-02", "epNotificationEOK2020") for i in range(1, new_count + 1))
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_sync_targets), [_target(company, k) for k in (*old, *new)])
    before = _counts(storage, company)
    selected = eligible_windows(EisSyncJournal(storage, company, "test"), now=NOW, limit=limit)
    assert selected[:2] == (old[0], new[0])
    assert len(selected) == min(limit, old_count + new_count) == len(set(selected))
    assert len(set(selected) & set(new)) == expected_new
    assert _counts(storage, company) == before


def test_daily_activation_rollover_uses_completed_dates_and_retains_pending(storage):
    from datetime import date

    from procurement.sources.eis_feed_sync import EisDateSelection

    company = f"daily-roll-{uuid.uuid4().hex}"
    anchor = _key(50, "2026-09-01")
    journal = EisSyncJournal(storage, company, "test")
    selections = tuple(
        EisDateSelection("50", date(2026, 10, day), 3, "epNotificationEOK2020") for day in (2, 3, 4)
    )
    assert journal.plan(selections) == 3
    assert journal.plan(selections) == 0
    with storage.transaction(company) as conn:
        conn.execute(insert(eis_sync_targets), [_target(company, anchor)])
    before = _counts(storage, company)
    assert eligible_windows(journal, now=NOW, limit=2) == (anchor, selections[0].window_key)
    # Midnight Moscow advances exactly one completed source day.
    rollover = datetime(2026, 10, 3, 21, tzinfo=UTC)
    assert eligible_windows(journal, now=rollover, limit=2) == (anchor, selections[1].window_key)
    assert _counts(storage, company) == before


def test_daily_no_ordinary_anchor_keeps_legacy_order_and_cooldown(storage):
    company = f"daily-no-anchor-{uuid.uuid4().hex}"
    retry = _key(50, "2026-09-01")
    cooling = _key(51, "2026-09-01")
    completed = _key(52, "2026-09-01")
    new = _key(50, "2026-10-02", "epNotificationEOK2020")
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_targets),
            [_target(company, k) for k in (retry, cooling, completed, new)],
        )
        conn.execute(
            insert(eis_sync_attempts),
            [
                _attempt(company, retry, "SERVICE_ERROR", NOW - timedelta(hours=24)),
                _attempt(company, cooling, "NO_DATA", NOW - timedelta(hours=23)),
            ],
        )
        conn.execute(
            insert(eis_feed_windows).values(
                company_id=company,
                window_key=completed,
                response_sha256="b" * 64,
                manifest_sha256="c" * 64,
                archive_count=1,
                notice_count=0,
                coverage="UNKNOWN",
                ingested_at=NOW,
            )
        )
    before = _counts(storage, company)
    assert eligible_windows(EisSyncJournal(storage, company, "test"), now=NOW, limit=2) == (
        retry,
        new,
    )
    assert _counts(storage, company) == before


def test_active_daily_attempted_anchor_fill_uses_latest_time_and_tie_identity(storage):
    company = f"daily-attempted-{uuid.uuid4().hex}"
    old, due, cooling, transient = tuple(_key(i, "2026-09-01") for i in range(1, 5))
    new = tuple(_key(i, "2026-10-02", "epNotificationEOK2020") for i in range(1, 20))
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_targets),
            [_target(company, k) for k in (old, due, cooling, transient, *new)],
        )
        attempts = [
            _attempt(company, old, "NO_DATA", NOW - timedelta(hours=48)),
            _attempt(company, cooling, "NO_DATA", NOW - timedelta(hours=23)),
        ]
        # At the exact 24h boundary, highest attempt ID chooses whether this is
        # ordinary backlog or a reserved transient; earliest history cannot win.
        for index, (key, outcomes) in enumerate(
            ((due, ("SERVICE_ERROR", "NO_DATA")), (transient, ("NO_DATA", "SERVICE_ERROR")))
        ):
            for ordinal, outcome in enumerate(outcomes):
                item = _attempt(company, key, outcome, NOW - timedelta(hours=24))
                item["attempt_id"] = f"00000000-0000-0000-0000-{index * 2 + ordinal + 1:012d}"
                attempts.append(item)
        conn.execute(insert(eis_sync_attempts), list(reversed(attempts)))
    journal = EisSyncJournal(storage, company, "test")
    before = _counts(storage, company)
    assert eligible_windows(journal, now=NOW, limit=2) == (old, new[0])
    selected = eligible_windows(journal, now=NOW, limit=10)
    assert selected[:3] == (old, new[0], new[1])
    assert transient in selected
    assert due in selected and cooling not in selected
    assert len(selected) == len(set(selected)) == 10
    assert len(set(selected) & set(new)) == 7  # ordinary old backlog exhausted, overflow allowed
    assert _counts(storage, company) == before
