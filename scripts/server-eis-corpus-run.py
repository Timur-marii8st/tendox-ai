"""Serialized bounded continuation. Host only; never reads source credentials."""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, cast

REPO = Path("/home/syurai/vibe-seller")
STATE = Path("/home/syurai/vibe-seller-state")
COMPANY = "local-eis-supplier"
HORIZON = 840
MAX_SEGMENTS = 6
POLL_SECONDS = 2.0
OUTPUT_LIMIT = 1024 * 1024
COOPERATIVE = {"PRIORITY_REFRESH_REQUESTED", "REGIONAL_REFRESH_REQUESTED"}
COUNTERS = (
    "selected",
    "attempted",
    "synced",
    "skipped",
    "new_versions",
    "new_events",
    "partial_windows",
    "held_pairs",
    "replayed_projection_batches",
)


@dataclass(frozen=True)
class Segment:
    run_id: str
    started_at: str
    finished_at: str
    budget: int
    exit_code: int
    stdout_sha256: str
    status: str
    reason: str | None
    attempted: int | None


@dataclass(frozen=True)
class Output:
    status: str
    reason: str | None
    attempted: int


def arguments(argv: list[str]) -> tuple[list[str], int]:
    """Remove one unambiguous budget option; each child receives remaining budget."""
    if not argv or argv[0] != "run":
        raise ValueError("INVALID_ACTION")
    result: list[str] = []
    values: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--max-windows":
            index += 1
            if index == len(argv):
                raise ValueError("INVALID_BUDGET")
            values.append(argv[index])
        elif item.startswith("--max-windows="):
            values.append(item.partition("=")[2])
        else:
            result.append(item)
        index += 1
    if len(values) > 1 or (values and not re.fullmatch(r"[1-9][0-9]?", values[0])):
        raise ValueError("INVALID_BUDGET")
    budget = int(values[0]) if values else 60
    if not 1 <= budget <= 60:
        raise ValueError("INVALID_BUDGET")
    return result, budget


def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_KEY")
        result[key] = value
    return result


def validate_output(raw: bytes, budget: int, exit_code: int) -> Output:
    value = json.loads(raw, object_pairs_hook=no_duplicate_keys)
    expected = {*COUNTERS, "status", "reason", "rejected_windows", "coverage"}
    if not isinstance(value, dict) or set(value) != expected or value["coverage"] != "UNKNOWN":
        raise ValueError("INVALID_OUTPUT")
    if value["status"] not in {"PARTIAL", "BLOCKED"}:
        raise ValueError("INVALID_OUTPUT")
    reason = value["reason"]
    if reason is not None and (
        not isinstance(reason, str) or not re.fullmatch(r"[A-Z_]{1,80}", reason)
    ):
        raise ValueError("INVALID_OUTPUT")
    if (value["status"] == "BLOCKED") != (reason is not None):
        raise ValueError("INVALID_OUTPUT")
    if exit_code != (2 if value["status"] == "BLOCKED" else 0):
        raise ValueError("INVALID_EXIT")
    for key in COUNTERS:
        if type(value[key]) is not int or not 0 <= value[key] <= 2**63 - 1:
            raise ValueError("INVALID_COUNTER")
    if not 0 <= value["attempted"] <= value["selected"] <= budget:
        raise ValueError("INVALID_COUNTER")
    if value["synced"] + value["skipped"] > value["attempted"]:
        raise ValueError("INVALID_COUNTER")
    if value["partial_windows"] > value["attempted"]:
        raise ValueError("INVALID_COUNTER")
    if (
        not isinstance(value["rejected_windows"], list)
        or len(value["rejected_windows"]) > value["attempted"]
    ):
        raise ValueError("INVALID_COUNTER")
    return Output(value["status"], reason, value["attempted"])


def stamp() -> str:
    return datetime.now(UTC).isoformat()


