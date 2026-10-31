"""One bounded provider page and tenant-scoped recovery candidate selection."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from procurement.eis_freshness_dispatch_cli import joint_mandatory_status, urgent44_status
from procurement.eis_history_reader import read_history_demand
from procurement.sources.gosplan_queue import GosplanQueue, QueueError, release_guard_active
from procurement.sources.gosplan_recovery import RECOVERABLE_44
from procurement.sources.gosplan_scan import scan_page
from procurement.storage.models import eis_223_notice_versions, eis_notice_versions
from procurement.storage.repository import PostgresStorage

COMPANY = "local-eis-supplier"
QUEUE = Path("/var/lib/eis-browser/gosplan/local-eis-supplier/queue.sqlite")
SECRET = Path("/run/secrets/gosplan-key")
ALLOWED_223 = frozenset(("purchaseNoticeKESMBO", "purchaseNoticeZPESMBO"))


def read_secret(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("SECRET_PERMISSIONS_INVALID")
        raw = stream.read(1025)
    if not 1 <= len(raw) <= 1024:
        raise ValueError("SECRET_INVALID")
    key = raw.decode("ascii").strip()
    if not key or any(c.isspace() for c in key):
        raise ValueError("SECRET_INVALID")
    return key


def choose_candidate(queue: GosplanQueue, storage: PostgresStorage, law: str) -> str | None:
    """Select missing official IDs once; any prior attempt requires manual reconciliation."""
    pending = [row for row in queue.pending_with_types(COMPANY) if row[0] == law]
    attempted = {
        row[0]
        for row in queue.conn.execute(
            "SELECT DISTINCT number FROM attempts WHERE company=? AND law=?", (COMPANY, law)
        )
    }
    candidates = [row for row in pending if row[1] not in attempted]
    table = eis_notice_versions if law == "44" else eis_223_notice_versions
    with storage.transaction(COMPANY, consistent_read=True) as conn:
        conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
        conn.execute(text("SET LOCAL lock_timeout = '2000ms'"))
        present = set(
            conn.scalars(
                select(table.c.purchase_number)
                .distinct()
                .where(
                    table.c.company_id == COMPANY,
                    table.c.purchase_number.in_([row[1] for row in candidates]),
                )
            )
        )
    queue.discard_present(COMPANY, law, present)
    for _, number, _, family in candidates:
        if number not in present and family in (RECOVERABLE_44 if law == "44" else ALLOWED_223):
            return number
    return None


def preflight_recovery(storage: PostgresStorage) -> bool:
    """Advisory only: the real source wrapper repeats all checks under lease."""
    now = datetime.now(UTC)
    if urgent44_status(storage, COMPANY, now) not in ("IDLE", "READY"):
        return False
    if joint_mandatory_status(storage, COMPANY, now) not in ("IDLE", "READY"):
        return False
    return read_history_demand(storage, COMPANY, verify_quarantine=True).classification.status in (
        "IDLE",
        "READY",
    )


def run(law: str) -> dict[str, object]:
    if release_guard_active():
        return {"status": "UNKNOWN", "reason": "RELEASE_GUARD"}
    if law not in ("44", "223"):
        raise ValueError("LAW_INVALID")
    key = read_secret(SECRET)
    storage = PostgresStorage.from_url(
        os.environ["DATABASE_URL"],
        hide_parameters=True,
        connect_args={"options": "-c statement_timeout=5000 -c lock_timeout=2000"},
    )
    now = datetime.now(UTC)
    queue = GosplanQueue(QUEUE)
    try:
        with httpx.Client(timeout=25, trust_env=True) as client:
            batch = scan_page(client, key, queue, COMPANY, law, now)
        result = asdict(batch)
        if batch.status != "STOPPED":
            result["candidate"] = None
            return result
        result["candidate"] = choose_candidate(queue, storage, law)
        result["recovery_eligible"] = bool(result["candidate"] and preflight_recovery(storage))
        result["pending_count"] = len(queue.pending(COMPANY))
        result["law"] = law
        return result
    finally:
        queue.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--law", choices=("44", "223"), required=True)
    args = parser.parse_args()
    try:
        result = run(args.law)
    except (
        ValueError,
        KeyError,
        OSError,
        UnicodeError,
        sqlite3.Error,
        QueueError,
        SQLAlchemyError,
    ):
        result = {"status": "UNKNOWN", "reason": "CONFIG_STORE_OR_DATABASE_ERROR"}
    print(json.dumps(result, ensure_ascii=False))
    # An activated split advances one bounded page per cycle.  Its coverage is
    # still UNKNOWN, but this particular result is progress rather than failure.
    return 0 if (result["status"] == "STOPPED" or (
        result["status"] == "UNKNOWN" and result.get("reason") == "OFFSET_RECOVERY"
        and result.get("candidate") is None
    ) or (
        args.law == "44" and result["status"] == "UNKNOWN"
        and result.get("reason") == "OFFSET_RECOVERY_NEXT_223"
        and result.get("candidate") is None
    )) else 1


if __name__ == "__main__":
    raise SystemExit(main())
