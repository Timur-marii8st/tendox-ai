"""Bounded current-day hour intake and reconciliation, independent of backfill."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import and_, select, text
from sqlalchemy.exc import SQLAlchemyError

from procurement.eis_joint_budget import NATIONAL_RECOVERY_START, JointStartBudget
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
    checkpointed: bool = False
    mandatory_only: bool = False
    urgent_only: bool = False

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
    if scope.checkpointed:
        return checkpoint_due_freshness(journal, scope, now=now, limit=limit, plan=True)
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
    if scope.checkpointed:
        return checkpoint_due_freshness(journal, scope, now=now, limit=limit, plan=False)
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


def checkpoint_due_freshness(
    journal: EisSyncJournal,
    scope: EisFreshnessScope,
    *,
    now: datetime,
    limit: int,
    plan: bool,
) -> tuple[FreshnessTarget, ...]:
    """Bounded urgent lookup precedes and survives deferred historical work."""
    scope.targets(now)
    journal.freshness_recovery_reason = None
    zone = timezone(timedelta(hours=scope.utc_offset_hours))
    latest = (now.astimezone(zone) - timedelta(hours=2, minutes=5)).replace(
        minute=0, second=0, microsecond=0
    )
    candidates = tuple(
        FreshnessTarget(
            EisHourSelection(r, h.date(), h.hour, scope.utc_offset_hours, k),
            "RECENT_HOUR",
            timedelta(days=1),
        )
        for h in ((latest, latest - timedelta(hours=1)) if scope.urgent_only else (latest,))
        for r in scope.regions
        for k in scope.document_types
    )
    with journal.storage.transaction(journal.company_id, consistent_read=True) as conn:
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        rows = (
            conn.execute(
                select(eis_sync_attempts)
                .where(
                    eis_sync_attempts.c.company_id == journal.company_id,
                    eis_sync_attempts.c.window_key.in_(
                        [t.selection.window_key for t in candidates]
                    ),
                )
                .distinct(eis_sync_attempts.c.window_key)
                .order_by(
                    eis_sync_attempts.c.window_key,
                    eis_sync_attempts.c.attempted_at.desc(),
                    eis_sync_attempts.c.attempt_id.desc(),
                )
            )
            .mappings()
            .all()
        )
    observed = {r["window_key"]: r for r in rows}
    fresh = []
    for t in candidates:
        row = observed.get(t.selection.window_key)
        if row and row["outcome"] in {"SYNCED", "NO_DATA"} and row["source_response_sha256"]:
            continue
        if due_target(
            t,
            now=now,
            attempted_at=row["attempted_at"] if row else None,
            outcome=row["outcome"] if row else None,
            reason=row["reason_code"] if row else None,
        ):
            fresh.append(t)
    if plan:
        selections = [t.selection for t in candidates] + [
            EisDateSelection(
                r, now.astimezone(zone).date() - timedelta(days=1), scope.utc_offset_hours, k
            )
            for r in scope.regions
            for k in scope.document_types
        ]
        for offset in range(0, len(selections), 31):
            journal.plan(tuple(selections[offset : offset + 31]))
    if scope.urgent_only:
        return tuple(fresh[:limit])
    if len(fresh) >= limit:
        journal.freshness_recovery_reason = "DEFERRED_FOR_NEW_HOURS"
        return tuple(fresh[:limit])
    try:
        return _checkpoint_recovery_due(journal, scope, now=now, limit=limit, plan=plan)
    except SQLAlchemyError as error:
        if getattr(getattr(error, "orig", None), "sqlstate", None) != "57014":
            raise
        journal.freshness_recovery_reason = "RECOVERY_QUERY_TIMEOUT"
        return tuple(fresh)


def _checkpoint_recovery_due(
    journal: EisSyncJournal,
    scope: EisFreshnessScope,
    *,
    now: datetime,
    limit: int,
    plan: bool,
) -> tuple[FreshnessTarget, ...]:
    """Durable coordinate observations; missing hours recover through full days.

    No cursor acknowledges source data. Each available hour is planned before
    capture; missed calendar dates become durable daily reconciliation debt.
    An evidenced final-day observation closes debt, without claiming coverage.
    """
    if not 1 <= limit <= 1000:
        raise ValueError("FRESHNESS_LIMIT_INVALID")
    scope.targets(now)
    zone = timezone(timedelta(hours=scope.utc_offset_hours))
    local = now.astimezone(zone)
    latest = (local - timedelta(hours=2, minutes=5)).replace(minute=0, second=0, microsecond=0)
    latest_targets = tuple(
        FreshnessTarget(
            EisHourSelection(r, latest.date(), latest.hour, scope.utc_offset_hours, k),
            "RECENT_HOUR",
            timedelta(days=1),
        )
        for r in scope.regions
        for k in scope.document_types
    )
    params = {
        "co": journal.company_id,
        "regions": list(scope.regions),
        "types": list(scope.document_types),
        "now": now,
        "yesterday": local.date() - timedelta(days=1),
        "blocked_reasons": list(_SOURCE_CONFLICTS | _LOCAL_WINDOW_LIMITS),
        "offset": f"{scope.utc_offset_hours:+03d}:00",
        "limit": 1000,
        "mandatory": scope.mandatory_only,
        "reconcile_days": scope.reconcile_days,
        "recovery_start": NATIONAL_RECOVERY_START,
    }
    # All rowsets and database phases are bounded. Old terminal hourly history
    # never enters Python. The fixed SQL deadline is part of the240s start budget.
    hour_pattern = (
        r"^getDocsIP/PRIZ/[0-9]{1,2}/[0-9]{4}-[0-9]{2}-[0-9]{2}/"
        r"[0-9]{2}[+-][0-9]{2}:00(/[^/]+)?$"
    )
    day_pattern = (
        r"^getDocsIP/PRIZ/[0-9]{1,2}/[0-9]{4}-[0-9]{2}-[0-9]{2}"
        r"[+-][0-9]{2}:00(/[^/]+)?$"
    )
    # Latest observations and evidenced successes are scanned once per bounded
    # phase, rather than once for every retained target. Keep DISTINCT ON inline:
    # materializing it loses its uniqueness and can multiply planner estimates.
    observations = """
        WITH observations AS NOT MATERIALIZED (
            SELECT DISTINCT ON (window_key) window_key,attempted_at,outcome,
                   reason_code,source_response_sha256,
                   max(attempted_at) FILTER (WHERE outcome IN ('SYNCED','NO_DATA')
                       AND source_response_sha256 IS NOT NULL)
                       OVER (PARTITION BY window_key) AS last_evidenced
            FROM eis_sync_attempts WHERE company_id=:co
            ORDER BY window_key,attempted_at DESC,attempt_id DESC
        )
    """
    latest_attempt = "LEFT JOIN observations a ON a.window_key=t.window_key"
    rows = []
    with journal.storage.transaction(journal.company_id, consistent_read=True) as conn:
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        # Earliest retained coordinate start is never advanced past a missing
        # completed date. Index-ordered first-row lookups avoid full-ledger reads.
        missing = (
            conn.execute(
                text("""
            WITH starts AS MATERIALIZED (
                SELECT split_part(window_key,'/',3) AS r,
                       COALESCE(NULLIF(split_part(window_key,'/',6),''),
                                'epNotificationEF2020') AS k,
                       min(substring(window_key,'[0-9]{4}-[0-9]{2}-[0-9]{2}'))::date
                           AS first_day
                FROM eis_sync_targets WHERE company_id=:co AND window_key ~ :hour_pattern
                  AND split_part(window_key,'/',3)=ANY(:regions)
                  AND right(split_part(window_key,'/',5),6)=:offset
                  AND COALESCE(NULLIF(split_part(window_key,'/',6),''),
                               'epNotificationEF2020')=ANY(:types)
                GROUP BY r,k
            )
            SELECT 'getDocsIP/PRIZ/'||r||'/'||to_char(d,'YYYY-MM-DD')||:offset||
                   CASE WHEN k='epNotificationEF2020' THEN '' ELSE '/'||k END AS window_key
            FROM starts JOIN LATERAL generate_series(first_day::timestamp,
                 CAST(:yesterday AS timestamp),interval '1 day') d ON true
            WHERE NOT EXISTS(
                SELECT 1 FROM eis_sync_targets t WHERE company_id=:co
                AND window_key='getDocsIP/PRIZ/'||r||'/'||to_char(d,'YYYY-MM-DD')||:offset||
                    CASE WHEN k='epNotificationEF2020' THEN '' ELSE '/'||k END
            )
            ORDER BY d,r,k LIMIT 31
        """),
                {**params, "hour_pattern": hour_pattern},
            )
            .scalars()
            .all()
        )
        for pattern, suffix, hourly in ((hour_pattern, 6, True), (day_pattern, 5, False)):
            condition = (
                "(a.outcome IS NULL OR a.outcome NOT IN ('SYNCED','NO_DATA') "
                "OR a.source_response_sha256 IS NULL)"
                if hourly
                else "(a.outcome IS NULL OR a.outcome NOT IN ('SYNCED','NO_DATA') "
                "OR a.source_response_sha256 IS NULL "
                "OR a.attempted_at < ((substring(t.window_key,"
                "'[0-9]{4}-[0-9]{2}-[0-9]{2}')||'T00:00:00'||:offset)::timestamptz"
                "+interval '1 day 2 hours 5 minutes') "
                "OR (substring(t.window_key,'[0-9]{4}-[0-9]{2}-[0-9]{2}')::date"
                ">=CAST(:yesterday AS date)-2 AND a.attempted_at<=:now-interval '24 hours'))"
            )
            cutoff = (
                "((substring(t.window_key,'[0-9]{4}-[0-9]{2}-[0-9]{2}')"
                "||'T00:00:00'||:offset)::timestamptz+interval '1 day 2 hours 5 minutes')"
            )
            final_debt = (
                "false"
                if hourly
                else (
                    f"({cutoff} <= :now AND (a.last_evidenced < {cutoff} OR "
                    "(a.last_evidenced IS NULL AND substring(t.window_key,"
                    "'[0-9]{4}-[0-9]{2}-[0-9]{2}')::date >= :recovery_start)))"
                )
            )
            day_key = (
                "'getDocsIP/PRIZ/'||split_part(t.window_key,'/',3)||'/'||"
                "split_part(t.window_key,'/',4)||:offset||CASE "
                "WHEN split_part(t.window_key,'/',6)='' THEN '' "
                "ELSE '/'||split_part(t.window_key,'/',6) END"
            )
            daily_join = f"LEFT JOIN observations d ON d.window_key={day_key}" if hourly else ""
            daily_credit = (
                f"AND (d.last_evidenced IS NULL OR d.last_evidenced < {cutoff})" if hourly else ""
            )
            horizon = (
                "CAST(:yesterday AS date)"
                if hourly
                else "CAST(:yesterday AS date)+1-:reconcile_days"
            )
            day_order = "DESC" if hourly else "ASC"
            statement = (
                observations
                + f"""
                SELECT t.window_key,a.attempted_at,a.outcome,a.reason_code,
                       a.source_response_sha256,COALESCE({final_debt},false) AS final_debt
                FROM eis_sync_targets t {latest_attempt} {daily_join}
                WHERE t.company_id=:co
                  AND split_part(t.window_key,'/',3)=ANY(:regions)
                  AND COALESCE(NULLIF(split_part(t.window_key,'/',{suffix}),''),
                               'epNotificationEF2020')=ANY(:types)
                  AND t.window_key ~ :pattern AND {condition} {daily_credit}
                  AND right(split_part(t.window_key,'/',{5 if hourly else 4}),6)=:offset
                  AND (NOT :mandatory OR
                       substring(t.window_key,'[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}')::date
                       >= {horizon} OR {final_debt})
                  AND (a.attempted_at IS NULL OR a.outcome IN ('SYNCED','NO_DATA')
                       OR a.attempted_at <= :now-CASE
                         WHEN a.outcome='FAILED' AND a.reason_code=ANY(:blocked_reasons)
                         THEN interval '24 hours' ELSE interval '15 minutes' END)
                  AND substring(t.window_key,'[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}')::date
                      <= CAST(:yesterday AS date)+1
                ORDER BY substring(t.window_key,'[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}') {day_order},
                         split_part(t.window_key,'/',5) DESC,t.window_key
                LIMIT :limit
            """
            )
            rows += list(conn.execute(text(statement), {**params, "pattern": pattern}).mappings())
    # Current/latest full-day debt is materialized even when an outage created
    # no hourly targets at all. The existing durable daily planner covers old
    # dates before this national scope's retained start.
    yesterday_targets = tuple(
        EisDateSelection(r, local.date() - timedelta(days=1), scope.utc_offset_hours, k)
        for r in scope.regions
        for k in scope.document_types
    )

    def selection(key: str) -> EisSelection:
        pieces = key.split("/")
        day = datetime.fromisoformat(pieces[3][:10]).date()
        if len(pieces[3]) == 10:
            return EisHourSelection(
                pieces[2],
                day,
                int(pieces[4][:2]),
                scope.utc_offset_hours,
                pieces[5] if len(pieces) == 6 else "epNotificationEF2020",
            )
        return EisDateSelection(
            pieces[2],
            day,
            scope.utc_offset_hours,
            pieces[4] if len(pieces) == 5 else "epNotificationEF2020",
        )

    missing_days = tuple(selection(k) for k in missing)
    if plan:
        pending = (
            [t.selection for t in latest_targets] + list(yesterday_targets) + list(missing_days)
        )
        pending = list({s.window_key: s for s in pending}.values())
        for offset in range(0, len(pending), 31):
            journal.plan(tuple(pending[offset : offset + 31]))
    attempts = {r["window_key"]: r for r in rows}
    candidates = {r["window_key"]: selection(r["window_key"]) for r in rows}
    candidates.update((s.window_key, s) for s in (*yesterday_targets, *missing_days))
    candidates.update((t.selection.window_key, t.selection) for t in latest_targets)
    # Read terminal latest-hour observations too: their absence from the
    # outstanding SQL result must not mean they have never been captured.
    with journal.storage.transaction(journal.company_id, consistent_read=True) as conn:
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        for row in conn.execute(
            select(eis_sync_attempts)
            .where(
                eis_sync_attempts.c.company_id == journal.company_id,
                eis_sync_attempts.c.window_key.in_(
                    [t.selection.window_key for t in latest_targets]
                    + [s.window_key for s in yesterday_targets]
                ),
            )
            .distinct(eis_sync_attempts.c.window_key)
            .order_by(
                eis_sync_attempts.c.window_key,
                eis_sync_attempts.c.attempted_at.desc(),
                eis_sync_attempts.c.attempt_id.desc(),
            )
        ).mappings():
            attempts[row["window_key"]] = row
    fresh: list[FreshnessTarget] = []
    recovery: list[FreshnessTarget] = []
    reconciliation: list[FreshnessTarget] = []
    for key, s in candidates.items():
        observed = attempts.get(key)
        terminal = bool(
            observed
            and observed["outcome"] in {"SYNCED", "NO_DATA"}
            and observed["source_response_sha256"]
        )
        if isinstance(s, EisHourSelection) and terminal:
            continue
        hour = datetime.combine(s.day, datetime.min.time(), zone) + timedelta(
            hours=getattr(s, "hour", 0)
        )
        if isinstance(s, EisHourSelection) and hour > latest:
            continue
        lane: Literal["RECENT_HOUR", "RECONCILE_DAY", "EARLIER_HOUR"] = (
            "RECENT_HOUR"
            if isinstance(s, EisHourSelection) and hour >= latest - timedelta(hours=1)
            else "EARLIER_HOUR"
            if isinstance(s, EisHourSelection)
            else "RECONCILE_DAY"
        )
        t = FreshnessTarget(s, lane, timedelta(days=1))
        final_cutoff = datetime.combine(s.day, datetime.min.time(), zone) + timedelta(
            days=1, hours=2, minutes=5
        )
        final_debt = (
            isinstance(s, EisDateSelection)
            and observed is not None
            and (
                observed.get("final_debt", False)
                or (terminal and observed["attempted_at"] < final_cutoff <= now)
            )
        )
        # A missed final observation remains mandatory even after a long restart.
        # Other old coordinates have the existing historical executor.
        if (
            scope.mandatory_only
            and not final_debt
            and s.day
            < local.date()
            - timedelta(days=scope.reconcile_days if isinstance(s, EisDateSelection) else 1)
        ):
            continue
        if not (final_debt and terminal) and not due_target(
            t,
            now=now,
            attempted_at=observed["attempted_at"] if observed else None,
            outcome=observed["outcome"] if observed else None,
            reason=observed["reason_code"] if observed else None,
        ):
            continue
        (
            fresh
            if lane == "RECENT_HOUR"
            else recovery
            if lane == "EARLIER_HOUR"
            else reconciliation
        ).append(t)
    fresh.sort(key=lambda t: (t.selection.day, getattr(t.selection, "hour", -1)), reverse=True)
    if scope.mandatory_only:
        # Mandatory daily rechecks share the turn, not an arbitrary one-eighth
        # residue. Older coordinates remain persisted for the historical lane.
        return tuple((fresh + reconciliation + recovery)[:limit])
    chosen = fresh[:limit]
    chosen += reconciliation[: min(limit - len(chosen), max(1, limit // 8))]
    chosen += recovery[: limit - len(chosen)]
    return tuple(chosen)


def read_due_reconciliation(
    journal: EisSyncJournal,
    scope: EisFreshnessScope,
    *,
    now: datetime,
    limit: int,
) -> tuple[FreshnessTarget, ...]:
    """Read only recent completed-day coordinates, with no historical-ledger scan."""
    scope.targets(now)
    if not 1 <= limit <= 1000:
        raise ValueError("FRESHNESS_LIMIT_INVALID")
    zone = timezone(timedelta(hours=scope.utc_offset_hours))
    local_day = now.astimezone(zone).date()
    selections = tuple(
        EisDateSelection(region, local_day - timedelta(days=days), scope.utc_offset_hours, kind)
        for days in range(1, scope.reconcile_days + 1)
        for region in scope.regions
        for kind in scope.document_types
        if datetime.combine(local_day - timedelta(days=days), datetime.min.time(), zone)
        + timedelta(days=1, hours=2, minutes=5)
        <= now
    )
    with journal.storage.transaction(journal.company_id, consistent_read=True) as conn:
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        rows = (
            conn.execute(
                select(eis_sync_attempts)
                .where(
                    eis_sync_attempts.c.company_id == journal.company_id,
                    eis_sync_attempts.c.window_key.in_([s.window_key for s in selections]),
                )
                .distinct(eis_sync_attempts.c.window_key)
                .order_by(
                    eis_sync_attempts.c.window_key,
                    eis_sync_attempts.c.attempted_at.desc(),
                    eis_sync_attempts.c.attempt_id.desc(),
                )
            )
            .mappings()
            .all()
        )
    attempts = {row["window_key"]: row for row in rows}
    due = []
    for selection in selections:
        row = attempts.get(selection.window_key)
        target = FreshnessTarget(selection, "RECONCILE_DAY", timedelta(days=1))
        cutoff = datetime.combine(selection.day, datetime.min.time(), zone) + timedelta(
            days=1,
            hours=2,
            minutes=5,
        )
        terminal = row and row["outcome"] in {"SYNCED", "NO_DATA"} and row["source_response_sha256"]
        if (terminal and row["attempted_at"] < cutoff) or due_target(
            target,
            now=now,
            attempted_at=row["attempted_at"] if row else None,
            outcome=row["outcome"] if row else None,
            reason=row["reason_code"] if row else None,
        ):
            due.append(target)
    due.sort(
        key=lambda t: (
            0
            if t.selection.window_key not in attempts
            else 2
            if attempts[t.selection.window_key]["outcome"] in {"SYNCED", "NO_DATA"}
            else 1,
            -t.selection.day.toordinal(),
            t.selection.window_key,
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
    recovery_reason: str | None = None


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
    paced_transport: bool = False,
    joint_budget: JointStartBudget | None = None,
) -> EisFreshnessReport:
    started = time.monotonic()
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
    pending_reconciliation: tuple[Literal["44", "223"], ...] = ()
    if (
        not stopped
        and joint_budget is not None
        and joint_budget.protected_reconciliation is True
        and scope.checkpointed
        and not scope.urgent_only
    ):
        from procurement.storage.eis_223_regions import regional_due_windows

        daily = read_due_reconciliation(journal, scope, now=now, limit=max_windows)
        daily223 = regional_due_windows(
            journal.storage,
            journal.company_id,
            now,
            limit=2,
            fresh_first=True,
            reconciliation_only=True,
        )
        pending_reconciliation = tuple(
            law for law, due in (("44", daily), ("223", daily223)) if due
        )
        if daily and joint_budget.recovery_reserved("44"):
            prefix = daily[: max(1, max_windows // 4)]
            for offset in range(0, len(prefix), 31):
                journal.plan(tuple(t.selection for t in prefix[offset : offset + 31]))
            selected = {t.selection.window_key for t in prefix}
            targets = prefix + tuple(t for t in targets if t.selection.window_key not in selected)
            targets = targets[:max_windows]
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
        recovery_law = "44" if target.lane != "RECENT_HOUR" else None
        if joint_budget is not None:
            borrow = False
            protected = (
                target.lane == "RECONCILE_DAY" and joint_budget.recovery_reserved("44") is True
            )
            if recovery_law and not protected:
                from procurement.storage.eis_223_regions import regional_due_windows

                if regional_due_windows(
                    journal.storage,
                    journal.company_id,
                    datetime.now(UTC),
                    limit=2,
                    fresh_first=True,
                    fresh_only=True,
                ):
                    stopped = "FRESH_223_WORK_READY"
                    break
                borrow = True
            if (
                recovery_law
                and not protected
                and read_due_freshness(
                    journal,
                    EisFreshnessScope(
                        scope.regions,
                        scope.document_types,
                        scope.utc_offset_hours,
                        checkpointed=True,
                        mandatory_only=True,
                        urgent_only=True,
                    ),
                    now=datetime.now(UTC),
                    limit=1,
                )
            ):
                stopped = "FRESH_WORK_READY"
                break
            if not joint_budget.can_start(
                recovery_law,
                borrow=borrow,
                pending_reconciliation=pending_reconciliation,
            ):
                stopped = "JOINT_START_BUDGET_REACHED"
                break
            joint_budget.begin_window(recovery_law)
        if time.monotonic() - started >= max_seconds:
            stopped = "RUN_TIME_BUDGET_REACHED"
            break
        key = target.selection.window_key
        attempted += 1
        keys.append(key)
        window_started_at = datetime.now(UTC)
        window_started = time.monotonic()
        try:
            if transport is None:
                request = sync_eis_window_via_browser(
                    journal.storage,
                    journal.company_id,
                    journal.actor_id,
                    target.selection,
                    token,
                    refresh=True,
                )
            else:
                request = sync_eis_window(
                    journal.storage,
                    journal.company_id,
                    journal.actor_id,
                    target.selection,
                    token,
                    transport,
                    refresh=True,
                )
            if joint_budget is None:
                result = await request
            else:
                try:
                    result = await asyncio.wait_for(request, timeout=180)
                except TimeoutError as error:
                    raise EisSyncError("RUN_TIME_BUDGET_REACHED") from error
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
        if joint_budget is not None:
            joint_budget.end_window()
        if not paced_transport:
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
        recovery_reason=journal.freshness_recovery_reason if scope.checkpointed else None,
    )
