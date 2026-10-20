"""Read-only operator quota and lifecycle evidence; never delete source replies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, create_engine, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_no_data_evidence import (
    APPLICATION_ID,
    FILE,
    MAX_DATABASE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PAYLOAD_BYTES,
    MAX_RECORDS,
    MAX_REPLY_BYTES,
    OVERFLOW_FILE,
    Failure,
    NoDataRetention,
    StoreFile,
    _private_path,
    no_data_evidence_root,
)
from procurement.storage.models import audit_events, eis_sync_attempts
from procurement.storage.repository import PostgresStorage

COMPANY: Literal["local-eis-supplier"] = "local-eis-supplier"
ROOT = Path("/var/lib/eis-browser/research/rejected")
WARNING_PERCENT: Literal[80] = 80
REVIEW_AGE_DAYS: Literal[30] = 30


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Quota(Evidence):
    used: int = Field(ge=0)
    limit: int = Field(gt=0)
    remaining: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent(self) -> Quota:
        if self.used > self.limit or self.remaining != self.limit - self.used:
            raise ValueError("QUOTA_INVALID")
        return self


class Store(Evidence):
    checked_at: AwareDatetime
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    reason: Literal[
        "COUNTERS_MATCH", "STORE_INVALID", "STORE_UNAVAILABLE", "STORE_MISSING", "DISABLED"
    ]
    snapshot_scope: Literal["SQLITE_METADATA_ONLY"] = "SQLITE_METADATA_ONLY"
    rows: Quota | None = None
    payload: Quota | None = None
    database: Quota | None = None
    tenant_rows: int | None = Field(default=None, ge=0)
    tenant_payload_bytes: int | None = Field(default=None, ge=0)
    tenant_oldest_at: AwareDatetime | None = None
    tenant_newest_at: AwareDatetime | None = None
    tenant_review_age_rows: int | None = Field(default=None, ge=0)
    review_age_days: Literal[30] = REVIEW_AGE_DAYS

    @model_validator(mode="after")
    def consistent(self) -> Store:
        refs = (
            self.rows,
            self.payload,
            self.database,
            self.tenant_rows,
            self.tenant_payload_bytes,
            self.tenant_review_age_rows,
        )
        if self.status != "PASS":
            if any(v is not None for v in refs) or self.tenant_oldest_at or self.tenant_newest_at:
                raise ValueError("UNKNOWN_COUNTERS_INVALID")
            if (self.status == "FAIL") != (self.reason == "STORE_INVALID"):
                raise ValueError("STORE_REASON_INVALID")
            if self.reason == "COUNTERS_MATCH":
                raise ValueError("STORE_REASON_INVALID")
            return self
        if self.reason != "COUNTERS_MATCH" or any(v is None for v in refs):
            raise ValueError("STORE_COUNTERS_REQUIRED")
        assert self.rows and self.payload and self.database
        assert self.tenant_rows is not None and self.tenant_payload_bytes is not None
        assert self.tenant_review_age_rows is not None
        if (self.rows.limit, self.payload.limit, self.database.limit) != (
            MAX_RECORDS,
            MAX_PAYLOAD_BYTES,
            MAX_DATABASE_BYTES,
        ):
            raise ValueError("STORE_LIMIT_INVALID")
        if (
            self.tenant_rows > self.rows.used
            or self.tenant_payload_bytes > self.payload.used
            or self.tenant_review_age_rows > self.tenant_rows
        ):
            raise ValueError("TENANT_COUNTERS_INVALID")
        if bool(self.tenant_rows) != bool(self.tenant_oldest_at and self.tenant_newest_at):
            raise ValueError("TENANT_AGE_INVALID")
        if (
            self.tenant_oldest_at
            and self.tenant_newest_at
            and not (self.tenant_oldest_at <= self.tenant_newest_at <= self.checked_at)
        ):
            raise ValueError("TENANT_AGE_INVALID")
        return self


def quota(used: int, limit: int) -> Quota:
    return Quota(used=used, limit=limit, remaining=limit - used)


def read_store(
    root: Path | None, now: datetime | None = None, *, store_file: StoreFile = FILE
) -> Store:
    """A bounded independent SQLite snapshot, not a raw-artifact integrity check."""
    fixed_now = now
    now = now or datetime.now(UTC)
    base = dict(checked_at=now)
    if root is None:
        return Store(status="UNKNOWN", reason="DISABLED", **base)
    conn = None
    try:
        path = _private_path(root, create=False, store_file=store_file)
        if not path.exists():
            return Store(status="UNKNOWN", reason="STORE_MISSING", **base)
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
        started = time.monotonic()
        conn.set_progress_handler(lambda: int(time.monotonic() - started > 2), 1000)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA cache_size=-1024")
        conn.execute("BEGIN")
        if (
            conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
            or conn.execute("PRAGMA user_version").fetchone()[0] != 1
            or conn.execute("PRAGMA page_size").fetchone()[0] != 4096
        ):
            raise ValueError("STORE_INVALID")
        if fixed_now is None:
            now = datetime.now(UTC)
            base = dict(checked_at=now)
        count = conn.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM replies LIMIT ?)", (MAX_RECORDS + 1,)
        ).fetchone()[0]
        if count > MAX_RECORDS:
            raise ValueError("STORE_INVALID")
        records, used = conn.execute("SELECT records,bytes FROM usage WHERE id=1").fetchone()
        total, invalid = conn.execute(
            """SELECT COALESCE(SUM(payload_bytes),0),
            COALESCE(SUM(CASE WHEN typeof(raw)!='blob' OR typeof(manifest)!='blob'
                OR length(raw) NOT BETWEEN 1 AND ? OR length(manifest) NOT BETWEEN 1 AND ?
                OR payload_bytes!=length(raw)+length(manifest) THEN 1 ELSE 0 END),0)
            FROM replies""",
            (MAX_REPLY_BYTES, MAX_MANIFEST_BYTES),
        ).fetchone()
        if (
            records != count
            or used != total
            or invalid
            or not isinstance(records, int)
            or not isinstance(used, int)
        ):
            raise ValueError("STORE_INVALID")
        # No foreign identity/metadata leaves SQLite. Only operator global counters do.
        rows, tenant_bytes = conn.execute(
            """SELECT COUNT(*),COALESCE(SUM(payload_bytes),0)
            FROM replies WHERE company_id=?""",
            (COMPANY,),
        ).fetchone()
        oldest = newest = None
        review = 0
        if rows:
            for (manifest,) in conn.execute(
                "SELECT manifest FROM replies WHERE company_id=?", (COMPANY,)
            ):
                if time.monotonic() - started > 2:
                    raise TimeoutError("STORE_UNAVAILABLE")
                data = json.loads(manifest)
                if data["company_id"] != COMPANY:
                    raise ValueError("STORE_INVALID")
                captured = datetime.fromisoformat(data["captured_at"])
                if captured.tzinfo is None or captured.utcoffset() is None or captured > now:
                    raise ValueError("STORE_INVALID")
                oldest = min(oldest, captured) if oldest else captured
                newest = max(newest, captured) if newest else captured
                review += captured <= now - timedelta(days=REVIEW_AGE_DAYS)
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        return Store(
            status="PASS",
            reason="COUNTERS_MATCH",
            rows=quota(records, MAX_RECORDS),
            payload=quota(used, MAX_PAYLOAD_BYTES),
            database=quota(pages * 4096, MAX_DATABASE_BYTES),
            tenant_rows=rows,
            tenant_payload_bytes=tenant_bytes,
            tenant_oldest_at=oldest,
            tenant_newest_at=newest,
            tenant_review_age_rows=review,
            **base,
        )
    except (ValueError, TypeError, KeyError, IndexError, sqlite3.DatabaseError) as error:
        unavailable = isinstance(error, sqlite3.OperationalError) and any(
            term in str(error).lower()
            for term in ("locked", "busy", "interrupted", "unable to open")
        )
        return Store(
            status="UNKNOWN" if unavailable else "FAIL",
            reason="STORE_UNAVAILABLE" if unavailable else "STORE_INVALID",
            **base,
        )
    except OSError:
        return Store(status="UNKNOWN", reason="STORE_UNAVAILABLE", **base)
    finally:
        if conn is not None:
            conn.close()


class FailureSample(Evidence):
    event_id: UUID
    occurred_at: AwareDatetime
    reason: Failure
    window_key: str = Field(max_length=160)
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Report(Evidence):
    schema_version: Literal["eis-no-data-store-health-v1"] = "eis-no-data-store-health-v1"
    company_id: Literal["local-eis-supplier"] = COMPANY
    checked_at: AwareDatetime
    since: AwareDatetime
    pg_snapshot: str
    store: Store
    overflow_store: Store | None = None
    maximum_database_bytes: Literal[268435456] = 268435456
    retained_events: int = Field(ge=0)
    failed_events: int = Field(ge=0)
    failure_counts: dict[Failure, int]
    failure_samples: tuple[FailureSample, ...] = Field(max_length=10)
    no_data_attempts: int = Field(ge=0)
    attempts_without_capture_audit: int = Field(ge=0)
    audit_completeness: Literal["PASS", "UNKNOWN"]
    action: Literal["OBSERVE", "PLAN_ARCHIVE", "INVESTIGATE_FAILURES", "RESTORE_VISIBILITY"]
    warning_percent: Literal[80] = WARNING_PERCENT
    lifecycle: Literal["HOLD_IMMUTABLE_EVIDENCE"] = "HOLD_IMMUTABLE_EVIDENCE"
    source_requests: Literal[0] = 0
    database_writes: Literal[0] = 0
    source_absence: Literal["UNKNOWN"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> Report:
        validate_since(self.since, self.checked_at)
        if (
            sum(self.failure_counts.values()) != self.failed_events
            or any(n < 0 for n in self.failure_counts.values())
            or len(self.failure_samples) > self.failed_events
            or self.attempts_without_capture_audit > self.no_data_attempts
            or len({s.event_id for s in self.failure_samples}) != len(self.failure_samples)
            or any(not self.since <= s.occurred_at <= self.checked_at for s in self.failure_samples)
        ):
            raise ValueError("REPORT_COUNTS_INVALID")
        if self.audit_completeness != (
            "UNKNOWN"
            if self.attempts_without_capture_audit or not self.no_data_attempts
            else "PASS"
        ):
            raise ValueError("AUDIT_STATUS_INVALID")
        if self.action != action_for(
            self.store, self.failed_events, self.attempts_without_capture_audit, self.overflow_store
        ):
            raise ValueError("REPORT_ACTION_INVALID")
        return self


def action_for(store: Store, failed: int, missing: int, overflow: Store | None = None) -> str:
    if store.status != "PASS" or (overflow is not None and overflow.status != "PASS"):
        return "RESTORE_VISIBILITY"
    if failed or missing:
        return "INVESTIGATE_FAILURES"
    writable = overflow if overflow is not None else store
    quotas = (writable.rows, writable.payload, writable.database)
    if (
        any(q and q.used * 100 >= q.limit * WARNING_PERCENT for q in quotas)
        or store.tenant_review_age_rows
        or (overflow is not None and overflow.tenant_review_age_rows)
    ):
        return "PLAN_ARCHIVE"
    return "OBSERVE"


def validate_since(since: datetime, now: datetime) -> None:
    if (
        since.tzinfo is None
        or since.utcoffset() is None
        or not now - timedelta(days=7) <= since <= now
    ):
        raise ValueError("REPORT_TIME_RANGE_INVALID")


def read_report(conn: Connection, since: datetime) -> Report:
    if (
        conn.scalar(text("SHOW transaction_read_only")) != "on"
        or conn.scalar(text("SHOW transaction_isolation")) != "repeatable read"
    ):
        raise ValueError("REPORT_SNAPSHOT_INVALID")
    conn.execute(text("SET LOCAL statement_timeout='30s'"))
    now = conn.scalar(text("SELECT clock_timestamp()"))
    validate_since(since, now)
    snapshot = str(conn.scalar(text("SELECT pg_current_snapshot()::text")))
    audit = audit_events
    cond = (
        audit.c.company_id == COMPANY,
        audit.c.event_type == "EIS_NO_DATA_RESPONSE_EVIDENCE",
        audit.c.occurred_at.between(since, now),
    )
    status = audit.c.basis["evidence"]["status"].astext
    reason = audit.c.basis["evidence"]["reason"].astext
    counts = {
        r[0]: r[1] for r in conn.execute(select(status, func.count()).where(*cond).group_by(status))
    }
    if set(counts) - {"RETAINED", "FAILED"}:
        raise ValueError("AUDIT_STATUS_INVALID")
    failures = {
        r[0]: r[1]
        for r in conn.execute(
            select(reason, func.count()).where(*cond, status == "FAILED").group_by(reason)
        )
    }
    samples = []
    for row in conn.execute(
        select(audit.c.event_id, audit.c.occurred_at, audit.c.basis)
        .where(*cond, status == "FAILED")
        .order_by(audit.c.occurred_at.desc(), audit.c.event_id.desc())
        .limit(10)
    ):
        receipt = NoDataRetention.model_validate(row.basis["evidence"])
        if (
            receipt.status != "FAILED"
            or receipt.company_id != COMPANY
            or receipt.observed_at != row.occurred_at
        ):
            raise ValueError("AUDIT_BINDING_INVALID")
        samples.append(
            FailureSample(
                event_id=row.event_id,
                occurred_at=row.occurred_at,
                reason=receipt.reason,
                window_key=receipt.window_key,
                source_response_sha256=receipt.source_response_sha256,
            )
        )
    attempts = eis_sync_attempts
    capture_sha = audit.c.basis["evidence"]["source_response_sha256"].astext
    # Reduce matching captures once, rather than rescan audit for every attempt.
    # The earliest valid capture is sufficient for the existing <= time rule.
    captures = (
        select(
            audit.c.object_id.label("window_key"),
            audit.c.actor_id,
            capture_sha.label("sha"),
            func.min(audit.c.occurred_at).label("captured_at"),
        )
        .where(
            *cond,
            audit.c.basis["evidence"]["window_key"].astext == audit.c.object_id,
            audit.c.basis["evidence"]["company_id"].astext == COMPANY,
            status.in_(("RETAINED", "FAILED")),
        )
        .group_by(
            audit.c.object_id,
            audit.c.actor_id,
            capture_sha,
        )
        .subquery("captures")
    )
    attempted, missing = conn.execute(
        select(func.count(), func.count().filter(captures.c.captured_at.is_(None)))
        .select_from(
            attempts.outerjoin(
                captures,
                and_(
                    captures.c.window_key == attempts.c.window_key,
                    captures.c.actor_id == attempts.c.actor_id,
                    captures.c.sha == attempts.c.source_response_sha256,
                    captures.c.captured_at <= attempts.c.attempted_at,
                ),
            )
        )
        .where(
            attempts.c.company_id == COMPANY,
            attempts.c.outcome == "NO_DATA",
            attempts.c.attempted_at.between(since, now),
        )
    ).one()
    store = read_store(no_data_evidence_root())
    overflow_state = read_store(no_data_evidence_root(), store_file=OVERFLOW_FILE)
    overflow = None if overflow_state.reason in {"STORE_MISSING", "DISABLED"} else overflow_state
    failed = counts.get("FAILED", 0)
    return Report(
        checked_at=now,
        since=since,
        pg_snapshot=snapshot,
        store=store,
        overflow_store=overflow,
        retained_events=counts.get("RETAINED", 0),
        failed_events=failed,
        failure_counts=failures,
        failure_samples=tuple(samples),
        no_data_attempts=attempted,
        attempts_without_capture_audit=missing,
        audit_completeness="UNKNOWN" if missing or not attempted else "PASS",
        action=action_for(store, failed, missing, overflow),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=datetime.fromisoformat, required=True)
    args = parser.parse_args(argv)
    validate_since(args.since, datetime.now(UTC))
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with PostgresStorage(engine).transaction(COMPANY, consistent_read=True) as conn:
            report = read_report(conn, args.since)
    finally:
        engine.dispose()
    blob = report.model_dump_json(indent=2).encode()
    if len(blob) > 1024**2:
        raise ValueError("REPORT_SIZE_INVALID")
    path = ROOT / f"s199-store-health-{uuid4()}.json"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(blob)
    print(
        json.dumps(
            dict(
                status="OBSERVED",
                checked_at=report.checked_at.isoformat(),
                store=report.store.model_dump(mode="json"),
                overflow_store=(
                    report.overflow_store.model_dump(mode="json") if report.overflow_store else None
                ),
                maximum_database_bytes=report.maximum_database_bytes,
                retained_events=report.retained_events,
                failed_events=report.failed_events,
                failure_counts=report.failure_counts,
                no_data_attempts=report.no_data_attempts,
                attempts_without_capture_audit=report.attempts_without_capture_audit,
                audit_completeness=report.audit_completeness,
                action=report.action,
                proof=str(path),
                sha256=hashlib.sha256(blob).hexdigest(),
                source_requests=0,
                database_writes=0,
                coverage="UNKNOWN",
            )
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, SQLAlchemyError, OSError, KeyError):
        print('{"status":"BLOCKED","reason":"STORE_REPORT_UNAVAILABLE","coverage":"UNKNOWN"}')
        raise SystemExit(65) from None
