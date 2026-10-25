"""Private bounded source-response retention. A verified empty reply is not absence."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import UUID
from xml.etree import ElementTree as ET

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from procurement.sources.eis_feed import EisFeedResponse, parse_get_docs_ip_response

MAX_REPLY_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 16 * 1024
MAX_PAYLOAD_BYTES = 96 * 1024**2
MAX_RECORDS = 65536
MAX_DATABASE_BYTES = 128 * 1024**2
APPLICATION_ID = 0x4549534E
StoreFile = Literal["no-data.sqlite3", "no-data-overflow.sqlite3"]
FILE: StoreFile = "no-data.sqlite3"
OVERFLOW_FILE: StoreFile = "no-data-overflow.sqlite3"
STORE_FILES: tuple[StoreFile, ...] = (FILE, OVERFLOW_FILE)
KEY = (
    r"^getDocsIP/PRIZ/[0-9]{1,2}/([0-9]{4}-[0-9]{2}-[0-9]{2})(?:/([0-9]{2}))?"
    r"([+-][0-9]{2}):00(?:/(?:epNotificationEZK2020|epNotificationEOK2020|"
    r"epNotificationCancel|epNotificationCancelFailure))?$"
)
Failure = Literal[
    "BINDING_REJECTED",
    "RESPONSE_UNSAFE",
    "QUOTA_REACHED",
    "STORE_BUSY",
    "STORE_UNSAFE",
    "IO_FAILED",
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def no_data_evidence_root() -> Path | None:
    configured = os.environ.get("EIS_NO_DATA_EVIDENCE_DIR")
    state = os.environ.get("EIS_BROWSER_STATE_DIR")
    root = (
        configured
        if configured is not None
        else (str(Path(state) / "no-data-evidence") if state else "")
    )
    return Path(root) if root.strip() else None


class NoDataManifest(Evidence):
    schema_version: Literal["eis-no-data-response-v1"] = "eis-no-data-response-v1"
    company_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    actor_id: str = Field(min_length=1, max_length=256)
    window_key: str = Field(pattern=KEY, max_length=160)
    captured_at: AwareDatetime
    request_id: UUID
    response_id: UUID
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_bytes: int = Field(ge=1, le=MAX_REPLY_BYTES)
    source_created_at: AwareDatetime | None
    source_time_raw: str = Field(min_length=1, max_length=80)
    source_time_status: Literal["AWARE", "UNKNOWN_TZ"]
    service: Literal["IP"] = "IP"
    kind: Literal["BY_REGION"] = "BY_REGION"
    source_mode: Literal["PROD"] = "PROD"
    state: Literal["NO_DATA"] = "NO_DATA"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    source_absence: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> NoDataManifest:
        match = re.fullmatch(KEY, self.window_key)
        if match is None:
            raise ValueError("WINDOW_INVALID")
        day, hour, offset = match.groups()
        date.fromisoformat(day)
        if (hour is not None and not 0 <= int(hour) <= 23) or not -12 <= int(offset) <= 14:
            raise ValueError("WINDOW_INVALID")
        if (self.source_created_at is not None) != (self.source_time_status == "AWARE"):
            raise ValueError("SOURCE_TIME_INVALID")
        return self


class NoDataRetention(Evidence):
    status: Literal["RETAINED", "DISABLED", "FAILED"]
    reason: Failure | None = None
    company_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    window_key: str = Field(pattern=KEY, max_length=160)
    observed_at: AwareDatetime
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: NoDataManifest | None = None
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    record_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    relative_store_path: StoreFile | None = None
    replayed: bool = False
    source_requests: Literal[0] = 0
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> NoDataRetention:
        refs = (self.manifest, self.manifest_sha256, self.record_key, self.relative_store_path)
        if self.status == "RETAINED":
            if any(v is None for v in refs) or self.reason is not None:
                raise ValueError("RETENTION_REF_INVALID")
            assert self.manifest is not None
            if (
                self.manifest.company_id != self.company_id
                or self.manifest.window_key != self.window_key
                or self.manifest.source_response_sha256 != self.source_response_sha256
                or self.manifest.captured_at > self.observed_at
                or _identity(self.company_id, self.window_key, self.source_response_sha256)
                != self.record_key
                or hashlib.sha256(_encode(self.manifest)).hexdigest() != self.manifest_sha256
            ):
                raise ValueError("RETENTION_BINDING_INVALID")
        elif any(v is not None for v in refs) or self.replayed:
            raise ValueError("RETENTION_REF_INVALID")
        if (self.status == "FAILED") != (self.reason is not None):
            raise ValueError("RETENTION_REASON_INVALID")
        return self


class NoDataVerification(Evidence):
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    reason: Literal[
        "MATCHED_RAW_REPLY", "ARTIFACT_MISSING", "ARTIFACT_INVALID", "STORE_UNAVAILABLE"
    ]
    company_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    window_key: str = Field(pattern=KEY, max_length=160)
    source_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: NoDataManifest | None = None
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_requests: Literal[0] = 0
    source_absence: Literal["UNKNOWN"] = "UNKNOWN"
    independent_corroboration: Literal["UNKNOWN"] = "UNKNOWN"
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> NoDataVerification:
        if self.status == "PASS":
            if self.reason != "MATCHED_RAW_REPLY" or self.manifest is None:
                raise ValueError("VERIFICATION_INVALID")
            if (
                self.manifest.company_id != self.company_id
                or self.manifest.window_key != self.window_key
                or self.manifest.source_response_sha256 != self.source_response_sha256
                or hashlib.sha256(_encode(self.manifest)).hexdigest() != self.manifest_sha256
            ):
                raise ValueError("VERIFICATION_BINDING_INVALID")
        elif self.manifest is not None or self.manifest_sha256 is not None:
            raise ValueError("VERIFICATION_INVALID")
        if (self.status == "FAIL" and self.reason != "ARTIFACT_INVALID") or (
            self.status == "UNKNOWN"
            and self.reason not in ("ARTIFACT_MISSING", "STORE_UNAVAILABLE")
        ):
            raise ValueError("VERIFICATION_INVALID")
        return self


def _encode(manifest: NoDataManifest) -> bytes:
    return manifest.model_dump_json().encode()


def _identity(company: str, key: str, sha: str) -> str:
    return hashlib.sha256(
        json.dumps([company, key, sha], separators=(",", ":")).encode()
    ).hexdigest()


def _private_path(root: Path, *, create: bool, store_file: StoreFile = FILE) -> Path:
    if store_file not in STORE_FILES:
        raise ValueError("STORE_UNSAFE")
    root = root.absolute()
    for p in (root, *root.parents):
        if p.is_symlink():
            raise ValueError("STORE_UNSAFE")
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    elif not root.exists():
        return root / store_file
    if not root.is_dir() or (os.name != "nt" and stat.S_IMODE(root.stat().st_mode) & 0o077):
        raise ValueError("STORE_UNSAFE")
    path = root / store_file
    for suffix in ("", "-journal", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
            raise ValueError("STORE_UNSAFE")
    if create:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
    if path.exists() and (
        path.stat().st_size > MAX_DATABASE_BYTES
        or path.stat().st_nlink != 1
        or (os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600)
    ):
        raise ValueError("STORE_UNSAFE")
    return path


def _writer(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=1, isolation_level=None)
    try:
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA cache_size=-1024")
        conn.execute("PRAGMA page_size=4096")
        if conn.execute("PRAGMA page_size").fetchone()[0] != 4096:
            raise ValueError("STORE_UNSAFE")
        if conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise ValueError("STORE_UNSAFE")
        conn.execute("PRAGMA synchronous=FULL")
        pages = MAX_DATABASE_BYTES // 4096
        if conn.execute(f"PRAGMA max_page_count={pages}").fetchone()[0] > pages:
            raise ValueError("QUOTA_REACHED")
        conn.execute("BEGIN IMMEDIATE")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        app = conn.execute("PRAGMA application_id").fetchone()[0]
        if version == app == 0 and not conn.execute("SELECT name FROM sqlite_master").fetchone():
            conn.execute("""CREATE TABLE replies (
                record_key TEXT PRIMARY KEY, company_id TEXT NOT NULL,
                window_key TEXT NOT NULL, response_sha TEXT NOT NULL,
                manifest_sha TEXT NOT NULL, manifest BLOB NOT NULL, raw BLOB NOT NULL,
                payload_bytes INTEGER NOT NULL,
                UNIQUE(company_id,window_key,response_sha))""")
            conn.execute(
                "CREATE TABLE usage (id INTEGER PRIMARY KEY CHECK(id=1), "
                "records INTEGER, bytes INTEGER)"
            )
            conn.execute("INSERT INTO usage VALUES (1,0,0)")
            for verb in ("UPDATE", "DELETE"):
                conn.execute(
                    f"CREATE TRIGGER immutable_{verb.lower()} BEFORE {verb} ON replies "
                    "BEGIN SELECT RAISE(ABORT,'IMMUTABLE'); END"
                )
            conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
            conn.execute("PRAGMA user_version=1")
        elif version != 1 or app != APPLICATION_ID:
            raise ValueError("STORE_UNSAFE")
        return conn
    except BaseException:
        conn.close()
        raise


def _row(
    conn: sqlite3.Connection, company: str, key: str, sha: str
) -> tuple[NoDataManifest, str] | None:
    row = conn.execute(
        """SELECT manifest_sha,
        CASE WHEN length(manifest)<=? THEN manifest END,
        CASE WHEN length(raw)<=? THEN raw END
        FROM replies WHERE company_id=? AND window_key=? AND response_sha=? AND record_key=?""",
        (MAX_MANIFEST_BYTES, MAX_REPLY_BYTES, company, key, sha, _identity(company, key, sha)),
    ).fetchone()
    if row is None:
        return None
    manifest_sha, encoded, raw = row
    if not isinstance(encoded, bytes) or not isinstance(raw, bytes):
        raise ValueError("ARTIFACT_INVALID")
    manifest = NoDataManifest.model_validate_json(encoded)
    if hashlib.sha256(encoded).hexdigest() != manifest_sha or _encode(manifest) != encoded:
        raise ValueError("ARTIFACT_INVALID")
    parsed = parse_get_docs_ip_response(raw)
    if (
        manifest.company_id != company
        or manifest.window_key != key
        or manifest.source_response_sha256 != sha
        or parsed.source_sha256 != sha
        or manifest.raw_bytes != len(raw)
        or manifest.request_id != UUID(parsed.request_id)
        or manifest.response_id != UUID(parsed.response_id)
        or (parsed.service, parsed.kind, parsed.source_mode, parsed.state)
        != ("IP", "BY_REGION", "PROD", "NO_DATA")
        or manifest.source_created_at != parsed.created_at
        or manifest.source_time_raw != parsed.source_time_raw
        or manifest.source_time_status != parsed.source_time_status
    ):
        raise ValueError("ARTIFACT_INVALID")
    return manifest, manifest_sha


def _persist_reply(
    root: Path, store_file: StoreFile, manifest: NoDataManifest, raw: bytes
) -> tuple[NoDataManifest, str, bool]:
    path = _private_path(root, create=True, store_file=store_file)
    conn = _writer(path)
    try:
        existing = _row(
            conn, manifest.company_id, manifest.window_key, manifest.source_response_sha256
        )
        replayed = existing is not None
        if existing is None:
            encoded = _encode(manifest)
            if len(encoded) > MAX_MANIFEST_BYTES:
                raise ValueError("BINDING_REJECTED")
            records, used = conn.execute("SELECT records,bytes FROM usage WHERE id=1").fetchone()
            size = len(raw) + len(encoded)
            allocated = conn.execute("PRAGMA page_count").fetchone()[0] * 4096
            if (
                records >= MAX_RECORDS
                or used + size > MAX_PAYLOAD_BYTES
                or allocated >= MAX_DATABASE_BYTES
            ):
                raise ValueError("QUOTA_REACHED")
            sha = hashlib.sha256(encoded).hexdigest()
            conn.execute(
                "INSERT INTO replies VALUES (?,?,?,?,?,?,?,?)",
                (
                    _identity(
                        manifest.company_id, manifest.window_key, manifest.source_response_sha256
                    ),
                    manifest.company_id,
                    manifest.window_key,
                    manifest.source_response_sha256,
                    sha,
                    encoded,
                    raw,
                    size,
                ),
            )
            conn.execute("UPDATE usage SET records=records+1,bytes=bytes+? WHERE id=1", (size,))
        else:
            manifest, sha = existing
        conn.commit()
        return manifest, sha, replayed
    finally:
        conn.close()  # Roll back failed inserts before opening the next segment.


def _quota_error(error: ValueError | sqlite3.Error) -> bool:
    return str(error) == "QUOTA_REACHED" or (
        isinstance(error, sqlite3.Error)
        and getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL
    )


@contextmanager
def _retention_lock(root: Path) -> Iterator[None]:
    """Serialize the two-file transition; never wait more than one second."""
    _private_path(root, create=False)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_path(root, create=False)
    path = root / "no-data.lock"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("STORE_UNSAFE")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    acquired = False
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size > 1
            or (os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o600)
        ):
            raise ValueError("STORE_UNSAFE")
        if not info.st_size:
            os.write(fd, b"0")
        deadline = time.monotonic() + 1
        while not acquired:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError("STORE_BUSY") from None
                time.sleep(0.02)
        yield
    finally:
        try:
            if acquired:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def retain_no_data_reply(
    raw: bytes,
    reply: EisFeedResponse,
    *,
    company_id: str,
    actor_id: str,
    window_key: str,
    request_id: str,
    observed_at: datetime,
    token: str,
    root: Path | None,
) -> NoDataRetention:
    base = dict(
        company_id=company_id,
        window_key=window_key,
        observed_at=observed_at,
        source_response_sha256=reply.source_sha256,
    )
    # Reject config reflection before any persisted metadata or filesystem write.
    if not token or any(token in v for v in (company_id, actor_id, window_key)):
        raise ValueError("RETENTION_CONFIG_INVALID")
    NoDataRetention(status="DISABLED", **base)
    if root is None:
        return NoDataRetention(status="DISABLED", **base)
    try:
        if not 1 <= len(raw) <= MAX_REPLY_BYTES:
            raise ValueError("RESPONSE_UNSAFE")
        # The feed parser rejects DTD/entity declarations before ElementTree sees them.
        if (
            parse_get_docs_ip_response(raw) != reply
            or (reply.service, reply.kind, reply.source_mode, reply.state)
            != ("IP", "BY_REGION", "PROD", "NO_DATA")
            or reply.request_id != request_id
        ):
            raise ValueError("BINDING_REJECTED")
        decoded = raw.decode("utf-8")
        if token in decoded or token in html.unescape(decoded):
            raise ValueError("RESPONSE_UNSAFE")
        tree = ET.fromstring(raw)
        values = "".join(tree.itertext()) + " ".join(
            v for e in tree.iter() for v in e.attrib.values()
        )
        if token in values or any(
            e.tag.rsplit("}", 1)[-1] == "Header" and len(e) for e in tree.iter()
        ):
            raise ValueError("RESPONSE_UNSAFE")
        manifest = NoDataManifest(
            company_id=company_id,
            actor_id=actor_id,
            window_key=window_key,
            captured_at=observed_at,
            request_id=UUID(request_id),
            response_id=UUID(reply.response_id),
            source_response_sha256=reply.source_sha256,
            raw_bytes=len(raw),
            source_created_at=reply.created_at,
            source_time_raw=reply.source_time_raw,
            source_time_status=reply.source_time_status,
        )
        with _retention_lock(root):
            stores = STORE_FILES
            if _private_path(root, create=False, store_file=OVERFLOW_FILE).exists():
                if not _private_path(root, create=False).exists():
                    raise ValueError("STORE_UNSAFE")
                archived = _verify_no_data_reply_file(
                    root, company_id, window_key, reply.source_sha256, FILE
                )
                if archived.status == "PASS":
                    return NoDataRetention(
                        status="RETAINED",
                        **base,
                        manifest=archived.manifest,
                        manifest_sha256=archived.manifest_sha256,
                        record_key=_identity(company_id, window_key, reply.source_sha256),
                        relative_store_path=FILE,
                        replayed=True,
                    )
                if archived.status == "FAIL":
                    raise ValueError("STORE_UNSAFE")
                if archived.reason != "ARTIFACT_MISSING":
                    raise OSError("ARCHIVE_UNAVAILABLE")
                stores = (OVERFLOW_FILE,)
            for store_file in stores:
                try:
                    manifest, sha, replayed = _persist_reply(root, store_file, manifest, raw)
                    break
                except (ValueError, sqlite3.Error) as error:
                    if not _quota_error(error):
                        raise
            else:
                raise ValueError("QUOTA_REACHED")
            return NoDataRetention(
                status="RETAINED",
                **base,
                manifest=manifest,
                manifest_sha256=sha,
                record_key=_identity(company_id, window_key, reply.source_sha256),
                relative_store_path=store_file,
                replayed=replayed,
            )
    except sqlite3.Error as error:
        code = getattr(error, "sqlite_errorcode", None)
        reason: Failure = (
            "STORE_BUSY"
            if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
            else ("QUOTA_REACHED" if code == sqlite3.SQLITE_FULL else "IO_FAILED")
        )
    except (ValueError, UnicodeError, ET.ParseError) as error:
        safe = str(error)
        reason = (
            cast(Failure, safe)
            if safe
            in (
                "BINDING_REJECTED",
                "RESPONSE_UNSAFE",
                "QUOTA_REACHED",
                "STORE_UNSAFE",
                "STORE_BUSY",
            )
            else "BINDING_REJECTED"
        )
    except OSError:
        reason = "IO_FAILED"
    return NoDataRetention(status="FAILED", reason=reason, **base)


def _verify_no_data_reply_file(
    root: Path, company_id: str, window_key: str, sha: str, store_file: StoreFile
) -> NoDataVerification:
    base = dict(company_id=company_id, window_key=window_key, source_response_sha256=sha)
    conn = None
    try:
        path = _private_path(root, create=False, store_file=store_file)
        if not path.exists():
            return NoDataVerification(status="UNKNOWN", reason="ARTIFACT_MISSING", **base)
        if store_file == OVERFLOW_FILE and not _private_path(root, create=False).exists():
            return NoDataVerification(status="UNKNOWN", reason="STORE_UNAVAILABLE", **base)
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA cache_size=-1024")
        if (
            conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
            or conn.execute("PRAGMA user_version").fetchone()[0] != 1
            or conn.execute("PRAGMA page_size").fetchone()[0] != 4096
        ):
            raise ValueError("STORE_UNSAFE")
        row = _row(conn, company_id, window_key, sha)
        if row is None:
            return NoDataVerification(status="UNKNOWN", reason="ARTIFACT_MISSING", **base)
        manifest, manifest_sha = row
        return NoDataVerification(
            status="PASS",
            reason="MATCHED_RAW_REPLY",
            **base,
            manifest=manifest,
            manifest_sha256=manifest_sha,
        )
    except ValueError:
        return NoDataVerification(status="FAIL", reason="ARTIFACT_INVALID", **base)
    except (sqlite3.Error, OSError):
        return NoDataVerification(status="UNKNOWN", reason="STORE_UNAVAILABLE", **base)
    finally:
        if conn is not None:
            conn.close()


def verify_no_data_reply(
    root: Path, company_id: str, window_key: str, sha: str
) -> NoDataVerification:
    """Resolve legacy and overflow audit references without hiding corruption."""
    for store_file in STORE_FILES:
        result = _verify_no_data_reply_file(root, company_id, window_key, sha, store_file)
        if result.reason != "ARTIFACT_MISSING":
            return result
    return result
