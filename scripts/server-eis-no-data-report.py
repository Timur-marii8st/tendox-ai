"""Bounded read-only aging census of planned 44-FZ date-window NO_DATA evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Date, and_, case, cast, create_engine, exists, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.selectable import CTE

from procurement.storage.eis_sync_journal import latest_eis_attempts
from procurement.storage.models import eis_feed_windows, eis_sync_targets
from procurement.storage.repository import PostgresStorage

COMPANY: Literal["local-eis-supplier"] = "local-eis-supplier"
MOSCOW = timezone(timedelta(hours=3))
KINDS = (
    "epNotificationEF2020",
    "epNotificationEZK2020",
    "epNotificationEOK2020",
    "epNotificationCancel",
    "epNotificationCancelFailure",
)
KEY = (
    r"^getDocsIP/PRIZ/(0[1-9]|[1-9][0-9])/[0-9]{4}-[0-9]{2}-[0-9]{2}\+03:00"
    r"(/(epNotificationEZK2020|epNotificationEOK2020|epNotificationCancel|"
    r"epNotificationCancelFailure))?$"
)
ROOT = Path("/var/lib/eis-browser/research/rejected")


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Cohort(Evidence):
    day: date
    document_type: Literal[
        "epNotificationEF2020",
        "epNotificationEZK2020",
        "epNotificationEOK2020",
        "epNotificationCancel",
        "epNotificationCancelFailure",
    ]
    no_data: int = Field(ge=1, le=99)
    due: int = Field(ge=0, le=99)
    cooldown: int = Field(ge=0, le=99)
    within_recent_dates: bool
    oldest_attempt_at: AwareDatetime
    newest_attempt_at: AwareDatetime


class Sample(Evidence):
    window_key: str = Field(pattern=KEY)
    attempt_id: uuid.UUID
    attempted_at: AwareDatetime
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_for_recent_reserve: bool


class Report(Evidence):
    schema_version: Literal["eis-no-data-aging-v1"] = "eis-no-data-aging-v1"
    company_id: Literal["local-eis-supplier"] = COMPANY
    checked_at: AwareDatetime
    snapshot: str = Field(min_length=1, max_length=500)
    first_day: date
    last_day: date
    cohorts: tuple[Cohort, ...] = Field(max_length=450)
    samples: tuple[Sample, ...] = Field(max_length=20)
    latest_no_data: int = Field(ge=0, le=44550)
    due_recent: int = Field(ge=0, le=3465)
    due_older: int = Field(ge=0, le=44550)
    cooldown: int = Field(ge=0, le=44550)
    oldest_due_age_seconds: int | None = Field(ge=86400)
    transaction_read_only: Literal[True] = True
    source_requests: Literal[0] = 0
    database_writes: Literal[0] = 0
    # This report reads journal hashes, not source bodies or an independent feed.
    evidence_level: Literal["JOURNAL_RESPONSE_HASH"] = "JOURNAL_RESPONSE_HASH"
    response_body_retention: Literal["UNKNOWN"] = "UNKNOWN"
    independent_corroboration: Literal["UNKNOWN"] = "UNKNOWN"
    source_absence: Literal["UNKNOWN"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    region_registry_status: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> Report:
        validate_range(self.first_day, self.last_day, self.checked_at)
        today = self.checked_at.astimezone(MOSCOW).date()
        cutoff = self.checked_at - timedelta(hours=24)
        ids = [(c.day, c.document_type) for c in self.cohorts]
        if len(ids) != len(set(ids)) or ids != sorted(ids):
            raise ValueError("COHORT_IDENTITY_INVALID")
        for c in self.cohorts:
            recent = today - timedelta(days=7) <= c.day < today
            if (
                not self.first_day <= c.day <= self.last_day
                or c.no_data != c.due + c.cooldown
                or c.within_recent_dates != recent
                or not c.oldest_attempt_at <= c.newest_attempt_at <= self.checked_at
                or (c.due == 0 and c.oldest_attempt_at <= cutoff)
                or (c.due > 0 and c.oldest_attempt_at > cutoff)
                or (c.cooldown == 0 and c.newest_attempt_at > cutoff)
                or (c.cooldown > 0 and c.newest_attempt_at <= cutoff)
            ):
                raise ValueError("COHORT_COUNTS_OR_TIME_INVALID")
        due_rows = [c for c in self.cohorts if c.due]
        oldest = min((c.oldest_attempt_at for c in due_rows), default=None)
        age = int((self.checked_at - oldest).total_seconds()) if oldest else None
        if (
            self.latest_no_data != sum(c.no_data for c in self.cohorts)
            or self.due_recent != sum(c.due for c in self.cohorts if c.within_recent_dates)
            or self.due_older != sum(c.due for c in self.cohorts if not c.within_recent_dates)
            or self.cooldown != sum(c.cooldown for c in self.cohorts)
            or self.latest_no_data != self.due_recent + self.due_older + self.cooldown
            or self.oldest_due_age_seconds != age
        ):
            raise ValueError("REPORT_COUNT_PARITY_INVALID")
        if len({s.window_key for s in self.samples}) != len(self.samples):
            raise ValueError("SAMPLE_DUPLICATE")
        for lane in (True, False):
            samples = [s for s in self.samples if s.eligible_for_recent_reserve == lane]
            expected = min(10, self.due_recent if lane else self.due_older)
            if len(samples) != expected or samples != sorted(
                samples, key=lambda s: (s.attempted_at, s.window_key)
            ):
                raise ValueError("SAMPLE_LANE_INVALID")
        cohort_map: dict[tuple[date, str], Cohort] = {
            identity: c for identity, c in zip(ids, self.cohorts, strict=True)
        }
        for s in self.samples:
            parts = s.window_key.split("/")
            day = date.fromisoformat(parts[3][:10])
            kind = parts[4] if len(parts) == 5 else KINDS[0]
            sample_cohort = cohort_map.get((day, kind))
            if (
                sample_cohort is None
                or not sample_cohort.due
                or sample_cohort.within_recent_dates != s.eligible_for_recent_reserve
                or not sample_cohort.oldest_attempt_at
                <= s.attempted_at
                <= min(sample_cohort.newest_attempt_at, cutoff)
            ):
                raise ValueError("SAMPLE_PROVENANCE_INVALID")
        return self


def validate_range(first: date, last: date, now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    if not 1 <= (last - first).days + 1 <= 90 or last >= now.astimezone(MOSCOW).date():
        raise ValueError("COMPLETED_DATE_RANGE_INVALID")


def pending_query(first: date, last: date) -> CTE:
    """Latest timestamp/UUID before filtering outcome; planned + tenant + no canonical."""
    latest = latest_eis_attempts(COMPANY)
    target, feed = eis_sync_targets, eis_feed_windows
    raw_day = func.substring(latest.c.window_key, r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
    day = case((func.pg_input_is_valid(raw_day, "date"), cast(raw_day, Date)), else_=None)
    suffix = func.split_part(latest.c.window_key, "/", 5)
    kind = case((suffix == "", KINDS[0]), else_=suffix)
    canonical = exists(
        select(feed.c.window_key).where(
            feed.c.company_id == COMPANY,
            feed.c.window_key == latest.c.window_key,
            feed.c.intake_kind == "LEGACY_CANONICAL",
        )
    )
    return (
        select(
            latest.c.window_key,
            latest.c.attempt_id,
            latest.c.attempted_at,
            latest.c.source_response_sha256,
            day.label("day"),
            kind.label("document_type"),
        )
        .join(
            target,
            and_(
                target.c.company_id == COMPANY,
                target.c.window_key == latest.c.window_key,
            ),
        )
        .where(
            latest.c.window_key.op("~")(KEY),
            day.between(first, last),
            latest.c.outcome == "NO_DATA",
            ~canonical,
        )
        .cte("planned_latest_no_data")
    )


def read_report(conn: Connection, first: date, last: date) -> Report:
    if (
        conn.scalar(text("SHOW transaction_read_only")) != "on"
        or conn.scalar(text("SHOW transaction_isolation")) != "repeatable read"
    ):
        raise ValueError("READ_ONLY_SNAPSHOT_REQUIRED")
    conn.execute(text("SET LOCAL statement_timeout = '30s'"))
    snapshot = str(conn.scalar(text("SELECT pg_current_snapshot()::text")))
    now = conn.scalar(text("SELECT clock_timestamp()"))
    validate_range(first, last, now)
    recent_first = now.astimezone(MOSCOW).date() - timedelta(days=7)
    cutoff = now - timedelta(hours=24)
    base = pending_query(first, last)
    due = base.c.attempted_at <= cutoff
    sha_valid = base.c.source_response_sha256.op("~")(r"^[0-9a-f]{64}$")
    # Fail rather than silently omit invalid/future provenance from the denominator.
    grouped = (
        select(
            base.c.day,
            base.c.document_type,
            func.count().label("no_data"),
            func.count().filter(due).label("due"),
            func.count().filter(base.c.attempted_at > cutoff).label("cooldown"),
            func.min(base.c.attempted_at).label("oldest_attempt_at"),
            func.max(base.c.attempted_at).label("newest_attempt_at"),
            func.count().filter(func.coalesce(sha_valid, False).is_(False)).label("bad_sha"),
        )
        .group_by(base.c.day, base.c.document_type)
        .order_by(base.c.day, base.c.document_type)
        .limit(451)
    )
    rows = tuple(conn.execute(grouped).mappings())
    if len(rows) > 450 or any(row["bad_sha"] for row in rows):
        raise ValueError("NO_DATA_PROVENANCE_OR_BOUND_INVALID")
    cohorts = tuple(
        Cohort(
            **{k: v for k, v in row.items() if k != "bad_sha"},
            within_recent_dates=row["day"] >= recent_first,
        )
        for row in rows
    )
    samples: list[Sample] = []
    for recent in (True, False):
        lane = base.c.day >= recent_first if recent else base.c.day < recent_first
        sample_query = (
            select(
                base.c.window_key,
                base.c.attempt_id,
                base.c.attempted_at,
                base.c.source_response_sha256,
            )
            .where(due, lane)
            .order_by(base.c.attempted_at, base.c.window_key)
            .limit(10)
        )
        samples.extend(
            Sample(**row, eligible_for_recent_reserve=recent)
            for row in conn.execute(sample_query).mappings()
        )
    oldest = min((c.oldest_attempt_at for c in cohorts if c.due), default=None)
    return Report(
        checked_at=now,
        snapshot=snapshot,
        first_day=first,
        last_day=last,
        cohorts=cohorts,
        samples=tuple(samples),
        latest_no_data=sum(c.no_data for c in cohorts),
        due_recent=sum(c.due for c in cohorts if c.within_recent_dates),
        due_older=sum(c.due for c in cohorts if not c.within_recent_dates),
        cooldown=sum(c.cooldown for c in cohorts),
        oldest_due_age_seconds=int((now - oldest).total_seconds()) if oldest else None,
    )


def save_report(report: Report) -> tuple[Path, str]:
    blob = report.model_dump_json(indent=2).encode()
    if len(blob) > 1024 * 1024:
        raise ValueError("REPORT_SIZE_INVALID")
    proof = ROOT / f"s196-no-data-{uuid.uuid4()}.json"
    fd = os.open(proof, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(blob)
        stream.flush()
        os.fsync(stream.fileno())
    return proof, hashlib.sha256(blob).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-day", type=date.fromisoformat, required=True)
    parser.add_argument("--last-day", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    validate_range(args.first_day, args.last_day, datetime.now(UTC))
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with PostgresStorage(engine).transaction(COMPANY, consistent_read=True) as conn:
            report = read_report(conn, args.first_day, args.last_day)
    finally:
        engine.dispose()
    proof, sha = save_report(report)
    summary = report.model_dump(mode="json", exclude={"samples"})
    print(
        json.dumps(
            {"status": "OBSERVED", **summary, "proof": str(proof), "sha256": sha},
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, SQLAlchemyError, OSError, KeyError):
        print('{"status":"BLOCKED","reason":"NO_DATA_REPORT_UNAVAILABLE","coverage":"UNKNOWN"}')
        raise SystemExit(65) from None
