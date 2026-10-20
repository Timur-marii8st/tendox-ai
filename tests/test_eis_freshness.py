"""Freshness never equates recent polling with a complete or fresh EIS corpus."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock

import pytest

from procurement.sources import eis_freshness
from procurement.sources.eis_corpus import priority_requested, run_corpus
from procurement.sources.eis_feed_sync import EisHourSelection, EisHourSyncResult, EisSyncError
from procurement.sources.eis_freshness import EisFreshnessScope, due_target

NOW = datetime(2026, 10, 1, 10, 15, tzinfo=UTC)


@pytest.mark.parametrize("replayed", [False, True])
def test_partial_intake_persists_failed_observation_and_replay_delta(monkeypatch, replayed):
    from procurement.sources.eis_feed_sync import EisRejectedWindowError
    from procurement.sources.eis_variant_intake import EisVariantIntakeReport
    from procurement.storage.eis_notice_projection import EisNoticeProjectionReport

    scope = EisFreshnessScope(("50",))
    target = scope.targets(NOW)[0]
    journal = Mock(company_id="tenant-a", actor_id="worker")
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: (target,))
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(eis_freshness.asyncio, "sleep", AsyncMock())
    projection = EisNoticeProjectionReport(
        batch_id="batch",
        receipt_id="receipt",
        archive_count=1,
        occurrence_count=3,
        pair_count=2,
        projected_count=1,
        replayed_count=0,
        held_count=1,
        replayed=replayed,
        audit_event_id="audit",
    )
    intake = EisVariantIntakeReport(
        status="PARTIAL",
        stage="COMPLETE",
        reason=None,
        ledger_receipt_id="receipt",
        ledger_audit_event_id="ledger-audit",
        projection=projection,
    )
    error = EisRejectedWindowError(
        "DUPLICATE_NOTICE_VERSION",
        "b" * 64,
        SimpleNamespace(status="RETAINED", manifest_sha256="d" * 64),
        "RECORDED",
        SimpleNamespace(sha256="e" * 64),
        "RECORDED",
        variant_intake=intake,
    )
    monkeypatch.setattr(eis_freshness, "sync_eis_window_via_browser", AsyncMock(side_effect=error))
    report = asyncio.run(eis_freshness.run_freshness(journal, "secret", scope, now=NOW))
    assert report.partial_windows == report.failed == report.held_pairs == 1
    assert report.synced == 0 and report.new_versions == (0 if replayed else 1)
    assert report.replayed_projection_batches == int(replayed)
    observation = journal.record.call_args.kwargs["observation"]
    assert observation.variant_intake == intake and observation.outcome == "FAILED"
    assert observation.new_versions == report.new_versions
    assert report.coverage == report.freshness == "UNKNOWN"


def test_automatic_database_failure_stops_freshness_without_losing_conflict(monkeypatch):
    from procurement.sources.eis_feed_sync import EisRejectedWindowError
    from procurement.sources.eis_variant_intake import EisVariantIntakeReport

    scope = EisFreshnessScope(("50",))
    journal = Mock(company_id="tenant-a", actor_id="worker")
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: scope.targets(NOW)[:2])
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    intake = EisVariantIntakeReport(status="FAILED", stage="RETENTION", reason="DATABASE_FAILED")
    error = EisRejectedWindowError(
        "NOTICE_VERSION_CONFLICT", "b" * 64, None, "FAILED", variant_intake=intake
    )
    sync = AsyncMock(side_effect=error)
    monkeypatch.setattr(eis_freshness, "sync_eis_window_via_browser", sync)
    report = asyncio.run(eis_freshness.run_freshness(journal, "secret", scope, now=NOW))
    assert sync.await_count == 1 and report.reason == "DATABASE_FAILED"
    assert report.failed == 1 and report.partial_windows == 0
    assert report.observations[0].reason == "NOTICE_VERSION_CONFLICT"


@pytest.mark.parametrize("diagnosed", [False, True])
def test_quarantined_conflict_keeps_failed_fingerprint_and_other_window_progress(
    monkeypatch, diagnosed
):
    from procurement.sources.eis_feed_sync import EisRejectedWindowError

    scope = EisFreshnessScope(("50",))
    targets = scope.targets(NOW)[:2]
    journal = Mock(company_id="tenant-a", actor_id="worker")
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: targets)
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    calls = []

    async def sync(*a, **k):
        calls.append(a[3].window_key)
        if len(calls) == 1:
            raise EisRejectedWindowError(
                "DUPLICATE_NOTICE_VERSION",
                "b" * 64,
                SimpleNamespace(status="RETAINED", manifest_sha256="d" * 64) if diagnosed else None,
                "RECORDED" if diagnosed else "FAILED",
                SimpleNamespace(sha256="e" * 64) if diagnosed else None,
                "RECORDED" if diagnosed else "NOT_REQUIRED",
            )
        return EisHourSyncResult(a[3].window_key, "NO_DATA", source_response_sha256="c" * 64)

    async def no_wait(*a):
        pass

    monkeypatch.setattr(eis_freshness, "sync_eis_window_via_browser", sync)
    monkeypatch.setattr(eis_freshness.asyncio, "sleep", no_wait)
    report = asyncio.run(eis_freshness.run_freshness(journal, "secret", scope, now=NOW))
    assert report.attempted == 2 and report.failed == 1 and report.no_data == 1
    failed = journal.record.call_args_list[0]
    assert failed.args[1] == "FAILED" and failed.kwargs["source_response_sha256"] == "b" * 64
    assert failed.kwargs["observation"].response_sha256 == "b" * 64
    observed = failed.kwargs["observation"]
    assert observed.rejection_retention_status == ("RETAINED" if diagnosed else "UNAVAILABLE")
    assert observed.rejection_audit_status == ("RECORDED" if diagnosed else "FAILED")
    assert observed.rejection_diagnosis_audit_status == (
        "RECORDED" if diagnosed else "NOT_REQUIRED"
    )
    assert observed.rejection_diagnosis_sha256 == ("e" * 64 if diagnosed else None)


def test_schedule_uses_closed_local_hours_and_completed_reconciliation_days() -> None:
    targets = EisFreshnessScope(("50", "77")).targets(NOW)
    assert len(targets) == 150
    hours = [item for item in targets if isinstance(item.selection, EisHourSelection)]
    assert hours[0].selection.hour == 11
    assert all(item.selection.day.isoformat() == "2026-10-01" for item in hours)
    assert all(item.selection.hour <= 11 for item in hours)
    assert sum(item.lane == "RECENT_HOUR" for item in targets) == 20
    assert sum(item.lane == "RECONCILE_DAY" for item in targets) == 30
    assert len({item.selection.window_key for item in targets}) == len(targets)
    midnight = EisFreshnessScope(("50",)).targets(datetime(2026, 9, 30, 21, 5, tzinfo=UTC))
    assert len(midnight) == 15
    assert all(item.lane == "RECONCILE_DAY" for item in midnight)
    before_margin = EisFreshnessScope(("50",)).targets(datetime(2026, 9, 30, 23, 4, tzinfo=UTC))
    assert all(item.lane == "RECONCILE_DAY" for item in before_margin)
    at_margin = EisFreshnessScope(("50",)).targets(datetime(2026, 9, 30, 23, 5, tzinfo=UTC))
    assert sum(isinstance(item.selection, EisHourSelection) for item in at_margin) == 5
    assert any(t.selection.document_type == "epNotificationEOK2020" for t in at_margin)
    with pytest.raises(ValueError, match="NOW_TIMEZONE_MISSING"):
        EisFreshnessScope(("50",)).targets(NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        EisFreshnessScope(("00",)).targets(NOW)


def test_success_and_no_data_are_rechecked_and_failures_have_bounded_backoff() -> None:
    targets = EisFreshnessScope(("50",)).targets(NOW)
    recent = targets[0]
    day = next(item for item in targets if item.lane == "RECONCILE_DAY")
    for outcome in ("SYNCED", "NO_DATA"):
        assert not due_target(
            recent, now=NOW, attempted_at=NOW - timedelta(minutes=59), outcome=outcome
        )
        assert due_target(recent, now=NOW, attempted_at=NOW - timedelta(hours=1), outcome=outcome)
        assert not due_target(day, now=NOW, attempted_at=NOW - timedelta(hours=23), outcome=outcome)
        assert due_target(day, now=NOW, attempted_at=NOW - timedelta(hours=24), outcome=outcome)
    assert not due_target(day, now=NOW, attempted_at=NOW - timedelta(minutes=14), outcome="FAILED")
    assert due_target(day, now=NOW, attempted_at=NOW - timedelta(minutes=15), outcome="FAILED")
    assert not due_target(day, now=NOW, attempted_at=NOW + timedelta(hours=1), outcome="SYNCED")
    with pytest.raises(ValueError, match="ATTEMPT_TIMEZONE_MISSING"):
        due_target(day, now=NOW, attempted_at=NOW.replace(tzinfo=None), outcome="SYNCED")


def test_priority_hint_expires_and_backfill_yields_before_network(
    tmp_path: Path, monkeypatch
) -> None:
    flag = tmp_path / "priority.request"
    flag.touch()
    now = datetime.now(UTC)
    assert priority_requested(flag, now=now)
    assert not priority_requested(flag, now=now + timedelta(minutes=11))
    assert not priority_requested(None, now=now)
    journal = Mock()
    monkeypatch.setattr("procurement.sources.eis_corpus.eligible_windows", lambda *a, **k: ("key",))
    gate = Mock()
    monkeypatch.setattr("procurement.sources.eis_corpus.resource_gate", gate)
    result = asyncio.run(run_corpus(journal, "secret", now=now, priority_request=flag))
    assert result["reason"] == "PRIORITY_REFRESH_REQUESTED" and result["attempted"] == 0
    gate.assert_not_called()
    journal.record.assert_not_called()


def test_freshness_refreshes_and_stops_on_source_failure(monkeypatch) -> None:
    scope = EisFreshnessScope(("50",))
    targets = scope.targets(NOW)[:2]
    journal = Mock(company_id="tenant-a", actor_id="worker")
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: targets)
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    calls = []

    async def failed(*args, **kwargs):
        calls.append(kwargs)
        raise EisSyncError("SOURCE_TRANSPORT_FAILED")

    monkeypatch.setattr(eis_freshness, "sync_eis_window_via_browser", failed)
    report = asyncio.run(eis_freshness.run_freshness(journal, "secret", scope, now=NOW))
    assert calls == [{"refresh": True}]
    assert report.attempted == 1 and report.reason == "SOURCE_TRANSPORT_FAILED"
    assert report.coverage == report.freshness == "UNKNOWN"
    journal.record.assert_called_once_with(
        targets[0].selection.window_key,
        "FAILED",
        reason_code="SOURCE_TRANSPORT_FAILED",
        source_response_sha256=None,
        observation=ANY,
    )


def test_freshness_no_data_evidence_and_resource_budget(monkeypatch) -> None:
    scope = EisFreshnessScope(("50",))
    target = scope.targets(NOW)[0]
    journal = Mock(company_id="tenant-a", actor_id="worker")
    select = Mock(return_value=(target,))
    monkeypatch.setattr(eis_freshness, "eligible_freshness", select)
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: "DISK_RESERVE_REACHED")
    report = asyncio.run(eis_freshness.run_freshness(journal, "secret", scope, now=NOW))
    assert report.attempted == 0 and report.reason == "DISK_RESERVE_REACHED"
    select.assert_not_called()

    async def empty(*args, **kwargs):
        return EisHourSyncResult(
            target.selection.window_key, "NO_DATA", source_response_sha256="a" * 64
        )

    async def no_wait(*args):
        pass

    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(eis_freshness, "sync_eis_window_via_browser", empty)
    monkeypatch.setattr(eis_freshness.asyncio, "sleep", no_wait)
    report = asyncio.run(eis_freshness.run_freshness(journal, "secret", scope, now=NOW))
    assert report.no_data == report.attempted == 1 and report.synced == 0
    assert report.status == "PARTIAL" and report.freshness == report.coverage == "UNKNOWN"
    journal.record.assert_called_once_with(
        target.selection.window_key,
        "NO_DATA",
        reason_code=None,
        source_response_sha256="a" * 64,
        observation=ANY,
    )


def test_service_error_keeps_source_code_and_sha_and_stops(monkeypatch) -> None:
    scope = EisFreshnessScope(("50",))
    target = scope.targets(NOW)[0]
    journal = Mock(company_id="tenant-a", actor_id="worker")
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: (target, target))
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)

    async def rejected(*args, **kwargs):
        return EisHourSyncResult(
            target.selection.window_key,
            "SERVICE_ERROR",
            source_error_code=8,
            source_response_sha256="b" * 64,
        )

    monkeypatch.setattr(eis_freshness, "sync_eis_window_via_browser", rejected)
    report = asyncio.run(eis_freshness.run_freshness(journal, "secret", scope, now=NOW))
    assert report.attempted == 1 and report.source_error_code == 8
    assert report.reason == "SOURCE_SERVICE_ERROR" and report.coverage == "UNKNOWN"
    journal.record.assert_called_once_with(
        target.selection.window_key,
        "SERVICE_ERROR",
        reason_code="SOURCE_SERVICE_ERROR_8",
        source_response_sha256="b" * 64,
        observation=ANY,
    )


@pytest.mark.parametrize(
    "reason",
    ["DUPLICATE_NOTICE_VERSION", "ARCHIVE_WINDOW_SIZE_LIMIT", "ARCHIVE_WINDOW_COUNT_LIMIT"],
)
def test_conflict_is_retained_with_backoff_and_other_window_progresses(monkeypatch, reason) -> None:
    from procurement.sources.eis_feed_archive import EisFeedArchiveError

    scope = EisFreshnessScope(("50",))
    targets = scope.targets(NOW)[:2]
    target = targets[0]
    assert not due_target(
        target,
        now=NOW,
        attempted_at=NOW - timedelta(hours=23),
        outcome="FAILED",
        reason=reason,
    )
    assert due_target(
        target,
        now=NOW,
        attempted_at=NOW - timedelta(hours=24),
        outcome="FAILED",
        reason=reason,
    )
    journal = Mock(company_id="tenant-a", actor_id="worker")
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: targets)
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    calls = 0

    async def sync(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            if reason == "DUPLICATE_NOTICE_VERSION":
                raise EisFeedArchiveError(reason)
            raise EisSyncError(reason)
        return EisHourSyncResult(
            targets[1].selection.window_key, "NO_DATA", source_response_sha256="c" * 64
        )

    async def no_wait(*args):
        pass

    monkeypatch.setattr(eis_freshness, "sync_eis_window_via_browser", sync)
    monkeypatch.setattr(eis_freshness.asyncio, "sleep", no_wait)
    report = asyncio.run(eis_freshness.run_freshness(journal, "secret", scope, now=NOW))
    assert report.attempted == 2 and report.failed == report.no_data == 1
    assert report.status == "PARTIAL" and report.reason is None
    assert [item.outcome for item in report.observations] == ["FAILED", "NO_DATA"]
    assert report.observations[0].response_sha256 is None
    assert journal.record.call_count == 2 and report.coverage == "UNKNOWN"


def test_shared_transport_reaches_every_window_and_failure_is_durable(monkeypatch) -> None:
    scope = EisFreshnessScope(("50",))
    targets = scope.targets(NOW)[:3]
    journal = Mock(company_id="tenant-a", actor_id="worker")
    transport = Mock()
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: targets)
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    calls = []

    async def sync(storage, company, actor, selection, token, shared, *, refresh):
        assert shared is transport and refresh is True
        calls.append(selection.window_key)
        if len(calls) == 2:
            raise EisSyncError("SOURCE_TRANSPORT_FAILED")
        return EisHourSyncResult(selection.window_key, "NO_DATA", source_response_sha256="c" * 64)

    async def no_wait(*args):
        pass

    monkeypatch.setattr(eis_freshness, "sync_eis_window", sync)
    monkeypatch.setattr(eis_freshness.asyncio, "sleep", no_wait)
    report = asyncio.run(
        eis_freshness.run_freshness(journal, "secret", scope, now=NOW, transport=transport)
    )
    assert report.attempted == 2 and report.no_data == report.failed == 1
    assert report.reason == "SOURCE_TRANSPORT_FAILED"
    assert journal.record.call_count == 2
    assert [item.outcome for item in report.observations] == ["NO_DATA", "FAILED"]


def test_foreground_shares_bounded_pass_with_baseline_and_scope_is_truthful(monkeypatch):
    from procurement.storage import eis_freshness_requests as requests

    scope = EisFreshnessScope(("50",))
    baseline = scope.targets(NOW)[:4]
    foreground = EisFreshnessScope(("66",)).targets(NOW)[:4]
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: baseline)
    monkeypatch.setattr(requests, "pending_refresh_targets", lambda *a, **k: foreground)
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    journal = Mock(company_id="tenant-a", actor_id="worker")
    calls = []

    async def sync(storage, company, actor, selection, token, shared, *, refresh):
        calls.append(selection.region)
        return EisHourSyncResult(selection.window_key, "NO_DATA", source_response_sha256="c" * 64)

    async def no_wait(*args):
        pass

    monkeypatch.setattr(eis_freshness, "sync_eis_window", sync)
    monkeypatch.setattr(eis_freshness.asyncio, "sleep", no_wait)
    report = asyncio.run(
        eis_freshness.run_freshness(
            journal,
            "secret",
            scope,
            now=NOW,
            max_windows=4,
            transport=Mock(),
            include_requests=True,
        )
    )
    assert calls == ["50", "66", "50", "66"]
    assert report.regions == ("50", "66") and report.attempted == 4


def test_expired_foreground_target_never_starts_network(monkeypatch):
    from dataclasses import replace

    scope = EisFreshnessScope(("50",))
    target = replace(scope.targets(NOW)[0], expires_at=datetime.now(UTC) - timedelta(seconds=1))
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: (target,))
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    journal = Mock(company_id="tenant-a", actor_id="worker")
    report = asyncio.run(eis_freshness.run_freshness(journal, "secret", scope, now=NOW))
    assert report.attempted == 0 and report.expired_targets == 1
    journal.record.assert_not_called()


def test_read_due_targets_preserves_lane_fairness_latest_cooldown_and_stable_ties():
    from contextlib import contextmanager

    scope = EisFreshnessScope(("50", "77"))
    targets = scope.targets(NOW)
    recent = tuple(item for item in targets if item.lane == "RECENT_HOUR")
    # The database returns latest rows. Missing rows are unattempted, including
    # missing journal targets; they sort ahead of older attempted work in a lane.
    rows = [
        {
            "window_key": recent[0].selection.window_key,
            "attempted_at": NOW - timedelta(hours=2),
            "outcome": "NO_DATA",
            "reason_code": None,
        },
        {
            "window_key": recent[1].selection.window_key,
            "attempted_at": NOW - timedelta(hours=3),
            "outcome": "NO_DATA",
            "reason_code": None,
        },
        {
            "window_key": recent[2].selection.window_key,
            "attempted_at": NOW - timedelta(minutes=5),
            "outcome": "FAILED",
            "reason_code": "SOURCE_TRANSPORT_FAILED",
        },
    ]
    connection = Mock()
    connection.execute.return_value.mappings.return_value.all.return_value = rows

    @contextmanager
    def read_transaction(company, *, consistent_read):
        assert company == "tenant-a" and consistent_read
        yield connection

    journal = Mock(company_id="tenant-a")
    journal.storage.transaction = read_transaction
    result = eis_freshness.read_due_freshness(journal, scope, now=NOW, limit=1000)
    assert result[: len(recent) - 3] == recent[3:]
    assert result[len(recent) - 3 : len(recent) - 1] == (recent[1], recent[0])
    assert recent[2] not in result
    assert result[len(recent) - 1].lane == "RECONCILE_DAY"
    journal.plan.assert_not_called()


def test_unprocessable_metadata_window_uses_daily_local_limit_cooldown():
    target = EisFreshnessScope(("50",)).targets(NOW)[0]
    assert not due_target(
        target,
        now=NOW,
        attempted_at=NOW - timedelta(hours=23),
        outcome="FAILED",
        reason="ATTACHMENT_METADATA_COUNT_LIMIT",
    )
    assert due_target(
        target,
        now=NOW,
        attempted_at=NOW - timedelta(hours=24),
        outcome="FAILED",
        reason="ATTACHMENT_METADATA_COUNT_LIMIT",
    )
