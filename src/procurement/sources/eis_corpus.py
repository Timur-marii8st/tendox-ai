"""Resumable multi-region date queue; source completeness stays explicit UNKNOWN."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    and_,
    case,
    cast,
    exists,
    func,
    insert,
    literal,
    or_,
    select,
    true,
    union_all,
)
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_feed_archive import SUPPORTED_NOTICE_TYPES, EisFeedArchiveError
from procurement.sources.eis_feed_sync import (
    EisDateSelection,
    EisRejectedWindowError,
    EisSyncError,
    sync_eis_window,
    sync_eis_window_via_browser,
)
from procurement.storage.eis_notice_index import EisIndexConflict
from procurement.storage.eis_sync_journal import EisSyncJournal, latest_eis_attempts
from procurement.storage.models import (
    audit_events,
    eis_feed_windows,
    eis_sync_attempts,
    eis_sync_targets,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Connection
    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.selectable import CTE

    from procurement.sources.eis_feed_sync import EisFeedTransport
    from procurement.storage.repository import PostgresStorage

_KEY = re.compile(
    r"^getDocsIP/PRIZ/([0-9]{1,2})/([0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"([+-][0-9]{2}):00(?:/(epNotificationEZK2020|epNotificationEOK2020|epNotificationCancel|epNotificationCancelFailure))?$"
)
_SAFE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")


@dataclass(frozen=True)
class EisCorpusScope:
    regions: tuple[str, ...]
    document_types: tuple[str, ...]
    first_day: date
    last_day: date
    utc_offset_hours: int = 3
    # Addressable codes are candidate queries, not a verified region registry.
    region_registry_status: str = "UNKNOWN"
    source_completeness: str = "UNKNOWN"

    def validate(self, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("NOW_TIMEZONE_MISSING")
        if (
            not self.regions
            or len(self.regions) > 99
            or len(set(self.regions)) != len(self.regions)
            or any(
                not re.fullmatch(r"[0-9]{2}", code) or not 1 <= int(code) <= 99
                for code in self.regions
            )
            or not self.document_types
            or len(set(self.document_types)) != len(self.document_types)
            or any(kind not in SUPPORTED_NOTICE_TYPES for kind in self.document_types)
            or not -12 <= self.utc_offset_hours <= 14
            or self.region_registry_status != "UNKNOWN"
            or self.source_completeness != "UNKNOWN"
            or not 1 <= (self.last_day - self.first_day).days + 1 <= 366
        ):
            raise ValueError("CORPUS_SCOPE_INVALID")
        today = now.astimezone(timezone(timedelta(hours=self.utc_offset_hours))).date()
        if self.last_day >= today:
            raise ValueError("CORPUS_DATE_NOT_COMPLETED")

    @property
    def expected_windows(self) -> int:
        return (
            len(self.regions)
            * len(self.document_types)
            * ((self.last_day - self.first_day).days + 1)
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()

    def batches(self) -> Iterator[tuple[EisDateSelection, ...]]:
        """Newest dates first, with at most 31 targets per transaction."""
        batch: list[EisDateSelection] = []
        day = self.last_day
        while day >= self.first_day:
            for region in self.regions:
                for kind in self.document_types:
                    batch.append(EisDateSelection(region, day, self.utc_offset_hours, kind))
                    if len(batch) == 31:
                        yield tuple(batch)
                        batch.clear()
            day -= timedelta(days=1)
        if batch:
            yield tuple(batch)


def plan_corpus(
    journal: EisSyncJournal,
    scope: EisCorpusScope,
    *,
    now: datetime,
    base_scope_sha256: str | None = None,
) -> int:
    """Persist every requested window before network I/O; safe to repeat after interruption."""
    scope.validate(now)
    new = sum(journal.plan(batch) for batch in scope.batches())
    with journal.storage.transaction(journal.company_id) as connection:
        connection.execute(
            insert(audit_events).values(
                event_id=str(uuid.uuid4()),
                company_id=journal.company_id,
                actor_id=journal.actor_id,
                event_type="EIS_CORPUS_SCOPE_PLANNED",
                object_type="EIS_CORPUS_SCOPE",
                object_id=scope.sha256,
                basis={
                    "scope": json.loads(json.dumps(asdict(scope), default=str)),
                    "expected_windows": scope.expected_windows,
                    "new_targets": new,
                    "coverage": "UNKNOWN",
                    "base_scope_sha256": base_scope_sha256,
                },
                occurred_at=now,
            )
        )
    return new


def extend_corpus(journal: EisSyncJournal, base_sha256: str, *, now: datetime) -> int:
    """Catch up every missed date from a committed baseline, including after a long outage."""
    from pydantic import TypeAdapter

    if not re.fullmatch(r"[0-9a-f]{64}", base_sha256):
        raise ValueError("CORPUS_BASE_INVALID")
    with journal.storage.transaction(journal.company_id) as connection:
        basis = connection.scalar(
            select(audit_events.c.basis)
            .where(
                and_(
                    audit_events.c.company_id == journal.company_id,
                    audit_events.c.event_type == "EIS_CORPUS_SCOPE_PLANNED",
                    audit_events.c.object_id == base_sha256,
                )
            )
            .order_by(audit_events.c.occurred_at)
            .limit(1)
        )
        if basis is None:
            raise ValueError("CORPUS_BASE_MISSING")
        base = TypeAdapter(EisCorpusScope).validate_python(basis["scope"])
        base.validate(now)
        if base.sha256 != base_sha256:
            raise ValueError("CORPUS_BASE_MISMATCH")
        prior_day = connection.scalar(
            select(func.max(audit_events.c.basis["scope"]["last_day"].astext)).where(
                and_(
                    audit_events.c.company_id == journal.company_id,
                    audit_events.c.event_type == "EIS_CORPUS_SCOPE_PLANNED",
                    or_(
                        audit_events.c.object_id == base_sha256,
                        audit_events.c.basis["base_scope_sha256"].astext == base_sha256,
                    ),
                )
            )
        )
    assert prior_day is not None
    last_day = now.astimezone(timezone(timedelta(hours=base.utc_offset_hours))).date() - timedelta(
        days=1
    )
    first_day = max(base.first_day, date.fromisoformat(prior_day) - timedelta(days=2))
    new = 0
    while first_day <= last_day:
        through_day = min(last_day, first_day + timedelta(days=365))
        selected = EisCorpusScope(
            base.regions, base.document_types, first_day, through_day, base.utc_offset_hours
        )
        new += plan_corpus(journal, selected, now=now, base_scope_sha256=base_sha256)
        first_day = through_day + timedelta(days=1)
    return new


def parse_date_window(key: str) -> EisDateSelection:
    match = _KEY.fullmatch(key)
    if match is None:
        raise ValueError("CORPUS_WINDOW_INVALID")
    region, raw_day, offset, kind = match.groups()
    return EisDateSelection(
        region, date.fromisoformat(raw_day), int(offset), kind or "epNotificationEF2020"
    )


def historical_source_retry_clause(latest: CTE, now: datetime) -> ColumnElement[bool]:
    """Exact old-source transient eligibility; caller excludes canonical completions."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("CORPUS_QUEUE_INVALID")
    today = now.astimezone(timezone(timedelta(hours=3))).date()
    raw_day = func.substring(latest.c.window_key, r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
    source_day = case((func.pg_input_is_valid(raw_day, "date"), cast(raw_day, Date)), else_=None)
    return and_(
        latest.c.window_key.op("~")(_KEY.pattern),
        source_day < today - timedelta(days=7),
        source_day < today,
        latest.c.attempted_at <= now - timedelta(hours=24),
        or_(
            and_(
                latest.c.outcome == "FAILED",
                latest.c.reason_code.in_(("SOURCE_TRANSPORT_FAILED", "SOURCE_WSDL_UNAVAILABLE")),
            ),
            latest.c.outcome.in_(("SERVICE_ERROR", "PREPARING")),
        ),
    )


def eligible_windows(journal: EisSyncJournal, *, now: datetime, limit: int) -> tuple[str, ...]:
    """Reserve recent and historical retry lanes, then fill from the normal backlog."""
    if now.tzinfo is None or now.utcoffset() is None or not 1 <= limit <= 1000:
        raise ValueError("CORPUS_QUEUE_INVALID")
    target, attempt = eis_sync_targets, eis_sync_attempts
    moscow_today = now.astimezone(timezone(timedelta(hours=3))).date()
    recent_first_day = moscow_today - timedelta(days=7)
    recent_last_day = moscow_today - timedelta(days=1)
    repair_slots = min((limit + 4) // 5, 12, max(0, limit - 1))
    historical_slots = min((limit + 19) // 20, 3)
    raw_recent_day = func.substring(attempt.c.window_key, r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
    window_day = case(
        (func.pg_input_is_valid(raw_recent_day, "date"), cast(raw_recent_day, Date)), else_=None
    )
    ranked_attempts = (
        select(
            attempt.c.window_key,
            attempt.c.outcome,
            attempt.c.attempted_at,
            attempt.c.source_response_sha256,
            window_day.label("window_day"),
            func.row_number()
            .over(
                partition_by=attempt.c.window_key,
                order_by=(attempt.c.attempted_at.desc(), attempt.c.attempt_id.desc()),
            )
            .label("attempt_rank"),
        )
        .where(
            and_(
                attempt.c.company_id == journal.company_id,
                attempt.c.window_key.op("~")(_KEY.pattern),
                window_day.between(recent_first_day, recent_last_day),
            )
        )
        .cte("recent_ranked_attempts")
    )
    recent_completed = exists(
        select(eis_feed_windows.c.window_key).where(
            and_(
                eis_feed_windows.c.company_id == journal.company_id,
                eis_feed_windows.c.window_key == ranked_attempts.c.window_key,
                eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
            )
        )
    )
    recent_base = (
        select(
            ranked_attempts.c.window_key,
            func.row_number()
            .over(
                order_by=(
                    ranked_attempts.c.window_day.desc(),
                    ranked_attempts.c.attempted_at.asc(),
                    ranked_attempts.c.window_key,
                )
            )
            .label("position"),
        )
        .join(
            target,
            and_(
                target.c.company_id == journal.company_id,
                target.c.window_key == ranked_attempts.c.window_key,
            ),
        )
        .where(
            and_(
                ranked_attempts.c.attempt_rank == 1,
                ranked_attempts.c.outcome == "FAILED",
                ranked_attempts.c.attempted_at <= now - timedelta(hours=24),
                ~recent_completed,
            )
        )
        .cte("recent_failure_base")
    )
    no_data_cap = min((limit + 19) // 20, 3, max(0, repair_slots - 1))
    no_data_due = (
        select(
            ranked_attempts.c.window_key,
            func.row_number()
            .over(order_by=(ranked_attempts.c.attempted_at, ranked_attempts.c.window_key))
            .label("position"),
        )
        .join(
            target,
            and_(
                target.c.company_id == journal.company_id,
                target.c.window_key == ranked_attempts.c.window_key,
            ),
        )
        .where(
            ranked_attempts.c.attempt_rank == 1,
            ranked_attempts.c.outcome == "NO_DATA",
            ranked_attempts.c.source_response_sha256.op("~")(r"^[0-9a-f]{64}$"),
            ranked_attempts.c.attempted_at <= now - timedelta(hours=24),
            ~recent_completed,
        )
        .cte("recent_no_data_due")
    )
    no_data = (
        select(no_data_due.c.window_key, no_data_due.c.position)
        .where(no_data_due.c.position <= no_data_cap)
        .cte("recent_no_data_limited")
    )
    no_data_count = select(func.count()).select_from(no_data).scalar_subquery()
    repair_lanes = union_all(
        select(no_data.c.window_key, literal(0).label("lane"), no_data.c.position),
        select(recent_base.c.window_key, literal(1).label("lane"), recent_base.c.position).where(
            recent_base.c.position <= repair_slots - no_data_count
        ),
    ).cte("recent_repair_lanes")
    recent = select(
        repair_lanes.c.window_key,
        func.row_number()
        .over(order_by=(repair_lanes.c.lane, repair_lanes.c.position))
        .label("position"),
    ).cte("recent_repair_lane")
    historical_latest_attempts = (
        select(
            attempt.c.window_key,
            func.max(attempt.c.attempted_at).label("latest_at"),
        )
        .where(attempt.c.company_id == journal.company_id)
        .group_by(attempt.c.window_key)
        .cte("historical_latest_attempts")
    )
    completed = exists(
        select(eis_feed_windows.c.window_key).where(
            and_(
                eis_feed_windows.c.company_id == target.c.company_id,
                eis_feed_windows.c.window_key == target.c.window_key,
                eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
            )
        )
    )
    recent_count = select(func.count()).select_from(recent).scalar_subquery()
    latest = latest_eis_attempts(journal.company_id)
    raw_historical_day = func.substring(latest.c.window_key, r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
    historical_day = case(
        (func.pg_input_is_valid(raw_historical_day, "date"), cast(raw_historical_day, Date)),
        else_=None,
    )
    historical_ranked = (
        select(
            latest.c.window_key,
            latest.c.outcome,
            latest.c.reason_code,
            latest.c.attempted_at,
            historical_day.label("window_day"),
        )
        .where(historical_source_retry_clause(latest, now))
        .cte("historical_transient_latest")
    )
    historical_due = (
        select(
            historical_ranked.c.window_key,
            historical_ranked.c.attempted_at,
            historical_ranked.c.window_day,
        )
        .join(
            target,
            and_(
                target.c.company_id == journal.company_id,
                target.c.window_key == historical_ranked.c.window_key,
            ),
        )
        .where(
            ~completed,
        )
        .order_by(
            historical_ranked.c.attempted_at,
            historical_ranked.c.window_day.desc(),
            historical_ranked.c.window_key,
        )
        .limit(func.least(historical_slots, func.greatest(0, limit - recent_count - 1)))
        .cte("historical_transient_limited")
    )
    historical = select(
        historical_due.c.window_key,
        func.row_number()
        .over(
            order_by=(
                historical_due.c.attempted_at,
                historical_due.c.window_day.desc(),
                historical_due.c.window_key,
            )
        )
        .label("position"),
    ).cte("historical_transient_lane")
    historical_count = select(func.count()).select_from(historical).scalar_subquery()
    # Older empty replies lose the seven-day repair reserve. Give one of them an
    # early slot from ordinary fill, leaving all existing retry/new-date caps intact.
    older_empty_cap = int(limit >= 30)
    older_empty_due = (
        select(
            latest.c.window_key,
            func.row_number()
            .over(order_by=(latest.c.attempted_at, latest.c.window_key))
            .label("position"),
        )
        .join(
            target,
            and_(
                target.c.company_id == journal.company_id,
                target.c.window_key == latest.c.window_key,
            ),
        )
        .where(
            latest.c.window_key.op("~")(_KEY.pattern),
            historical_day < recent_first_day,
            latest.c.outcome == "NO_DATA",
            latest.c.source_response_sha256.op("~")(r"^[0-9a-f]{64}$"),
            latest.c.attempted_at <= now - timedelta(hours=24),
            ~completed,
        )
        .cte("older_no_data_due")
    )
    older_empty = (
        select(older_empty_due.c.window_key, older_empty_due.c.position)
        .where(older_empty_due.c.position <= older_empty_cap)
        .cte("older_no_data_reserved")
    )
    older_empty_count = select(func.count()).select_from(older_empty).scalar_subquery()
    old_limited = (
        select(
            target.c.window_key,
            historical_latest_attempts.c.latest_at.label("last_attempt"),
            func.substring(target.c.window_key, r"[0-9]{4}-[0-9]{2}-[0-9]{2}").label("window_day"),
        )
        .outerjoin(
            historical_latest_attempts,
            historical_latest_attempts.c.window_key == target.c.window_key,
        )
        .where(
            and_(
                target.c.company_id == journal.company_id,
                target.c.window_key.op("~")(_KEY.pattern),
                ~completed,
                or_(
                    historical_latest_attempts.c.latest_at.is_(None),
                    historical_latest_attempts.c.latest_at <= now - timedelta(hours=24),
                ),
                ~exists(
                    select(recent.c.window_key).where(recent.c.window_key == target.c.window_key)
                ),
                ~exists(
                    select(historical.c.window_key).where(
                        historical.c.window_key == target.c.window_key
                    )
                ),
                ~exists(
                    select(older_empty.c.window_key).where(
                        older_empty.c.window_key == target.c.window_key
                    )
                ),
            )
        )
        .order_by(
            historical_latest_attempts.c.latest_at.asc().nulls_first(),
            func.substring(target.c.window_key, r"[0-9]{4}-[0-9]{2}-[0-9]{2}").desc(),
            target.c.window_key,
        )
        .limit(limit - recent_count - historical_count - older_empty_count)
        .cte("historical_queue_limited")
    )
    old = select(
        old_limited.c.window_key,
        func.row_number()
        .over(
            order_by=(
                old_limited.c.last_attempt.asc().nulls_first(),
                old_limited.c.window_day.desc(),
                old_limited.c.window_key,
            )
        )
        .label("position"),
    ).cte("historical_queue_lane")
    lanes = union_all(
        select(older_empty.c.window_key, literal(0).label("lane"), older_empty.c.position),
        select(recent.c.window_key, literal(1).label("lane"), recent.c.position),
        select(historical.c.window_key, literal(2).label("lane"), historical.c.position),
        select(old.c.window_key, literal(3).label("lane"), old.c.position),
    ).cte("bounded_corpus_lanes")
    statement = select(lanes.c.window_key).order_by(lanes.c.lane, lanes.c.position).limit(limit)
    with journal.storage.transaction(journal.company_id, consistent_read=True) as connection:
        if limit >= 2:
            fair = _daily_backlog_fair_selection(
                connection,
                journal.company_id,
                now,
                limit,
                recent_base,
                historical_ranked,
                recent,
                older_empty_due,
            )
            if fair is not None:
                return fair
        return tuple(connection.execute(statement).scalars())


def _daily_backlog_fair_selection(
    connection: Connection,
    company_id: str,
    now: datetime,
    limit: int,
    recent_failures: CTE,
    historical_retries: CTE,
    recent_repairs: CTE,
    older_empty_due: CTE,
) -> tuple[str, ...] | None:
    """Activate only with both a new completed date and an ordinary old anchor."""
    target = eis_sync_targets
    today = now.astimezone(timezone(timedelta(hours=3))).date()
    recent_first = today - timedelta(days=7)
    raw_day = func.substring(target.c.window_key, r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
    day = case((func.pg_input_is_valid(raw_day, "date"), cast(raw_day, Date)), else_=None)
    completed = target.c.window_key.in_(
        select(eis_feed_windows.c.window_key).where(
            eis_feed_windows.c.company_id == company_id,
            eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
            eis_feed_windows.c.window_key.is_not(None),
        )
    )
    has_attempt = exists(
        select(eis_sync_attempts.c.attempt_id).where(
            eis_sync_attempts.c.company_id == company_id,
            eis_sync_attempts.c.window_key == target.c.window_key,
        )
    )
    recent_new = and_(day.between(recent_first, today - timedelta(days=1)), ~has_attempt)
    base_conditions = (
        target.c.company_id == company_id,
        target.c.window_key.op("~")(_KEY.pattern),
        ~completed,
    )
    new_keys = tuple(
        connection.execute(
            select(target.c.window_key)
            .where(*base_conditions, recent_new)
            .order_by(raw_day.desc(), target.c.window_key)
            .limit(limit)
        ).scalars()
    )
    if not new_keys:
        return None
    # Uncorrelated membership lets PostgreSQL compute the latest-attempt set once,
    # rather than pushing each target key through its DISTINCT ON derivation.
    transient = target.c.window_key.in_(
        select(historical_retries.c.window_key).where(historical_retries.c.window_key.is_not(None))
    )
    last_attempts = (
        select(eis_sync_attempts.c.attempted_at.label("latest_at"))
        .where(
            eis_sync_attempts.c.company_id == company_id,
            eis_sync_attempts.c.window_key == target.c.window_key,
        )
        .order_by(eis_sync_attempts.c.attempted_at.desc(), eis_sync_attempts.c.attempt_id.desc())
        .limit(1)
        .lateral("fair_latest_attempt")
    )
    ordinary = (
        select(target.c.window_key)
        .outerjoin(last_attempts, true())
        .where(
            *base_conditions,
            or_(
                last_attempts.c.latest_at.is_(None),
                last_attempts.c.latest_at <= now - timedelta(hours=24),
            ),
        )
        .order_by(
            last_attempts.c.latest_at.asc().nulls_first(), raw_day.desc(), target.c.window_key
        )
    )
    anchor = connection.scalar(ordinary.where(day < recent_first, ~transient).limit(1))
    if anchor is None:
        return None
    selected = [anchor, new_keys[0]]
    if len(selected) == limit:
        return tuple(selected)
    if limit >= 30:
        # An eligible attempted old anchor already fulfills the single-slot reserve.
        anchor_empty = (
            select(func.count())
            .select_from(older_empty_due)
            .where(older_empty_due.c.window_key.in_(selected))
            .scalar_subquery()
        )
        selected.extend(
            connection.execute(
                select(older_empty_due.c.window_key)
                .where(older_empty_due.c.window_key.not_in(selected))
                .order_by(older_empty_due.c.position)
                .limit(func.greatest(0, 1 - anchor_empty))
            ).scalars()
        )
    repair_cap = min((limit + 4) // 5, 12, limit - 1)
    selected.extend(
        connection.execute(
            select(recent_repairs.c.window_key)
            .where(recent_repairs.c.window_key.not_in(selected))
            .order_by(recent_repairs.c.position)
            .limit(min(repair_cap, limit - len(selected)))
        ).scalars()
    )
    if len(selected) < limit:
        selected.extend(
            connection.execute(
                select(historical_retries.c.window_key)
                .join(
                    target,
                    and_(
                        target.c.company_id == company_id,
                        target.c.window_key == historical_retries.c.window_key,
                    ),
                )
                .where(~completed, historical_retries.c.window_key.not_in(selected))
                .order_by(
                    historical_retries.c.attempted_at,
                    historical_retries.c.window_day.desc(),
                    historical_retries.c.window_key,
                )
                .limit(min((limit + 19) // 20, 3, limit - len(selected)))
            ).scalars()
        )
    new_cap = (3 * limit + 4) // 5
    selected.extend(new_keys[1 : 1 + min(new_cap - 1, limit - len(selected))])
    if len(selected) < limit:
        # New-date keys cannot consume the ordinary older-backlog allocation.
        recent_failure = target.c.window_key.in_(
            select(recent_failures.c.window_key).where(recent_failures.c.window_key.is_not(None))
        )
        remaining = limit - len(selected)
        normal = tuple(
            connection.execute(
                ordinary.where(
                    ~recent_new, ~transient, ~recent_failure, target.c.window_key.not_in(selected)
                ).limit(remaining)
            ).scalars()
        )
        selected.extend(normal)
        if len(normal) < remaining:
            # Exhausted the eligible ordinary fill (including all old anchors).
            selected.extend(key for key in new_keys if key not in selected)
            del selected[limit:]
    return _interleave_daily_first_attempts(selected, new_keys)


def _interleave_daily_first_attempts(
    selected: list[str], new_keys: tuple[str, ...]
) -> tuple[str, ...]:
    """Disperse a retry prefix; preserve an already contiguous fresh prefix."""
    fresh = frozenset(new_keys)
    if len(selected) <= 2 or selected[2] in fresh:
        return tuple(selected)
    result = selected[:2]
    new_tail = [key for key in selected[2:] if key in fresh]
    other_tail = [key for key in selected[2:] if key not in fresh]
    for offset in range(max((len(new_tail) + 2) // 3, (len(other_tail) + 1) // 2)):
        result.extend(new_tail[3 * offset : 3 * offset + 3])
        result.extend(other_tail[2 * offset : 2 * offset + 2])
    return tuple(result)


def resource_gate(
    storage: PostgresStorage, company_id: str, *, max_database_bytes: int, min_free_bytes: int
) -> str | None:
    """Stop before the next atomic window when storage approaches the operator budget."""
    if max_database_bytes <= 0 or min_free_bytes <= 0:
        raise ValueError("CORPUS_BUDGET_INVALID")
    with storage.transaction(company_id) as connection:
        size = connection.scalar(select(func.pg_database_size(func.current_database())))
    if size is None or int(size) >= max_database_bytes:
        return "DATABASE_BUDGET_REACHED"
    return "DISK_RESERVE_REACHED" if shutil.disk_usage("/").free < min_free_bytes else None


def _history_priority_reason(
    journal: EisSyncJournal,
    *,
    now: datetime,
    priority_request: Path | None,
    regional_request: Path | None,
    mandatory_fresh_first: bool,
) -> str | None:
    """Проверить допуск под общим lease до подготовки и перед каждым окном."""
    if priority_requested(priority_request, now=datetime.now(now.tzinfo)):
        return "PRIORITY_REFRESH_REQUESTED"
    if priority_requested(regional_request, now=datetime.now(now.tzinfo)):
        return "REGIONAL_REFRESH_REQUESTED"
    if mandatory_fresh_first:
        # Marker lifetime is shorter than persisted demand. Check under the
        # shared import lease before every historical atomic source window.
        from procurement.eis_freshness_dispatch_cli import probe_dispatch
        from procurement.sources.eis_freshness import EisFreshnessScope
        from procurement.storage.eis_223_regions import _accepted_catalog

        try:
            with journal.storage.transaction(journal.company_id, consistent_read=True) as conn:
                catalog = _accepted_catalog(conn, journal.company_id)
            if catalog is None:
                return "MANDATORY_DEMAND_UNAVAILABLE"
            demand = probe_dispatch(
                journal.storage,
                journal.company_id,
                EisFreshnessScope(
                    tuple(sorted(catalog["regions"])), checkpointed=True, mandatory_only=True
                ),
                now=datetime.now(now.tzinfo),
                include_regional=True,
            )
        except (ValueError, SQLAlchemyError):
            return "MANDATORY_DEMAND_UNAVAILABLE"
        if demand.status != "IDLE":
            return (
                "MANDATORY_FRESH_WORK_READY"
                if demand.status == "READY"
                else "MANDATORY_DEMAND_UNAVAILABLE"
            )
    return None


async def run_corpus(
    journal: EisSyncJournal,
    token: str,
    *,
    now: datetime,
    max_windows: int = 60,
    max_database_bytes: int = 100 * 1024**3,
    min_free_bytes: int = 40 * 1024**3,
    priority_request: Path | None = None,
    regional_request: Path | None = None,
    transport: EisFeedTransport | None = None,
    mandatory_fresh_first: bool = False,
) -> dict[str, object]:
    """Bounded sequential worker; fail fast on egress/DB failure and retain all gaps."""
    stopped = (
        _history_priority_reason(
            journal,
            now=now,
            priority_request=priority_request,
            regional_request=regional_request,
            mandatory_fresh_first=True,
        )
        if mandatory_fresh_first
        else None
    )
    keys = () if stopped else eligible_windows(journal, now=now, limit=max_windows)
    synced = skipped = new_versions = new_events = attempted = 0
    rejected_windows: list[dict[str, object]] = []
    partial_windows = held_pairs = replayed_projection_batches = 0
    for key in keys:
        stopped = _history_priority_reason(
            journal,
            now=now,
            priority_request=priority_request,
            regional_request=regional_request,
            mandatory_fresh_first=mandatory_fresh_first,
        )
        if stopped:
            break
        stopped = resource_gate(
            journal.storage,
            journal.company_id,
            max_database_bytes=max_database_bytes,
            min_free_bytes=min_free_bytes,
        )
        if stopped:
            break
        selection = parse_date_window(key)
        attempted += 1
        try:
            if transport is None:
                result = await sync_eis_window_via_browser(
                    journal.storage, journal.company_id, journal.actor_id, selection, token
                )
            else:
                result = await sync_eis_window(
                    journal.storage,
                    journal.company_id,
                    journal.actor_id,
                    selection,
                    token,
                    transport,
                )
        except (EisSyncError, EisFeedArchiveError, EisIndexConflict) as error:
            raw = str(error)
            reason = raw if _SAFE.fullmatch(raw) else "SOURCE_FAILURE"
            if isinstance(error, EisRejectedWindowError):
                rejected_windows.append({"window_key": key, **error.safe_metadata()})
            journal.record(
                key,
                "FAILED",
                reason_code=reason,
                source_response_sha256=getattr(error, "source_response_sha256", None),
                variant_intake=error.variant_intake
                if isinstance(error, EisRejectedWindowError)
                and error.variant_intake.status != "NOT_ATTEMPTED"
                else None,
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
            if reason in {
                "SOURCE_TRANSPORT_FAILED",
                "SOURCE_WSDL_UNAVAILABLE",
                "PROXY_CONFIG_INVALID",
                "BROWSER_DEPENDENCY_MISSING",
            }:
                stopped = reason
                break
        except SQLAlchemyError:
            stopped = "DATABASE_FAILED"
            break
        else:
            journal.record(key, result.status, source_response_sha256=result.source_response_sha256)
            synced += int(result.status == "SYNCED")
            skipped += int(result.status == "SKIPPED")
            new_versions += result.new_versions
            new_events += result.new_events
            if result.status == "SERVICE_ERROR":
                stopped = "SOURCE_SERVICE_ERROR"
                break
        # Global server lock and conservative spacing; no parallel request flood.
        await asyncio.sleep(2)
    return {
        "status": "BLOCKED" if stopped else "PARTIAL",
        "reason": stopped,
        "selected": len(keys),
        "attempted": attempted,
        "synced": synced,
        "skipped": skipped,
        "new_versions": new_versions,
        "new_events": new_events,
        "rejected_windows": rejected_windows,
        "partial_windows": partial_windows,
        "held_pairs": held_pairs,
        "replayed_projection_batches": replayed_projection_batches,
        "coverage": "UNKNOWN",
    }


def priority_requested(path: Path | None, *, now: datetime) -> bool:
    """A short-lived operational hint; never interrupt a window transaction."""
    if path is None:
        return False
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_MISSING")
    try:
        age = now.timestamp() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return 0 <= age <= 600
