"""Read-only PostgreSQL collector for the frozen EIS search package."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import (
    Boolean,
    Connection,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    and_,
    cast,
    event,
    exists,
    func,
    inspect,
    literal,
    or_,
    select,
    text,
    true,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError

from procurement.sources.eis_search_capture import (
    EXPECTED_RELATIONS,
    V3_COLLECTOR_FREE_BYTES,
    V3_FRAGMENT_RELATION_SET,
    V3_MEMBERSHIP_PAGES,
    AuditFragmentDescriptor,
    CaptureFormatError,
    CaptureManifest,
    CaptureManifestV2,
    CaptureManifestV3,
    CapturePlanAny,
    CapturePlanV2,
    CapturePlanV3,
    CollectorStateV3,
    CurrentMembership,
    FragmentedAuditRowDescriptor,
    FragmentedRowDescriptorV3,
    FutureVersionDiagnostic,
    IncompleteCapture,
    IncompleteCaptureV2,
    IncompleteCaptureV3,
    RelationDescriptor,
    RelationDescriptorV2,
    RelationDescriptorV3,
    RelationSpec,
    RowFragmentDescriptorV3,
    RuntimeIdentity,
    ShardDescriptor,
    SqliteRuntimeIdentity,
    SqliteStateObservationV3,
    TransientCleanupV3,
    _commit_and_observe_sqlite_v3,
    _configure_sqlite_connection_v3,
    _SqliteDeadlineV3,
    _validate_sqlite_file_facts,
    _validate_v3_sqlite_observation,
    canonical_bytes,
    encode_row,
    encode_value,
    iter_encoded_row,
    load_capture_plan,
    sha256_bytes,
)
from procurement.storage.models import metadata
from procurement.storage.repository import PostgresStorage

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_VERIFIER_SOURCE = _REPOSITORY_ROOT / "src/procurement/sources/eis_search_capture.py"
_COLLECTOR_SOURCE = Path(__file__).resolve()
_CAPTURE_METADATA = MetaData()
for _relation_name in EXPECTED_RELATIONS:
    metadata.tables[_relation_name].to_metadata(_CAPTURE_METADATA, schema="public")


def _table(name: str) -> Table:
    return _CAPTURE_METADATA.tables["public." + name]


class CaptureCollectionError(RuntimeError):
    """The database cannot produce a complete package under the reviewed plan."""


class _TimeoutResultCleanupError(RuntimeError):
    """Retain the primary failure when timeout-result cleanup also fails."""

    def __init__(self, primary: Exception) -> None:
        super().__init__("TIMEOUT_RESULT_CLOSE_FAILED")
        self.primary = primary


class _PackageBudget:
    def __init__(self, plan: CapturePlanAny, started: float) -> None:
        self.plan = plan
        self.started = started
        self.payload_bytes = 0
        self.shards = 0

    def check_time(self) -> None:
        if time.monotonic() - self.started > self.plan.limits.capture_timeout_seconds:
            raise CaptureCollectionError("CAPTURE_TIMEOUT")

    def remaining_statement_timeout_ms(self) -> int:
        remaining = self.plan.limits.capture_timeout_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            raise CaptureCollectionError("CAPTURE_TIMEOUT")
        return max(1, min(self.plan.limits.statement_timeout_ms, int(remaining * 1000)))

    def reserve_file(self) -> None:
        self.reserve_files(1)

    def reserve_files(self, count: int) -> None:
        self.reserve_payload(count, 0)

    def reserve_payload(self, file_count: int, size: int) -> None:
        if file_count < 0 or self.shards + file_count > self.plan.limits.max_shards:
            raise CaptureCollectionError("SHARD_COUNT_LIMIT")
        if size < 0 or self.payload_bytes + size > self.plan.limits.total_payload_bytes:
            raise CaptureCollectionError("PAYLOAD_SIZE_LIMIT")
        self.shards += file_count
        self.payload_bytes += size

    def reserve_bytes(self, size: int) -> None:
        self.reserve_payload(0, size)

    def add_shard(self, size: int) -> None:
        """Compatibility helper; new writers reserve before opening or writing."""
        self.reserve_file()
        self.reserve_bytes(size)


class _RelationWriter:
    def __init__(
        self,
        root: Path,
        spec: RelationSpec,
        budget: _PackageBudget,
    ) -> None:
        self.root = root
        self.spec = spec
        self.budget = budget
        self.relation_digest = hashlib.sha256()
        self.shards: list[ShardDescriptor] = []
        self.total_rows = 0
        self._stream: Any | None = None
        self._digest = hashlib.sha256()
        self._ordered_digest = hashlib.sha256()
        self._bytes = 0
        self._rows = 0
        self._first_key: tuple[object, ...] | None = None
        self._last_key: tuple[object, ...] | None = None

    def _check_write_capacity(self, amount: int) -> None:
        self.budget.check_time()
        reserve = (
            self.budget.plan.limits.free_disk_min_bytes
            if isinstance(self.budget.plan, CapturePlanV3)
            else 0
        )
        if amount < 0 or shutil.disk_usage(self.root).free < amount + reserve:
            raise CaptureCollectionError("FREE_DISK_LIMIT_DURING_ROW")

    def _reserve_write(self, amount: int) -> None:
        self.budget.reserve_bytes(amount)
        self._check_write_capacity(amount)

    def _open(self, first_write_bytes: int) -> None:
        self.budget.reserve_file()
        self._reserve_write(first_write_bytes)
        path = self.root / f"relations/{self.spec.name}-{len(self.shards) + 1:05d}.jsonl"
        path.parent.mkdir(exist_ok=True)
        self._stream = path.open("xb")

    def write(self, row: Mapping[str, object]) -> None:
        self.write_encoded(
            encode_row(self.spec, row),
            tuple(row[name] for name in self.spec.primary_key),
        )

    def write_encoded(self, line: bytes, key: tuple[object, ...]) -> None:
        if len(line) > self.budget.plan.limits.shard_bytes:
            raise CaptureCollectionError("ROW_EXCEEDS_SHARD_LIMIT")
        if (
            self._stream is not None
            and self._bytes + len(line) > self.budget.plan.limits.shard_bytes
        ):
            self._close_shard()
        if self._stream is None:
            self._open(len(line))
        else:
            self._reserve_write(len(line))
        assert self._stream is not None
        if self._stream.write(line) != len(line):
            raise CaptureCollectionError("PAYLOAD_PARTIAL_WRITE")
        self._digest.update(line)
        framed = len(line).to_bytes(8, "big") + line
        self._ordered_digest.update(framed)
        self.relation_digest.update(framed)
        self._bytes += len(line)
        self._rows += 1
        self.total_rows += 1
        self._first_key = self._first_key or key
        self._last_key = key

    def _close_shard(self) -> None:
        if self._stream is None:
            return
        self._stream.flush()
        self._stream.close()
        if self._first_key is None or self._last_key is None:
            raise CaptureCollectionError("EMPTY_SHARD")
        path = f"relations/{self.spec.name}-{len(self.shards) + 1:05d}.jsonl"
        descriptor = ShardDescriptor(
            path=path,
            sha256=self._digest.hexdigest(),
            bytes=self._bytes,
            rows=self._rows,
            first_primary_key=self._first_key,
            last_primary_key=self._last_key,
            ordered_rows_sha256=self._ordered_digest.hexdigest(),
        )
        self.shards.append(descriptor)
        self._stream = None
        self._digest = hashlib.sha256()
        self._ordered_digest = hashlib.sha256()
        self._bytes = 0
        self._rows = 0
        self._first_key = None
        self._last_key = None

    def finish(self, source_count: int) -> RelationDescriptor:
        self._close_shard()
        if self.total_rows != source_count:
            raise CaptureCollectionError("RELATION_COUNT_CHANGED")
        return RelationDescriptor(
            name=self.spec.name,
            rows=self.total_rows,
            shards=tuple(self.shards),
            ordered_rows_sha256=self.relation_digest.hexdigest(),
            source_count=source_count,
        )

    def abort(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None


class _RelationWriterV2:
    def __init__(
        self,
        root: Path,
        spec: RelationSpec,
        budget: _PackageBudget,
        plan: CapturePlanV2,
    ) -> None:
        self.root = root
        self.spec = spec
        self.budget = budget
        self.plan = plan
        self.inline = _RelationWriter(root, spec, budget)
        self.fragmented_rows: list[FragmentedAuditRowDescriptor] = []
        self.relation_digest = hashlib.sha256()
        self.logical_rows = 0
        self._pending = root / ".audit-row.pending"

    def _check_write_capacity(self, amount: int) -> None:
        self.budget.check_time()
        if amount < 0 or shutil.disk_usage(self.root).free < amount:
            raise CaptureCollectionError("FREE_DISK_LIMIT_DURING_ROW")

    def _spool_audit_row(self, row: Mapping[str, object]) -> tuple[int, str]:
        size = 0
        digest = hashlib.sha256()
        try:
            with self._pending.open("xb") as stream:
                for chunk in iter_encoded_row(self.spec, row):
                    size += len(chunk)
                    if size > self.plan.limits.audit_typed_row_bytes:
                        raise CaptureCollectionError("TYPED_AUDIT_ROW_LIMIT")
                    self._check_write_capacity(len(chunk))
                    stream.write(chunk)
                    digest.update(chunk)
                stream.flush()
        except Exception:
            self._pending.unlink(missing_ok=True)
            raise
        return size, digest.hexdigest()

    def write(self, row: Mapping[str, object]) -> None:
        key = tuple(row[name] for name in self.spec.primary_key)
        if self.spec.name != "audit_events":
            line = encode_row(self.spec, row)
            self.inline.write_encoded(line, key)
            self.relation_digest.update(len(line).to_bytes(8, "big") + line)
            self.logical_rows += 1
            return
        size, whole_sha = self._spool_audit_row(row)
        try:
            self.relation_digest.update(size.to_bytes(8, "big"))
            if size <= self.plan.limits.shard_bytes:
                line = self._pending.read_bytes()
                if len(line) != size:
                    raise CaptureCollectionError("TYPED_AUDIT_ROW_CHANGED")
                self.inline.write_encoded(line, key)
                self.relation_digest.update(line)
            else:
                self.inline._close_shard()
                fragments: list[AuditFragmentDescriptor] = []
                offset = 0
                with self._pending.open("rb") as stream:
                    while offset < size:
                        self.budget.check_time()
                        ordinal = len(fragments)
                        if ordinal >= self.plan.limits.audit_max_fragments:
                            raise CaptureCollectionError("AUDIT_FRAGMENT_COUNT_LIMIT")
                        content = stream.read(self.plan.limits.shard_bytes)
                        if not content:
                            raise CaptureCollectionError("AUDIT_FRAGMENT_EMPTY")
                        self.budget.reserve_file()
                        self.budget.reserve_bytes(len(content))
                        self._check_write_capacity(len(content))
                        path = f"fragments/audit_events-{self.logical_rows:07d}-{ordinal:02d}.bin"
                        destination = self.root / path
                        destination.parent.mkdir(exist_ok=True)
                        with destination.open("xb") as fragment_stream:
                            if fragment_stream.write(content) != len(content):
                                raise CaptureCollectionError("PAYLOAD_PARTIAL_WRITE")
                            fragment_stream.flush()
                        fragments.append(
                            AuditFragmentDescriptor(
                                path=path,
                                ordinal=ordinal,
                                offset=offset,
                                bytes=len(content),
                                sha256=sha256_bytes(content),
                            )
                        )
                        self.relation_digest.update(content)
                        offset += len(content)
                if offset != size or len(fragments) < 2:
                    raise CaptureCollectionError("AUDIT_FRAGMENT_LENGTH_INVALID")
                columns = {column.name: column for column in self.spec.columns}
                typed_key = tuple(
                    encode_value(row[name], columns[name].kind) for name in self.spec.primary_key
                )
                self.fragmented_rows.append(
                    FragmentedAuditRowDescriptor(
                        kind="AUDIT_ROW_FRAGMENTS_V2",
                        relation="audit_events",
                        tenant=str(row["company_id"]),
                        typed_primary_key=typed_key,
                        logical_ordinal=self.logical_rows,
                        whole_bytes=size,
                        whole_sha256=whole_sha,
                        fragment_count=len(fragments),
                        fragments=tuple(fragments),
                    )
                )
            self.logical_rows += 1
        finally:
            self._pending.unlink(missing_ok=True)

    def finish(self, source_count: int) -> RelationDescriptorV2:
        inline_rows = source_count - len(self.fragmented_rows)
        inline_descriptor = self.inline.finish(inline_rows)
        if self.logical_rows != source_count:
            raise CaptureCollectionError("RELATION_COUNT_CHANGED")
        return RelationDescriptorV2(
            name=self.spec.name,
            rows=self.logical_rows,
            shards=inline_descriptor.shards,
            fragmented_rows=tuple(self.fragmented_rows),
            ordered_rows_sha256=self.relation_digest.hexdigest(),
            source_count=source_count,
        )

    def abort(self) -> None:
        self.inline.abort()
        self._pending.unlink(missing_ok=True)


def _create_exclusive_transient(path: Path) -> tuple[Any, tuple[int, int]]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise CaptureCollectionError("TRANSIENT_CREATE_FAILED") from error
    try:
        os.fchmod(descriptor, 0o600)  # type: ignore[attr-defined]
        facts = os.fstat(descriptor)
        _validate_sqlite_file_facts(
            is_regular=stat.S_ISREG(facts.st_mode),
            is_symlink=False,
            mode=facts.st_mode,
            uid=facts.st_uid,
            nlink=facts.st_nlink,
            size=facts.st_size,
        )
        return os.fdopen(descriptor, "w+b"), (facts.st_dev, facts.st_ino)
    except Exception:
        os.close(descriptor)
        raise


def _remove_same_transient(path: Path, identity: tuple[int, int]) -> None:
    try:
        facts = path.lstat()
    except FileNotFoundError as error:
        raise CaptureCollectionError("TRANSIENT_MISSING") from error
    if (
        stat.S_ISLNK(facts.st_mode)
        or not stat.S_ISREG(facts.st_mode)
        or (facts.st_dev, facts.st_ino) != identity
        or facts.st_uid != 1_000
        or stat.S_IMODE(facts.st_mode) != 0o600
        or facts.st_nlink != 1
    ):
        raise CaptureCollectionError("TRANSIENT_IDENTITY_CHANGED")
    path.unlink()


class _RelationWriterV3:
    def __init__(
        self,
        root: Path,
        spec: RelationSpec,
        budget: _PackageBudget,
        plan: CapturePlanV3,
        pending_observer: Callable[[int | None], None] | None = None,
        cleanup_observer: Callable[[bool], None] | None = None,
    ) -> None:
        self.root = root
        self.spec = spec
        self.budget = budget
        self.plan = plan
        self.inline = _RelationWriter(root, spec, budget)
        self.fragmented_rows: list[FragmentedRowDescriptorV3] = []
        self.relation_digest = hashlib.sha256()
        self.logical_rows = 0
        self.pending_peak_bytes: int | None = 0
        self._pending_observer = pending_observer
        self._cleanup_observer = cleanup_observer
        self._pending = root / ".fragment-row.pending"
        self._pending_identity: tuple[int, int] | None = None
        self._pending_stream: Any | None = None
        self._pending_close_failed = False

    def _observe_pending(self, value: int | None) -> None:
        if value is None:
            self.pending_peak_bytes = None
        elif self.pending_peak_bytes is not None:
            self.pending_peak_bytes = max(self.pending_peak_bytes, value)
        if self._pending_observer is not None:
            self._pending_observer(value)

    def _cleanup_pending(self) -> str | None:
        if self._pending_stream is not None:
            if self._pending_close_failed:
                return "PENDING_CLOSE_FAILED"
            try:
                self._pending_stream.close()
            except Exception:
                self._pending_close_failed = True
                if self._cleanup_observer is not None:
                    self._cleanup_observer(False)
                return "PENDING_CLOSE_FAILED"
            self._pending_stream = None
        if self._pending_identity is not None:
            try:
                _remove_same_transient(self._pending, self._pending_identity)
            except (OSError, CaptureCollectionError):
                if self._cleanup_observer is not None:
                    self._cleanup_observer(False)
                return "PENDING_REMOVE_FAILED"
            self._pending_identity = None
        if self._cleanup_observer is not None:
            self._cleanup_observer(True)
        return None

    def _check_write_capacity(self, amount: int) -> None:
        self.budget.check_time()
        if (
            amount < 0
            or shutil.disk_usage(self.root).free < amount + self.plan.limits.free_disk_min_bytes
        ):
            raise CaptureCollectionError("FREE_DISK_LIMIT_DURING_ROW")

    def _spool_row(self, row: Mapping[str, object]) -> tuple[int, str, Any]:
        size = 0
        digest = hashlib.sha256()
        stream: Any | None = None
        try:
            stream, self._pending_identity = _create_exclusive_transient(self._pending)
            self._pending_stream = stream
            self._pending_close_failed = False
            for chunk in iter_encoded_row(self.spec, row):
                proposed_size = size + len(chunk)
                if proposed_size > self.plan.fragmentation.encoded_row_bytes:
                    raise CaptureCollectionError("TYPED_ROW_LIMIT")
                self._check_write_capacity(len(chunk))
                try:
                    written = stream.write(chunk)
                except Exception:
                    self._observe_pending(None)
                    raise
                if written != len(chunk):
                    if isinstance(written, int) and 0 <= written <= len(chunk):
                        self._observe_pending(size + written)
                    self._observe_pending(None)
                    raise CaptureCollectionError("PENDING_PARTIAL_WRITE")
                size = proposed_size
                self._observe_pending(size)
                digest.update(chunk)
            stream.flush()
        except Exception:
            self._cleanup_pending()
            raise
        assert stream is not None
        stream.seek(0)
        return size, digest.hexdigest(), stream

    def write(self, row: Mapping[str, object]) -> None:
        key = tuple(row[name] for name in self.spec.primary_key)
        if self.spec.name not in V3_FRAGMENT_RELATION_SET:
            line = encode_row(self.spec, row)
            self.inline.write_encoded(line, key)
            self.relation_digest.update(len(line).to_bytes(8, "big") + line)
            self.logical_rows += 1
            return
        size, whole_sha, pending_stream = self._spool_row(row)
        try:
            self.relation_digest.update(size.to_bytes(8, "big"))
            if size <= self.plan.fragmentation.fragment_bytes:
                line = pending_stream.read(self.plan.fragmentation.encoded_row_bytes + 1)
                if len(line) != size:
                    raise CaptureCollectionError("TYPED_ROW_CHANGED")
                self.inline.write_encoded(line, key)
                self.relation_digest.update(line)
            else:
                self.inline._close_shard()
                fragments: list[RowFragmentDescriptorV3] = []
                offset = 0
                fragment_count = (
                    size + self.plan.fragmentation.fragment_bytes - 1
                ) // self.plan.fragmentation.fragment_bytes
                if not 2 <= fragment_count <= self.plan.fragmentation.max_fragments:
                    raise CaptureCollectionError("FRAGMENT_COUNT_LIMIT")
                self.budget.reserve_payload(fragment_count, size)
                self._check_write_capacity(size)
                while offset < size:
                    self.budget.check_time()
                    ordinal = len(fragments)
                    content = pending_stream.read(self.plan.fragmentation.fragment_bytes)
                    if not content:
                        raise CaptureCollectionError("FRAGMENT_EMPTY")
                    path = f"fragments/{self.spec.name}-{self.logical_rows:07d}-{ordinal:02d}.bin"
                    destination = self.root / path
                    destination.parent.mkdir(exist_ok=True)
                    with destination.open("xb") as fragment_stream:
                        if fragment_stream.write(content) != len(content):
                            raise CaptureCollectionError("PAYLOAD_PARTIAL_WRITE")
                        fragment_stream.flush()
                    fragments.append(
                        RowFragmentDescriptorV3(
                            path=path,
                            ordinal=ordinal,
                            offset=offset,
                            bytes=len(content),
                            sha256=sha256_bytes(content),
                        )
                    )
                    self.relation_digest.update(content)
                    offset += len(content)
                if offset != size or len(fragments) < 2:
                    raise CaptureCollectionError("FRAGMENT_LENGTH_INVALID")
                columns = {column.name: column for column in self.spec.columns}
                typed_key = tuple(
                    encode_value(row[name], columns[name].kind) for name in self.spec.primary_key
                )
                self.fragmented_rows.append(
                    FragmentedRowDescriptorV3(
                        kind="ROW_FRAGMENTS_V3",
                        relation=self.spec.name,
                        tenant=str(row["company_id"]),
                        typed_primary_key=typed_key,
                        logical_ordinal=self.logical_rows,
                        whole_bytes=size,
                        whole_sha256=whole_sha,
                        fragment_count=len(fragments),
                        fragments=tuple(fragments),
                    )
                )
            self.logical_rows += 1
        except Exception:
            self._cleanup_pending()
            raise
        cleanup_error = self._cleanup_pending()
        if cleanup_error is not None:
            raise CaptureCollectionError(cleanup_error)

    def finish(self, source_count: int) -> RelationDescriptorV3:
        inline_rows = source_count - len(self.fragmented_rows)
        inline_descriptor = self.inline.finish(inline_rows)
        if self.logical_rows != source_count:
            raise CaptureCollectionError("RELATION_COUNT_CHANGED")
        return RelationDescriptorV3(
            name=self.spec.name,
            rows=self.logical_rows,
            shards=inline_descriptor.shards,
            fragmented_rows=tuple(self.fragmented_rows),
            ordered_rows_sha256=self.relation_digest.hexdigest(),
            source_count=source_count,
        )

    def abort(self) -> None:
        self.inline.abort()
        cleanup_error = self._cleanup_pending()
        if cleanup_error is not None:
            raise CaptureCollectionError(cleanup_error)


class _MembershipDatabaseV3:
    def __init__(
        self,
        root: Path,
        expected_runtime: SqliteRuntimeIdentity,
        started: float,
        timeout_seconds: int = 900,
    ) -> None:
        self.path = root / ".current-membership.sqlite3"
        self.expected_runtime = expected_runtime
        self.deadline = _SqliteDeadlineV3(started, timeout_seconds=timeout_seconds)
        self.identity: tuple[int, int] | None = None
        self.database: sqlite3.Connection | None = None
        self.runtime: SqliteRuntimeIdentity | None = None
        self.configuration: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
        self.page_size: int | None = None
        self.max_pages: int | None = None
        self.journal_mode: Literal["off"] | None = None
        self.temp_store: Literal[2] | None = None
        self.page_count: int | None = None
        self.file_bytes: int | None = 0
        self.identity_unchanged: bool | None = None
        self.closed: bool | None = None
        self.failure_code: str | None = None

    def _opening_identity_matches(self) -> bool:
        if self.identity is None:
            return False
        try:
            facts = self.path.lstat()
        except OSError:
            return False
        return (
            stat.S_ISREG(facts.st_mode)
            and not stat.S_ISLNK(facts.st_mode)
            and (facts.st_dev, facts.st_ino) == self.identity
            and facts.st_uid == 1_000
            and stat.S_IMODE(facts.st_mode) == 0o600
            and facts.st_nlink == 1
            and facts.st_size == 0
        )

    def open(self) -> sqlite3.Connection:
        stream, self.identity = _create_exclusive_transient(self.path)
        stream.close()
        self.closed = True
        if not self._opening_identity_matches():
            self.identity_unchanged = False
            raise CaptureCollectionError("MEMBERSHIP_OPEN_IDENTITY_INVALID")
        try:
            database = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=0
            )
            self.database = database
            self.closed = False
            if not self._opening_identity_matches():
                self.identity_unchanged = False
                raise CaptureCollectionError("MEMBERSHIP_OPEN_IDENTITY_INVALID")
            (
                self.runtime,
                self.page_size,
                self.max_pages,
                self.journal_mode,
                self.temp_store,
                self.page_count,
            ) = _configure_sqlite_connection_v3(
                database,
                expected_runtime=self.expected_runtime,
                max_page_count=V3_MEMBERSHIP_PAGES,
                deadline=self.deadline,
            )
            database.execute(
                "CREATE TABLE current_versions (law TEXT, purchase_number TEXT, "
                "version_number INTEGER, source_sha TEXT, "
                "PRIMARY KEY (law, purchase_number))"
            )
            database.execute(
                "CREATE TABLE future_versions (law TEXT, purchase_number TEXT, "
                "version_number INTEGER, source_sha TEXT, ingested_at TEXT, "
                "PRIMARY KEY (law, purchase_number, version_number))"
            )
            self.deadline.check()
            self.configuration = "PASS"
            return database
        except sqlite3.Error as error:
            self.configuration = "FAIL"
            self.failure_code = (
                "SQLITE_DEADLINE" if self.deadline.progress() else "SQLITE_OPERATION_FAILED"
            )
            raise CaptureCollectionError(self.failure_code) from error

    def observe_success(self) -> None:
        if self.database is None:
            raise CaptureCollectionError("SQLITE_CONNECTION_MISSING")
        self.page_count = None
        try:
            self.page_count = _commit_and_observe_sqlite_v3(self.database, self.deadline)
        except (CaptureFormatError, sqlite3.Error) as error:
            self.configuration = "FAIL"
            self.failure_code = (
                "SQLITE_DEADLINE"
                if isinstance(error, CaptureFormatError) and str(error) == "SQLITE_DEADLINE"
                else "SQLITE_OPERATION_FAILED"
            )
            raise CaptureCollectionError(self.failure_code) from error

    def mark_failure(self, error: Exception) -> None:
        if isinstance(error, sqlite3.Error):
            self.configuration = "FAIL"
            self.failure_code = (
                "SQLITE_DEADLINE" if self.deadline.progress() else "SQLITE_OPERATION_FAILED"
            )

    def close_and_remove(self) -> tuple[SqliteStateObservationV3, bool, str | None]:
        failure: str | None = None
        if self.database is not None:
            try:
                self.database.set_progress_handler(None, 0)
                self.database.close()
                self.closed = True
            except sqlite3.Error:
                self.closed = False
                failure = "MEMBERSHIP_CLOSE_FAILED"
            if self.closed:
                self.database = None
        if self.identity is not None:
            try:
                facts = self.path.lstat()
                self.identity_unchanged = (
                    stat.S_ISREG(facts.st_mode)
                    and not stat.S_ISLNK(facts.st_mode)
                    and (facts.st_dev, facts.st_ino) == self.identity
                    and facts.st_uid == 1_000
                    and stat.S_IMODE(facts.st_mode) == 0o600
                    and facts.st_nlink == 1
                )
                self.file_bytes = facts.st_size
                if not self.identity_unchanged:
                    raise CaptureCollectionError("MEMBERSHIP_IDENTITY_CHANGED")
                if self.closed is not True:
                    removed = False
                    failure = failure or "MEMBERSHIP_CLOSE_UNCONFIRMED"
                else:
                    _remove_same_transient(self.path, self.identity)
                    removed = not self.path.exists()
            except (OSError, CaptureCollectionError):
                removed = False
                failure = failure or "MEMBERSHIP_REMOVE_FAILED"
        else:
            removed = not self.path.exists()
        observation = SqliteStateObservationV3(
            purpose="COLLECTOR_MEMBERSHIP",
            runtime=self.runtime,
            configuration=self.configuration,
            page_size=self.page_size,
            max_page_count=self.max_pages,
            journal_mode=self.journal_mode,
            temp_store=self.temp_store,
            page_count_last_observed=self.page_count,
            main_file_bytes_last_observed=self.file_bytes,
            file_identity_unchanged=self.identity_unchanged,
            connection_closed=self.closed,
            failure_code=self.failure_code,
        )
        return observation, removed, failure


def _write_metadata(path: Path, value: object, cap: int) -> bytes:
    content = canonical_bytes(value) + b"\n"
    if len(content) > cap:
        raise CaptureCollectionError("METADATA_SIZE_LIMIT")
    path.write_bytes(content)
    return content


def _verify_source_pins(plan: CapturePlanAny) -> None:
    for pin in plan.source_pins:
        path = (_REPOSITORY_ROOT / pin.path).resolve(strict=True)
        if not path.is_relative_to(_REPOSITORY_ROOT) or not path.is_file():
            raise CaptureCollectionError("SOURCE_PIN_PATH_INVALID")
        if hashlib.sha256(path.read_bytes()).hexdigest() != pin.sha256:
            raise CaptureCollectionError("SOURCE_PIN_MISMATCH:" + pin.path)


def _runtime_identity(
    connection: Connection,
    plan: CapturePlanAny,
    external: dict[str, str],
    *,
    clock_mode: str,
    budget: _PackageBudget | None = None,
) -> RuntimeIdentity:
    row = _bounded_database_call(
        connection,
        budget,
        lambda: (
            connection.execute(
                text(
                    "SELECT current_user AS current_user, session_user AS session_user, "
                    "current_setting('server_version_num') AS server_version_num, "
                    "current_setting('transaction_isolation') AS transaction_isolation, "
                    "current_setting('transaction_read_only') AS transaction_read_only, "
                    "current_setting('row_security') AS row_security, "
                    "current_setting('app.company_id') AS app_company_id, "
                    "txid_current_snapshot()::text AS txid_current_snapshot, "
                    "transaction_timestamp() AS transaction_timestamp, "
                    "current_setting('TimeZone') AS timezone, "
                    "current_setting('search_path') AS search_path, "
                    "r.rolsuper AS rolsuper, r.rolbypassrls AS rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname=current_user"
                )
            )
            .mappings()
            .one()
        ),
    )
    revision = _bounded_database_call(
        connection,
        budget,
        lambda: connection.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalar_one(),
    )
    collation = _bounded_database_call(
        connection,
        budget,
        lambda: connection.execute(
            text("SELECT datcollate, datctype FROM pg_database WHERE datname=current_database()")
        ).one(),
    )
    policy_rows = _bounded_database_call(
        connection,
        budget,
        lambda: connection.execute(
            text(
                "SELECT tablename, policyname, permissive, roles::text, cmd, qual, with_check "
                "FROM pg_policies WHERE schemaname='public' AND tablename = ANY(:tables) "
                "ORDER BY tablename, policyname"
            ),
            {"tables": sorted(item.name for item in plan.relations)},
        ).all(),
    )
    grant_rows = _bounded_database_call(
        connection,
        budget,
        lambda: connection.execute(
            text(
                "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                "WHERE table_schema='public' AND grantee=current_user "
                "AND table_name = ANY(:tables) ORDER BY table_name, privilege_type"
            ),
            {"tables": sorted(item.name for item in plan.relations)},
        ).all(),
    )
    if str(row["server_version_num"])[:2] != str(plan.postgres_major):
        raise CaptureCollectionError("POSTGRES_MAJOR_MISMATCH")
    if revision != plan.schema_revision:
        raise CaptureCollectionError("SCHEMA_REVISION_MISMATCH")
    if (
        row["transaction_isolation"] != "repeatable read"
        or row["transaction_read_only"] != "on"
        or row["row_security"] != "on"
    ):
        raise CaptureCollectionError("TRANSACTION_MODE_INVALID")
    if row["app_company_id"] != plan.tenant:
        raise CaptureCollectionError("TENANT_CONTEXT_MISMATCH")
    if row["rolsuper"] or row["rolbypassrls"]:
        raise CaptureCollectionError("PRIVILEGED_DATABASE_ROLE")
    required_external = {
        "deployed_source_sha256",
        "image_id",
        "lxml_version",
        "psycopg_version",
        "pydantic_version",
        "python_version",
        "repository_commit",
        "snowballstemmer_version",
        "sqlalchemy_version",
        "uv_lock_sha256",
    }
    if set(external) != required_external or any(not value for value in external.values()):
        raise CaptureCollectionError("EXTERNAL_RUNTIME_IDENTITY_INVALID")
    return RuntimeIdentity(
        current_user=row["current_user"],
        session_user=row["session_user"],
        server_version_num=str(row["server_version_num"]),
        transaction_isolation=row["transaction_isolation"],
        transaction_read_only=row["transaction_read_only"],
        row_security=row["row_security"],
        app_company_id=row["app_company_id"],
        schema_revision=revision,
        snapshot_id=row["txid_current_snapshot"],
        transaction_timestamp=row["transaction_timestamp"],
        clock_mode=clock_mode,
        timezone=row["timezone"],
        search_path=row["search_path"],
        database_collation=collation.datcollate,
        database_ctype=collation.datctype,
        rls_policy_sha256=sha256_bytes(canonical_bytes([tuple(item) for item in policy_rows])),
        role_grants_sha256=sha256_bytes(canonical_bytes([tuple(item) for item in grant_rows])),
        role_superuser=False,
        role_bypassrls=False,
        external=external,
    )


def _validate_schema(
    connection: Connection,
    plan: CapturePlanAny,
    budget: _PackageBudget | None = None,
) -> None:
    with _catalog_deadline_guard(connection, budget):
        _validate_schema_inner(connection, plan, budget)


def _validate_schema_inner(
    connection: Connection, plan: CapturePlanAny, budget: _PackageBudget | None
) -> None:
    inspector = inspect(connection)
    rls_rows = _bounded_database_call(
        connection,
        budget,
        lambda: connection.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, c.relkind, "
                "pg_has_role(current_user, c.relowner, 'MEMBER') AS owner_membership "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = ANY(:tables)"
            ),
            {"tables": sorted(item.name for item in plan.relations)},
        ).all(),
    )
    effective_rls = {
        row.relname
        for row in rls_rows
        if row.relkind == "r"
        and row.relrowsecurity
        and (row.relforcerowsecurity or not row.owner_membership)
    }
    if effective_rls != {item.name for item in plan.relations}:
        raise CaptureCollectionError("SCHEMA_RLS_DRIFT")
    for spec in plan.relations:
        expected_columns = {column.name: column for column in spec.columns}
        source_columns = {
            item["name"]: item
            for item in _bounded_database_call(
                connection,
                budget,
                partial(inspector.get_columns, spec.name, schema="public"),
            )
        }
        if set(source_columns) != set(expected_columns) | set(spec.omitted_source_columns):
            raise CaptureCollectionError("SCHEMA_COLUMN_DRIFT:" + spec.name)
        for name, column in expected_columns.items():
            if bool(source_columns[name]["nullable"]) != column.nullable:
                raise CaptureCollectionError("SCHEMA_NULLABILITY_DRIFT:" + spec.name)
            if _column_kind(source_columns[name]["type"]) != column.kind:
                raise CaptureCollectionError("SCHEMA_TYPE_DRIFT:" + spec.name)
            if _sql_type(source_columns[name]["type"]) != column.sql_type:
                raise CaptureCollectionError("SCHEMA_TYPE_DETAIL_DRIFT:" + spec.name)
        primary_result = _bounded_database_call(
            connection,
            budget,
            partial(inspector.get_pk_constraint, spec.name, schema="public"),
        )
        primary = primary_result.get("constrained_columns") or []
        if tuple(primary) != spec.primary_key:
            raise CaptureCollectionError("SCHEMA_PRIMARY_KEY_DRIFT:" + spec.name)
        expected_indexes = {
            (
                index.name,
                index.columns,
                index.unique,
                index.method,
                index.predicate,
            )
            for index in spec.indexes
        }
        actual_indexes: set[tuple[str, tuple[str, ...], bool, str, str | None]] = set()
        indexes = _bounded_database_call(
            connection,
            budget,
            partial(inspector.get_indexes, spec.name, schema="public"),
        )
        for index in indexes:
            raw_index_columns = index.get("column_names") or []
            raw_index_name = index.get("name")
            if isinstance(raw_index_name, str) and all(
                isinstance(value, str) for value in raw_index_columns
            ):
                actual_indexes.add(
                    (
                        raw_index_name,
                        tuple(value for value in raw_index_columns if value),
                        bool(index["unique"]),
                        _index_method((index.get("dialect_options") or {}).get("postgresql_using")),
                        _index_predicate(
                            (index.get("dialect_options") or {}).get("postgresql_where")
                        ),
                    )
                )
        uniques = _bounded_database_call(
            connection,
            budget,
            partial(inspector.get_unique_constraints, spec.name, schema="public"),
        )
        for unique in uniques:
            raw_unique_name = unique.get("name")
            raw_unique_columns = unique.get("column_names") or []
            if isinstance(raw_unique_name, str) and all(
                isinstance(value, str) for value in raw_unique_columns
            ):
                actual_indexes.add(
                    (
                        raw_unique_name,
                        tuple(value for value in raw_unique_columns if value),
                        True,
                        "btree",
                        None,
                    )
                )
        if expected_indexes != actual_indexes:
            raise CaptureCollectionError("SCHEMA_INDEX_DRIFT:" + spec.name)
        expected_fks = {
            (foreign.columns, foreign.target_relation, foreign.target_columns)
            for foreign in spec.foreign_keys
        }
        foreign_keys = _bounded_database_call(
            connection,
            budget,
            partial(inspector.get_foreign_keys, spec.name, schema="public"),
        )
        actual_fks = {
            (
                tuple(foreign["constrained_columns"]),
                foreign["referred_table"],
                tuple(foreign["referred_columns"]),
            )
            for foreign in foreign_keys
            if foreign.get("referred_schema") in (None, "public")
        }
        if expected_fks != actual_fks:
            raise CaptureCollectionError("SCHEMA_FOREIGN_KEY_DRIFT:" + spec.name)


def _column_kind(value: object) -> str:
    if isinstance(value, ARRAY):
        return "ARRAY"
    if isinstance(value, JSONB):
        return "JSON"
    if isinstance(value, Boolean):
        return "BOOLEAN"
    if isinstance(value, Integer):
        return "INTEGER"
    if isinstance(value, Numeric):
        return "DECIMAL"
    if isinstance(value, DateTime):
        return "DATETIME"
    if isinstance(value, Date):
        return "DATE"
    if isinstance(value, UUID):
        return "UUID"
    if isinstance(value, (Text, String)):
        return "TEXT"
    raise CaptureCollectionError("SCHEMA_TYPE_UNSUPPORTED")


def _sql_type(value: object) -> str:
    if not hasattr(value, "compile"):
        raise CaptureCollectionError("SCHEMA_TYPE_UNSUPPORTED")
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    return " ".join(str(value.compile(dialect=dialect)).upper().split())


def _index_method(value: object) -> str:
    return "btree" if value in (None, False, "") else str(value).lower()


def _index_predicate(value: object) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()).lower()


def _base_select(table: Table, spec: RelationSpec, tenant: str) -> Any:
    projections = []
    for column in spec.columns:
        expression: Any = table.c[column.name]
        if column.kind == "JSON":
            expression = cast(expression, Text).label(column.name)
        projections.append(expression)
    return select(*projections).where(table.c.company_id == tenant)


def _selection(spec: RelationSpec, tenant: str) -> Any:
    table = _table(spec.name)
    statement = _base_select(table, spec, tenant)
    if spec.selection == "FULL_TENANT":
        return statement
    if spec.name == "audit_events":
        batches = _table("eis_notice_projection_batches")
        receipts = _table("eis_notice_variant_receipts")
        linked = (
            select(batches.c.audit_event_id.label("event_id"))
            .where(batches.c.company_id == tenant)
            .union_all(
                select(receipts.c.retention_audit_event_id).where(receipts.c.company_id == tenant),
                select(receipts.c.diagnosis_audit_event_id).where(receipts.c.company_id == tenant),
                select(receipts.c.ledger_audit_event_id).where(receipts.c.company_id == tenant),
            )
            .subquery()
        )
        return statement.where(table.c.event_id.in_(select(linked.c.event_id)))
    if spec.name == "eis_feed_archives":
        columns = ("company_id", "window_key", "response_sha256", "archive_sha256")
        notices = _table("eis_notice_versions")
        events = _table("eis_procedure_events")
        linked = (
            select(*(notices.c[name] for name in columns))
            .where(notices.c.company_id == tenant)
            .union(
                select(*(events.c[name] for name in columns)).where(events.c.company_id == tenant)
            )
            .subquery("linked_feed_archive_keys")
        )
        return statement.join(
            linked,
            and_(*(linked.c[name] == table.c[name] for name in columns)),
        )
    predicates = _parent_predicates(spec.name, table, tenant)
    return statement.where(or_(*predicates))


def _matches(left: Table, right: Table, columns: tuple[str, ...], tenant: str) -> Any:
    return exists(
        select(1)
        .select_from(right)
        .where(
            and_(right.c.company_id == tenant, *(right.c[name] == left.c[name] for name in columns))
        )
    )


def _parent_predicates(name: str, table: Table, tenant: str) -> tuple[Any, ...]:
    if name in {
        "eis_223_archive_sources",
        "eis_223_event_archive_sources",
        "eis_223_lot_event_archive_sources",
    }:
        child = {
            "eis_223_archive_sources": "eis_223_notice_versions",
            "eis_223_event_archive_sources": "eis_223_events",
            "eis_223_lot_event_archive_sources": "eis_223_lot_events",
        }[name]
        columns = ("company_id", "window_key", "response_sha256", "archive_sha256")
        return (_matches(table, _table(child), columns, tenant),)
    if name in {"eis_223_event_windows", "eis_223_lot_event_windows"}:
        source_name = name.replace("_windows", "_archive_sources")
        runtime_name = name.replace("_windows", "s")
        window_columns = ("company_id", "window_key", "response_sha256")
        source = _table(source_name)
        runtime = _table(runtime_name)
        retained = exists(
            select(1)
            .select_from(source)
            .where(
                and_(
                    source.c.company_id == tenant,
                    *(source.c[column] == table.c[column] for column in window_columns),
                    _matches(
                        source,
                        runtime,
                        ("company_id", "window_key", "response_sha256", "archive_sha256"),
                        tenant,
                    ),
                )
            )
        )
        return (retained,)
    if name == "eis_223_blobs":
        blob_columns = ("company_id", "archive_sha256")
        chains = (
            ("eis_223_archive_sources", "eis_223_notice_versions"),
            ("eis_223_event_archive_sources", "eis_223_events"),
            ("eis_223_lot_event_archive_sources", "eis_223_lot_events"),
        )
        predicates = []
        for source_name, runtime_name in chains:
            source = _table(source_name)
            runtime = _table(runtime_name)
            predicates.append(
                exists(
                    select(1)
                    .select_from(source)
                    .where(
                        and_(
                            source.c.company_id == tenant,
                            *(source.c[column] == table.c[column] for column in blob_columns),
                            _matches(
                                source,
                                runtime,
                                (
                                    "company_id",
                                    "window_key",
                                    "response_sha256",
                                    "archive_sha256",
                                ),
                                tenant,
                            ),
                        )
                    )
                )
            )
        return tuple(predicates)
    raise CaptureCollectionError("SELECTION_NOT_IMPLEMENTED:" + name)


def _normalize_row(spec: RelationSpec, row: RowMapping) -> dict[str, object]:
    result: dict[str, object] = {}
    for column in spec.columns:
        value = row[column.name]
        if column.kind == "JSON" and isinstance(value, str):
            value = json.loads(value, parse_float=Decimal)
        result[column.name] = value
    return result


def _ordered_capture_statement(
    spec: RelationSpec, statement: Any, *, version3: bool = False
) -> Any:
    columns = {column.name: column for column in spec.columns}
    table = _table(spec.name)

    def order(source: Any) -> list[Any]:
        return [
            (source.c[name].collate("C") if columns[name].kind == "TEXT" else source.c[name]).asc()
            for name in spec.primary_key
        ]

    if not version3 or spec.name != "eis_notice_versions":
        return statement.order_by(*order(table))
    # Keep the wide JSON-to-text projection out of the blocking key sort.
    # OFFSET 0 prevents flattening; outer ORDER BY still defines the exact order.
    ordered_keys = (
        statement.with_only_columns(*(table.c[name] for name in spec.primary_key))
        .order_by(*order(table))
        .offset(0)
        .subquery("ordered_keys")
    )
    payload = (
        statement.where(and_(*(table.c[name] == ordered_keys.c[name] for name in spec.primary_key)))
        .correlate(ordered_keys)
        .offset(0)
        .lateral("payload")
    )
    return (
        select(*(payload.c[column.name] for column in spec.columns))
        .select_from(ordered_keys.join(payload, true()))
        .order_by(*order(ordered_keys))
    )


def _v3_database_failure(
    error: Exception, relation: str, operation: str, backend_id: int | None
) -> Exception:
    if isinstance(error, _TimeoutResultCleanupError):
        primary = _v3_database_failure(error.primary, relation, operation, backend_id)
        return CaptureCollectionError(
            _safe_collection_reason(primary) + ";TIMEOUT_RESULT_CLOSE_FAILED"
        )
    if not isinstance(error, DBAPIError):
        return error
    try:
        state = getattr(error.orig, "sqlstate", None)
    except Exception:
        state = None
    sqlstate = (
        state if isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state) else "UNKNOWN"
    )
    name = relation if relation in EXPECTED_RELATIONS else "UNKNOWN_RELATION"
    phase = (
        operation
        if operation
        in {"PREFLIGHT", "CURSOR_DECLARE", "CURSOR_FETCH", "TIMEOUT_SET", "CURSOR_CLOSE"}
        else "UNKNOWN_PHASE"
    )
    backend = (
        str(backend_id)
        if type(backend_id) is int and 0 < backend_id <= 2_147_483_647
        else "UNKNOWN"
    )
    return CaptureCollectionError(f"PG_ERROR:{name}:{phase}:{sqlstate}:BACKEND_{backend}")


def _raw_size(value: object) -> int:
    if value is None:
        return 1
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, (bool, int, Decimal, datetime)):
        return len(str(value).encode("utf-8"))
    if isinstance(value, (list, tuple)):
        return sum(_raw_size(item) for item in value)
    raise CaptureCollectionError("RAW_ROW_TYPE_UNSUPPORTED")


def _source_count_and_max_row_bytes(
    connection: Connection, statement: Any, spec: RelationSpec
) -> tuple[int, int]:
    selected = statement.order_by(None).subquery()
    row_bytes: Any = literal(0)
    for column in spec.columns:
        row_bytes += func.coalesce(func.octet_length(cast(selected.c[column.name], Text)), 1)
    count, maximum = connection.execute(
        select(func.count(), func.coalesce(func.max(row_bytes), 0)).select_from(selected)
    ).one()
    return int(count), int(maximum)


def _bound_statement_timeout(connection: Connection, budget: _PackageBudget) -> None:
    statement = text("SELECT set_config('statement_timeout', :value, true)")
    parameters = {"value": str(budget.remaining_statement_timeout_ms())}
    if not isinstance(budget.plan, CapturePlanV3):
        connection.execute(statement, parameters)
        return
    result = connection.execute(
        statement,
        parameters,
        execution_options={"stream_results": False, "yield_per": None},
    )
    try:
        result.scalar_one()
    except Exception as primary:
        try:
            result.close()
        except Exception:
            raise _TimeoutResultCleanupError(primary) from primary
        raise
    result.close()


def _bounded_database_call(
    connection: Connection,
    budget: _PackageBudget | None,
    operation: Callable[[], Any],
) -> Any:
    if budget is not None:
        _bound_statement_timeout(connection, budget)
        budget.check_time()
    result = operation()
    if budget is not None:
        budget.check_time()
    return result


@contextmanager
def _catalog_deadline_guard(
    connection: Connection, budget: _PackageBudget | None
) -> Iterator[None]:
    if budget is None or not isinstance(connection, Connection):
        yield
        return

    def before_cursor_execute(
        _connection: object,
        cursor: Any,
        _statement: object,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        remaining = budget.remaining_statement_timeout_ms()
        cursor.execute("SELECT set_config('statement_timeout', %s, true)", (str(remaining),))

    event.listen(connection, "before_cursor_execute", before_cursor_execute)
    try:
        yield
    finally:
        event.remove(connection, "before_cursor_execute", before_cursor_execute)


def _record_current(
    database: sqlite3.Connection, relation: str, row: Mapping[str, object], clock: datetime
) -> None:
    law = (
        "44"
        if relation == "eis_notice_versions"
        else "223"
        if relation == "eis_223_notice_versions"
        else None
    )
    ingested_at = row.get("ingested_at")
    if law is None:
        return
    if not isinstance(ingested_at, datetime):
        raise CaptureCollectionError("NOTICE_INGESTED_AT_INVALID")
    if ingested_at > clock:
        database.execute(
            "INSERT INTO future_versions VALUES (?, ?, ?, ?, ?)",
            (
                law,
                row["purchase_number"],
                row["version_number"],
                row["xml_sha256"],
                ingested_at.isoformat(),
            ),
        )
        return
    database.execute(
        "INSERT INTO current_versions VALUES (?, ?, ?, ?) "
        "ON CONFLICT(law, purchase_number) DO UPDATE SET "
        "version_number=excluded.version_number, source_sha=excluded.source_sha "
        "WHERE excluded.version_number > current_versions.version_number",
        (law, row["purchase_number"], row["version_number"], row["xml_sha256"]),
    )


def _current_membership(
    database: sqlite3.Connection,
    budget: _PackageBudget | None = None,
) -> tuple[CurrentMembership, CurrentMembership]:
    result: list[CurrentMembership] = []
    for law in ("44", "223"):
        digest = hashlib.sha256()
        count = 0
        rows = database.execute(
            "SELECT purchase_number, version_number, source_sha FROM current_versions "
            "WHERE law=? ORDER BY purchase_number",
            (law,),
        )
        for number, version, source_sha in rows:
            if budget is not None:
                budget.check_time()
            line = canonical_bytes([law, number, version, source_sha]) + b"\n"
            digest.update(len(line).to_bytes(8, "big") + line)
            count += 1
        result.append(
            CurrentMembership(law=law, rows=count, ordered_identity_sha256=digest.hexdigest())
        )
    return result[0], result[1]


def _future_diagnostics(
    database: sqlite3.Connection,
    budget: _PackageBudget | None = None,
) -> tuple[FutureVersionDiagnostic, FutureVersionDiagnostic]:
    result = []
    for law in ("44", "223"):
        digest = hashlib.sha256()
        count = 0
        rows = database.execute(
            "SELECT purchase_number, version_number, source_sha, ingested_at "
            "FROM future_versions WHERE law=? ORDER BY purchase_number, version_number",
            (law,),
        )
        for number, version, source_sha, ingested_at in rows:
            if budget is not None:
                budget.check_time()
            line = canonical_bytes([law, number, version, source_sha, ingested_at]) + b"\n"
            digest.update(len(line).to_bytes(8, "big") + line)
            count += 1
        result.append(
            FutureVersionDiagnostic(law=law, rows=count, ordered_identity_sha256=digest.hexdigest())
        )
    return result[0], result[1]


def _capture_relations(
    connection: Connection,
    plan: CapturePlanAny,
    root: Path,
    clock: datetime,
    budget: _PackageBudget,
    current_database: sqlite3.Connection,
    pending_observer: Callable[[int | None], None] | None = None,
    pending_cleanup_observer: Callable[[bool], None] | None = None,
) -> tuple[
    tuple[RelationDescriptor | RelationDescriptorV2 | RelationDescriptorV3, ...],
    dict[str, int],
    int | None,
]:
    descriptors: list[RelationDescriptor | RelationDescriptorV2 | RelationDescriptorV3] = []
    counts: dict[str, int] = {}
    pending_peak: int | None = 0 if isinstance(plan, CapturePlanV3) else None

    def observe_pending(value: int | None) -> None:
        nonlocal pending_peak
        if pending_peak is None:
            return
        pending_peak = None if value is None else max(pending_peak, value)
        if pending_observer is not None:
            pending_observer(value)

    statements = {spec.name: _selection(spec, plan.tenant) for spec in plan.relations}
    backend_id: int | None = None
    if isinstance(plan, CapturePlanV3):
        _bound_statement_timeout(connection, budget)
        observed = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
        if type(observed) is not int or not 0 < observed <= 2_147_483_647:
            raise CaptureCollectionError("PG_BACKEND_ID_INVALID")
        backend_id = observed
    source_counts: dict[str, int] = {}
    fetch_rows: dict[str, int] = {}
    for spec in plan.relations:
        budget.check_time()
        phase = "TIMEOUT_SET"
        try:
            _bound_statement_timeout(connection, budget)
            phase = "PREFLIGHT"
            source_count, maximum_row_bytes = _source_count_and_max_row_bytes(
                connection, statements[spec.name], spec
            )
        except Exception as error:
            failure = (
                _v3_database_failure(error, spec.name, phase, backend_id)
                if isinstance(plan, CapturePlanV3)
                else error
            )
            if failure is error:
                raise
            raise failure from error
        if source_count > spec.max_rows:
            raise CaptureCollectionError("RELATION_ROW_LIMIT:" + spec.name)
        raw_limit = (
            plan.fragmentation.audit_raw_row_bytes
            if isinstance(plan, CapturePlanV3) and spec.name == "audit_events"
            else plan.fragmentation.ordinary_raw_row_bytes
            if isinstance(plan, CapturePlanV3)
            else plan.limits.audit_raw_row_bytes
            if isinstance(plan, CapturePlanV2) and spec.name == "audit_events"
            else plan.limits.shard_bytes
        )
        if maximum_row_bytes > raw_limit:
            raise CaptureCollectionError("RAW_ROW_EXCEEDS_SHARD_LIMIT:" + spec.name)
        source_counts[spec.name] = source_count
        fetch_rows[spec.name] = min(
            plan.limits.batch_rows,
            plan.limits.batch_bytes // max(1, maximum_row_bytes),
        )
        if fetch_rows[spec.name] < 1:
            raise CaptureCollectionError("RAW_PREFETCH_LIMIT:" + spec.name)
    for spec in plan.relations:
        budget.check_time()
        try:
            _bound_statement_timeout(connection, budget)
        except Exception as error:
            failure = (
                _v3_database_failure(error, spec.name, "TIMEOUT_SET", backend_id)
                if isinstance(plan, CapturePlanV3)
                else error
            )
            if failure is error:
                raise
            raise failure from error
        statement = statements[spec.name]
        source_count = source_counts[spec.name]
        writer: _RelationWriter | _RelationWriterV2 | _RelationWriterV3
        if isinstance(plan, CapturePlanV3):
            writer = _RelationWriterV3(
                root,
                spec,
                budget,
                plan,
                observe_pending,
                pending_cleanup_observer,
            )
        elif isinstance(plan, CapturePlanV2):
            writer = _RelationWriterV2(root, spec, budget, plan)
        else:
            writer = _RelationWriter(root, spec, budget)
        result: Any = None
        phase = "CURSOR_DECLARE"
        try:
            ordered = _ordered_capture_statement(
                spec, statement, version3=isinstance(plan, CapturePlanV3)
            )
            relation_fetch_rows = fetch_rows[spec.name]
            result = connection.execution_options(
                stream_results=True, yield_per=relation_fetch_rows
            ).execute(ordered)
            partitions = iter(result.mappings().partitions(relation_fetch_rows))
            while True:
                phase = "TIMEOUT_SET"
                _bound_statement_timeout(connection, budget)
                budget.check_time()
                try:
                    phase = "CURSOR_FETCH"
                    partition = next(partitions)
                except StopIteration:
                    break
                budget.check_time()
                partition_bytes = 0
                for raw in partition:
                    if isinstance(plan, CapturePlanV3):
                        budget.check_time()
                        if shutil.disk_usage(root).free < plan.limits.free_disk_min_bytes:
                            raise CaptureCollectionError("FREE_DISK_LIMIT_DURING_ROW")
                    raw_bytes = sum(_raw_size(raw[column.name]) for column in spec.columns)
                    raw_limit = (
                        plan.fragmentation.audit_raw_row_bytes
                        if isinstance(plan, CapturePlanV3) and spec.name == "audit_events"
                        else plan.fragmentation.ordinary_raw_row_bytes
                        if isinstance(plan, CapturePlanV3)
                        else plan.limits.audit_raw_row_bytes
                        if isinstance(plan, CapturePlanV2) and spec.name == "audit_events"
                        else plan.limits.shard_bytes
                    )
                    if raw_bytes > raw_limit:
                        raise CaptureCollectionError("RAW_ROW_EXCEEDS_SHARD_LIMIT")
                    partition_bytes += raw_bytes
                    if partition_bytes > plan.limits.batch_bytes:
                        raise CaptureCollectionError("RAW_BATCH_SIZE_LIMIT")
                    row = _normalize_row(spec, raw)
                    writer.write(row)
                    _record_current(current_database, spec.name, row, clock)
                    if isinstance(plan, CapturePlanV3):
                        budget.check_time()
            if isinstance(plan, CapturePlanV3):
                phase = "CURSOR_CLOSE"
                closing_result, result = result, None
                closing_result.close()
            descriptor = writer.finish(source_count)
        except Exception as error:
            failure = (
                _v3_database_failure(error, spec.name, phase, backend_id)
                if isinstance(plan, CapturePlanV3)
                else error
            )
            if isinstance(plan, CapturePlanV3) and result is not None:
                try:
                    result.close()
                except Exception:
                    failure = CaptureCollectionError(
                        _safe_collection_reason(failure) + ";CURSOR_CLOSE_FAILED"
                    )
            try:
                writer.abort()
            except Exception as cleanup_error:
                raise CaptureCollectionError(
                    _safe_collection_reason(failure) + ";WRITER_ABORT_FAILED"
                ) from cleanup_error
            if failure is error:
                raise
            raise failure from error
        descriptors.append(descriptor)
        counts[spec.name] = descriptor.rows
        if isinstance(writer, _RelationWriterV3):
            observe_pending(writer.pending_peak_bytes)
        budget.check_time()
    return tuple(descriptors), counts, pending_peak


def _partial_relation_counts(root: Path, plan: CapturePlanAny) -> dict[str, int]:
    counts: dict[str, int] = {}
    relations_root = root / "relations"
    if not relations_root.is_dir():
        return counts
    for spec in plan.relations:
        if (
            isinstance(plan, CapturePlanV2)
            and spec.name == "audit_events"
            and any((root / "fragments").glob("audit_events-*.bin"))
        ) or (
            isinstance(plan, CapturePlanV3)
            and spec.name in V3_FRAGMENT_RELATION_SET
            and any((root / "fragments").glob(f"{spec.name}-*.bin"))
        ):
            # A fragment has no authoritative logical-row descriptor until the
            # terminal manifest is published. Omitting the count is UNKNOWN;
            # counting only inline rows would falsely assert completeness.
            continue
        rows = 0
        total_bytes = 0
        for path in sorted(relations_root.glob(f"{spec.name}-*.jsonl")):
            if path.is_symlink() or not path.is_file():
                raise CaptureCollectionError("PARTIAL_FILETYPE_INVALID")
            with path.open("rb") as stream:
                while True:
                    line = stream.readline(plan.limits.shard_bytes + 1)
                    if not line:
                        break
                    if len(line) > plan.limits.shard_bytes or not line.endswith(b"\n"):
                        raise CaptureCollectionError("PARTIAL_ROW_INVALID")
                    rows += 1
                    total_bytes += len(line)
                    if rows > spec.max_rows or total_bytes > plan.limits.total_payload_bytes:
                        raise CaptureCollectionError("PARTIAL_CAPTURE_LIMIT")
        if rows:
            counts[spec.name] = rows
    return counts


def _publish_manifest(
    root: Path,
    manifest: CaptureManifest | CaptureManifestV2 | CaptureManifestV3,
    metadata_cap: int,
    budget: _PackageBudget,
) -> None:
    pending = root / ".manifest.pending"
    try:
        _write_metadata(pending, manifest, metadata_cap)
        budget.check_time()
        pending.replace(root / "manifest.json")
    except Exception:
        if pending.exists():
            pending.unlink()
        raise


def _collect_snapshot(
    storage: PostgresStorage,
    plan: CapturePlanAny,
    output_root: Path,
    budget: _PackageBudget,
    current_database: sqlite3.Connection,
    external_runtime: Mapping[str, str],
    clock: datetime | None,
    synthetic_clock: bool,
    runtime_observer: Callable[[RuntimeIdentity], None],
    pending_observer: Callable[[int | None], None],
    pending_cleanup_observer: Callable[[bool], None],
) -> tuple[
    tuple[RelationDescriptor | RelationDescriptorV2 | RelationDescriptorV3, ...],
    dict[str, int],
    int | None,
    tuple[CurrentMembership, CurrentMembership],
    tuple[FutureVersionDiagnostic, FutureVersionDiagnostic],
    RuntimeIdentity,
    datetime,
]:
    with storage.transaction(plan.tenant, consistent_read=True) as connection:
        budget.check_time()
        connection.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": str(plan.limits.statement_timeout_ms)},
        )
        connection.execute(
            text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": str(plan.limits.lock_timeout_ms)},
        )
        _bound_statement_timeout(connection, budget)
        runtime = _runtime_identity(
            connection,
            plan,
            dict(external_runtime),
            clock_mode="SYNTHETIC_OVERRIDE" if synthetic_clock else "DB_TRANSACTION",
            budget=budget,
        )
        runtime_observer(runtime)
        budget.check_time()
        effective_clock = (
            clock.astimezone(UTC)
            if clock is not None
            else runtime.transaction_timestamp.astimezone(UTC)
        )
        _bound_statement_timeout(connection, budget)
        _validate_schema(connection, plan, budget)
        budget.check_time()
        if isinstance(plan, CapturePlanV3):
            descriptors, counts, pending_peak = _capture_relations(
                connection,
                plan,
                output_root,
                effective_clock,
                budget,
                current_database,
                pending_observer,
                pending_cleanup_observer,
            )
        else:
            descriptors, counts, pending_peak = _capture_relations(
                connection, plan, output_root, effective_clock, budget, current_database
            )
        membership = _current_membership(current_database, budget)
        future = _future_diagnostics(current_database, budget)
        budget.check_time()
    return (
        descriptors,
        counts,
        pending_peak,
        membership,
        future,
        runtime,
        effective_clock,
    )


def _safe_collection_reason(error: Exception) -> str:
    if isinstance(error, _TimeoutResultCleanupError):
        return _safe_collection_reason(error.primary) + ";TIMEOUT_RESULT_CLOSE_FAILED"
    if isinstance(error, CaptureCollectionError):
        value = str(error).removeprefix("CaptureCollectionError:")
        if (
            value
            and len(value) <= 200
            and all(character.isalnum() or character in "_:;-. ," for character in value)
        ):
            return "CaptureCollectionError:" + value
    return type(error).__name__ + ":CAPTURE_FAILED"


def capture_search_projection(
    storage: PostgresStorage,
    plan_path: Path,
    output_root: Path,
    *,
    capture_id: str,
    external_runtime: Mapping[str, str],
    expected_sqlite_runtime: SqliteRuntimeIdentity | None = None,
    clock: datetime | None = None,
    synthetic_clock: bool = False,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> (
    CaptureManifest
    | CaptureManifestV2
    | CaptureManifestV3
    | IncompleteCapture
    | IncompleteCaptureV2
    | IncompleteCaptureV3
):
    """Create one new package; every database read occurs in one read-only snapshot."""
    if (clock is None) == synthetic_clock:
        raise ValueError("synthetic clock requires both an override and explicit opt-in")
    if clock is not None:
        offset = clock.utcoffset()
        if clock.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("clock must be timezone-aware UTC")
    plan, plan_content = load_capture_plan(plan_path)
    if isinstance(plan, CapturePlanV3):
        if expected_sqlite_runtime is None:
            raise CaptureCollectionError("V3_SQLITE_CONTEXT_REQUIRED")
        if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 1_000:
            raise CaptureCollectionError("SQLITE_PLATFORM_UID_UNSUPPORTED")
    elif expected_sqlite_runtime is not None:
        raise CaptureCollectionError("SQLITE_CONTEXT_FORBIDDEN_FOR_LEGACY")
    if output_root.exists():
        raise CaptureCollectionError("OUTPUT_ALREADY_EXISTS")
    _verify_source_pins(plan)
    required_free = (
        plan.limits.total_payload_bytes + (V3_COLLECTOR_FREE_BYTES - 4_294_967_296)
        if isinstance(plan, CapturePlanV3)
        else plan.limits.free_disk_min_bytes
    )
    if disk_usage(output_root.parent).free < required_free:
        raise CaptureCollectionError("FREE_DISK_LIMIT")
    output_parent = output_root.parent.stat()
    output_root.mkdir(parents=False)
    output_facts = output_root.stat()
    if isinstance(plan, CapturePlanV3) and (
        output_parent.st_dev != output_facts.st_dev or output_facts.st_uid != 1_000
    ):
        raise CaptureCollectionError("V3_OUTPUT_FILESYSTEM_IDENTITY_INVALID")
    (output_root / "plan.json").write_bytes(plan_content)
    started = time.monotonic()
    attempted_at = datetime.now(UTC)
    budget = _PackageBudget(plan, started)
    counts: dict[str, int] = {}
    runtime: RuntimeIdentity | None = None
    runtime_observations: list[RuntimeIdentity] = []
    pending_peak: int | None = 0 if isinstance(plan, CapturePlanV3) else None
    pending_cleanup_confirmed: bool | None = True if isinstance(plan, CapturePlanV3) else None

    def observe_pending(value: int | None) -> None:
        nonlocal pending_peak
        if not isinstance(plan, CapturePlanV3) or pending_peak is None:
            return
        pending_peak = None if value is None else max(pending_peak, value)

    def observe_pending_cleanup(value: bool) -> None:
        nonlocal pending_cleanup_confirmed
        if pending_cleanup_confirmed is not None:
            pending_cleanup_confirmed = pending_cleanup_confirmed and value

    membership_observation: SqliteStateObservationV3 | None = None
    membership_removed: bool | None = None
    pending_removed: bool | None = None
    cleanup_failures: list[str] = []
    manager: _MembershipDatabaseV3 | None = None
    legacy_database: sqlite3.Connection | None = None
    try:
        if isinstance(plan, CapturePlanV3):
            assert expected_sqlite_runtime is not None
            manager = _MembershipDatabaseV3(
                output_root, expected_sqlite_runtime, started, plan.limits.capture_timeout_seconds
            )
            current_database = manager.open()
        else:
            legacy_database = sqlite3.connect(output_root / ".current-membership.sqlite3")
            current_database = legacy_database
            current_database.execute(
                "CREATE TABLE current_versions (law TEXT, purchase_number TEXT, "
                "version_number INTEGER, source_sha TEXT, "
                "PRIMARY KEY (law, purchase_number))"
            )
            current_database.execute(
                "CREATE TABLE future_versions (law TEXT, purchase_number TEXT, "
                "version_number INTEGER, source_sha TEXT, ingested_at TEXT, "
                "PRIMARY KEY (law, purchase_number, version_number))"
            )
        (
            descriptors,
            counts,
            pending_peak,
            membership,
            future,
            runtime,
            effective_clock,
        ) = _collect_snapshot(
            storage,
            plan,
            output_root,
            budget,
            current_database,
            external_runtime,
            clock,
            synthetic_clock,
            runtime_observations.append,
            observe_pending,
            observe_pending_cleanup,
        )
        budget.check_time()
        if manager is not None:
            manager.observe_success()
            membership_observation, membership_removed, cleanup_error = manager.close_and_remove()
            if cleanup_error is not None:
                cleanup_failures.append(cleanup_error)
            pending_removed = (
                pending_cleanup_confirmed is True
                and not (output_root / ".fragment-row.pending").exists()
            )
            if not membership_removed or not pending_removed:
                raise CaptureCollectionError("V3_TRANSIENT_CLEANUP_INCOMPLETE")
        else:
            assert legacy_database is not None
            legacy_database.close()
            legacy_database = None
            (output_root / ".current-membership.sqlite3").unlink()
        files_list = [
            "plan.json",
            *[shard.path for descriptor in descriptors for shard in descriptor.shards],
        ]
        if isinstance(plan, CapturePlanV3):
            assert expected_sqlite_runtime is not None
            if membership_observation is None or pending_peak is None:
                raise CaptureCollectionError("V3_COLLECTOR_STATE_INCOMPLETE")
            try:
                _validate_v3_sqlite_observation(
                    membership_observation,
                    purpose="COLLECTOR_MEMBERSHIP",
                    expected_runtime=expected_sqlite_runtime,
                )
            except CaptureFormatError as error:
                raise CaptureCollectionError("V3_COLLECTOR_STATE_INCOMPLETE") from error
            files_list.extend(
                fragment.path
                for descriptor in descriptors
                if isinstance(descriptor, RelationDescriptorV3)
                for row in descriptor.fragmented_rows
                for fragment in row.fragments
            )
            v3_descriptors = tuple(
                descriptor
                for descriptor in descriptors
                if isinstance(descriptor, RelationDescriptorV3)
            )
            if len(v3_descriptors) != len(descriptors):
                raise CaptureCollectionError("V3_RELATION_DESCRIPTOR_REQUIRED")
            collector_state = CollectorStateV3(
                membership=membership_observation,
                pending_peak_bytes=pending_peak,
                cleanup=TransientCleanupV3(
                    status="PASS",
                    membership_removed=True,
                    pending_removed=True,
                    failure_codes=(),
                ),
            )
            manifest: CaptureManifest | CaptureManifestV2 | CaptureManifestV3 = CaptureManifestV3(
                version="eis-search-capture-manifest-v3",
                status="COMPLETE",
                capture_id=capture_id,
                tenant=plan.tenant,
                clock=effective_clock,
                plan_sha256=sha256_bytes(plan_content),
                collector_sha256=hashlib.sha256(_COLLECTOR_SOURCE.read_bytes()).hexdigest(),
                verifier_sha256=hashlib.sha256(_VERIFIER_SOURCE.read_bytes()).hexdigest(),
                runtime=runtime,
                relations=v3_descriptors,
                current_membership=membership,
                future_versions=future,
                total_payload_bytes=budget.payload_bytes,
                total_shards=budget.shards,
                files=tuple(files_list),
                collector_state=collector_state,
            )
        elif isinstance(plan, CapturePlanV2):
            files_list.extend(
                fragment.path
                for descriptor in descriptors
                if isinstance(descriptor, RelationDescriptorV2)
                for row in descriptor.fragmented_rows
                for fragment in row.fragments
            )
            v2_descriptors = tuple(
                descriptor
                for descriptor in descriptors
                if isinstance(descriptor, RelationDescriptorV2)
            )
            if len(v2_descriptors) != len(descriptors):
                raise CaptureCollectionError("V2_RELATION_DESCRIPTOR_REQUIRED")
            manifest = CaptureManifestV2(
                version="eis-search-capture-manifest-v2",
                status="COMPLETE",
                capture_id=capture_id,
                tenant=plan.tenant,
                clock=effective_clock,
                plan_sha256=sha256_bytes(plan_content),
                collector_sha256=hashlib.sha256(_COLLECTOR_SOURCE.read_bytes()).hexdigest(),
                verifier_sha256=hashlib.sha256(_VERIFIER_SOURCE.read_bytes()).hexdigest(),
                runtime=runtime,
                relations=v2_descriptors,
                current_membership=membership,
                future_versions=future,
                total_payload_bytes=budget.payload_bytes,
                total_shards=budget.shards,
                files=tuple(files_list),
            )
        else:
            v1_descriptors = tuple(
                descriptor for descriptor in descriptors if type(descriptor) is RelationDescriptor
            )
            if len(v1_descriptors) != len(descriptors):
                raise CaptureCollectionError("V1_RELATION_DESCRIPTOR_REQUIRED")
            manifest = CaptureManifest(
                version="eis-search-capture-manifest-v1",
                status="COMPLETE",
                capture_id=capture_id,
                tenant=plan.tenant,
                clock=effective_clock,
                plan_sha256=sha256_bytes(plan_content),
                collector_sha256=hashlib.sha256(_COLLECTOR_SOURCE.read_bytes()).hexdigest(),
                verifier_sha256=hashlib.sha256(_VERIFIER_SOURCE.read_bytes()).hexdigest(),
                runtime=runtime,
                relations=v1_descriptors,
                current_membership=membership,
                future_versions=future,
                total_payload_bytes=budget.payload_bytes,
                total_shards=budget.shards,
                files=tuple(files_list),
            )
        _publish_manifest(output_root, manifest, plan.limits.metadata_bytes, budget)
        return manifest
    except Exception as error:
        if runtime is None and runtime_observations:
            runtime = runtime_observations[-1]
        reason = _safe_collection_reason(error)
        if manager is not None:
            manager.mark_failure(error)
        if manager is not None and membership_removed is None:
            membership_observation, membership_removed, cleanup_error = manager.close_and_remove()
            if cleanup_error is not None:
                cleanup_failures.append(cleanup_error)
        elif legacy_database is not None:
            legacy_database.close()
            legacy_database = None
            marker = output_root / ".current-membership.sqlite3"
            if marker.exists():
                marker.unlink()
        pending = output_root / ".fragment-row.pending"
        pending_removed = pending_cleanup_confirmed is True and not pending.exists()
        pending_manifest = output_root / ".manifest.pending"
        if pending_manifest.exists():
            pending_manifest.unlink()
        files = tuple(
            sorted(
                path.relative_to(output_root).as_posix()
                for path in output_root.rglob("*")
                if path.is_file()
            )
        )
        try:
            partial_counts = _partial_relation_counts(output_root, plan)
        except Exception:
            partial_counts = counts
            reason += ";PARTIAL_COUNT_ERROR"
        if isinstance(plan, CapturePlanV3):
            if membership_removed is not True:
                cleanup_failures.append("MEMBERSHIP_NOT_REMOVED")
            if pending_removed is not True:
                cleanup_failures.append("PENDING_NOT_REMOVED")
            cleanup_codes = tuple(dict.fromkeys(cleanup_failures))[:8]
            cleanup_status: Literal["PASS", "FAIL", "UNKNOWN"] = (
                "PASS" if membership_removed is True and pending_removed is True else "UNKNOWN"
            )
            collector_state = CollectorStateV3(
                membership=membership_observation,
                pending_peak_bytes=pending_peak,
                cleanup=TransientCleanupV3(
                    status=cleanup_status,
                    membership_removed=membership_removed,
                    pending_removed=pending_removed,
                    failure_codes=cleanup_codes,
                ),
            )
            incomplete: IncompleteCapture | IncompleteCaptureV2 | IncompleteCaptureV3
            incomplete = IncompleteCaptureV3(
                version="eis-search-capture-incomplete-v3",
                status="INCOMPLETE",
                capture_id=capture_id,
                tenant=plan.tenant,
                attempted_at=attempted_at,
                transaction_timestamp=(runtime.transaction_timestamp if runtime else None),
                snapshot_id=runtime.snapshot_id if runtime else None,
                runtime=runtime,
                plan_sha256=sha256_bytes(plan_content),
                reasons=(reason,),
                actual_relation_rows=partial_counts,
                files=files,
                collector_state=collector_state,
            )
        elif isinstance(plan, CapturePlanV2):
            incomplete = IncompleteCaptureV2(
                version="eis-search-capture-incomplete-v2",
                status="INCOMPLETE",
                capture_id=capture_id,
                tenant=plan.tenant,
                attempted_at=attempted_at,
                transaction_timestamp=(runtime.transaction_timestamp if runtime else None),
                snapshot_id=runtime.snapshot_id if runtime else None,
                runtime=runtime,
                plan_sha256=sha256_bytes(plan_content),
                reasons=(reason,),
                actual_relation_rows=partial_counts,
                files=files,
            )
        else:
            incomplete = IncompleteCapture(
                version="eis-search-capture-incomplete-v1",
                status="INCOMPLETE",
                capture_id=capture_id,
                tenant=plan.tenant,
                clock=clock.astimezone(UTC) if clock is not None else attempted_at,
                plan_sha256=sha256_bytes(plan_content),
                reasons=(reason,),
                actual_relation_rows=partial_counts,
                files=files,
            )
        _write_metadata(output_root / "incomplete.json", incomplete, plan.limits.metadata_bytes)
        return incomplete


def build_storage(database_url: str) -> PostgresStorage:
    """Build the existing repository boundary without logging the supplied URL."""
    return PostgresStorage.from_url(database_url, pool_pre_ping=True)
