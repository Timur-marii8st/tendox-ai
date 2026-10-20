"""Read-only evidence for a bounded completed-date EIS cohort; no source traffic."""

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
from sqlalchemy import and_, create_engine, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_corpus import EisCorpusScope
from procurement.storage.eis_gap_status import gap_category
from procurement.storage.models import (
    eis_feed_windows,
    eis_notice_search_keys,
    eis_notice_versions,
    eis_procedure_events,
    eis_sync_attempts,
    eis_sync_targets,
)
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
ROOT = Path("/var/lib/eis-browser/research/rejected")


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Window(EvidenceModel):
    window_key: str = Field(min_length=1, max_length=160)
    planned_at: AwareDatetime | None
    attempt_id: str | None = Field(max_length=80)
    attempted_at: AwareDatetime | None
    outcome: Literal["SYNCED", "SKIPPED", "NO_DATA", "PREPARING", "SERVICE_ERROR", "FAILED"] | None
    reason_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    source_response_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_at: AwareDatetime | None
    canonical_response_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    transport_present: bool
    notice_versions: int = Field(ge=0)
    indexed_versions: int = Field(ge=0)
    procedure_events: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent(self) -> Window:
        if self.indexed_versions > self.notice_versions:
            raise ValueError("INDEX_COUNT_INVALID")
        attempted = (self.attempt_id, self.attempted_at, self.outcome)
        if any(v is not None for v in attempted) and any(v is None for v in attempted):
            raise ValueError("ATTEMPT_EVIDENCE_INVALID")
        if self.attempted_at is None and (
            self.reason_code is not None or self.source_response_sha256 is not None
        ):
            raise ValueError("ATTEMPT_EVIDENCE_INVALID")
        if self.outcome == "NO_DATA" and self.source_response_sha256 is None:
            raise ValueError("NO_DATA_EVIDENCE_MISSING")
        if (self.canonical_at is None) != (self.canonical_response_sha256 is None):
            raise ValueError("CANONICAL_EVIDENCE_MISSING")
        return self

    @property
    def state(self) -> str:
        # An immutable canonical receipt wins over a later failed refresh attempt.
        if self.canonical_at is not None:
            return "CANONICAL"
        if self.planned_at is None:
            return "MISSING_PLAN"
        return gap_category(self.outcome, self.reason_code).value


class Cohort(EvidenceModel):
    day: date
    document_type: str
    expected: int = Field(ge=1, le=99)
    states: dict[str, int]
    transport_without_canonical: int = Field(ge=0)
    notice_versions: int = Field(ge=0)
    indexed_versions: int = Field(ge=0)
    procedure_events: int = Field(ge=0)
    oldest_pending_plan_age_seconds: int | None = Field(ge=0)
    oldest_pending_attempt_age_seconds: int | None = Field(ge=0)
    max_canonical_completed_day_lag_seconds: int | None = Field(ge=0)


