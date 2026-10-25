"""Create a fully readable backup before retaining two verified dumps and the original."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

COMPANY = "local-eis-supplier"
ORIGINAL = "procurement-20260927T202610Z.dump"
ORIGINAL_SHA = "a51b9165049995110ae1ea44e3ec077e2050b0afe78d309e6bedfb5a95d1657d"
NAME = re.compile(r"procurement-(\d{8}T\d{6}Z)\.dump")
RESERVE = 40 * 1024**3


class BackupFailure(RuntimeError):
    """Public codes contain no command output or credentials."""


@dataclass(frozen=True)
class Paths:
    project: Path = Path("/home/syurai/vibe-seller")
    state: Path = Path("/home/syurai/vibe-seller-state")
    original_sha: str = ORIGINAL_SHA

    @property
    def backups(self) -> Path:
        return self.state / "backups"

    @property
    def evidence(self) -> Path:
        return self.state / "backup-rotation" / COMPANY


@dataclass(frozen=True)
class Identity:
    name: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


def identity(path: Path) -> Identity:
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise BackupFailure("UNSAFE_BACKUP_FILE")
    return Identity(
        path.name, value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
    )


def unchanged(folder: Path, expected: Identity) -> None:
    if identity(folder / expected.name) != expected:
        raise BackupFailure("BACKUP_CHANGED")


def secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = path.stat()
    if path.resolve() != path.absolute() or value.st_uid != os.getuid() or value.st_mode & 0o022:
        raise BackupFailure("UNSAFE_BACKUP_DIRECTORY")


def sync_directory(folder: Path) -> None:
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def persist(path: Path, payload: dict) -> None:
    """Immutable, durable local evidence; never overwrite a prior run."""
    fd, temporary = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        os.unlink(temporary)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def backup_lock(paths: Paths):
    fd = os.open(paths.state / "server-backup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
            raise BackupFailure("UNSAFE_BACKUP_LOCK")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BackupFailure("BACKUP_BUSY") from error
        yield
    finally:
        os.close(fd)


class Operations:
    def __init__(self, paths: Paths):
        self.prefix = [
            "sudo",
            "-n",
            "docker",
            "compose",
            "-p",
            "vibe-seller",
            "-f",
            str(paths.project / "docker-compose.server.yml"),
            "exec",
            "-T",
            "db",
        ]

    def command(self, args: list[str], code: str, **kwargs) -> bytes:
        try:
            return (
                subprocess.run(
                    self.prefix + args, check=True, stderr=subprocess.PIPE, timeout=7200, **kwargs
                ).stdout
                or b""
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise BackupFailure(code) from error

    def database_size(self) -> int:
        raw = self.command(
            [
                "psql",
                "-U",
                "procurement_owner",
                "-d",
                "procurement",
                "-Atqc",
                "SELECT pg_database_size(current_database())",
            ],
            "DATABASE_SIZE_UNAVAILABLE",
            stdout=subprocess.PIPE,
        ).strip()
        if not raw.isdigit() or int(raw) <= 0:
            raise BackupFailure("DATABASE_SIZE_UNAVAILABLE")
        return int(raw)

    def dump(self, stream: BinaryIO) -> None:
        self.command(
            ["pg_dump", "-U", "procurement_owner", "-d", "procurement", "-Fc", "--no-owner"],
            "DUMP_FAILED",
            stdout=stream,
        )

    def verify(self, stream: BinaryIO) -> None:
        # Decode ALL data, not only the table of contents. No database writes.
        self.command(
            ["pg_restore", "--file=/dev/null"],
            "ARCHIVE_UNREADABLE",
            stdin=stream,
            stdout=subprocess.DEVNULL,
        )

    def audit(self, payload: dict) -> None:
        code = (
            "R="
            + repr(payload)
            + "\n"
            + """import os,uuid
from datetime import datetime,timezone
from sqlalchemy import create_engine,insert
from procurement.storage.repository import PostgresStorage
from procurement.storage.models import audit_events
e=create_engine(os.environ['DATABASE_URL'],hide_parameters=True)
try:
 with PostgresStorage(e).transaction(R['company_id']) as c:
  c.execute(insert(audit_events).values(company_id=R['company_id'],event_id=str(uuid.uuid4()),actor_id='scheduled-backup',event_type='EIS_BACKUP_ROTATION',object_type='installation-backup',object_id=R['run_id'],occurred_at=datetime.now(timezone.utc),basis=R))
