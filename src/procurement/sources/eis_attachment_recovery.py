"""Explicit bounded recovery of windows rejected by the obsolete attachment count cap."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta
from typing import Any, Literal

from psycopg import Error as PsycopgError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Date, DateTime, Integer, and_, case, cast, exists, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Select

from procurement.sources.eis_corpus import resource_gate
from procurement.sources.eis_feed_archive import EisFeedArchiveError
from procurement.sources.eis_feed_sync import (
    EisDateSelection,
    EisFeedTransport,
    EisHourSelection,
    EisRejectedWindowError,
    EisSelection,
    EisSyncError,
    sync_eis_window,
)
from procurement.sources.eis_variant_intake import EisVariantIntakeReport
from procurement.storage.eis_notice_index import EisIndexConflict
from procurement.storage.eis_sync_journal import (
    EisAttemptOutcome,
    EisSyncJournal,
    latest_eis_attempts,
)
from procurement.storage.models import eis_feed_windows, eis_sync_targets

_KEY = re.compile(
    r"^getDocsIP/PRIZ/(?P<region>0?[1-9]|[1-9][0-9])/(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?:/(?P<hour>[0-9]{2}))?[+]03:00"
    r"(?:/(?P<kind>epNotificationEZK2020|epNotificationEOK2020|epNotificationCancel|epNotificationCancelFailure))?$"
)
_SQL_KEY = re.sub(r"\(\?P<[^>]+>", "(?:", _KEY.pattern)
_TOKEN = re.compile(r"^[A-Za-z0-9-]{16,128}$")
_SAFE = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
_DB_ERRORS = (SQLAlchemyError, PsycopgError)


class RecoveryModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AttachmentRecoveryCandidate(RecoveryModel):
    window_key: str
    original_attempt_id: str = Field(min_length=1)
    original_attempted_at: datetime
    original_source_response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("window_key")
    @classmethod
    def supported_window(cls, value: str) -> str:
        parse_attachment_recovery_window(value)
        return value

    @field_validator("original_attempted_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("ATTACHMENT_RECOVERY_TIME_INVALID")
        return value


class AttachmentRecoveryPlan(RecoveryModel):
    company_id: str = Field(min_length=1)
    checked_at: datetime
    eligible_count: int = Field(ge=0)
    candidates: tuple[AttachmentRecoveryCandidate, ...] = Field(max_length=3)
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> AttachmentRecoveryPlan:
        if (
            self.checked_at.utcoffset() is None
            or self.eligible_count < len(self.candidates)
            or len({item.window_key for item in self.candidates}) != len(self.candidates)
        ):
            raise ValueError("ATTACHMENT_RECOVERY_PLAN_INVALID")
        return self


class AttachmentRecoveryOutcome(RecoveryModel):
    candidate: AttachmentRecoveryCandidate
    new_attempt_id: str | None = None
    outcome: Literal[
        "NOT_ATTEMPTED", "FAILED", "SYNCED", "SKIPPED", "NO_DATA", "PREPARING", "SERVICE_ERROR"
    ]
    reason: str | None = None
    source_response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    new_versions: int = Field(default=0, ge=0)
    new_events: int = Field(default=0, ge=0)
    canonical_checkpoint: bool = False
    variant_intake: EisVariantIntakeReport | None = None

    @model_validator(mode="after")
    def consistent(self) -> AttachmentRecoveryOutcome:
        if (
            self.canonical_checkpoint != (self.outcome in {"SYNCED", "SKIPPED"})
            or (
                self.outcome == "NOT_ATTEMPTED"
                and (
                    self.new_attempt_id is not None
                    or self.new_versions
                    or self.new_events
                    or self.variant_intake is not None
                )
            )
            or (self.variant_intake is not None and self.outcome != "FAILED")
            or (self.outcome in {"FAILED", "NOT_ATTEMPTED"} and not self.reason)
            or (self.outcome in {"SYNCED", "NO_DATA"} and self.source_response_sha256 is None)
        ):
            raise ValueError("ATTACHMENT_RECOVERY_OUTCOME_INVALID")
        return self


class AttachmentRecoveryRunReport(RecoveryModel):
    company_id: str = Field(min_length=1)
    checked_at: datetime
    status: Literal["FINISHED", "BLOCKED"]
    reason: str | None = None
    plan: AttachmentRecoveryPlan
    selected: int = Field(ge=0, le=3)
    attempted: int = Field(ge=0, le=3)
    outcomes: tuple[AttachmentRecoveryOutcome, ...] = Field(max_length=3)
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> AttachmentRecoveryRunReport:
        if (
            self.checked_at.utcoffset() is None
            or self.company_id != self.plan.company_id
            or self.checked_at != self.plan.checked_at
            or tuple(item.candidate for item in self.outcomes)
            != self.plan.candidates[: len(self.outcomes)]
            or len({item.candidate.window_key for item in self.outcomes}) != len(self.outcomes)
            or (self.status == "FINISHED" and self.attempted != self.selected)
            or self.selected != len(self.plan.candidates)
            or self.attempted > self.selected
            or self.attempted != sum(item.outcome != "NOT_ATTEMPTED" for item in self.outcomes)
            or (self.status == "BLOCKED") != (self.reason is not None)
        ):
            raise ValueError("ATTACHMENT_RECOVERY_RUN_INVALID")
        return self


def parse_attachment_recovery_window(key: str) -> EisSelection:
    match = _KEY.fullmatch(key)
    if match is None:
        raise ValueError("ATTACHMENT_RECOVERY_WINDOW_INVALID")
    try:
        from datetime import date

        day = date.fromisoformat(match["day"])
        kind = match["kind"] or "epNotificationEF2020"
        if match["hour"] is not None:
            return EisHourSelection(match["region"], day, int(match["hour"]), 3, kind)
        return EisDateSelection(match["region"], day, 3, kind)
    except ValueError as error:
        raise ValueError("ATTACHMENT_RECOVERY_WINDOW_INVALID") from error


def _completed(company: str, key: str | ColumnElement[str]) -> ColumnElement[bool]:
    return exists(
        select(eis_feed_windows.c.window_key).where(
            eis_feed_windows.c.company_id == company,
            eis_feed_windows.c.window_key == key,
            eis_feed_windows.c.intake_kind == "LEGACY_CANONICAL",
        )
    )


def _eligible(journal: EisSyncJournal, now: datetime) -> Select[Any]:
    latest = latest_eis_attempts(journal.company_id)
    raw_day = func.substring(latest.c.window_key, r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
    day = case((func.pg_input_is_valid(raw_day, "date"), cast(raw_day, Date)), else_=None)
    raw_hour = func.substring(latest.c.window_key, r"/([0-9]{2})[+]03:00")
    hour = cast(raw_hour, Integer)
    end = func.timezone(
        "Europe/Moscow",
        cast(day, DateTime)
        + func.make_interval(
            0, 0, 0, case((raw_hour.is_(None), 1), else_=0), func.coalesce(hour + 1, 0)
        ),
    )
    return (
        select(
            latest.c.window_key,
            latest.c.attempt_id.label("original_attempt_id"),
            latest.c.attempted_at.label("original_attempted_at"),
            latest.c.source_response_sha256.label("original_source_response_sha256"),
        )
        .join(
            eis_sync_targets,
            and_(
                eis_sync_targets.c.company_id == journal.company_id,
                eis_sync_targets.c.window_key == latest.c.window_key,
            ),
        )
        .where(
            latest.c.outcome == "FAILED",
            latest.c.reason_code == "ATTACHMENT_COUNT_LIMIT",
            latest.c.attempted_at <= now - timedelta(hours=24),
            latest.c.window_key.op("~")(_SQL_KEY),
            (raw_hour.is_(None) | hour.between(0, 23)),
            end <= now,
            ~_completed(journal.company_id, latest.c.window_key),
        )
    )


def read_attachment_recovery_plan(
    journal: EisSyncJournal, *, now: datetime, limit: int = 3
) -> AttachmentRecoveryPlan:
    if now.utcoffset() is None or not 1 <= limit <= 3:
        raise ValueError("ATTACHMENT_RECOVERY_CONFIG_INVALID")
    eligible = _eligible(journal, now).cte("attachment_recovery_eligible")
    with journal.storage.transaction(journal.company_id, consistent_read=True) as conn:
        count = int(conn.scalar(select(func.count()).select_from(eligible)) or 0)
        rows = (
            conn.execute(
                select(eligible)
                .order_by(
                    eligible.c.original_attempted_at,
                    eligible.c.window_key,
                )
                .limit(limit)
            )
            .mappings()
            .all()
        )
    return AttachmentRecoveryPlan(
        company_id=journal.company_id,
        checked_at=now,
        eligible_count=count,
        candidates=tuple(AttachmentRecoveryCandidate(**dict(row)) for row in rows),
    )


def _recheck(
    journal: EisSyncJournal, candidate: AttachmentRecoveryCandidate, now: datetime
) -> str | None:
    with journal.storage.transaction(journal.company_id, consistent_read=True) as conn:
        if conn.scalar(select(_completed(journal.company_id, candidate.window_key))):
            return "SOURCE_CANDIDATE_COMPLETED"
        eligible = _eligible(journal, now).subquery()
        latest = (
            conn.execute(
                select(eligible).where(
                    eligible.c.window_key == candidate.window_key,
                    eligible.c.original_attempt_id == candidate.original_attempt_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if latest is None or dict(latest) != candidate.model_dump():
            return "SOURCE_CANDIDATE_CHANGED"
    return None


def _checkpoint(journal: EisSyncJournal, key: str) -> bool:
    with journal.storage.transaction(journal.company_id, consistent_read=True) as conn:
        return bool(conn.scalar(select(_completed(journal.company_id, key))))


async def run_attachment_recovery(
    journal: EisSyncJournal,
    token: str,
    *,
    now: datetime,
    max_windows: int = 3,
    max_database_bytes: int = 100 * 1024**3,
    min_free_bytes: int = 40 * 1024**3,
    transport: EisFeedTransport,
    max_seconds: int = 600,
) -> AttachmentRecoveryRunReport:
    """Use the existing sync protocol; wall-clock limits gate only the next call."""
    if (
        not _TOKEN.fullmatch(token)
        or now.utcoffset() is None
        or not 1 <= max_windows <= 3
        or not 1 <= max_seconds <= 600
        or max_database_bytes <= 0
        or min_free_bytes <= 0
    ):
        raise ValueError("ATTACHMENT_RECOVERY_CONFIG_INVALID")
    started = time.monotonic()
    plan = read_attachment_recovery_plan(journal, now=now, limit=max_windows)
    outcomes: list[AttachmentRecoveryOutcome] = []
    attempted = 0
    stopped = None
    for candidate in plan.candidates:
        try:
            elapsed = time.monotonic() - started
            stopped = "RECOVERY_TIME_BUDGET_REACHED" if elapsed >= max_seconds else None
            if stopped is None:
                stopped = resource_gate(
                    journal.storage,
                    journal.company_id,
                    max_database_bytes=max_database_bytes,
                    min_free_bytes=min_free_bytes,
                )
            if stopped is None:
                stopped = _recheck(journal, candidate, now + timedelta(seconds=elapsed))
        except _DB_ERRORS:
            stopped = "DATABASE_FAILED"
        if stopped:
            outcomes.append(
                AttachmentRecoveryOutcome(
                    candidate=candidate, outcome="NOT_ATTEMPTED", reason=stopped
                )
            )
            break
        selection = parse_attachment_recovery_window(candidate.window_key)
        attempted += 1
        outcome: EisAttemptOutcome
        reason = None
        response_sha = None
        new_versions = new_events = 0
        checkpoint = False
        variant_intake = None
        try:
            result = await sync_eis_window(
                journal.storage, journal.company_id, journal.actor_id, selection, token, transport
            )
            outcome, response_sha = result.status, result.source_response_sha256
            new_versions, new_events = result.new_versions, result.new_events
            if outcome in {"SYNCED", "SKIPPED"}:
                checkpoint = _checkpoint(journal, candidate.window_key)
                if not checkpoint:
                    outcome, reason, stopped = (
                        "FAILED",
                        "CANONICAL_CHECKPOINT_MISSING",
                        "CANONICAL_CHECKPOINT_MISSING",
                    )
                    new_versions = new_events = 0
            if outcome == "SERVICE_ERROR":
                stopped = "SOURCE_SERVICE_ERROR"
        except (EisSyncError, EisFeedArchiveError, EisIndexConflict) as error:
            outcome = "FAILED"
            reason = str(error) if _SAFE.fullmatch(str(error)) else "SOURCE_FAILURE"
            response_sha = getattr(error, "source_response_sha256", None)
            stopped = reason
            if isinstance(error, EisRejectedWindowError):
                variant_intake = error.variant_intake
                if variant_intake.status == "PARTIAL":
                    new_versions = variant_intake.new_versions
                    stopped = None
                elif variant_intake.status == "FAILED":
                    stopped = variant_intake.reason
        except _DB_ERRORS:
            outcomes.append(
                AttachmentRecoveryOutcome(
                    candidate=candidate, outcome="FAILED", reason="DATABASE_FAILED"
                )
            )
            stopped = "DATABASE_FAILED"
            break
        attempt_id = None
        try:
            attempt_id = journal.record(
                candidate.window_key,
                outcome,
                reason_code=reason,
                source_response_sha256=response_sha,
                variant_intake=variant_intake
                if variant_intake and variant_intake.status != "NOT_ATTEMPTED"
                else None,
            )
        except _DB_ERRORS:
            stopped = "DATABASE_FAILED"
        outcomes.append(
            AttachmentRecoveryOutcome(
                candidate=candidate,
                new_attempt_id=attempt_id,
                outcome=outcome,
                reason=reason,
                source_response_sha256=response_sha,
                new_versions=new_versions,
                new_events=new_events,
                canonical_checkpoint=checkpoint,
                variant_intake=variant_intake,
            )
        )
        if stopped:
            break
        if len(outcomes) < len(plan.candidates):
            await asyncio.sleep(2)
    return AttachmentRecoveryRunReport(
        company_id=journal.company_id,
        checked_at=now,
        status="BLOCKED" if stopped else "FINISHED",
        reason=stopped,
        plan=plan,
        selected=len(plan.candidates),
        attempted=attempted,
        outcomes=tuple(outcomes),
    )
