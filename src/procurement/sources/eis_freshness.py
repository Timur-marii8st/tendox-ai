"""Bounded current-day hour intake and reconciliation, independent of backfill."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_corpus import EisCorpusScope, resource_gate
from procurement.sources.eis_feed_archive import SUPPORTED_NOTICE_TYPES, EisFeedArchiveError
from procurement.sources.eis_feed_sync import (
    EisDateSelection,
    EisFeedTransport,
    EisHourSelection,
    EisHourSyncResult,
    EisRejectedWindowError,
    EisSelection,
    EisSyncError,
    sync_eis_window,
    sync_eis_window_via_browser,
)
from procurement.sources.eis_freshness_status import EisWindowObservation
from procurement.storage.eis_notice_index import EisIndexConflict
from procurement.storage.eis_sync_journal import EisAttemptOutcome, EisSyncJournal
from procurement.storage.models import eis_sync_attempts

_SAFE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_SOURCE_CONFLICTS = frozenset(
    {
        "DUPLICATE_NOTICE_VERSION",
        "DUPLICATE_NOTICE_VERSION_IN_WINDOW",
        "DUPLICATE_PROCEDURE_EVENT",
        "DUPLICATE_PROCEDURE_EVENT_IN_WINDOW",
        "NOTICE_VERSION_CONFLICT",
        "TRANSPORT_WINDOW_NOT_CANONICAL",
        "PROCEDURE_EVENT_CONFLICT",
        "WINDOW_REPLAY_CONFLICT",
    }
)
_LOCAL_WINDOW_LIMITS = frozenset(
    {"ARCHIVE_WINDOW_COUNT_LIMIT", "ARCHIVE_WINDOW_SIZE_LIMIT", "ATTACHMENT_METADATA_COUNT_LIMIT"}
)


@dataclass(frozen=True)
class FreshnessTarget:
    selection: EisSelection
    lane: Literal["RECENT_HOUR", "RECONCILE_DAY", "EARLIER_HOUR"]
    interval: timedelta
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.expires_at is not None and (
            self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None
        ):
            raise ValueError("TARGET_EXPIRY_TIMEZONE_MISSING")


@dataclass(frozen=True)
class EisFreshnessScope:
    regions: tuple[str, ...]
    document_types: tuple[str, ...] = SUPPORTED_NOTICE_TYPES
    utc_offset_hours: int = 3
    reconcile_days: int = 3

    def targets(self, now: datetime) -> tuple[FreshnessTarget, ...]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        if not 1 <= self.reconcile_days <= 7:
            raise ValueError("FRESHNESS_SCOPE_INVALID")
        local = now.astimezone(timezone(timedelta(hours=self.utc_offset_hours)))
        yesterday = local.date() - timedelta(days=1)
        # Reuse the validated region/type contract; current-day hours are separate.
        EisCorpusScope(
            self.regions, self.document_types, yesterday, yesterday, self.utc_offset_hours
        ).validate(now)
        result: list[FreshnessTarget] = []
        # ADR-0044 / official oneHourInfo: start must be MORE than two hours old.
        # A small margin also avoids boundary/clock skew requests.
        latest_start = local - timedelta(hours=2, minutes=5)
        eligible_hours = (
            range(latest_start.hour, -1, -1) if latest_start.date() == local.date() else ()
        )
        for hour in eligible_hours:
            recent = hour >= latest_start.hour - 1
            for region in self.regions:
                for kind in self.document_types:
                    result.append(
                        FreshnessTarget(
                            EisHourSelection(
                                region, local.date(), hour, self.utc_offset_hours, kind
                            ),
                            "RECENT_HOUR" if recent else "EARLIER_HOUR",
                            timedelta(hours=1 if recent else 6),
                        )
                    )
        for days in range(1, self.reconcile_days + 1):
            for region in self.regions:
                for kind in self.document_types:
                    result.append(
                        FreshnessTarget(
                            EisDateSelection(
                                region,
                                local.date() - timedelta(days=days),
                                self.utc_offset_hours,
                                kind,
                            ),
                            "RECONCILE_DAY",
                            timedelta(hours=24),
                        )
                    )
        return tuple(result)


def due_target(
    target: FreshnessTarget,
    *,
    now: datetime,
    attempted_at: datetime | None,
    outcome: str | None,
    reason: str | None = None,
) -> bool:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    if attempted_at is None:
        return True
    if attempted_at.tzinfo is None or attempted_at.utcoffset() is None:
        raise ValueError("ATTEMPT_TIMEZONE_MISSING")
    interval = (
        timedelta(minutes=15)
        if outcome in {"FAILED", "PREPARING", "SERVICE_ERROR", "SKIPPED"}
        else target.interval
    )
    if outcome == "FAILED" and reason in _SOURCE_CONFLICTS | _LOCAL_WINDOW_LIMITS:
        interval = timedelta(hours=24)
    # NO_DATA is a source observation, not a successful corpus checkpoint.
    return now - attempted_at >= interval


def eligible_freshness(
    journal: EisSyncJournal, scope: EisFreshnessScope, *, now: datetime, limit: int
) -> tuple[FreshnessTarget, ...]:
    """Persist the worker's scope, then select with the same rules as its read probe."""
    if not 1 <= limit <= 1000:
        raise ValueError("FRESHNESS_LIMIT_INVALID")
    targets = scope.targets(now)
    selections = tuple(target.selection for target in targets)
    for offset in range(0, len(selections), 31):
        journal.plan(selections[offset : offset + 31])
    return read_due_freshness(journal, scope, now=now, limit=limit)