finally:e.dispose()
"""
        )
        try:
            subprocess.run(
                ["sudo", "-n", "docker", "exec", "-i", "vibe-seller-api-1", "python", "-"],
                input=code.encode(),
                check=True,
                capture_output=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise BackupFailure("AUDIT_UNAVAILABLE") from error


def checked_hash(path: Path, ops: Operations | None = None) -> tuple[Identity, str]:
    before = identity(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if ops is not None:
            ops.verify(stream)
            stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    unchanged(path.parent, before)
    return before, digest


def inventory(folder: Path, now: datetime) -> dict[str, Identity]:
    result = {}
    for path in folder.iterdir():
        match = NAME.fullmatch(path.name)
        if match is None:
            continue
        stamp = datetime.strptime(match[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if stamp > now:
            raise BackupFailure("BACKUP_DATE_IN_FUTURE")
        result[path.name] = identity(path)
    return result


def run_backup(paths: Paths, ops: Operations, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise BackupFailure("NAIVE_BACKUP_TIME")
    now = now.astimezone(UTC)
    for folder in (paths.state, paths.backups, paths.evidence):
        secure_directory(folder)
    with backup_lock(paths):
        old = inventory(paths.backups, now)
        original, digest = checked_hash(paths.backups / ORIGINAL)
        if digest != paths.original_sha:
            raise BackupFailure("ORIGINAL_BACKUP_CHANGED")
        size = ops.database_size()
        if size <= 0 or shutil.disk_usage(paths.backups).free < size + RESERVE:
            raise BackupFailure("DISK_RESERVE_REACHED")
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        final = paths.backups / ("procurement-" + stamp + ".dump")
        if final.exists() or final.is_symlink():
            raise BackupFailure("BACKUP_NAME_EXISTS")
        fd, temporary = tempfile.mkstemp(prefix=".procurement-" + stamp + "-", dir=paths.backups)
        try:
            with os.fdopen(fd, "wb") as stream:
                ops.dump(stream)
                stream.flush()
                os.fsync(stream.fileno())
            _, new_sha = checked_hash(Path(temporary), ops)
            os.link(temporary, final)
            os.unlink(temporary)
            sync_directory(paths.backups)
        finally:
            Path(temporary).unlink(missing_ok=True)
        created = identity(final)
        verified = [{"identity": asdict(created), "sha256": new_sha}]
        prior = sorted((name for name in old if name != ORIGINAL), reverse=True)
        if prior:
            previous, previous_sha = checked_hash(paths.backups / prior[0], ops)
            if previous != old[prior[0]]:
                raise BackupFailure("BACKUP_CHANGED")
            verified.append({"identity": asdict(previous), "sha256": previous_sha})
        keep = {entry["identity"]["name"] for entry in verified} | {ORIGINAL}
        expected = old | {final.name: created}
        if inventory(paths.backups, now) != expected:
            raise BackupFailure("BACKUP_SET_CHANGED")
        plan = {
            "schema_version": "backup-rotation-v1",
            "company_id": COMPANY,
            "scope": "installation",
            "run_id": stamp,
            "status": "PREPARED",
            "verified": verified,
            "original": {"identity": asdict(original), "sha256": digest},
            "delete": [asdict(old[name]) for name in sorted(old) if name not in keep],
        }
        persist(paths.evidence / (stamp + ".plan.json"), plan)
        ops.audit(plan)
        deleted = []
        for entry in plan["delete"]:
            if inventory(paths.backups, now) != expected:
                raise BackupFailure("BACKUP_SET_CHANGED")
            for name in keep:
                unchanged(paths.backups, expected[name])
            target = Identity(**entry)
            unchanged(paths.backups, target)
            (paths.backups / target.name).unlink()
            sync_directory(paths.backups)
            deleted.append(target.name)
            expected.pop(target.name)
            persist(
                paths.evidence / (stamp + f".deleted-{len(deleted):04d}.json"),
                {"company_id": COMPANY, "run_id": stamp, "deleted": entry},
            )
        result = plan | {"status": "COMPLETED", "deleted": deleted}
        persist(paths.evidence / (stamp + ".completed.json"), result)
        ops.audit(result)
        return result


def main() -> int:
    try:
        paths = Paths()
        result = run_backup(paths, Operations(paths))
        print(
            json.dumps(
                {
                    "status": "BACKUP_OK",
                    "run_id": result["run_id"],
                    "deleted_count": len(result["deleted"]),
                    "company_id": COMPANY,
                }
            )
        )
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, BackupFailure) else "BACKUP_OPERATION_FAILED"
        print(json.dumps({"status": "BACKUP_FAILED", "reason": reason, "company_id": COMPANY}))
        return 75 if reason in {"BACKUP_BUSY", "DISK_RESERVE_REACHED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
