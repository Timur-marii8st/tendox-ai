"""Fail-closed date backfill for one official EIS region and document type.

Successful dates are checkpointed by the importer. Re-running the same range
skips them. Official NO_DATA days stay unresolved in the summary.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_feed_archive import DEFAULT_NOTICE_TYPE, EisFeedArchiveError
from procurement.sources.eis_feed_sync import (
    EisDateSelection,
    EisHourSyncResult,
    EisSyncError,
    sync_eis_window_via_browser,
)
from procurement.storage.eis_notice_index import EisIndexConflict

if TYPE_CHECKING:
    from procurement.storage.eis_sync_journal import EisSyncJournal
    from procurement.storage.repository import PostgresStorage

MAX_DAYS_PER_RUN = 31
_SAFE_FAILURE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")


def recent_completed_date_range(
    now: datetime, utc_offset_hours: int, days: int
) -> tuple[date, date]:
    """Anchor a rolling run to local completed dates, never the live day."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if not -12 <= utc_offset_hours <= 14 or not 1 <= days <= MAX_DAYS_PER_RUN:
        raise ValueError("BACKFILL_RANGE_INVALID")
    last_day = now.astimezone(timezone(timedelta(hours=utc_offset_hours))).date()
    last_day -= timedelta(days=1)
    return last_day - timedelta(days=days - 1), last_day


@dataclass(frozen=True)
class EisNoDataObservation:
    day: date
    source_response_sha256: str


@dataclass(frozen=True)
class EisBackfillSummary:
    region: str
    first_day: date
    last_day: date
    completed_days: int
    synced_days: int
    skipped_days: int
    archive_count: int
    notice_count: int
    new_versions: int
    document_type: str = DEFAULT_NOTICE_TYPE
    new_events: int = 0
    no_data_observations: tuple[EisNoDataObservation, ...] = ()
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


class EisBackfillIncomplete(ValueError):
    """A dated source gap remains; preceding successful dates are durable."""

    def __init__(self, day: date, code: str, completed_days: int) -> None:
        self.day = day
        self.code = code
        self.completed_days = completed_days
        super().__init__(code)


def _validate_dates(first_day: date, last_day: date, utc_offset_hours: int, now: datetime) -> int:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if not -12 <= utc_offset_hours <= 14:
        raise ValueError("BACKFILL_RANGE_INVALID")
    day_count = (last_day - first_day).days + 1
    local_today = now.astimezone(timezone(timedelta(hours=utc_offset_hours))).date()
    if not 1 <= day_count <= MAX_DAYS_PER_RUN or last_day >= local_today:
        raise ValueError("BACKFILL_RANGE_INVALID")
    return day_count


async def backfill_eis_dates(
    storage: PostgresStorage,
    company_id: str,
    actor_id: str,
    region: str,
    first_day: date,
    last_day: date,
    utc_offset_hours: int,
    token: str,
    *,
    now: datetime | None = None,
    between_dates_seconds: float = 1,
    journal: EisSyncJournal | None = None,
    document_type: str = DEFAULT_NOTICE_TYPE,
) -> EisBackfillSummary:
    """Import at most 31 past dates, stopping on a transport or service failure."""
    if not 0 <= between_dates_seconds <= 60:
        raise ValueError("BACKFILL_DELAY_INVALID")
    reference_time = now or datetime.now(UTC)
    count = _validate_dates(first_day, last_day, utc_offset_hours, reference_time)
    selections = tuple(
        EisDateSelection(
            region, first_day + timedelta(days=offset), utc_offset_hours, document_type
        )
        for offset in range(count)
    )
    if journal is not None:
        if journal.company_id != company_id or journal.actor_id != actor_id:
            raise ValueError("JOURNAL_SCOPE_MISMATCH")
        journal.plan(selections)
    completed: list[EisHourSyncResult] = []
    no_data_observations: list[EisNoDataObservation] = []
    for offset, selection in enumerate(selections):
        day = selection.day
        if offset:
            await asyncio.sleep(between_dates_seconds)
        try:
            result = await sync_eis_window_via_browser(
                storage, company_id, actor_id, selection, token
            )
        except (EisSyncError, EisFeedArchiveError, EisIndexConflict) as error:
            code = str(error)
            safe_code = code if _SAFE_FAILURE.fullmatch(code) else "SOURCE_FAILURE"
            if journal is not None:
                journal.record(selection.window_key, "FAILED", reason_code=safe_code)
            raise EisBackfillIncomplete(day, safe_code, len(completed)) from error
        except SQLAlchemyError as error:
            if journal is not None:
                journal.record(selection.window_key, "FAILED", reason_code="DATABASE_FAILED")
            raise EisBackfillIncomplete(day, "DATABASE_FAILED", len(completed)) from error
        if result.status == "NO_DATA":
            if result.source_response_sha256 is None:
                if journal is not None:
                    journal.record(
                        selection.window_key, "FAILED", reason_code="NO_DATA_EVIDENCE_MISSING"
                    )
                raise EisBackfillIncomplete(day, "NO_DATA_EVIDENCE_MISSING", len(completed))
            if journal is not None:
                journal.record(
                    selection.window_key,
                    "NO_DATA",
                    source_response_sha256=result.source_response_sha256,
                )
            no_data_observations.append(EisNoDataObservation(day, result.source_response_sha256))
            continue
        if journal is not None:
            journal.record(
                selection.window_key,
                result.status,
                source_response_sha256=result.source_response_sha256,
            )
        if result.status not in {"SYNCED", "SKIPPED"}:
            raise EisBackfillIncomplete(day, result.status, len(completed))
        completed.append(result)
    return EisBackfillSummary(
        region=region,
        first_day=first_day,
        last_day=last_day,
        completed_days=len(completed),
        synced_days=sum(item.status == "SYNCED" for item in completed),
        skipped_days=sum(item.status == "SKIPPED" for item in completed),
        archive_count=sum(item.archive_count for item in completed),
        notice_count=sum(item.notice_count for item in completed),
        new_versions=sum(item.new_versions for item in completed),
        document_type=document_type,
        new_events=sum(item.new_events for item in completed),
        no_data_observations=tuple(no_data_observations),
    )