def read_due_freshness(
    journal: EisSyncJournal, scope: EisFreshnessScope, *, now: datetime, limit: int
) -> tuple[FreshnessTarget, ...]:
    """Read attempts without planning; a missing target is unattempted due work."""
    if not 1 <= limit <= 1000:
        raise ValueError("FRESHNESS_LIMIT_INVALID")
    targets = scope.targets(now)
    attempt = eis_sync_attempts
    with journal.storage.transaction(journal.company_id, consistent_read=True) as connection:
        rows = (
            connection.execute(
                select(
                    attempt.c.window_key,
                    attempt.c.attempted_at,
                    attempt.c.outcome,
                    attempt.c.reason_code,
                )
                .where(
                    and_(
                        attempt.c.company_id == journal.company_id,
                        attempt.c.window_key.in_([item.selection.window_key for item in targets]),
                    )
                )
                .distinct(attempt.c.window_key)
                .order_by(
                    attempt.c.window_key, attempt.c.attempted_at.desc(), attempt.c.attempt_id.desc()
                )
            )
            .mappings()
            .all()
        )
    attempts = {row["window_key"]: row for row in rows}
    empty: dict[str, Any] = {}
    due = [
        item
        for item in targets
        if due_target(
            item,
            now=now,
            attempted_at=attempts.get(item.selection.window_key, empty).get("attempted_at"),
            outcome=attempts.get(item.selection.window_key, empty).get("outcome"),
            reason=attempts.get(item.selection.window_key, empty).get("reason_code"),
        )
    ]
    lanes = {"RECENT_HOUR": 0, "RECONCILE_DAY": 1, "EARLIER_HOUR": 2}
    due.sort(
        key=lambda item: (
            lanes[item.lane],
            attempts.get(item.selection.window_key, empty).get("attempted_at")
            or datetime.min.replace(tzinfo=now.tzinfo),
            # Stable targets ordering gives newest unattempted hour first.
        )
    )
    return tuple(due[:limit])


@dataclass(frozen=True)
class EisFreshnessReport:
    status: Literal["PARTIAL", "BLOCKED"]
    company_id: str
    checked_at: datetime
    regions: tuple[str, ...]
    document_types: tuple[str, ...]
    selected: int
    attempted: int
    synced: int
    no_data: int
    new_versions: int
    new_events: int
    reason: str | None
    window_keys: tuple[str, ...]
    source_error_code: int | None = None
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"
    failed: int = 0
    observations: tuple[EisWindowObservation, ...] = ()
    expired_targets: int = 0
    partial_windows: int = 0
    held_pairs: int = 0
    replayed_projection_batches: int = 0


def _observe(
    journal: EisSyncJournal,
    target: FreshnessTarget,
    started_at: datetime,
    started: float,
    outcome: EisAttemptOutcome,
    *,
    reason: str | None = None,
    response_sha256: str | None = None,
    result: EisHourSyncResult | None = None,
    rejection: EisRejectedWindowError | None = None,
) -> EisWindowObservation:
    return EisWindowObservation(
        company_id=journal.company_id,
        window_key=target.selection.window_key,
        region=target.selection.region,
        document_type=target.selection.document_type,
        lane=target.lane,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        duration_ms=Decimal(str((time.monotonic() - started) * 1000)).quantize(Decimal("0.001")),
        outcome=outcome,
        reason=reason,
        response_sha256=response_sha256,
        archive_bytes=result.archive_bytes if result else None,
        new_versions=result.new_versions
        if result
        else rejection.variant_intake.new_versions
        if rejection
        else 0,
        new_events=result.new_events if result else 0,
        rejection_manifest_sha256=rejection.evidence.manifest_sha256
        if rejection and rejection.evidence
        else None,
        rejection_retention_status=rejection.evidence.status
        if rejection and rejection.evidence
        else "UNAVAILABLE"
        if rejection
        else None,
        rejection_audit_status=rejection.audit_status if rejection else None,
        rejection_diagnosis_sha256=rejection.diagnosis.sha256
        if rejection and rejection.diagnosis
        else None,
        rejection_diagnosis_audit_status=rejection.diagnosis_audit_status if rejection else None,
        variant_intake=rejection.variant_intake if rejection else None,
    )


