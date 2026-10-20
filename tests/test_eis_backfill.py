"""Date backfill resumes successful checkpoints and never skips a source gap."""

import asyncio
from datetime import UTC, date, datetime

import pytest

from procurement.sources import eis_backfill
from procurement.sources.eis_backfill import (
    EisBackfillIncomplete,
    backfill_eis_dates,
    recent_completed_date_range,
)
from procurement.sources.eis_feed_archive import EisFeedArchiveError
from procurement.sources.eis_feed_sync import EisHourSyncResult, EisSyncError

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def test_rolling_range_uses_local_completed_days() -> None:
    assert recent_completed_date_range(datetime(2026, 9, 26, 22, tzinfo=UTC), 3, 3) == (
        date(2026, 9, 24), date(2026, 9, 26)
    )
    assert recent_completed_date_range(datetime(2026, 9, 26, 20, tzinfo=UTC), 3, 1) == (
        date(2026, 9, 25), date(2026, 9, 25)
    )
    with pytest.raises(ValueError, match="NOW_TIMEZONE_MISSING"):
        recent_completed_date_range(datetime(2026, 9, 27), 3, 1)
    with pytest.raises(ValueError, match="BACKFILL_RANGE_INVALID"):
        recent_completed_date_range(NOW, 3, 32)


def test_backfill_dates_are_ordered_and_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake_sync(
        storage: object, company: str, actor: str, selection: object, token: str
    ) -> EisHourSyncResult:
        key = selection.window_key
        seen.append(key)
        if len(seen) == 1:
            return EisHourSyncResult(key, "SYNCED", 2, 145, 139)
        return EisHourSyncResult(key, "SKIPPED")

    monkeypatch.setattr(eis_backfill, "sync_eis_window_via_browser", fake_sync)
    summary = asyncio.run(
        backfill_eis_dates(
            None, "tenant-a", "worker", "50", date(2026, 9, 25), date(2026, 9, 26),
            3, "token", now=NOW, between_dates_seconds=0,
        )
    )
    assert seen == [
        "getDocsIP/PRIZ/50/2026-09-25+03:00",
        "getDocsIP/PRIZ/50/2026-09-26+03:00",
    ]
    assert (summary.completed_days, summary.synced_days, summary.skipped_days) == (2, 1, 1)
    assert (summary.archive_count, summary.notice_count, summary.new_versions) == (2, 145, 139)
    assert summary.coverage == "UNKNOWN"


def test_backfill_reports_no_data_gap_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[date] = []

    async def fake_sync(
        storage: object, company: str, actor: str, selection: object, token: str
    ) -> EisHourSyncResult:
        seen.append(selection.day)
        if len(seen) == 2:
            return EisHourSyncResult(
                selection.window_key, "NO_DATA", source_response_sha256="a" * 64
            )
        return EisHourSyncResult(selection.window_key, "SYNCED")

    monkeypatch.setattr(eis_backfill, "sync_eis_window_via_browser", fake_sync)
    summary = asyncio.run(
        backfill_eis_dates(
            None, "tenant-a", "worker", "50", date(2026, 9, 24),
            date(2026, 9, 26), 3, "token", now=NOW, between_dates_seconds=0,
        )
    )
    assert summary.completed_days == 2
    assert summary.no_data_observations[0].day == date(2026, 9, 25)
    assert summary.no_data_observations[0].source_response_sha256 == "a" * 64
    assert seen == [date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26)]


def test_transport_failure_and_incomplete_current_date_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sync(
        storage: object, company: str, actor: str, selection: object, token: str
    ) -> EisHourSyncResult:
        raise EisSyncError("ARCHIVE_DOWNLOAD_HTTP_404")

    monkeypatch.setattr(eis_backfill, "sync_eis_window_via_browser", fake_sync)
    with pytest.raises(EisBackfillIncomplete, match="ARCHIVE_DOWNLOAD_HTTP_404"):
        asyncio.run(
            backfill_eis_dates(
                None, "tenant-a", "worker", "50", date(2026, 9, 25),
                date(2026, 9, 25), 3, "token", now=NOW,
            )
        )
    async def malformed_archive(
        storage: object, company: str, actor: str, selection: object, token: str
    ) -> EisHourSyncResult:
        raise EisFeedArchiveError("XML_INVALID")

    monkeypatch.setattr(eis_backfill, "sync_eis_window_via_browser", malformed_archive)
    with pytest.raises(EisBackfillIncomplete, match="XML_INVALID"):
        asyncio.run(
            backfill_eis_dates(
                None, "tenant-a", "worker", "50", date(2026, 9, 25),
                date(2026, 9, 25), 3, "token", now=NOW,
            )
        )
    with pytest.raises(ValueError, match="BACKFILL_RANGE_INVALID"):
        asyncio.run(
            backfill_eis_dates(
                None, "tenant-a", "worker", "50", date(2026, 9, 27),
                date(2026, 9, 27), 3, "token", now=NOW,
            )
        )


def test_journal_plans_every_date_before_first_request_and_keeps_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []

    class FakeJournal:
        company_id = "tenant-a"
        actor_id = "worker"

        def plan(self, selections: tuple[object, ...]) -> int:
            events.append(("PLAN", tuple(item.window_key for item in selections)))
            return len(selections)

        def record(
            self, window_key: str, outcome: str, *, reason_code: str | None = None,
            source_response_sha256: str | None = None,
        ) -> str:
            events.append(("ATTEMPT", (window_key, outcome, reason_code, source_response_sha256)))
            return "attempt-id"

    async def fake_sync(
        storage: object, company: str, actor: str, selection: object, token: str
    ) -> EisHourSyncResult:
        events.append(("REQUEST", selection.window_key))
        raise EisSyncError("ARCHIVE_DOWNLOAD_HTTP_404")

    monkeypatch.setattr(eis_backfill, "sync_eis_window_via_browser", fake_sync)
    with pytest.raises(EisBackfillIncomplete, match="ARCHIVE_DOWNLOAD_HTTP_404"):
        asyncio.run(
            backfill_eis_dates(
                None, "tenant-a", "worker", "50", date(2026, 9, 24),
                date(2026, 9, 26), 3, "token", now=NOW,
                journal=FakeJournal(),
            )
        )
    assert events[0] == (
        "PLAN",
        (
            "getDocsIP/PRIZ/50/2026-09-24+03:00",
            "getDocsIP/PRIZ/50/2026-09-25+03:00",
            "getDocsIP/PRIZ/50/2026-09-26+03:00",
        ),
    )
    assert events[1] == ("REQUEST", "getDocsIP/PRIZ/50/2026-09-24+03:00")
    assert events[2] == (
        "ATTEMPT",
        ("getDocsIP/PRIZ/50/2026-09-24+03:00", "FAILED", "ARCHIVE_DOWNLOAD_HTTP_404", None),
    )