class Runner:
    def __init__(self, argv: list[str]) -> None:
        self.argv, self.budget = arguments(argv)
        self.parent_id = str(uuid.uuid4())
        self.started_at = stamp()
        self.deadline = time.monotonic() + HORIZON
        self.cancelled = 0
        self.segments: list[Segment] = []
        self.attempted = 0
        self.segment_id = ""

    def cancel(self, signum: int, _frame: object) -> None:
        # Waiting stops promptly; an already running atomic window finishes safely.
        self.cancelled = signum

    def metric(self, phase: str, result: str = "", code: int | None = None) -> None:
        with suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                [
                    "python3",
                    str(REPO / "scripts/server-eis-metrics.py"),
                    COMPANY,
                    "corpus",
                    "run",
                    self.segment_id,
                    phase,
                    result,
                    "" if code is None else str(code),
                    signal.Signals(self.cancelled).name.removeprefix("SIG")
                    if self.cancelled
                    else "",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )

    def receipt(self, reason: str) -> None:
        directory = STATE / "eis-corpus-runs" / COMPANY
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        record = (
            json.dumps(
                {
                    "schema_version": 1,
                    "company_id": COMPANY,
                    "parent_id": self.parent_id,
                    "started_at": self.started_at,
                    "observed_at": stamp(),
                    "budget": self.budget,
                    "attempted": (
                        None if any(s.attempted is None for s in self.segments) else self.attempted
                    ),
                    "known_attempted_lower_bound": self.attempted,
                    "reason": reason,
                    "coverage": "UNKNOWN",
                    "horizon_seconds": HORIZON,
                    "segments": [asdict(s) for s in self.segments],
                },
                separators=(",", ":"),
            ).encode()
            + b"\n"
        )
        # Parent dispatch lease serializes writers. Bounded safe metadata only.
        current = directory / "runs.jsonl"
        if current.exists() and current.stat().st_size + len(record) > 2 * 1024 * 1024:
            os.replace(current, directory / "runs.previous.jsonl")
        fd = os.open(current, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "ab") as stream:
            stream.write(record)
            stream.flush()
            os.fsync(stream.fileno())

    def acquire(self, lease: BinaryIO) -> bool:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    def wait_import(self, lease: BinaryIO) -> bool:
        # Dispatch owners create/clean markers while holding their leases. Never
        # take import before those owners finish, never hold their leases at work.
        while not self.cancelled and time.monotonic() < self.deadline:
            with (STATE / "eis-223-dispatch.lock").open("ab") as regional:
                if self.acquire(regional):
                    with (STATE / "eis-priority.lock").open("ab") as priority:
                        if self.acquire(priority) and self.acquire(lease):
                            return True
            time.sleep(POLL_SECONDS)
        return False

    def worker(self, lease: BinaryIO, dispatch: BinaryIO, remaining: int) -> tuple[int, bytes, str]:
        command = [
            "sudo",
            "-n",
            "docker",
            "compose",
            "-p",
            "vibe-seller",
            "-f",
            "docker-compose.server.yml",
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "worker",
            "python",
            "-m",
            "procurement.eis_corpus_cli",
            *self.argv,
            "--max-windows",
            str(remaining),
            "--priority-request",
            "/var/lib/eis-browser/eis-priority.request",
            "--regional-request",
            "/var/lib/eis-browser/eis-223-refresh.request",
            "--company-id",
            COMPANY,
            "--actor-id",
            "server-corpus-worker",
            "--mandatory-fresh-first",
        ]
        captured = bytearray()
        digest = hashlib.sha256()
        overflow = False
        with subprocess.Popen(
            command, cwd=REPO, stdout=subprocess.PIPE, pass_fds=(lease.fileno(), dispatch.fileno())
        ) as child:
            assert child.stdout is not None
            while chunk := cast(io.BufferedReader, child.stdout).read1(65536):
                digest.update(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                if len(captured) + len(chunk) <= OUTPUT_LIMIT and not overflow:
                    captured.extend(chunk)
                else:
                    overflow = True
            code = child.wait()
        return code, b"" if overflow else bytes(captured), digest.hexdigest()

    def execute(self) -> int:
        with (STATE / "eis-corpus-dispatch.lock").open("ab") as dispatch:
            if not self.acquire(dispatch):
                print('{"status":"BLOCKED","reason":"CORPUS_WORKER_BUSY","coverage":"UNKNOWN"}')
                return 75
            with (STATE / "eis-import.lock").open("ab") as lease:
                for index in range(MAX_SEGMENTS):
                    remaining = self.budget - self.attempted
                    self.segment_id = str(uuid.uuid4())
                    self.metric("dispatch_start")
                    self.metric("import_wait_start")
                    acquired = self.acquire(lease) if index == 0 else self.wait_import(lease)
                    if not acquired:
                        code = 128 + self.cancelled if self.cancelled else 75
                        reason = (
                            "INTERRUPTED"
                            if self.cancelled
                            else (
                                "SERVER_IMPORT_BUSY"
                                if index == 0
                                else "CONTINUATION_HORIZON_REACHED"
                            )
                        )
                        self.metric(
                            "dispatch_finish", "INTERRUPTED" if self.cancelled else "BUSY", code
                        )
                        self.receipt(reason)
                        print(
                            json.dumps(
                                {"status": "BLOCKED", "reason": reason, "coverage": "UNKNOWN"}
                            )
                        )
                        return code
                    self.metric("import_acquired")
                    try:
                        health = subprocess.run(
                            [
                                "sudo",
                                "-n",
                                "docker",
                                "inspect",
                                "-f",
                                "{{.State.Health.Status}}",
                                "vibe-seller-eis-proxy-1",
                            ],
                            capture_output=True,
                            timeout=10,
                            check=False,
                        )
                        if health.returncode != 0 or health.stdout.strip() != b"healthy":
                            self.metric("dispatch_finish", "ERROR", 69)
                            self.receipt("PROXY_UNAVAILABLE")
                            return 69
                        # Proxy probe/metrics can consume the remaining start horizon.
                        if self.cancelled or (index > 0 and time.monotonic() >= self.deadline):
                            code = 128 + self.cancelled if self.cancelled else 75
                            self.metric(
                                "dispatch_finish",
                                "INTERRUPTED" if self.cancelled else "TIMEOUT",
                                code,
                            )
                            self.receipt(
                                "INTERRUPTED" if self.cancelled else "CONTINUATION_HORIZON_REACHED"
                            )
                            return code
                        started = stamp()
                        self.metric("work_start")
                        code, raw, digest = self.worker(lease, dispatch, remaining)
                        self.metric("work_finish", "SUCCESS" if code == 0 else "ERROR", code)
                    finally:
                        fcntl.flock(lease, fcntl.LOCK_UN)
                    self.metric("dispatch_finish", "SUCCESS" if code == 0 else "ERROR", code)
                    try:
                        value = validate_output(raw, remaining, code)
                    except (ValueError, TypeError, UnicodeDecodeError):
                        self.segments.append(
                            Segment(
                                self.segment_id,
                                started,
                                stamp(),
                                remaining,
                                code,
                                digest,
                                "UNKNOWN",
                                "INVALID_WORKER_OUTPUT",
                                None,
                            )
                        )
                        self.receipt("INVALID_WORKER_OUTPUT")
                        return code if code != 0 else 65
                    count = value.attempted
                    self.attempted += count
                    status, worker_reason = value.status, value.reason
                    self.segments.append(
                        Segment(
                            self.segment_id,
                            started,
                            stamp(),
                            remaining,
                            code,
                            digest,
                            status,
                            worker_reason,
                            count,
                        )
                    )
                    if self.cancelled:
                        self.receipt("INTERRUPTED")
                        return 128 + self.cancelled
                    if worker_reason not in COOPERATIVE:
                        self.receipt(worker_reason or "PASS_FINISHED")
                        return code
                    if self.attempted == self.budget:
                        self.receipt("WINDOW_BUDGET_EXHAUSTED")
                        return code
                    if index + 1 == MAX_SEGMENTS:
                        self.receipt("CONTINUATION_SEGMENT_LIMIT")
                        return code
                    self.receipt("WAITING_AFTER_YIELD")
        return 2


def main() -> int:
    os.umask(0o077)
    try:
        runner = Runner(sys.argv[1:])
        signal.signal(signal.SIGTERM, runner.cancel)
        signal.signal(signal.SIGINT, runner.cancel)
        return runner.execute()
    except (ValueError, OSError, subprocess.TimeoutExpired):
        print('{"status":"FAILED","reason":"CORPUS_DISPATCH_FAILED","coverage":"UNKNOWN"}')
        return 69


if __name__ == "__main__":
    raise SystemExit(main())