async def run_freshness(
    journal: EisSyncJournal,
    token: str,
    scope: EisFreshnessScope,
    *,
    now: datetime,
    max_windows: int = 24,
    max_seconds: int = 240,
    max_database_bytes: int = 100 * 1024**3,
    min_free_bytes: int = 40 * 1024**3,
    transport: EisFeedTransport | None = None,
    include_requests: bool = False,
) -> EisFreshnessReport:
    scope.targets(now)  # Validate time/scope even when a resource gate blocks intake.
    if not 1 <= max_seconds <= 3600 or not 1 <= max_windows <= 1000:
        raise ValueError("FRESHNESS_BUDGET_INVALID")
    keys: list[str] = []
    attempted = synced = no_data = new_versions = new_events = 0
    source_error_code = None
    observations: list[EisWindowObservation] = []
    failed = 0
    partial_windows = held_pairs = replayed_projection_batches = 0
    stopped = resource_gate(
        journal.storage,
        journal.company_id,
        max_database_bytes=max_database_bytes,
        min_free_bytes=min_free_bytes,
    )
    targets = () if stopped else eligible_freshness(journal, scope, now=now, limit=max_windows)
    if not stopped and include_requests:
        from procurement.storage.eis_freshness_requests import fair_targets, pending_refresh_targets

        targets = fair_targets(
            pending_refresh_targets(journal, now=now), targets, limit=max_windows
        )
    started = time.monotonic()
    expired = 0
    for target in targets:
        if target.expires_at is not None and datetime.now(UTC) >= target.expires_at:
            expired += 1
            continue
        if time.monotonic() - started >= max_seconds:
            stopped = "RUN_TIME_BUDGET_REACHED"
            break
        stopped = resource_gate(
            journal.storage,
            journal.company_id,
            max_database_bytes=max_database_bytes,
            min_free_bytes=min_free_bytes,
        )
        if stopped:
            break
        key = target.selection.window_key
        attempted += 1
        keys.append(key)
        window_started_at = datetime.now(UTC)
        window_started = time.monotonic()
        try:
            if transport is None:
                result = await sync_eis_window_via_browser(
                    journal.storage,
                    journal.company_id,
                    journal.actor_id,
                    target.selection,
                    token,
                    refresh=True,
                )
            else:
                result = await sync_eis_window(
                    journal.storage,
                    journal.company_id,
                    journal.actor_id,
                    target.selection,
                    token,
                    transport,
                    refresh=True,
                )
        except (EisSyncError, EisFeedArchiveError, EisIndexConflict) as error:
            raw = str(error)
            reason = raw if _SAFE.fullmatch(raw) else "SOURCE_FAILURE"
            observation = _observe(
                journal,
                target,
                window_started_at,
                window_started,
                "FAILED",
                reason=reason,
                response_sha256=getattr(error, "source_response_sha256", None),
                rejection=error if isinstance(error, EisRejectedWindowError) else None,
            )
            observations.append(observation)
            failed += 1
            journal.record(
                key,
                "FAILED",
                reason_code=reason,
                observation=observation,
                source_response_sha256=observation.response_sha256,
            )
            if isinstance(error, EisRejectedWindowError):
                intake = error.variant_intake
                if intake.status == "PARTIAL" and intake.projection is not None:
                    partial_windows += 1
                    new_versions += intake.new_versions
                    held_pairs += intake.projection.held_count
                    replayed_projection_batches += int(intake.projection.replayed)
                elif intake.status == "FAILED":
                    stopped = intake.reason
                    break
            if (
                isinstance(error, (EisFeedArchiveError, EisIndexConflict))
                or reason in _LOCAL_WINDOW_LIMITS | _SOURCE_CONFLICTS
            ):
                # Keep the rejected atomic window as a gap; other sources can progress.
                pass
            else:
                stopped = reason
                break
        except SQLAlchemyError:
            stopped = "DATABASE_FAILED"
            break
        else:
            source_error_code = result.source_error_code
            observation = _observe(
                journal,
                target,
                window_started_at,
                window_started,
                result.status,
                response_sha256=result.source_response_sha256,
                result=result,
                reason=f"SOURCE_SERVICE_ERROR_{source_error_code}"
                if result.status == "SERVICE_ERROR"
                else None,
            )
            observations.append(observation)
            journal.record(
                key,
                result.status,
                reason_code=(
                    f"SOURCE_SERVICE_ERROR_{source_error_code}"
                    if result.status == "SERVICE_ERROR" and source_error_code is not None
                    else None
                ),
                source_response_sha256=result.source_response_sha256,
                observation=observation,
            )
            synced += int(result.status == "SYNCED")
            no_data += int(result.status == "NO_DATA")
            new_versions += result.new_versions
            new_events += result.new_events
            if result.status == "SERVICE_ERROR":
                stopped = "SOURCE_SERVICE_ERROR"
                break
        await asyncio.sleep(2)
    return EisFreshnessReport(
        "BLOCKED" if stopped else "PARTIAL",
        journal.company_id,
        now,
        tuple(sorted(set(scope.regions) | {item.selection.region for item in targets})),
        tuple(
            sorted(set(scope.document_types) | {item.selection.document_type for item in targets})
        ),
        len(targets),
        attempted,
        synced,
        no_data,
        new_versions,
        new_events,
        stopped,
        tuple(keys),
        source_error_code,
        failed=failed,
        observations=tuple(observations),
        expired_targets=expired,
        partial_windows=partial_windows,
        held_pairs=held_pairs,
        replayed_projection_batches=replayed_projection_batches,
    )