class Report(EvidenceModel):
    schema_version: Literal["eis-recent-ingestion-v1"] = "eis-recent-ingestion-v1"
    company_id: Literal["local-eis-supplier"] = COMPANY
    checked_at: AwareDatetime
    snapshot: str = Field(min_length=1, max_length=500)
    first_day: date
    last_day: date
    scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_windows: int = Field(ge=1, le=1485)
    windows: tuple[Window, ...]
    cohorts: tuple[Cohort, ...]
    evidence_tables: tuple[str, ...] = (
        "eis_sync_targets",
        "eis_sync_attempts",
        "eis_feed_windows",
        "eis_notice_versions",
        "eis_notice_search_keys",
        "eis_procedure_events",
    )
    transaction_read_only: Literal[True] = True
    source_requests: Literal[0] = 0
    database_writes: Literal[0] = 0
    region_registry_status: Literal["UNKNOWN"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    freshness: Literal["UNKNOWN"] = "UNKNOWN"
    document_coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> Report:
        scope = make_scope(self.first_day, self.last_day, self.checked_at)
        coordinates = scope_coordinates(scope)
        keys = [w.window_key for w in self.windows]
        if (
            self.scope_sha256 != scope.sha256
            or self.expected_windows != scope.expected_windows
            or len(keys) != len(set(keys))
            or set(keys) != set(coordinates)
            or self.cohorts != summarize(self.windows, coordinates, self.checked_at)
        ):
            raise ValueError("REPORT_SCOPE_OR_COUNTS_INVALID")
        for w in self.windows:
            if any(
                t is not None and t > self.checked_at
                for t in (
                    w.planned_at,
                    w.attempted_at,
                    w.canonical_at,
                )
            ):
                raise ValueError("REPORT_FUTURE_EVIDENCE")
        return self


def make_scope(first: date, last: date, now: datetime) -> EisCorpusScope:
    if not 1 <= (last - first).days + 1 <= 3:
        raise ValueError("REPORT_DATE_BOUND_INVALID")
    scope = EisCorpusScope(tuple(f"{n:02d}" for n in range(1, 100)), KINDS, first, last)
    scope.validate(now)
    return scope


def scope_coordinates(scope: EisCorpusScope) -> dict[str, tuple[date, str]]:
    return {
        selection.window_key: (selection.day, selection.document_type)
        for batch in scope.batches()
        for selection in batch
    }


def summarize(
    windows: tuple[Window, ...],
    coordinates: dict[str, tuple[date, str]],
    now: datetime,
) -> tuple[Cohort, ...]:
    grouped: dict[tuple[date, str], list[Window]] = {}
    for w in windows:
        grouped.setdefault(coordinates[w.window_key], []).append(w)
    result = []
    for (day, kind), rows in sorted(grouped.items()):
        states: dict[str, int] = {}
        for w in rows:
            states[w.state] = states.get(w.state, 0) + 1
        pending = [w for w in rows if w.state != "CANONICAL"]
        plan_ages = [int((now - w.planned_at).total_seconds()) for w in pending if w.planned_at]
        attempt_ages = [
            int((now - w.attempted_at).total_seconds()) for w in pending if w.attempted_at
        ]
        completed_day = datetime.combine(day + timedelta(days=1), datetime.min.time(), MOSCOW)
        lags = [
            max(0, int((w.canonical_at - completed_day).total_seconds()))
            for w in rows
            if w.canonical_at
        ]
        result.append(
            Cohort(
                day=day,
                document_type=kind,
                expected=len(rows),
                states=dict(sorted(states.items())),
                transport_without_canonical=sum(w.transport_present for w in pending),
                notice_versions=sum(w.notice_versions for w in rows),
                indexed_versions=sum(w.indexed_versions for w in rows),
                procedure_events=sum(w.procedure_events for w in rows),
                oldest_pending_plan_age_seconds=max(plan_ages) if plan_ages else None,
                oldest_pending_attempt_age_seconds=max(attempt_ages) if attempt_ages else None,
                max_canonical_completed_day_lag_seconds=max(lags) if lags else None,
            )
        )
    return tuple(result)


def read_windows(conn: Connection, keys: tuple[str, ...]) -> tuple[Window, ...]:
    target, attempt, feed = eis_sync_targets, eis_sync_attempts, eis_feed_windows
    latest = (
        select(attempt)
        .where(attempt.c.company_id == COMPANY, attempt.c.window_key.in_(keys))
        .distinct(attempt.c.window_key)
        .order_by(attempt.c.window_key, attempt.c.attempted_at.desc(), attempt.c.attempt_id.desc())
        .cte("cohort_latest")
    )
    planned = {
        row.window_key: row.planned_at
        for row in conn.execute(
            select(target.c.window_key, target.c.planned_at).where(
                target.c.company_id == COMPANY,
                target.c.window_key.in_(keys),
            )
        )
    }
    attempts = {row["window_key"]: row for row in conn.execute(select(latest)).mappings()}
    canonical = {
        row.window_key: (row.ingested_at, row.response_sha256)
        for row in conn.execute(
            select(feed.c.window_key, feed.c.ingested_at, feed.c.response_sha256)
            .where(
                feed.c.company_id == COMPANY,
                feed.c.window_key.in_(keys),
                feed.c.intake_kind == "LEGACY_CANONICAL",
            )
            .distinct(feed.c.window_key)
            .order_by(feed.c.window_key, feed.c.ingested_at, feed.c.response_sha256)
        )
    }
    transport = set(
        conn.execute(
            select(feed.c.window_key).where(
                feed.c.company_id == COMPANY,
                feed.c.window_key.in_(keys),
                feed.c.intake_kind == "VARIANT_TRANSPORT",
            )
        ).scalars()
    )
    version, search = eis_notice_versions, eis_notice_search_keys
    counts = {
        row.window_key: (row.versions, row.indexed)
        for row in conn.execute(
            select(
                version.c.window_key,
                func.count().label("versions"),
                func.count(search.c.version_number).label("indexed"),
            )
            .select_from(
                version.outerjoin(
                    search,
                    and_(
                        search.c.company_id == version.c.company_id,
                        search.c.company_id == COMPANY,
                        search.c.purchase_number == version.c.purchase_number,
                        search.c.version_number == version.c.version_number,
                        search.c.key_version == "eis-lexical-v1",
                    ),
                )
            )
            .where(version.c.company_id == COMPANY, version.c.window_key.in_(keys))
            .group_by(version.c.window_key)
        )
    }
    events = eis_procedure_events
    event_counts = {
        row[0]: row[1]
        for row in conn.execute(
            select(events.c.window_key, func.count())
            .where(
                events.c.company_id == COMPANY,
                events.c.window_key.in_(keys),
            )
            .group_by(events.c.window_key)
        )
    }
    result = []
    for key in sorted(keys):
        row = attempts.get(key)
        versions, indexed = counts.get(key, (0, 0))
        result.append(
            Window(
                window_key=key,
                planned_at=planned.get(key),
                attempt_id=row["attempt_id"] if row else None,
                attempted_at=row["attempted_at"] if row else None,
                outcome=row["outcome"] if row else None,
                reason_code=row["reason_code"] if row else None,
                source_response_sha256=row["source_response_sha256"] if row else None,
                canonical_at=canonical[key][0] if key in canonical else None,
                canonical_response_sha256=canonical[key][1] if key in canonical else None,
                transport_present=key in transport,
                notice_versions=versions,
                indexed_versions=indexed,
                procedure_events=event_counts.get(key, 0),
            )
        )
    return tuple(result)


class Progress(EvidenceModel):
    company_id: Literal["local-eis-supplier"] = COMPANY
    scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    before_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    before_at: AwareDatetime
    after_at: AwareDatetime
    elapsed_seconds: int = Field(ge=1)
    first_attempt_observed: int = Field(ge=0)
    latest_attempt_changed: int = Field(ge=0)
    newly_canonical: int = Field(ge=0)
    canonical_regressions: int = Field(ge=0)
    notice_version_delta: int
    indexed_version_delta: int
    event_delta: int
    state_transitions: dict[str, int]
    source_call_count: Literal["UNKNOWN"] = "UNKNOWN"
    capacity: Literal["UNKNOWN"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"


def compare(before: Report, after: Report) -> Progress:
    """Compare exact cohorts; latest-attempt changes are not source call counts."""
    elapsed = int((after.checked_at - before.checked_at).total_seconds())
    if before.scope_sha256 != after.scope_sha256 or elapsed < 1:
        raise ValueError("REPORT_COMPARISON_SCOPE_OR_TIME_INVALID")
    old = {w.window_key: w for w in before.windows}
    transitions: dict[str, int] = {}
    for w in after.windows:
        previous = old[w.window_key]
        if previous.state != w.state:
            pair = previous.state + "->" + w.state
            transitions[pair] = transitions.get(pair, 0) + 1
    return Progress(
        scope_sha256=after.scope_sha256,
        before_sha256=hashlib.sha256(before.model_dump_json(indent=2).encode()).hexdigest(),
        after_sha256=hashlib.sha256(after.model_dump_json(indent=2).encode()).hexdigest(),
        before_at=before.checked_at,
        after_at=after.checked_at,
        elapsed_seconds=elapsed,
        first_attempt_observed=sum(
            old[w.window_key].attempt_id is None and w.attempt_id is not None for w in after.windows
        ),
        latest_attempt_changed=sum(
            old[w.window_key].attempt_id != w.attempt_id for w in after.windows
        ),
        newly_canonical=sum(
            old[w.window_key].canonical_at is None and w.canonical_at is not None
            for w in after.windows
        ),
        canonical_regressions=sum(
            old[w.window_key].canonical_at is not None and w.canonical_at is None
            for w in after.windows
        ),
        notice_version_delta=sum(w.notice_versions for w in after.windows)
        - sum(w.notice_versions for w in before.windows),
        indexed_version_delta=sum(w.indexed_versions for w in after.windows)
        - sum(w.indexed_versions for w in before.windows),
        event_delta=sum(w.procedure_events for w in after.windows)
        - sum(w.procedure_events for w in before.windows),
        state_transitions=dict(sorted(transitions.items())),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-day", type=date.fromisoformat, required=True)
    parser.add_argument("--last-day", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    # Validate before opening a connection. No source clients are instantiated.
    scope = make_scope(args.first_day, args.last_day, datetime.now(UTC))
    coordinates = scope_coordinates(scope)
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with PostgresStorage(engine).transaction(COMPANY, consistent_read=True) as conn:
            if conn.scalar(text("SHOW transaction_read_only")) != "on":
                raise ValueError("REPORT_TRANSACTION_NOT_READ_ONLY")
            if conn.scalar(text("SHOW transaction_isolation")) != "repeatable read":
                raise ValueError("REPORT_TRANSACTION_NOT_REPEATABLE_READ")
            conn.execute(text("SET LOCAL statement_timeout = '30s'"))
            snapshot = str(conn.scalar(text("SELECT pg_current_snapshot()::text")))
            windows = read_windows(conn, tuple(coordinates))
            # Snapshot is fixed; sample the clock after reading visible evidence.
            now = conn.scalar(text("SELECT clock_timestamp()"))
            report = Report(
                checked_at=now,
                snapshot=snapshot,
                first_day=scope.first_day,
                last_day=scope.last_day,
                scope_sha256=scope.sha256,
                expected_windows=scope.expected_windows,
                windows=windows,
                cohorts=summarize(windows, coordinates, now),
            )
    finally:
        engine.dispose()
    proof = ROOT / f"s192-ingestion-{uuid.uuid4()}.json"
    fd = os.open(proof, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf8") as stream:
        stream.write(report.model_dump_json(indent=2))
    proof.chmod(0o600)
    print(
        json.dumps(
            {
                "status": "OBSERVED",
                "company_id": COMPANY,
                "checked_at": now.isoformat(),
                "proof": str(proof),
                "sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
                "scope_sha256": scope.sha256,
                "expected_windows": scope.expected_windows,
                "cohorts": [c.model_dump(mode="json") for c in report.cohorts],
                "source_requests": 0,
                "database_writes": 0,
                "coverage": "UNKNOWN",
                "freshness": "UNKNOWN",
                "document_coverage": "UNKNOWN",
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, SQLAlchemyError, OSError, KeyError):
        # Never reflect an exception containing SQL parameters or environment values.
        print('{"status":"BLOCKED","reason":"INGESTION_REPORT_UNAVAILABLE","coverage":"UNKNOWN"}')
        raise SystemExit(65) from None
