"""Best-effort private process observations; never source receipts or worker output."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

DIRECTORY = Path("/home/syurai/vibe-seller-state/eis-worker-metrics")
MAX_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 2048
LANES = {
    "corpus": ("server-corpus-worker", {"run", "plan", "extend", "status", "unknown"}),
    "priority": ("server-freshness-worker", {"fresh", "smoke"}),
    "documents": ("server-document-dispatch", {"documents"}),
    "223_refresh": ("server-223-refresh", {"refresh"}),
}
PHASES = {
    "dispatch_start",
    "import_wait_start",
    "import_acquired",
    "work_start",
    "work_finish",
    "dispatch_finish",
}
RESULTS = {"SUCCESS", "IDLE", "BUSY", "TIMEOUT", "ERROR", "INTERRUPTED", "UNKNOWN"}


def event(arguments: list[str]) -> dict[str, object]:
    if len(arguments) != 8 or any(len(value) > 80 for value in arguments):
        raise ValueError("INVALID_EVENT")
    company, lane, operation, run_id, phase, result, raw_exit, signal = arguments
    if company != "local-eis-supplier" or lane not in LANES:
        raise ValueError("INVALID_EVENT")
    actor, operations = LANES[lane]
    if operation not in operations or phase not in PHASES or str(uuid.UUID(run_id)) != run_id:
        raise ValueError("INVALID_EVENT")
    if (result and result not in RESULTS) or (signal and signal not in {"INT", "TERM"}):
        raise ValueError("INVALID_EVENT")
    if raw_exit and (
        not raw_exit.isascii() or not raw_exit.isdecimal() or not 0 <= int(raw_exit) <= 255
    ):
        raise ValueError("INVALID_EVENT")
    with open("/proc/sys/kernel/random/boot_id", "rb") as source:
        boot = source.read(80).strip()
    if len(boot) != 36 or str(uuid.UUID(boot.decode("ascii"))).encode() != boot:
        raise ValueError("INVALID_BOOT")
    payload: dict[str, object] = {
        "schema_version": 1,
        "company_id": company,
        "actor_id": actor,
        "lane": lane,
        "operation": operation,
        "run_id": run_id,
        "phase": phase,
        "timestamp": datetime.now(UTC).isoformat(),
        "monotonic_ns": time.monotonic_ns(),
        "boot_id_sha256": hashlib.sha256(boot).hexdigest(),
    }
    if result:
        payload["result"] = result
    if raw_exit:
        payload["exit_code"] = int(raw_exit)
    if signal:
        payload["signal"] = signal
    return payload


def private_file(path: Path) -> int:
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        0o600,
    )
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
        os.close(fd)
        raise ValueError("INVALID_FILE")
    os.fchmod(fd, 0o600)
    return fd


def append(payload: dict[str, object]) -> None:
    import fcntl

    line = (json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    if len(line) > MAX_LINE_BYTES:
        raise ValueError("LINE_LIMIT")
    DIRECTORY.mkdir(mode=0o700, exist_ok=True)
    info = DIRECTORY.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError("INVALID_DIRECTORY")
    DIRECTORY.chmod(0o700)
    current = DIRECTORY / "local-eis-supplier.jsonl"
    previous = DIRECTORY / "local-eis-supplier.previous.jsonl"
    lock = private_file(DIRECTORY / "local-eis-supplier.lock")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if previous.exists():
            previous_fd = private_file(previous)
            try:
                if os.fstat(previous_fd).st_size > MAX_BYTES:
                    os.ftruncate(previous_fd, 0)
            finally:
                os.close(previous_fd)
        fd = private_file(current)
        try:
            size = os.fstat(fd).st_size
            if size > MAX_BYTES:
                # An unexpected oversized file cannot be promoted beyond the cap.
                os.ftruncate(fd, 0)
                size = 0
            if size + len(line) > MAX_BYTES:
                os.close(fd)
                fd = -1
                os.replace(current, previous)
                fd = private_file(current)
            if os.write(fd, line) != len(line):
                raise OSError("SHORT_APPEND")
        finally:
            if fd >= 0:
                os.close(fd)
    finally:
        os.close(lock)


def main(arguments: list[str]) -> int:
    # No reflection, including exception/argv/environment text.
    with suppress(Exception):
        append(event(arguments))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
