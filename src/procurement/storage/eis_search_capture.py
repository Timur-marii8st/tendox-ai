"""Read-only PostgreSQL collector for the frozen EIS search package."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

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
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.engine import RowMapping

from procurement.sources.eis_search_capture import (
    EXPECTED_RELATIONS,
    AuditFragmentDescriptor,
    CaptureManifest,
    CaptureManifestV2,
    CapturePlan,
    CapturePlanV2,
    CurrentMembership,
    FragmentedAuditRowDescriptor,
    FutureVersionDiagnostic,
    IncompleteCapture,
    IncompleteCaptureV2,
    RelationDescriptor,
    RelationDescriptorV2,
    RelationSpec,
    RuntimeIdentity,
    ShardDescriptor,
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


class _PackageBudget:
    def __init__(self, plan: CapturePlan | CapturePlanV2, started: float) -> None:
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
        if self.shards >= self.plan.limits.max_shards:
            raise CaptureCollectionError("SHARD_COUNT_LIMIT")
        self.shards += 1

    def reserve_bytes(self, size: int) -> None:
        if size < 0 or self.payload_bytes + size > self.plan.limits.total_payload_bytes:
            raise CaptureCollectionError("PAYLOAD_SIZE_LIMIT")
        self.payload_bytes += size

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
        if amount < 0 or shutil.disk_usage(self.root).free < amount:
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
                        path = (
                            f"fragments/audit_events-{self.logical_rows:07d}-{ordinal:02d}.bin"
                        )
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
                    encode_value(row[name], columns[name].kind)
                    for name in self.spec.primary_key
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


def _write_metadata(path: Path, value: object, cap: int) -> bytes:
    content = canonical_bytes(value) + b"\n"
    if len(content) > cap:
        raise CaptureCollectionError("METADATA_SIZE_LIMIT")
    path.write_bytes(content)
    return content


def _verify_source_pins(plan: CapturePlan | CapturePlanV2) -> None:
    for pin in plan.source_pins:
        path = (_REPOSITORY_ROOT / pin.path).resolve(strict=True)
        if not path.is_relative_to(_REPOSITORY_ROOT) or not path.is_file():
            raise CaptureCollectionError("SOURCE_PIN_PATH_INVALID")
        if hashlib.sha256(path.read_bytes()).hexdigest() != pin.sha256:
            raise CaptureCollectionError("SOURCE_PIN_MISMATCH:" + pin.path)


def _runtime_identity(
    connection: Connection,
    plan: CapturePlan | CapturePlanV2,
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
    plan: CapturePlan | CapturePlanV2,
    budget: _PackageBudget | None = None,
) -> None:
    with _catalog_deadline_guard(connection, budget):
        _validate_schema_inner(connection, plan, budget)


def _validate_schema_inner(
    connection: Connection, plan: CapturePlan | CapturePlanV2, budget: _PackageBudget | None
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
    if effective_rls != {
        item.name for item in plan.relations
    }:
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
                select(*(events.c[name] for name in columns)).where(
                    events.c.company_id == tenant
                )
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
    connection.execute(
        text("SELECT set_config('statement_timeout', :value, true)"),
        {"value": str(budget.remaining_statement_timeout_ms())},
    )


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
            line = canonical_bytes([law, number, version, source_sha]) + b"\n"
            digest.update(len(line).to_bytes(8, "big") + line)
            count += 1
        result.append(
            CurrentMembership(law=law, rows=count, ordered_identity_sha256=digest.hexdigest())
        )
    return result[0], result[1]


def _future_diagnostics(
    database: sqlite3.Connection,
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
            line = canonical_bytes([law, number, version, source_sha, ingested_at]) + b"\n"
            digest.update(len(line).to_bytes(8, "big") + line)
            count += 1
        result.append(
            FutureVersionDiagnostic(law=law, rows=count, ordered_identity_sha256=digest.hexdigest())
        )
    return result[0], result[1]


def _capture_relations(
    connection: Connection,
    plan: CapturePlan | CapturePlanV2,
    root: Path,
    clock: datetime,
    budget: _PackageBudget,
    current_database: sqlite3.Connection,
) -> tuple[tuple[RelationDescriptor | RelationDescriptorV2, ...], dict[str, int]]:
    descriptors: list[RelationDescriptor | RelationDescriptorV2] = []
    counts: dict[str, int] = {}
    statements = {spec.name: _selection(spec, plan.tenant) for spec in plan.relations}
    source_counts: dict[str, int] = {}
    fetch_rows: dict[str, int] = {}
    for spec in plan.relations:
        budget.check_time()
        _bound_statement_timeout(connection, budget)
        source_count, maximum_row_bytes = _source_count_and_max_row_bytes(
            connection, statements[spec.name], spec
        )
        if source_count > spec.max_rows:
            raise CaptureCollectionError("RELATION_ROW_LIMIT:" + spec.name)
        raw_limit = (
            plan.limits.audit_raw_row_bytes
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
        _bound_statement_timeout(connection, budget)
        statement = statements[spec.name]
        source_count = source_counts[spec.name]
        writer: _RelationWriter | _RelationWriterV2 = (
            _RelationWriterV2(root, spec, budget, plan)
            if isinstance(plan, CapturePlanV2)
            else _RelationWriter(root, spec, budget)
        )
        try:
            columns = {column.name: column for column in spec.columns}
            order = []
            for name in spec.primary_key:
                expression = _table(spec.name).c[name]
                order_expression: Any
                if columns[name].kind == "TEXT":
                    order_expression = expression.collate("C")
                else:
                    order_expression = expression
                order.append(order_expression.asc())
            ordered = statement.order_by(*order)
            relation_fetch_rows = fetch_rows[spec.name]
            result = connection.execution_options(
                stream_results=True, yield_per=relation_fetch_rows
            ).execute(ordered)
            partitions = iter(result.mappings().partitions(relation_fetch_rows))
            while True:
                _bound_statement_timeout(connection, budget)
                budget.check_time()
                try:
                    partition = next(partitions)
                except StopIteration:
                    break
                budget.check_time()
                partition_bytes = 0
                for raw in partition:
                    raw_bytes = sum(_raw_size(raw[column.name]) for column in spec.columns)
                    raw_limit = (
                        plan.limits.audit_raw_row_bytes
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
            descriptor = writer.finish(source_count)
        except Exception:
            writer.abort()
            raise
        descriptors.append(descriptor)
        counts[spec.name] = descriptor.rows
        budget.check_time()
    return tuple(descriptors), counts


def _partial_relation_counts(
    root: Path, plan: CapturePlan | CapturePlanV2
) -> dict[str, int]:
    counts: dict[str, int] = {}
    relations_root = root / "relations"
    if not relations_root.is_dir():
        return counts
    for spec in plan.relations:
        if (
            isinstance(plan, CapturePlanV2)
            and spec.name == "audit_events"
            and any((root / "fragments").glob("audit_events-*.bin"))
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
    manifest: CaptureManifest | CaptureManifestV2,
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


def capture_search_projection(
    storage: PostgresStorage,
    plan_path: Path,
    output_root: Path,
    *,
    capture_id: str,
    external_runtime: Mapping[str, str],
    clock: datetime | None = None,
    synthetic_clock: bool = False,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> CaptureManifest | CaptureManifestV2 | IncompleteCapture | IncompleteCaptureV2:
    """Create one new package; every database read occurs in one read-only snapshot."""
    if (clock is None) == synthetic_clock:
        raise ValueError("synthetic clock requires both an override and explicit opt-in")
    if clock is not None:
        offset = clock.utcoffset()
        if clock.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("clock must be timezone-aware UTC")
    plan, plan_content = load_capture_plan(plan_path)
    if output_root.exists():
        raise CaptureCollectionError("OUTPUT_ALREADY_EXISTS")
    _verify_source_pins(plan)
    if disk_usage(output_root.parent).free < plan.limits.free_disk_min_bytes:
        raise CaptureCollectionError("FREE_DISK_LIMIT")
    output_root.mkdir(parents=False)
    (output_root / "plan.json").write_bytes(plan_content)
    started = time.monotonic()
    attempted_at = datetime.now(UTC)
    budget = _PackageBudget(plan, started)
    counts: dict[str, int] = {}
    runtime: RuntimeIdentity | None = None
    reason = "CAPTURE_FAILED"
    try:
        with closing(
            sqlite3.connect(output_root / ".current-membership.sqlite3")
        ) as current_database:
            current_database.execute(
                "CREATE TABLE current_versions (law TEXT, purchase_number TEXT, "
                "version_number INTEGER, "
                "source_sha TEXT, PRIMARY KEY (law, purchase_number))"
            )
            current_database.execute(
                "CREATE TABLE future_versions (law TEXT, purchase_number TEXT, "
                "version_number INTEGER, source_sha TEXT, ingested_at TEXT, "
                "PRIMARY KEY (law, purchase_number, version_number))"
            )
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
                budget.check_time()
                effective_clock = (
                    clock.astimezone(UTC)
                    if clock is not None
                    else runtime.transaction_timestamp.astimezone(UTC)
                )
                _bound_statement_timeout(connection, budget)
                _validate_schema(connection, plan, budget)
                budget.check_time()
                descriptors, counts = _capture_relations(
                    connection, plan, output_root, effective_clock, budget, current_database
                )
                membership = _current_membership(current_database)
                future = _future_diagnostics(current_database)
                budget.check_time()
        budget.check_time()
        (output_root / ".current-membership.sqlite3").unlink()
        files_list = [
            "plan.json",
            *[shard.path for descriptor in descriptors for shard in descriptor.shards],
        ]
        if isinstance(plan, CapturePlanV2):
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
            manifest: CaptureManifest | CaptureManifestV2 = CaptureManifestV2(
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
                descriptor
                for descriptor in descriptors
                if not isinstance(descriptor, RelationDescriptorV2)
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
        reason = type(error).__name__ + ":" + str(error)
        marker = output_root / ".current-membership.sqlite3"
        if marker.exists():
            marker.unlink()
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
        except Exception as count_error:
            partial_counts = counts
            reason += ";PARTIAL_COUNT_ERROR:" + type(count_error).__name__ + ":" + str(count_error)
        if isinstance(plan, CapturePlanV2):
            incomplete: IncompleteCapture | IncompleteCaptureV2 = IncompleteCaptureV2(
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
