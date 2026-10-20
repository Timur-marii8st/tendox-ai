"""Offline reparse of retained NO_DATA replies, bound to tenant audit and attempt hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from procurement.sources.eis_no_data_evidence import (
    NoDataRetention,
    NoDataVerification,
    no_data_evidence_root,
    verify_no_data_reply,
)
from procurement.storage.models import audit_events, eis_sync_attempts
from procurement.storage.repository import PostgresStorage

COMPANY: Literal["local-eis-supplier"] = "local-eis-supplier"
ROOT = Path("/var/lib/eis-browser/research/rejected")


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Record(Evidence):
    audit_event_id: UUID
    audit_actor_id: str = Field(min_length=1, max_length=256)
    audit_at: AwareDatetime
    receipt: NoDataRetention
    verification: NoDataVerification
    journal_attempt_id: UUID | None
    journal_attempted_at: AwareDatetime | None
    journal_match_status: Literal["PASS", "UNKNOWN"]

    @model_validator(mode="after")
    def consistent(self) -> Record:
        if self.receipt.company_id != COMPANY or self.receipt.status != "RETAINED":
            raise ValueError("AUDIT_SCOPE_INVALID")
        if self.audit_at != self.receipt.observed_at:
            raise ValueError("AUDIT_TIME_INVALID")
        if self.verification.status == "PASS" and (
            self.receipt.manifest != self.verification.manifest
            or self.receipt.manifest_sha256 != self.verification.manifest_sha256
        ):
            raise ValueError("AUDIT_ARTIFACT_MISMATCH")
        if (self.journal_attempt_id is None) != (self.journal_attempted_at is None):
            raise ValueError("JOURNAL_REFERENCE_INVALID")
        if self.journal_match_status != ("PASS" if self.journal_attempt_id else "UNKNOWN"):
            raise ValueError("JOURNAL_REFERENCE_INVALID")
        if self.journal_attempted_at and self.journal_attempted_at < self.audit_at:
            raise ValueError("JOURNAL_TIME_INVALID")
        return self


class Report(Evidence):
    schema_version: Literal["eis-no-data-offline-verification-v1"] = (
        "eis-no-data-offline-verification-v1"
    )
    company_id: Literal["local-eis-supplier"] = COMPANY
    checked_at: AwareDatetime
    since: AwareDatetime
    snapshot: str
    limit: int = Field(ge=1, le=20)
    retention_status_counts: dict[Literal["RETAINED", "FAILED"], int]
    records: tuple[Record, ...] = Field(max_length=20)
    source_requests: Literal[0] = 0
    database_writes: Literal[0] = 0
    transaction_read_only: Literal[True] = True
    source_absence: Literal["UNKNOWN"] = "UNKNOWN"
    independent_corroboration: Literal["UNKNOWN"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> Report:
        validate_since(self.since, self.checked_at)
        if len(self.records) > self.limit or len({r.audit_event_id for r in self.records}) != len(
            self.records
        ):
            raise ValueError("REPORT_BOUND_INVALID")
        if len(self.records) > self.retention_status_counts.get("RETAINED", 0):
            raise ValueError("REPORT_COUNT_INVALID")
        if any(n < 0 for n in self.retention_status_counts.values()):
            raise ValueError("REPORT_COUNT_INVALID")
        if any(
            not self.since <= r.audit_at <= self.checked_at
            or (r.journal_attempted_at and r.journal_attempted_at > self.checked_at)
            for r in self.records
        ):
            raise ValueError("REPORT_TIME_INVALID")
        return self


def validate_since(since: datetime, now: datetime) -> None:
    if (
        since.tzinfo is None
        or since.utcoffset() is None
        or not now - timedelta(days=7) <= since <= now
    ):
        raise ValueError("REPORT_TIME_RANGE_INVALID")


def read_report(conn: Connection, since: datetime, limit: int) -> Report:
    if (
        conn.scalar(text("SHOW transaction_read_only")) != "on"
        or conn.scalar(text("SHOW transaction_isolation")) != "repeatable read"
    ):
        raise ValueError("REPORT_SNAPSHOT_INVALID")
    conn.execute(text("SET LOCAL statement_timeout='30s'"))
    now = conn.scalar(text("SELECT clock_timestamp()"))
    snapshot = str(conn.scalar(text("SELECT pg_current_snapshot()::text")))
    validate_since(since, now)
    if not 1 <= limit <= 20:
        raise ValueError("REPORT_BOUND_INVALID")
    root = no_data_evidence_root()
    if root is None:
        raise ValueError("RETENTION_DISABLED")
    audit = audit_events
    conditions = (
        audit.c.company_id == COMPANY,
        audit.c.event_type == "EIS_NO_DATA_RESPONSE_EVIDENCE",
        audit.c.occurred_at.between(since, now),
    )
    status = audit.c.basis["evidence"]["status"].astext
    counts: dict[Literal["RETAINED", "FAILED"], int] = {
        row[0]: row[1]
        for row in conn.execute(select(status, func.count()).where(*conditions).group_by(status))
    }
    records = []
    rows = conn.execute(
        select(audit.c.event_id, audit.c.actor_id, audit.c.occurred_at, audit.c.basis)
        .where(*conditions, status == "RETAINED")
        .order_by(audit.c.occurred_at.desc(), audit.c.event_id.desc())
        .limit(limit)
    ).mappings()
    for row in rows:
        receipt = NoDataRetention.model_validate(row["basis"]["evidence"])
        verified = verify_no_data_reply(
            root, COMPANY, receipt.window_key, receipt.source_response_sha256
        )
        attempt = eis_sync_attempts
        matching = conn.execute(
            select(attempt.c.attempt_id, attempt.c.attempted_at)
            .where(
                attempt.c.company_id == COMPANY,
                attempt.c.window_key == receipt.window_key,
                attempt.c.actor_id == row["actor_id"],
                attempt.c.outcome == "NO_DATA",
                attempt.c.source_response_sha256 == receipt.source_response_sha256,
                attempt.c.attempted_at.between(row["occurred_at"], now),
            )
            .order_by(attempt.c.attempted_at, attempt.c.attempt_id)
            .limit(1)
        ).first()
        records.append(
            Record(
                audit_event_id=row["event_id"],
                audit_actor_id=row["actor_id"],
                audit_at=row["occurred_at"],
                receipt=receipt,
                verification=verified,
                journal_attempt_id=matching.attempt_id if matching else None,
                journal_attempted_at=matching.attempted_at if matching else None,
                journal_match_status="PASS" if matching else "UNKNOWN",
            )
        )
    return Report(
        checked_at=now,
        since=since,
        snapshot=snapshot,
        limit=limit,
        retention_status_counts=counts,
        records=tuple(records),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=datetime.fromisoformat, required=True)
    parser.add_argument("--limit", type=int, default=20, choices=range(1, 21))
    args = parser.parse_args(argv)
    validate_since(args.since, datetime.now(UTC))
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with PostgresStorage(engine).transaction(COMPANY, consistent_read=True) as conn:
            report = read_report(conn, args.since, args.limit)
    finally:
        engine.dispose()
    blob = report.model_dump_json(indent=2).encode()
    if len(blob) > 1024**2:
        raise ValueError("REPORT_SIZE_INVALID")
    path = ROOT / f"s198-offline-replies-{uuid4()}.json"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(blob)
    print(
        json.dumps(
            dict(
                status="OBSERVED",
                checked_at=report.checked_at.isoformat(),
                retention_status_counts=report.retention_status_counts,
                verified_records=len(report.records),
                raw_matches=sum(r.verification.status == "PASS" for r in report.records),
                journal_matches=sum(r.journal_match_status == "PASS" for r in report.records),
                proof=str(path),
                sha256=hashlib.sha256(blob).hexdigest(),
                source_requests=0,
                database_writes=0,
                source_absence="UNKNOWN",
                independent_corroboration="UNKNOWN",
                coverage="UNKNOWN",
            )
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, SQLAlchemyError, OSError, KeyError):
        print(
            '{"status":"BLOCKED","reason":"NO_DATA_OFFLINE_REPORT_UNAVAILABLE","coverage":"UNKNOWN"}'
        )
        raise SystemExit(65) from None
