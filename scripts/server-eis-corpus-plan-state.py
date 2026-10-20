"""Fixed tenant cursor for source-free, bounded planning; never coverage approval."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

DIRECTORY = Path("/home/syurai/vibe-seller-state/eis-corpus-planner/local-eis-supplier")
COMPANY: Literal["local-eis-supplier"] = "local-eis-supplier"
FLOOR = date(2026, 10, 2)
KINDS = (
    "epNotificationEF2020",
    "epNotificationEZK2020",
    "epNotificationEOK2020",
    "epNotificationCancel",
    "epNotificationCancelFailure",
)


class ScopeFields(TypedDict):
    company_id: Literal["local-eis-supplier"]
    first_day: str
    last_day: str
    expected_windows: int
    scope_sha256: str
    coverage: Literal["UNKNOWN"]
    source_requests: Literal[0]


class Prepared(ScopeFields):
    status: Literal["READY"]


class Receipt(ScopeFields):
    status: Literal["PLANNED"]
    actor_id: Literal["server-corpus-worker"]
    new_targets: int
    checked_at: str


class Idle(TypedDict):
    status: Literal["IDLE"]
    company_id: Literal["local-eis-supplier"]
    coverage: Literal["UNKNOWN"]
    source_requests: Literal[0]


def scope(first: date, last: date) -> Prepared:
    body = dict(
        regions=tuple(f"{n:02d}" for n in range(1, 100)),
        document_types=KINDS,
        first_day=first,
        last_day=last,
        utc_offset_hours=3,
        region_registry_status="UNKNOWN",
        source_completeness="UNKNOWN",
    )
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()
    return dict(
        status="READY",
        company_id=COMPANY,
        first_day=first.isoformat(),
        last_day=last.isoformat(),
        expected_windows=495 * ((last - first).days + 1),
        scope_sha256=digest,
        coverage="UNKNOWN",
        source_requests=0,
    )


def validate_receipt(value: Any, today: date) -> Receipt:
    keys = {
        "status",
        "company_id",
        "actor_id",
        "first_day",
        "last_day",
        "expected_windows",
        "scope_sha256",
        "coverage",
        "source_requests",
        "new_targets",
        "checked_at",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("CURSOR_INVALID")
    first, last = date.fromisoformat(value["first_day"]), date.fromisoformat(value["last_day"])
    checked = datetime.fromisoformat(value["checked_at"])
    if (
        first < FLOOR
        or not 1 <= (last - first).days + 1 <= 3
        or last >= today
        or checked.utcoffset() != timedelta(0)
        or checked > datetime.now(UTC)
        or value["actor_id"] != "server-corpus-worker"
        or value["status"] != "PLANNED"
        or type(value["new_targets"]) is not int
        or not 0 <= value["new_targets"] <= value["expected_windows"]
    ):
        raise ValueError("CURSOR_INVALID")
    expected = scope(first, last)
    for key, wanted in expected.items():
        if key != "status" and (type(value[key]) is not type(wanted) or value[key] != wanted):
            raise ValueError("CURSOR_INVALID")
    return cast(Receipt, value)


def read_cursor(today: date) -> Receipt | None:
    if DIRECTORY.exists():
        parent = DIRECTORY.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid():
            raise ValueError("CURSOR_DIRECTORY_INVALID")
    path = DIRECTORY / "last-success.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size > 4096
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
        ):
            raise ValueError("CURSOR_INVALID")
        raw = os.read(fd, 4097)
        if len(raw) > 4096:
            raise ValueError("CURSOR_INVALID")
        return validate_receipt(json.loads(raw), today)
    finally:
        os.close(fd)


def due(today: date) -> Prepared | Idle:
    prior = read_cursor(today)
    first = date.fromisoformat(prior["last_day"]) + timedelta(days=1) if prior else FLOOR
    if first >= today:
        return dict(status="IDLE", company_id=COMPANY, coverage="UNKNOWN", source_requests=0)
    return scope(first, min(first + timedelta(days=2), today - timedelta(days=1)))


def complete(prepared: Any, result: Any, today: date) -> Receipt:
    if prepared != due(today) or prepared["status"] != "READY":
        raise ValueError("SCOPE_CHANGED")
    if (
        set(result)
        != {
            "status",
            "new_targets",
            "expected_windows",
            "scope_sha256",
            "region_registry_status",
            "coverage",
        }
        or result["status"] != "PLANNED"
        or result["coverage"] != "UNKNOWN"
        or result["region_registry_status"] != "UNKNOWN"
        or type(result["expected_windows"]) is not int
        or result["expected_windows"] != prepared["expected_windows"]
        or result["scope_sha256"] != prepared["scope_sha256"]
    ):
        raise ValueError("PLAN_RECEIPT_INVALID")
    receipt = prepared | dict(
        status="PLANNED",
        new_targets=result["new_targets"],
        actor_id="server-corpus-worker",
        checked_at=datetime.now(UTC).isoformat(),
    )
    receipt = validate_receipt(receipt, today)
    DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = DIRECTORY.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError("CURSOR_DIRECTORY_INVALID")
    DIRECTORY.chmod(0o700)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=DIRECTORY)
    try:
        with os.fdopen(fd, "w", encoding="utf8") as stream:
            json.dump(receipt, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, DIRECTORY / "last-success.json")
        directory_fd = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(name).unlink(missing_ok=True)
    return receipt


def main() -> int:
    today = datetime.now(timezone(timedelta(hours=3))).date()
    value: Prepared | Idle | Receipt
    try:
        if sys.argv[1:] == ["due"]:
            value = due(today)
        elif len(sys.argv) == 4 and sys.argv[1] == "complete":
            if any(len(v) > 4096 for v in sys.argv[2:]):
                raise ValueError("INPUT_LIMIT")
            value = complete(json.loads(sys.argv[2]), json.loads(sys.argv[3]), today)
        else:
            raise ValueError("COMMAND_INVALID")
    except (ValueError, TypeError, KeyError, OSError):
        print(
            json.dumps(
                dict(
                    status="BLOCKED",
                    reason="PLANNER_STATE_INVALID",
                    company_id=COMPANY,
                    coverage="UNKNOWN",
                    source_requests=0,
                )
            )
        )
        return 65
    print(json.dumps(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
