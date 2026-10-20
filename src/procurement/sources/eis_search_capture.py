"""Typed, bounded package format and offline verifier for frozen EIS search data."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sqlite3
import stat
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ColumnKind = Literal[
    "TEXT", "INTEGER", "DECIMAL", "BOOLEAN", "DATETIME", "DATE", "UUID", "JSON", "ARRAY"
]

RUNTIME_44 = frozenset(
    {
        "audit_events",
        "eis_feed_windows",
        "eis_notice_projection_batches",
        "eis_notice_projection_decisions",
        "eis_notice_search_keys",
        "eis_notice_variant_origins",
        "eis_notice_variant_receipts",
        "eis_notice_variants",
        "eis_notice_versions",
        "eis_procedure_events",
        "eis_sync_targets",
    }
)
RUNTIME_223 = frozenset(
    {
        "eis_223_event_schema_checks",
        "eis_223_events",
        "eis_223_lot_event_schema_checks",
        "eis_223_lot_events",
        "eis_223_notice_versions",
        "eis_223_schema_checks",
        "eis_223_windows",
    }
)
FK_PARENTS = frozenset(
    {
        "eis_223_archive_sources",
        "eis_223_blobs",
        "eis_223_event_archive_sources",
        "eis_223_event_windows",
        "eis_223_lot_event_archive_sources",
        "eis_223_lot_event_windows",
        "eis_feed_archives",
    }
)
EXPECTED_RELATIONS = RUNTIME_44 | RUNTIME_223 | FK_PARENTS


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ColumnSpec(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    kind: ColumnKind
    sql_type: str = Field(min_length=1, max_length=100)
    nullable: bool


class ForeignKeySpec(StrictModel):
    columns: tuple[str, ...] = Field(min_length=1)
    target_relation: str
    target_columns: tuple[str, ...] = Field(min_length=1)


class IndexSpec(StrictModel):
    name: str
    columns: tuple[str, ...] = Field(min_length=1)
    unique: bool
    method: Literal["btree", "gin"]
    predicate: str | None


class RelationSpec(StrictModel):
    name: str
    role: Literal["RUNTIME_44", "RUNTIME_223", "FK_PARENT"]
    columns: tuple[ColumnSpec, ...] = Field(min_length=1)
    primary_key: tuple[str, ...] = Field(min_length=1)
    foreign_keys: tuple[ForeignKeySpec, ...] = ()
    indexes: tuple[IndexSpec, ...] = ()
    omitted_source_columns: tuple[str, ...] = ()
    selection: Literal["FULL_TENANT", "LINKED_AUDIT", "TRANSITIVE_FK"]
    max_rows: int = Field(ge=1, le=1_000_000)


class CaptureLimits(StrictModel):
    shard_bytes: Literal[8_388_608]
    metadata_bytes: Literal[16_777_216]
    max_shards: Literal[512]
    total_payload_bytes: Literal[4_294_967_296]
    max_rows_per_relation: Literal[1_000_000]
    batch_rows: Literal[8]
    batch_bytes: Literal[67_108_864]
    statement_timeout_ms: Literal[30_000]
    lock_timeout_ms: Literal[1_000]
    capture_timeout_seconds: Literal[900]
    free_disk_min_bytes: Literal[5_368_709_120]


class CaptureLimitsV2(CaptureLimits):
    audit_raw_row_bytes: Literal[33_554_432]
    audit_typed_row_bytes: Literal[67_108_864]
    audit_max_fragments: Literal[8]


class RuntimeFilePin(StrictModel):
    path: str
    sha256: Sha256


class CapturePlan(StrictModel):
    version: Literal["eis-search-capture-plan-v1"]
    plan_id: Literal["m2b1-full-tenant-search-projection-v1"]
    tenant: str = Field(min_length=1)
    schema_revision: Literal["20261006_08", "20261006_12"]
    postgres_major: Literal[16]
    read_closure_sha256: Sha256
    source_pins: tuple[RuntimeFilePin, ...] = Field(min_length=1)
    limits: CaptureLimits
    relations: tuple[RelationSpec, ...] = Field(min_length=25, max_length=25)


class CapturePlanV2(StrictModel):
    version: Literal["eis-search-capture-plan-v2"]
    plan_id: Literal["m2b1-full-tenant-search-projection-v2"]
    tenant: str = Field(min_length=1)
    schema_revision: Literal["20261006_08", "20261006_12"]
    postgres_major: Literal[16]
    read_closure_sha256: Sha256
    source_pins: tuple[RuntimeFilePin, ...] = Field(min_length=1)
    limits: CaptureLimitsV2
    relations: tuple[RelationSpec, ...] = Field(min_length=25, max_length=25)


class ShardDescriptor(StrictModel):
    path: str
    sha256: Sha256
    bytes: int = Field(ge=1)
    rows: int = Field(ge=1)
    first_primary_key: tuple[object, ...]
    last_primary_key: tuple[object, ...]
    ordered_rows_sha256: Sha256


class AuditFragmentDescriptor(StrictModel):
    path: str
    ordinal: int = Field(ge=0, lt=8)
    offset: int = Field(ge=0, lt=67_108_864)
    bytes: int = Field(ge=1, le=8_388_608)
    sha256: Sha256


class FragmentedAuditRowDescriptor(StrictModel):
    kind: Literal["AUDIT_ROW_FRAGMENTS_V2"]
    relation: Literal["audit_events"]
    tenant: str
    typed_primary_key: tuple[dict[str, object], ...]
    logical_ordinal: int = Field(ge=0, lt=1_000_000)
    whole_bytes: int = Field(gt=8_388_608, le=67_108_864)
    whole_sha256: Sha256
    fragment_count: int = Field(ge=2, le=8)
    fragments: tuple[AuditFragmentDescriptor, ...] = Field(min_length=2, max_length=8)


class RelationDescriptor(StrictModel):
    name: str
    rows: int = Field(ge=0)
    shards: tuple[ShardDescriptor, ...]
    ordered_rows_sha256: Sha256
    source_count: int = Field(ge=0)


class RelationDescriptorV2(RelationDescriptor):
    fragmented_rows: tuple[FragmentedAuditRowDescriptor, ...] = ()


class CurrentMembership(StrictModel):
    law: Literal["44", "223"]
    rows: int = Field(ge=0)
    ordered_identity_sha256: Sha256


class FutureVersionDiagnostic(StrictModel):
    law: Literal["44", "223"]
    rows: int = Field(ge=0)
    ordered_identity_sha256: Sha256


class RuntimeIdentity(StrictModel):
    current_user: str
    session_user: str
    server_version_num: str
    transaction_isolation: Literal["repeatable read"]
    transaction_read_only: Literal["on"]
    row_security: Literal["on"]
    app_company_id: str
    schema_revision: str
    snapshot_id: str
    transaction_timestamp: AwareDatetime
    clock_mode: Literal["DB_TRANSACTION", "SYNTHETIC_OVERRIDE"]
    timezone: str
    search_path: str
    database_collation: str
    database_ctype: str
    rls_policy_sha256: Sha256
    role_grants_sha256: Sha256
    role_superuser: Literal[False]
    role_bypassrls: Literal[False]
    external: dict[str, str]


class CaptureManifest(StrictModel):
    version: Literal["eis-search-capture-manifest-v1"]
    status: Literal["COMPLETE"]
    capture_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    tenant: str
    clock: AwareDatetime
    plan_sha256: Sha256
    collector_sha256: Sha256
    verifier_sha256: Sha256
    runtime: RuntimeIdentity
    relations: tuple[RelationDescriptor, ...]
    current_membership: tuple[CurrentMembership, CurrentMembership]
    future_versions: tuple[FutureVersionDiagnostic, FutureVersionDiagnostic]
    total_payload_bytes: int = Field(ge=0)
    total_shards: int = Field(ge=0)
    files: tuple[str, ...]


class CaptureManifestV2(StrictModel):
    version: Literal["eis-search-capture-manifest-v2"]
    status: Literal["COMPLETE"]
    capture_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    tenant: str
    clock: AwareDatetime
    plan_sha256: Sha256
    collector_sha256: Sha256
    verifier_sha256: Sha256
    runtime: RuntimeIdentity
    relations: tuple[RelationDescriptorV2, ...]
    current_membership: tuple[CurrentMembership, CurrentMembership]
    future_versions: tuple[FutureVersionDiagnostic, FutureVersionDiagnostic]
    total_payload_bytes: int = Field(ge=0)
    total_shards: int = Field(ge=0)
    files: tuple[str, ...]


class IncompleteCapture(StrictModel):
    version: Literal["eis-search-capture-incomplete-v1"]
    status: Literal["INCOMPLETE"]
    capture_id: str
    tenant: str
    clock: AwareDatetime
    plan_sha256: Sha256
    reasons: tuple[str, ...] = Field(min_length=1)
    actual_relation_rows: dict[str, int]
    files: tuple[str, ...]


class IncompleteCaptureV2(StrictModel):
    version: Literal["eis-search-capture-incomplete-v2"]
    status: Literal["INCOMPLETE"]
    capture_id: str
    tenant: str
    attempted_at: AwareDatetime
    transaction_timestamp: AwareDatetime | None
    snapshot_id: str | None
    runtime: RuntimeIdentity | None
    plan_sha256: Sha256
    reasons: tuple[str, ...] = Field(min_length=1)
    actual_relation_rows: dict[str, int]
    files: tuple[str, ...]


class VerificationReport(StrictModel):
    version: Literal["eis-search-capture-verification-v1"]
    status: Literal["CAPTURE_CONTENT_VERIFIED", "FAIL", "INCOMPLETE"]
    capture_origin_trust: Literal["UNKNOWN"] = "UNKNOWN"
    package_manifest_sha256: Sha256 | None
    external_manifest_digest_match: bool | None
    reasons: tuple[str, ...]
    relation_rows: dict[str, int]
    total_payload_bytes: int
    total_shards: int


class VerificationReportV2(StrictModel):
    version: Literal["eis-search-capture-verification-v2"]
    status: Literal["CAPTURE_CONTENT_VERIFIED", "FAIL", "INCOMPLETE"]
    capture_origin_trust: Literal["UNKNOWN"] = "UNKNOWN"
    package_manifest_sha256: Sha256 | None
    external_manifest_digest_match: bool | None
    reasons: tuple[str, ...]
    relation_rows: dict[str, int]
    total_payload_bytes: int
    total_shards: int
    raw_width_validation: Literal["DECODED_LOWER_BOUND_ONLY"] = "DECODED_LOWER_BOUND_ONLY"
    source_raw_width_attestation: Literal["UNKNOWN"] = "UNKNOWN"


class CaptureFormatError(ValueError):
    """A capture package or plan violated its frozen contract."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _iter_json_string(value: str, *, chunk_chars: int = 16_384) -> Iterator[bytes]:
    yield b'"'
    buffer: list[str] = []
    size = 0
    escapes = {
        '"': '\\"',
        "\\": "\\\\",
        "\b": "\\b",
        "\f": "\\f",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
    }
    for character in value:
        escaped = escapes.get(character)
        if escaped is None:
            codepoint = ord(character)
            escaped = f"\\u{codepoint:04x}" if codepoint < 0x20 else character
        buffer.append(escaped)
        size += 1
        if size >= chunk_chars:
            yield "".join(buffer).encode("utf-8")
            buffer.clear()
            size = 0
    if buffer:
        yield "".join(buffer).encode("utf-8")
    yield b'"'


def iter_canonical_bytes(value: object) -> Iterator[bytes]:
    """Yield the exact canonical JSON encoding without constructing one unbounded bytes value."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if value is None:
        yield b"null"
    elif value is True:
        yield b"true"
    elif value is False:
        yield b"false"
    elif isinstance(value, int):
        yield str(value).encode("ascii")
    elif isinstance(value, str):
        yield from _iter_json_string(value)
    elif isinstance(value, (list, tuple)):
        yield b"["
        for index, item in enumerate(value):
            if index:
                yield b","
            yield from iter_canonical_bytes(item)
        yield b"]"
    elif isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CaptureFormatError("JSON_OBJECT_KEY_INVALID")
        yield b"{"
        for index, key in enumerate(sorted(value)):
            if index:
                yield b","
            yield from _iter_json_string(key)
            yield b":"
            yield from iter_canonical_bytes(value[key])
        yield b"}"
    else:
        raise CaptureFormatError("CANONICAL_VALUE_UNSUPPORTED")


def _read_bounded(path: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CaptureFormatError("ARTIFACT_OPEN_REFUSED") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CaptureFormatError("ARTIFACT_FILETYPE_INVALID")
        if before.st_size > limit:
            raise CaptureFormatError("ARTIFACT_SIZE_LIMIT")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            value = stream.read(limit + 1)
        after = os.fstat(descriptor)
        if len(value) > limit:
            raise CaptureFormatError("ARTIFACT_SIZE_LIMIT")
        if (
            len(value) != before.st_size
            or after.st_size != before.st_size
            or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise CaptureFormatError("ARTIFACT_SIZE_CHANGED")
        return value
    finally:
        os.close(descriptor)


def _resolve_regular(root: Path, relative: str) -> Path:
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or ".." in parsed.parts or "\\" in relative:
        raise CaptureFormatError("PACKAGE_PATH_INVALID")
    resolved_root = root.resolve(strict=True)
    current = resolved_root
    for part in parsed.parts:
        current /= part
        if current.is_symlink():
            raise CaptureFormatError("PACKAGE_SYMLINK_REJECTED")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise CaptureFormatError("PACKAGE_PATH_INVALID")
    return resolved


def load_capture_plan(path: Path) -> tuple[CapturePlan | CapturePlanV2, bytes]:
    try:
        path_stat = path.lstat()
    except OSError as error:
        raise CaptureFormatError("PLAN_PATH_INVALID") from error
    if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode):
        raise CaptureFormatError("PLAN_FILETYPE_INVALID")
    content = _read_bounded(path, 16_777_216)
    try:
        raw = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureFormatError("PLAN_JSON_INVALID") from error
    if not isinstance(raw, dict):
        raise CaptureFormatError("PLAN_JSON_INVALID")
    version = raw.get("version")
    if version == "eis-search-capture-plan-v1":
        plan: CapturePlan | CapturePlanV2 = CapturePlan.model_validate(raw)
    elif version == "eis-search-capture-plan-v2":
        plan = CapturePlanV2.model_validate(raw)
    else:
        raise CaptureFormatError("PLAN_VERSION_UNSUPPORTED")
    validate_plan(plan)
    return plan, content


def validate_plan(plan: CapturePlan | CapturePlanV2) -> None:
    names = [relation.name for relation in plan.relations]
    if len(names) != len(set(names)) or set(names) != EXPECTED_RELATIONS:
        raise CaptureFormatError("PLAN_RELATION_ALLOWLIST_MISMATCH")
    roles = {relation.name: relation.role for relation in plan.relations}
    if {name for name, role in roles.items() if role == "RUNTIME_44"} != RUNTIME_44:
        raise CaptureFormatError("PLAN_ROLE_MISMATCH")
    if {name for name, role in roles.items() if role == "RUNTIME_223"} != RUNTIME_223:
        raise CaptureFormatError("PLAN_ROLE_MISMATCH")
    if {name for name, role in roles.items() if role == "FK_PARENT"} != FK_PARENTS:
        raise CaptureFormatError("PLAN_ROLE_MISMATCH")
    for relation in plan.relations:
        columns = [column.name for column in relation.columns]
        if len(columns) != len(set(columns)) or not set(relation.primary_key) <= set(columns):
            raise CaptureFormatError("PLAN_RELATION_SCHEMA_INVALID")
        if "company_id" not in columns:
            raise CaptureFormatError("PLAN_TENANT_COLUMN_REQUIRED")
        if relation.max_rows != plan.limits.max_rows_per_relation:
            raise CaptureFormatError("PLAN_RELATION_LIMIT_MISMATCH")
        expected_selection = (
            "LINKED_AUDIT"
            if relation.name == "audit_events"
            else "TRANSITIVE_FK"
            if relation.name in FK_PARENTS
            else "FULL_TENANT"
        )
        if relation.selection != expected_selection:
            raise CaptureFormatError("PLAN_SELECTION_INVALID")
        for foreign_key in relation.foreign_keys:
            if len(foreign_key.columns) != len(foreign_key.target_columns):
                raise CaptureFormatError("PLAN_FOREIGN_KEY_INVALID")
            if not set(foreign_key.columns) <= set(columns):
                raise CaptureFormatError("PLAN_FOREIGN_KEY_INVALID")
            if foreign_key.target_relation not in EXPECTED_RELATIONS:
                raise CaptureFormatError("PLAN_FOREIGN_KEY_INVALID")
        index_names = [index.name for index in relation.indexes]
        if len(index_names) != len(set(index_names)):
            raise CaptureFormatError("PLAN_INDEX_INVALID")
        if any(not set(index.columns) <= set(columns) for index in relation.indexes):
            raise CaptureFormatError("PLAN_INDEX_INVALID")
    omissions = {
        relation.name: relation.omitted_source_columns
        for relation in plan.relations
        if relation.omitted_source_columns
    }
    if omissions != {"eis_feed_archives": ("content",), "eis_223_blobs": ("content",)}:
        raise CaptureFormatError("PLAN_BINARY_PROJECTION_INVALID")
    pin_paths = [pin.path for pin in plan.source_pins]
    if len(pin_paths) != len(set(pin_paths)) or any(
        PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path
        for path in pin_paths
    ):
        raise CaptureFormatError("PLAN_SOURCE_PIN_INVALID")


def _dynamic(value: object) -> object:
    if value is None:
        return {"t": "null"}
    if isinstance(value, bool):
        return {"t": "bool", "v": value}
    if isinstance(value, int):
        return {"t": "int", "v": str(value)}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CaptureFormatError("NON_FINITE_DECIMAL")
        return {"t": "decimal", "v": str(value)}
    if isinstance(value, float):
        raise CaptureFormatError("FLOAT_VALUE_FORBIDDEN")
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise CaptureFormatError("NAIVE_DATETIME")
        return {"t": "datetime", "v": value.isoformat()}
    if isinstance(value, date):
        return {"t": "date", "v": value.isoformat()}
    if isinstance(value, UUID):
        return {"t": "uuid", "v": str(value)}
    if isinstance(value, bytes):
        return {"t": "bytes", "v": base64.b64encode(value).decode("ascii")}
    if isinstance(value, str):
        return {"t": "str", "v": value}
    if isinstance(value, (list, tuple)):
        return {"t": "array", "v": [_dynamic(item) for item in value]}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CaptureFormatError("JSON_OBJECT_KEY_INVALID")
        return {"t": "object", "v": {key: _dynamic(value[key]) for key in sorted(value)}}
    raise CaptureFormatError("VALUE_TYPE_UNSUPPORTED")


def encode_value(value: object, kind: ColumnKind) -> object:
    if value is None:
        return {"k": kind, "v": {"t": "null"}}
    expected: dict[ColumnKind, tuple[type[object], ...]] = {
        "TEXT": (str,),
        "INTEGER": (int,),
        "DECIMAL": (Decimal, int),
        "BOOLEAN": (bool,),
        "DATETIME": (datetime,),
        "DATE": (date,),
        "UUID": (UUID, str),
        "JSON": (dict, list, tuple, str, int, bool, Decimal),
        "ARRAY": (list, tuple),
    }
    if isinstance(value, bool) and kind in {"INTEGER", "DECIMAL", "JSON"}:
        if kind != "JSON":
            raise CaptureFormatError("COLUMN_TYPE_MISMATCH")
    elif not isinstance(value, expected[kind]):
        raise CaptureFormatError("COLUMN_TYPE_MISMATCH")
    if kind == "DECIMAL" and isinstance(value, int):
        value = Decimal(value)
    return {"k": kind, "v": _dynamic(value)}


def _undynamic(value: object) -> object:
    if not isinstance(value, dict) or set(value) not in ({"t"}, {"t", "v"}):
        raise CaptureFormatError("TYPED_VALUE_INVALID")
    tag = value.get("t")
    raw = value.get("v")
    if tag == "null" and set(value) == {"t"}:
        return None
    if tag == "bool" and isinstance(raw, bool):
        return raw
    if tag == "int" and isinstance(raw, str):
        try:
            return int(raw)
        except ValueError as error:
            raise CaptureFormatError("TYPED_VALUE_INVALID") from error
    if tag == "decimal" and isinstance(raw, str):
        try:
            decimal_result = Decimal(raw)
        except InvalidOperation as error:
            raise CaptureFormatError("TYPED_VALUE_INVALID") from error
        if not decimal_result.is_finite():
            raise CaptureFormatError("TYPED_VALUE_INVALID")
        return decimal_result
    if tag == "datetime" and isinstance(raw, str):
        try:
            datetime_result = datetime.fromisoformat(raw)
        except ValueError as error:
            raise CaptureFormatError("TYPED_VALUE_INVALID") from error
        if datetime_result.utcoffset() is None:
            raise CaptureFormatError("TYPED_VALUE_INVALID")
        return datetime_result
    if tag == "date" and isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError as error:
            raise CaptureFormatError("TYPED_VALUE_INVALID") from error
    if tag == "uuid" and isinstance(raw, str):
        try:
            return UUID(raw)
        except ValueError as error:
            raise CaptureFormatError("TYPED_VALUE_INVALID") from error
    if tag == "bytes" and isinstance(raw, str):
        try:
            return base64.b64decode(raw, validate=True)
        except ValueError as error:
            raise CaptureFormatError("TYPED_VALUE_INVALID") from error
    if tag == "str" and isinstance(raw, str):
        return raw
    if tag == "array" and isinstance(raw, list):
        return [_undynamic(item) for item in raw]
    if tag == "object" and isinstance(raw, dict) and all(isinstance(key, str) for key in raw):
        return {key: _undynamic(raw[key]) for key in sorted(raw)}
    raise CaptureFormatError("TYPED_VALUE_INVALID")


def decode_value(value: object, kind: ColumnKind, nullable: bool) -> object:
    if not isinstance(value, dict) or value.get("k") != kind or set(value) != {"k", "v"}:
        raise CaptureFormatError("COLUMN_ENCODING_INVALID")
    result = _undynamic(value["v"])
    if result is None:
        if not nullable:
            raise CaptureFormatError("NULL_IN_REQUIRED_COLUMN")
        return None
    expected: dict[ColumnKind, tuple[type[object], ...]] = {
        "TEXT": (str,),
        "INTEGER": (int,),
        "DECIMAL": (Decimal,),
        "BOOLEAN": (bool,),
        "DATETIME": (datetime,),
        "DATE": (date,),
        "UUID": (UUID,),
        "JSON": (dict, list, str, int, bool, Decimal),
        "ARRAY": (list,),
    }
    if isinstance(result, bool) and kind in {"INTEGER", "DECIMAL"}:
        raise CaptureFormatError("COLUMN_ENCODING_INVALID")
    if not isinstance(result, expected[kind]):
        raise CaptureFormatError("COLUMN_ENCODING_INVALID")
    return result


def encode_row(spec: RelationSpec, row: Mapping[str, object]) -> bytes:
    if set(row) != {column.name for column in spec.columns}:
        raise CaptureFormatError("ROW_COLUMN_SET_MISMATCH")
    values = [encode_value(row[column.name], column.kind) for column in spec.columns]
    by_name = dict(zip((column.name for column in spec.columns), values, strict=True))
    payload = {"primary_key": [by_name[name] for name in spec.primary_key], "values": values}
    return canonical_bytes(payload) + b"\n"


def iter_encoded_row(spec: RelationSpec, row: Mapping[str, object]) -> Iterator[bytes]:
    if set(row) != {column.name for column in spec.columns}:
        raise CaptureFormatError("ROW_COLUMN_SET_MISMATCH")
    values = [encode_value(row[column.name], column.kind) for column in spec.columns]
    by_name = dict(zip((column.name for column in spec.columns), values, strict=True))
    payload = {"primary_key": [by_name[name] for name in spec.primary_key], "values": values}
    yield from iter_canonical_bytes(payload)
    yield b"\n"


def decode_row(spec: RelationSpec, line: bytes) -> tuple[tuple[object, ...], dict[str, object]]:
    if not line.endswith(b"\n") or b"\r" in line:
        raise CaptureFormatError("JSONL_LINE_ENDING_INVALID")
    try:
        payload = json.loads(line[:-1])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureFormatError("JSONL_INVALID") from error
    if not isinstance(payload, dict) or set(payload) != {"primary_key", "values"}:
        raise CaptureFormatError("ROW_SHAPE_INVALID")
    raw_values = payload["values"]
    if not isinstance(raw_values, list) or len(raw_values) != len(spec.columns):
        raise CaptureFormatError("ROW_SHAPE_INVALID")
    decoded = {
        column.name: decode_value(value, column.kind, column.nullable)
        for column, value in zip(spec.columns, raw_values, strict=True)
    }
    expected_pk = [
        encode_value(
            decoded[name], next(column.kind for column in spec.columns if column.name == name)
        )
        for name in spec.primary_key
    ]
    if payload["primary_key"] != expected_pk:
        raise CaptureFormatError("ROW_PRIMARY_KEY_MISMATCH")
    return tuple(decoded[name] for name in spec.primary_key), decoded


def _decoded_string_utf8_lower_bound(
    values: Iterable[object], limit: int, *, chunk_characters: int = 16_384
) -> int:
    """Count decoded string bytes without claiming PostgreSQL text-width equivalence."""
    total = 0

    def visit(value: object) -> None:
        nonlocal total
        if isinstance(value, str):
            for start in range(0, len(value), chunk_characters):
                total += len(value[start : start + chunk_characters].encode("utf-8"))
                if total > limit:
                    raise CaptureFormatError("DECODED_RAW_WIDTH_LOWER_BOUND_LIMIT")
            return
        if isinstance(value, dict):
            for key, item in value.items():
                visit(key)
                visit(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    for value in values:
        visit(value)
    return total


def _key_token(key: Sequence[object]) -> tuple[tuple[str, object], ...]:
    tokens = []
    for value in key:
        if isinstance(value, datetime):
            token: object = value.isoformat()
        elif isinstance(value, date):
            token = value.isoformat()
        elif isinstance(value, UUID):
            token = str(value)
        elif isinstance(value, Decimal) or (
            isinstance(value, (str, int)) and not isinstance(value, bool)
        ):
            token = value
        else:
            raise CaptureFormatError("PRIMARY_KEY_TYPE_INVALID")
        tokens.append((type(token).__name__, token))
    return tuple(tokens)


def _iter_lines(path: Path, cap: int) -> Iterator[bytes]:
    total = 0
    content = _read_bounded(path, cap)
    with io.BytesIO(content) as stream:
        while True:
            line = stream.readline(cap + 1)
            if not line:
                break
            total += len(line)
            if len(line) > cap or total > cap:
                raise CaptureFormatError("SHARD_SIZE_LIMIT")
            yield line


def _all_regular_files(root: Path) -> set[str]:
    result: set[str] = set()
    for directory, directories, files in os.walk(root, followlinks=False):
        base = Path(directory)
        for name in directories:
            if (base / name).is_symlink():
                raise CaptureFormatError("PACKAGE_SYMLINK_REJECTED")
        for name in files:
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise CaptureFormatError("PACKAGE_FILETYPE_INVALID")
            result.add(path.relative_to(root).as_posix())
    return result


def _verification_failure(
    status: Literal["FAIL", "INCOMPLETE"],
    reason: str,
    manifest_sha: str | None = None,
    *,
    version: Literal[
        "eis-search-capture-verification-v1", "eis-search-capture-verification-v2"
    ] = "eis-search-capture-verification-v1",
) -> VerificationReport | VerificationReportV2:
    values: dict[str, object] = dict(
        status=status,
        package_manifest_sha256=manifest_sha,
        external_manifest_digest_match=None,
        reasons=(reason,),
        relation_rows={},
        total_payload_bytes=0,
        total_shards=0,
    )
    if version == "eis-search-capture-verification-v2":
        return VerificationReportV2(version=version, **values)
    return VerificationReport(version=version, **values)


def _verification_report(
    version: Literal["eis-search-capture-verification-v1", "eis-search-capture-verification-v2"],
    **values: object,
) -> VerificationReport | VerificationReportV2:
    if version == "eis-search-capture-verification-v2":
        return VerificationReportV2(version=version, **values)
    return VerificationReport(version=version, **values)


def verify_capture_package(
    package_root: Path,
    plan_path: Path,
    *,
    expected_manifest_sha256: str | None = None,
) -> VerificationReport | VerificationReportV2:
    """Verify package bytes offline. External digest matching never self-asserts origin trust."""
    report_version: Literal[
        "eis-search-capture-verification-v1", "eis-search-capture-verification-v2"
    ] = "eis-search-capture-verification-v1"
    try:
        candidate_plan, _ = load_capture_plan(plan_path)
        if isinstance(candidate_plan, CapturePlanV2):
            report_version = "eis-search-capture-verification-v2"
        return _verify_capture_package(
            package_root, plan_path, expected_manifest_sha256=expected_manifest_sha256
        )
    except (CaptureFormatError, OSError, ValueError) as error:
        return _verification_failure(
            "FAIL", type(error).__name__ + ":" + str(error), version=report_version
        )


def _validate_fragment_declarations(
    descriptor: RelationDescriptor | RelationDescriptorV2,
    spec: RelationSpec,
    plan: CapturePlanV2,
) -> None:
    if not isinstance(descriptor, RelationDescriptorV2):
        raise CaptureFormatError("V2_RELATION_DESCRIPTOR_REQUIRED")
    rows = descriptor.fragmented_rows
    if spec.name != "audit_events" and rows:
        raise CaptureFormatError("FRAGMENT_RELATION_FORBIDDEN")
    ordinals = [row.logical_ordinal for row in rows]
    if ordinals != sorted(set(ordinals)) or any(value >= descriptor.rows for value in ordinals):
        raise CaptureFormatError("FRAGMENT_LOGICAL_ORDINAL_INVALID")
    for row in rows:
        if (
            row.relation != spec.name
            or row.tenant != plan.tenant
            or len(row.typed_primary_key) != len(spec.primary_key)
            or row.whole_bytes <= plan.limits.shard_bytes
            or row.whole_bytes > plan.limits.audit_typed_row_bytes
        ):
            raise CaptureFormatError("FRAGMENT_ROW_BINDING_INVALID")
        expected_count = (row.whole_bytes + plan.limits.shard_bytes - 1) // plan.limits.shard_bytes
        if (
            row.fragment_count != expected_count
            or len(row.fragments) != expected_count
            or expected_count > plan.limits.audit_max_fragments
        ):
            raise CaptureFormatError("FRAGMENT_COUNT_INVALID")
        offset = 0
        for index, fragment in enumerate(row.fragments):
            expected_path = (
                f"fragments/audit_events-{row.logical_ordinal:07d}-{index:02d}.bin"
            )
            expected_bytes = min(plan.limits.shard_bytes, row.whole_bytes - offset)
            if (
                fragment.path != expected_path
                or fragment.ordinal != index
                or fragment.offset != offset
                or fragment.bytes != expected_bytes
                or (index < expected_count - 1 and fragment.bytes != plan.limits.shard_bytes)
            ):
                raise CaptureFormatError("FRAGMENT_SEQUENCE_INVALID")
            offset += fragment.bytes
        if offset != row.whole_bytes:
            raise CaptureFormatError("FRAGMENT_LENGTH_INVALID")


def _verify_capture_package(
    package_root: Path,
    plan_path: Path,
    *,
    expected_manifest_sha256: str | None,
) -> VerificationReport | VerificationReportV2:
    if package_root.is_symlink():
        raise CaptureFormatError("PACKAGE_SYMLINK_REJECTED")
    root = package_root.resolve(strict=True)
    if not root.is_dir():
        raise CaptureFormatError("PACKAGE_ROOT_INVALID")
    plan, plan_content = load_capture_plan(plan_path)
    report_version: Literal[
        "eis-search-capture-verification-v1", "eis-search-capture-verification-v2"
    ] = (
        "eis-search-capture-verification-v2"
        if isinstance(plan, CapturePlanV2)
        else "eis-search-capture-verification-v1"
    )
    files = _all_regular_files(root)
    if "manifest.json" not in files:
        if "incomplete.json" in files:
            incomplete_content = _read_bounded(
                _resolve_regular(root, "incomplete.json"), plan.limits.metadata_bytes
            )
            incomplete = (
                IncompleteCaptureV2.model_validate_json(incomplete_content)
                if isinstance(plan, CapturePlanV2)
                else IncompleteCapture.model_validate_json(incomplete_content)
            )
            if incomplete.plan_sha256 != sha256_bytes(plan_content):
                raise CaptureFormatError("PLAN_SHA_MISMATCH")
            return _verification_report(
                report_version,
                status="INCOMPLETE",
                package_manifest_sha256=None,
                external_manifest_digest_match=None,
                reasons=incomplete.reasons,
                relation_rows=incomplete.actual_relation_rows,
                total_payload_bytes=0,
                total_shards=0,
            )
        raise CaptureFormatError("TERMINAL_MANIFEST_MISSING")
    if "incomplete.json" in files:
        raise CaptureFormatError("COMPLETE_WITH_INCOMPLETE_MARKER")
    manifest_content = _read_bounded(
        _resolve_regular(root, "manifest.json"), plan.limits.metadata_bytes
    )
    manifest_sha = sha256_bytes(manifest_content)
    if expected_manifest_sha256 is not None and expected_manifest_sha256 != manifest_sha:
        return _verification_report(
            report_version,
            status="FAIL",
            package_manifest_sha256=manifest_sha,
            external_manifest_digest_match=False,
            reasons=("EXTERNAL_MANIFEST_DIGEST_MISMATCH",),
            relation_rows={},
            total_payload_bytes=0,
            total_shards=0,
        )
    try:
        raw_manifest = json.loads(manifest_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureFormatError("MANIFEST_JSON_INVALID") from error
    if not isinstance(raw_manifest, dict):
        raise CaptureFormatError("MANIFEST_JSON_INVALID")
    if isinstance(plan, CapturePlanV2):
        if raw_manifest.get("version") != "eis-search-capture-manifest-v2":
            raise CaptureFormatError("MANIFEST_VERSION_MISMATCH")
        manifest: CaptureManifest | CaptureManifestV2 = CaptureManifestV2.model_validate(
            raw_manifest
        )
    else:
        if raw_manifest.get("version") != "eis-search-capture-manifest-v1":
            raise CaptureFormatError("MANIFEST_VERSION_MISMATCH")
        manifest = CaptureManifest.model_validate(raw_manifest)
    if manifest.plan_sha256 != sha256_bytes(plan_content) or manifest.tenant != plan.tenant:
        raise CaptureFormatError("MANIFEST_PLAN_BINDING_MISMATCH")
    if (
        manifest.runtime.app_company_id != plan.tenant
        or manifest.runtime.schema_revision != plan.schema_revision
        or not manifest.runtime.server_version_num.startswith(str(plan.postgres_major))
    ):
        raise CaptureFormatError("MANIFEST_RUNTIME_BINDING_MISMATCH")
    if (
        manifest.runtime.clock_mode == "DB_TRANSACTION"
        and manifest.clock != manifest.runtime.transaction_timestamp
    ):
        raise CaptureFormatError("MANIFEST_CLOCK_BINDING_MISMATCH")
    pins = {pin.path: pin.sha256 for pin in plan.source_pins}
    if (
        pins.get("src/procurement/sources/eis_search_capture.py") != manifest.verifier_sha256
        or pins.get("src/procurement/storage/eis_search_capture.py") != manifest.collector_sha256
    ):
        raise CaptureFormatError("MANIFEST_TOOL_PIN_MISMATCH")
    packaged_plan = _read_bounded(_resolve_regular(root, "plan.json"), plan.limits.metadata_bytes)
    if packaged_plan != plan_content:
        raise CaptureFormatError("PACKAGED_PLAN_MISMATCH")
    specs = {relation.name: relation for relation in plan.relations}
    descriptors = {relation.name: relation for relation in manifest.relations}
    if len(descriptors) != len(manifest.relations) or set(descriptors) != EXPECTED_RELATIONS:
        raise CaptureFormatError("MANIFEST_RELATION_SET_MISMATCH")
    declared_shards = [
        shard.path for descriptor in manifest.relations for shard in descriptor.shards
    ]
    declared_fragments = [
        fragment.path
        for descriptor in manifest.relations
        if isinstance(descriptor, RelationDescriptorV2)
        for row in descriptor.fragmented_rows
        for fragment in row.fragments
    ]
    allowed_files = {"plan.json", *declared_shards, *declared_fragments}
    if (
        len(manifest.files) != len(set(manifest.files))
        or len(declared_shards) != len(set(declared_shards))
        or len(declared_fragments) != len(set(declared_fragments))
        or bool(set(declared_shards) & set(declared_fragments))
    ):
        raise CaptureFormatError("PACKAGE_FILE_DECLARATION_DUPLICATE")
    if set(manifest.files) != allowed_files or files != allowed_files | {"manifest.json"}:
        raise CaptureFormatError("PACKAGE_FILE_SET_MISMATCH")
    declared_bytes = 0
    declared_shard_count = 0
    for descriptor in manifest.relations:
        spec = specs[descriptor.name]
        if descriptor.rows != descriptor.source_count or descriptor.rows > spec.max_rows:
            raise CaptureFormatError("RELATION_DECLARED_LIMIT")
        shard_rows = 0
        for shard in descriptor.shards:
            if shard.bytes > plan.limits.shard_bytes or shard.rows > spec.max_rows:
                raise CaptureFormatError("SHARD_DECLARED_LIMIT")
            declared_bytes += shard.bytes
            declared_shard_count += 1
            shard_rows += shard.rows
            if (
                declared_bytes > plan.limits.total_payload_bytes
                or declared_shard_count > plan.limits.max_shards
            ):
                raise CaptureFormatError("CAPTURE_DECLARED_LIMIT")
        fragmented_rows = (
            descriptor.fragmented_rows
            if isinstance(descriptor, RelationDescriptorV2)
            else ()
        )
        if fragmented_rows and not isinstance(plan, CapturePlanV2):
            raise CaptureFormatError("FRAGMENTS_FORBIDDEN_IN_V1")
        if spec.name != "audit_events" and fragmented_rows:
            raise CaptureFormatError("FRAGMENT_RELATION_FORBIDDEN")
        if isinstance(plan, CapturePlanV2):
            _validate_fragment_declarations(descriptor, spec, plan)
            for row in fragmented_rows:
                for fragment in row.fragments:
                    declared_bytes += fragment.bytes
                    declared_shard_count += 1
                    if (
                        declared_bytes > plan.limits.total_payload_bytes
                        or declared_shard_count > plan.limits.max_shards
                    ):
                        raise CaptureFormatError("CAPTURE_DECLARED_LIMIT")
        if shard_rows + len(fragmented_rows) != descriptor.rows:
            raise CaptureFormatError("RELATION_DECLARED_ROW_MISMATCH")
    if (
        declared_bytes != manifest.total_payload_bytes
        or declared_shard_count != manifest.total_shards
    ):
        raise CaptureFormatError("MANIFEST_DECLARED_TOTAL_MISMATCH")
    relation_rows: dict[str, int] = {}
    total_bytes = 0
    total_shards = 0
    with tempfile.TemporaryDirectory(prefix="eis-capture-verify-") as temporary:
        database = sqlite3.connect(Path(temporary) / "keys.sqlite3")
        try:
            database.execute(
                "CREATE TABLE keys (relation_name TEXT, key_name TEXT, key_value BLOB, "
                "PRIMARY KEY (relation_name, key_name, key_value))"
            )
            database.execute(
                "CREATE TABLE references_needed (relation_name TEXT, key_name TEXT, "
                "key_value BLOB, PRIMARY KEY (relation_name, key_name, key_value))"
            )
            database.execute(
                "CREATE TABLE current_versions (law TEXT, purchase_number TEXT, "
                "version_number INTEGER, source_sha TEXT, PRIMARY KEY (law, purchase_number))"
            )
            database.execute(
                "CREATE TABLE future_versions (law TEXT, purchase_number TEXT, "
                "version_number INTEGER, source_sha TEXT, ingested_at TEXT, "
                "PRIMARY KEY (law, purchase_number, version_number))"
            )
            database.execute(
                "CREATE TABLE audit_semantics (company_id TEXT, event_id TEXT, "
                "event_type TEXT, object_type TEXT, object_id TEXT, basis BLOB, "
                "PRIMARY KEY (company_id, event_id))"
            )
            database.execute(
                "CREATE TABLE projection_batches (company_id TEXT, batch_id TEXT, "
                "audit_event_id TEXT, receipt_id TEXT, payload_sha256 TEXT, "
                "pair_count INTEGER, row_value BLOB, PRIMARY KEY (company_id, batch_id))"
            )
            database.execute(
                "CREATE TABLE projection_decisions (company_id TEXT, batch_id TEXT, "
                "purchase_number TEXT, version_number INTEGER, row_value BLOB, "
                "PRIMARY KEY (company_id, batch_id, purchase_number, version_number))"
            )
            database.execute(
                "CREATE TABLE receipts (company_id TEXT, receipt_id TEXT, receipt_sha256 TEXT, "
                "row_value BLOB, PRIMARY KEY (company_id, receipt_id))"
            )
            database.execute(
                "CREATE TABLE variant_facts (company_id TEXT, purchase_number TEXT, "
                "version_number INTEGER, document_type TEXT, xml_sha256 TEXT, facts BLOB, "
                "PRIMARY KEY (company_id, purchase_number, version_number, "
                "document_type, xml_sha256))"
            )
            database.execute(
                "CREATE TABLE variant_origins (company_id TEXT, receipt_id TEXT, "
                "archive_ordinal INTEGER, member_filename TEXT, purchase_number TEXT, "
                "version_number INTEGER, document_type TEXT, xml_sha256 TEXT, row_value BLOB, "
                "PRIMARY KEY (company_id, receipt_id, archive_ordinal, member_filename))"
            )
            for name in sorted(EXPECTED_RELATIONS):
                spec = specs[name]
                descriptor = descriptors[name]
                if descriptor.source_count != descriptor.rows:
                    raise CaptureFormatError("RELATION_SOURCE_COUNT_MISMATCH")
                if isinstance(plan, CapturePlanV2):
                    if not isinstance(descriptor, RelationDescriptorV2):
                        raise CaptureFormatError("V2_RELATION_DESCRIPTOR_REQUIRED")
                    count, size, physical_files = _verify_relation_v2(
                        root, spec, descriptor, plan, database, manifest.clock
                    )
                else:
                    if not isinstance(descriptor, RelationDescriptor):
                        raise CaptureFormatError("V1_RELATION_DESCRIPTOR_REQUIRED")
                    count, size = _verify_relation(
                        root, spec, descriptor, plan, database, manifest.clock
                    )
                    physical_files = len(descriptor.shards)
                relation_rows[name] = count
                total_bytes += size
                total_shards += physical_files
            _verify_foreign_keys(database)
            _verify_exact_parent_sets(database, plan)
            _verify_exact_audit_set(database)
            _verify_receipt_audits(database)
            _verify_projection_audits(database)
            current = _current_membership(database)
            future = _future_diagnostics(database)
        finally:
            database.close()
    if total_bytes != manifest.total_payload_bytes or total_shards != manifest.total_shards:
        raise CaptureFormatError("MANIFEST_TOTAL_MISMATCH")
    if total_bytes > plan.limits.total_payload_bytes or total_shards > plan.limits.max_shards:
        raise CaptureFormatError("CAPTURE_LIMIT_EXCEEDED")
    if tuple(sorted(current, key=lambda item: item.law)) != tuple(
        sorted(manifest.current_membership, key=lambda item: item.law)
    ):
        raise CaptureFormatError("CURRENT_MEMBERSHIP_MISMATCH")
    if tuple(sorted(future, key=lambda item: item.law)) != tuple(
        sorted(manifest.future_versions, key=lambda item: item.law)
    ):
        raise CaptureFormatError("FUTURE_VERSION_DIAGNOSTIC_MISMATCH")
    return _verification_report(
        report_version,
        status="CAPTURE_CONTENT_VERIFIED",
        package_manifest_sha256=manifest_sha,
        external_manifest_digest_match=True if expected_manifest_sha256 is not None else None,
        reasons=(),
        relation_rows=relation_rows,
        total_payload_bytes=total_bytes,
        total_shards=total_shards,
    )


def _key_blob(values: Sequence[object]) -> bytes:
    return canonical_bytes([_dynamic(value) for value in values])


def _verify_relation(
    root: Path,
    spec: RelationSpec,
    descriptor: RelationDescriptor,
    plan: CapturePlan,
    database: sqlite3.Connection,
    clock: datetime,
) -> tuple[int, int]:
    count = 0
    size = 0
    relation_digest = hashlib.sha256()
    previous: tuple[tuple[str, object], ...] | None = None
    first_descriptor: tuple[object, ...] | None = None
    last_descriptor: tuple[object, ...] | None = None
    expected_paths = [
        f"relations/{spec.name}-{index:05d}.jsonl"
        for index in range(1, len(descriptor.shards) + 1)
    ]
    if [item.path for item in descriptor.shards] != expected_paths:
        raise CaptureFormatError("SHARD_PATH_SEQUENCE_INVALID")
    unique_targets: set[tuple[tuple[str, ...], str]] = {(spec.primary_key, "PK")}
    for relation in plan.relations:
        for foreign_key in relation.foreign_keys:
            if foreign_key.target_relation == spec.name:
                unique_targets.add(
                    (
                        foreign_key.target_columns,
                        "FK:" + ",".join(foreign_key.target_columns),
                    )
                )
    for shard in descriptor.shards:
        path = _resolve_regular(root, shard.path)
        if path.stat().st_size != shard.bytes or shard.bytes > plan.limits.shard_bytes:
            raise CaptureFormatError("SHARD_BYTE_COUNT_MISMATCH")
        file_digest = hashlib.sha256()
        ordered_digest = hashlib.sha256()
        shard_rows = 0
        shard_first: tuple[object, ...] | None = None
        shard_last: tuple[object, ...] | None = None
        for line in _iter_lines(path, plan.limits.shard_bytes):
            file_digest.update(line)
            ordered_digest.update(len(line).to_bytes(8, "big"))
            ordered_digest.update(line)
            relation_digest.update(len(line).to_bytes(8, "big"))
            relation_digest.update(line)
            key, row = decode_row(spec, line)
            if row["company_id"] != plan.tenant:
                raise CaptureFormatError("ROW_TENANT_MISMATCH")
            token = _key_token(key)
            if previous is not None and token <= previous:
                raise CaptureFormatError("ROW_ORDER_OR_DUPLICATE_INVALID")
            previous = token
            shard_first = shard_first or key
            shard_last = key
            count += 1
            shard_rows += 1
            _record_keys(database, spec, row, unique_targets)
            _record_references(database, spec, row)
            _record_current(database, spec.name, row, clock)
            _record_semantics(database, spec.name, row)
        if not shard_rows or shard_rows != shard.rows:
            raise CaptureFormatError("SHARD_ROW_COUNT_MISMATCH")
        if (
            file_digest.hexdigest() != shard.sha256
            or ordered_digest.hexdigest() != shard.ordered_rows_sha256
        ):
            raise CaptureFormatError("SHARD_DIGEST_MISMATCH")
        if (
            tuple(shard.first_primary_key) != shard_first
            or tuple(shard.last_primary_key) != shard_last
        ):
            raise CaptureFormatError("SHARD_BOUNDARY_MISMATCH")
        first_descriptor = first_descriptor or shard_first
        last_descriptor = shard_last
        size += shard.bytes
    if count != descriptor.rows or count > spec.max_rows:
        raise CaptureFormatError("RELATION_ROW_COUNT_MISMATCH")
    if relation_digest.hexdigest() != descriptor.ordered_rows_sha256:
        raise CaptureFormatError("RELATION_DIGEST_MISMATCH")
    if count == 0 and descriptor.shards:
        raise CaptureFormatError("EMPTY_RELATION_HAS_SHARDS")
    if count and (first_descriptor is None or last_descriptor is None):
        raise CaptureFormatError("RELATION_BOUNDARY_MISSING")
    return count, size


def _iter_verified_inline_rows(
    root: Path,
    spec: RelationSpec,
    descriptor: RelationDescriptorV2,
    plan: CapturePlanV2,
    stats: dict[str, int],
) -> Iterator[tuple[bytes, tuple[object, ...], dict[str, object]]]:
    expected_paths = [
        f"relations/{spec.name}-{index:05d}.jsonl" for index in range(1, len(descriptor.shards) + 1)
    ]
    if [item.path for item in descriptor.shards] != expected_paths:
        raise CaptureFormatError("SHARD_PATH_SEQUENCE_INVALID")
    for shard in descriptor.shards:
        path = _resolve_regular(root, shard.path)
        if path.stat().st_size != shard.bytes or shard.bytes > plan.limits.shard_bytes:
            raise CaptureFormatError("SHARD_BYTE_COUNT_MISMATCH")
        file_digest = hashlib.sha256()
        ordered_digest = hashlib.sha256()
        shard_rows = 0
        shard_first: tuple[object, ...] | None = None
        shard_last: tuple[object, ...] | None = None
        for line in _iter_lines(path, plan.limits.shard_bytes):
            if len(line) > plan.limits.shard_bytes:
                raise CaptureFormatError("INLINE_ROW_SIZE_INVALID")
            file_digest.update(line)
            ordered_digest.update(len(line).to_bytes(8, "big") + line)
            key, row = decode_row(spec, line)
            shard_first = shard_first or key
            shard_last = key
            shard_rows += 1
            yield line, key, row
        if not shard_rows or shard_rows != shard.rows:
            raise CaptureFormatError("SHARD_ROW_COUNT_MISMATCH")
        if (
            file_digest.hexdigest() != shard.sha256
            or ordered_digest.hexdigest() != shard.ordered_rows_sha256
        ):
            raise CaptureFormatError("SHARD_DIGEST_MISMATCH")
        if (
            tuple(shard.first_primary_key) != shard_first
            or tuple(shard.last_primary_key) != shard_last
        ):
            raise CaptureFormatError("SHARD_BOUNDARY_MISMATCH")
        stats["rows"] += shard_rows
        stats["bytes"] += shard.bytes


def _read_fragmented_row(
    root: Path,
    spec: RelationSpec,
    row: FragmentedAuditRowDescriptor,
    plan: CapturePlanV2,
) -> tuple[bytes, tuple[object, ...], dict[str, object]]:
    content = bytearray()
    digest = hashlib.sha256()
    for fragment in row.fragments:
        part = _read_bounded(_resolve_regular(root, fragment.path), plan.limits.shard_bytes)
        if len(part) != fragment.bytes or sha256_bytes(part) != fragment.sha256:
            raise CaptureFormatError("FRAGMENT_CONTENT_MISMATCH")
        content.extend(part)
        digest.update(part)
        if len(content) > row.whole_bytes or len(content) > plan.limits.audit_typed_row_bytes:
            raise CaptureFormatError("FRAGMENT_REASSEMBLY_LIMIT")
    if len(content) != row.whole_bytes or digest.hexdigest() != row.whole_sha256:
        raise CaptureFormatError("FRAGMENTED_ROW_DIGEST_MISMATCH")
    line = bytes(content)
    key, decoded = decode_row(spec, line)
    typed_key = tuple(
        encode_value(
            decoded[name], next(column.kind for column in spec.columns if column.name == name)
        )
        for name in spec.primary_key
    )
    if typed_key != row.typed_primary_key:
        raise CaptureFormatError("FRAGMENTED_ROW_PRIMARY_KEY_MISMATCH")
    return line, key, decoded


def _verify_relation_v2(
    root: Path,
    spec: RelationSpec,
    descriptor: RelationDescriptorV2,
    plan: CapturePlanV2,
    database: sqlite3.Connection,
    clock: datetime,
) -> tuple[int, int, int]:
    _validate_fragment_declarations(descriptor, spec, plan)
    inline_stats = {"rows": 0, "bytes": 0}
    inline = iter(_iter_verified_inline_rows(root, spec, descriptor, plan, inline_stats))
    fragments = {row.logical_ordinal: row for row in descriptor.fragmented_rows}
    unique_targets: set[tuple[tuple[str, ...], str]] = {(spec.primary_key, "PK")}
    for relation in plan.relations:
        for foreign_key in relation.foreign_keys:
            if foreign_key.target_relation == spec.name:
                unique_targets.add(
                    (foreign_key.target_columns, "FK:" + ",".join(foreign_key.target_columns))
                )
    relation_digest = hashlib.sha256()
    previous: tuple[tuple[str, object], ...] | None = None
    count = 0
    fragment_bytes = 0
    for logical_ordinal in range(descriptor.rows):
        fragmented = fragments.get(logical_ordinal)
        if fragmented is None:
            try:
                line, key, row = next(inline)
            except StopIteration as error:
                raise CaptureFormatError("INLINE_ROW_MISSING") from error
        else:
            line, key, row = _read_fragmented_row(root, spec, fragmented, plan)
            fragment_bytes += fragmented.whole_bytes
        if spec.name == "audit_events":
            _decoded_string_utf8_lower_bound(row.values(), plan.limits.audit_raw_row_bytes)
        if row["company_id"] != plan.tenant:
            raise CaptureFormatError("ROW_TENANT_MISMATCH")
        token = _key_token(key)
        if previous is not None and token <= previous:
            raise CaptureFormatError("ROW_ORDER_OR_DUPLICATE_INVALID")
        previous = token
        relation_digest.update(len(line).to_bytes(8, "big") + line)
        count += 1
        _record_keys(database, spec, row, unique_targets)
        _record_references(database, spec, row)
        _record_current(database, spec.name, row, clock)
        _record_semantics(database, spec.name, row)
    try:
        next(inline)
    except StopIteration:
        pass
    else:
        raise CaptureFormatError("INLINE_ROW_UNDECLARED")
    if inline_stats["rows"] + len(fragments) != count:
        raise CaptureFormatError("RELATION_ROW_COUNT_MISMATCH")
    if count != descriptor.rows or count > spec.max_rows:
        raise CaptureFormatError("RELATION_ROW_COUNT_MISMATCH")
    if relation_digest.hexdigest() != descriptor.ordered_rows_sha256:
        raise CaptureFormatError("RELATION_DIGEST_MISMATCH")
    physical_files = len(descriptor.shards) + sum(
        row.fragment_count for row in descriptor.fragmented_rows
    )
    return count, inline_stats["bytes"] + fragment_bytes, physical_files


def _record_keys(
    database: sqlite3.Connection,
    spec: RelationSpec,
    row: Mapping[str, object],
    targets: Iterable[tuple[tuple[str, ...], str]],
) -> None:
    for columns, key_name in targets:
        values = tuple(row[column] for column in columns)
        if any(value is None for value in values):
            continue
        try:
            database.execute(
                "INSERT INTO keys VALUES (?, ?, ?)", (spec.name, key_name, _key_blob(values))
            )
        except sqlite3.IntegrityError as error:
            raise CaptureFormatError("UNIQUE_KEY_DUPLICATE") from error


def _record_references(
    database: sqlite3.Connection, spec: RelationSpec, row: Mapping[str, object]
) -> None:
    for foreign_key in spec.foreign_keys:
        values = tuple(row[column] for column in foreign_key.columns)
        if any(value is None for value in values):
            continue
        database.execute(
            "INSERT OR IGNORE INTO references_needed VALUES (?, ?, ?)",
            (
                foreign_key.target_relation,
                "FK:" + ",".join(foreign_key.target_columns),
                _key_blob(values),
            ),
        )


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
    if law is None:
        return
    ingested_at = row["ingested_at"]
    if not isinstance(ingested_at, datetime):
        raise CaptureFormatError("NOTICE_INGESTED_AT_INVALID")
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


def _verify_foreign_keys(database: sqlite3.Connection) -> None:
    missing = database.execute(
        "SELECT r.relation_name, r.key_name FROM references_needed r "
        "LEFT JOIN keys k ON k.relation_name=r.relation_name AND k.key_name=r.key_name "
        "AND k.key_value=r.key_value WHERE k.key_value IS NULL LIMIT 1"
    ).fetchone()
    if missing:
        raise CaptureFormatError("FOREIGN_KEY_DEPENDENCY_MISSING")


def _verify_exact_parent_sets(
    database: sqlite3.Connection, plan: CapturePlan | CapturePlanV2
) -> None:
    for spec in plan.relations:
        if spec.role != "FK_PARENT":
            continue
        actual = {
            row[0]
            for row in database.execute(
                "SELECT key_value FROM keys WHERE relation_name=? AND key_name='PK'",
                (spec.name,),
            )
        }
        needed = {
            row[0]
            for row in database.execute(
                "SELECT key_value FROM references_needed WHERE relation_name=?",
                (spec.name,),
            )
        }
        if actual != needed:
            raise CaptureFormatError("FK_PARENT_SET_NOT_EXACT:" + spec.name)


def _verify_exact_audit_set(database: sqlite3.Connection) -> None:
    needed = {
        row[0]
        for row in database.execute(
            "SELECT key_value FROM references_needed WHERE relation_name='audit_events'"
        )
    }
    actual = {
        row[0]
        for row in database.execute("SELECT key_value FROM keys WHERE relation_name='audit_events'")
    }
    if actual != needed:
        raise CaptureFormatError("AUDIT_EVENT_SET_NOT_EXACT")


def _typed_blob(value: object) -> bytes:
    return canonical_bytes(_dynamic(value))


def _typed_unblob(value: bytes) -> object:
    return _undynamic(json.loads(value))


def _record_semantics(
    database: sqlite3.Connection, relation: str, row: Mapping[str, object]
) -> None:
    if relation == "audit_events":
        database.execute(
            "INSERT INTO audit_semantics VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["company_id"],
                row["event_id"],
                row["event_type"],
                row["object_type"],
                row["object_id"],
                _typed_blob(row["basis"]),
            ),
        )
    elif relation == "eis_notice_projection_batches":
        database.execute(
            "INSERT INTO projection_batches VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["company_id"],
                row["batch_id"],
                row["audit_event_id"],
                row["receipt_id"],
                row["payload_sha256"],
                row["pair_count"],
                _typed_blob(dict(row)),
            ),
        )
    elif relation == "eis_notice_projection_decisions":
        database.execute(
            "INSERT INTO projection_decisions VALUES (?, ?, ?, ?, ?)",
            (
                row["company_id"],
                row["batch_id"],
                row["purchase_number"],
                row["version_number"],
                _typed_blob(dict(row)),
            ),
        )
    elif relation == "eis_notice_variant_receipts":
        database.execute(
            "INSERT INTO receipts VALUES (?, ?, ?, ?)",
            (
                row["company_id"],
                row["receipt_id"],
                row["receipt_sha256"],
                _typed_blob(dict(row)),
            ),
        )
    elif relation == "eis_notice_variants":
        if row["facts_sha256"] != sha256_bytes(
            json.dumps(
                row["facts"], sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")
        ):
            raise CaptureFormatError("VARIANT_FACTS_HASH_MISMATCH")
        database.execute(
            "INSERT INTO variant_facts VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["company_id"],
                row["purchase_number"],
                row["version_number"],
                row["document_type"],
                row["xml_sha256"],
                _typed_blob(row["facts"]),
            ),
        )
    elif relation == "eis_notice_variant_origins":
        database.execute(
            "INSERT INTO variant_origins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["company_id"],
                row["receipt_id"],
                row["archive_ordinal"],
                row["member_filename"],
                row["purchase_number"],
                row["version_number"],
                row["document_type"],
                row["xml_sha256"],
                _typed_blob({key: value for key, value in row.items() if key != "company_id"}),
            ),
        )


def _jsonable(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _projection_sha(value: object) -> str:
    encoded = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(encoded)


def _audit_row(
    database: sqlite3.Connection, company: str, event_id: str
) -> tuple[str, str | None, str | None, object] | None:
    row = database.execute(
        "SELECT event_type, object_type, object_id, basis FROM audit_semantics "
        "WHERE company_id=? AND event_id=?",
        (company, event_id),
    ).fetchone()
    if row is None:
        return None
    return row[0], row[1], row[2], _typed_unblob(row[3])


def _verify_receipt_audits(database: sqlite3.Connection) -> None:
    for company, receipt_id, receipt_sha, receipt_blob in database.execute(
        "SELECT company_id, receipt_id, receipt_sha256, row_value FROM receipts"
    ):
        receipt = _typed_unblob(receipt_blob)
        if not isinstance(receipt, dict):
            raise CaptureFormatError("RECEIPT_AUDIT_BASIS_INVALID")
        origins = [
            _typed_unblob(item[0])
            for item in database.execute(
                "SELECT row_value FROM variant_origins WHERE company_id=? AND receipt_id=? "
                "ORDER BY archive_ordinal, member_filename",
                (company, receipt_id),
            )
        ]
        variants = []
        seen: set[tuple[object, ...]] = set()
        for origin in origins:
            if not isinstance(origin, dict):
                raise CaptureFormatError("RECEIPT_AUDIT_BASIS_INVALID")
            key = tuple(
                origin[name]
                for name in ("purchase_number", "version_number", "document_type", "xml_sha256")
            )
            if key in seen:
                continue
            seen.add(key)
            fact = database.execute(
                "SELECT facts FROM variant_facts WHERE company_id=? AND purchase_number=? "
                "AND version_number=? AND document_type=? AND xml_sha256=?",
                (company, *key),
            ).fetchone()
            if fact is None:
                raise CaptureFormatError("RECEIPT_VARIANT_FACT_MISSING")
            variants.append(_typed_unblob(fact[0]))
        variants.sort(
            key=lambda item: (
                (
                    item["purchase_number"],
                    item["version_number"],
                    item["document_type"],
                    item["xml_sha256"],
                )
                if isinstance(item, dict)
                else ()
            )
        )
        payload = {
            key: value
            for key, value in receipt.items()
            if key not in {"company_id", "receipt_sha256"}
        }
        observed_at = payload.get("observed_at")
        if isinstance(observed_at, datetime):
            payload["observed_at"] = observed_at.astimezone(UTC).isoformat()
        expected_sha = _projection_sha(
            {"receipt": payload, "variants": variants, "origins": origins}
        )
        if (
            expected_sha != receipt_sha
            or receipt.get("occurrence_count") != len(origins)
            or receipt.get("variant_count") != len(variants)
        ):
            raise CaptureFormatError("RECEIPT_CONTENT_INVALID")
        evidence = receipt.get("evidence")
        retention = _audit_row(database, company, str(receipt["retention_audit_event_id"]))
        diagnosis = _audit_row(database, company, str(receipt["diagnosis_audit_event_id"]))
        ledger = _audit_row(database, company, str(receipt["ledger_audit_event_id"]))
        expected_retention = {"evidence": evidence, "coverage": "UNKNOWN"}
        if retention != (
            "EIS_REJECTED_WINDOW_EVIDENCE",
            "eis_sync_target",
            receipt["window_key"],
            expected_retention,
        ):
            raise CaptureFormatError("RECEIPT_RETENTION_AUDIT_INVALID")
        if (
            diagnosis is None
            or diagnosis[:3]
            != (
                "EIS_NOTICE_CONFLICT_DIAGNOSIS",
                "eis_sync_target",
                receipt["window_key"],
            )
            or not isinstance(diagnosis[3], dict)
            or diagnosis[3].get("evidence") != evidence
            or not isinstance(diagnosis[3].get("diagnosis"), dict)
            or diagnosis[3]["diagnosis"].get("sha256") != receipt["diagnosis_sha256"]
        ):
            raise CaptureFormatError("RECEIPT_DIAGNOSIS_AUDIT_INVALID")
        expected_ledger = {
            "receipt": _jsonable(payload | {"receipt_sha256": receipt_sha}),
            "variants": _jsonable(variants),
            "origins": _jsonable(origins),
            "evidence_status": "EVIDENCE_ONLY",
            "resolution": "UNKNOWN",
            "canonical_admission": "NOT_ENABLED",
        }
        if ledger != (
            "EIS_NOTICE_VARIANT_LEDGER_RECORDED",
            "eis_notice_variant_receipt",
            receipt_id,
            expected_ledger,
        ):
            raise CaptureFormatError("RECEIPT_LEDGER_AUDIT_INVALID")


def _verify_projection_audits(database: sqlite3.Connection) -> None:
    rows = database.execute(
        "SELECT b.company_id, b.batch_id, b.payload_sha256, b.pair_count, b.row_value, "
        "a.event_type, a.object_type, a.object_id, a.basis, r.receipt_sha256 "
        "FROM projection_batches b "
        "LEFT JOIN audit_semantics a ON a.company_id=b.company_id "
        "AND a.event_id=b.audit_event_id "
        "LEFT JOIN receipts r ON r.company_id=b.company_id AND r.receipt_id=b.receipt_id"
    )
    for (
        company,
        batch_id,
        payload_sha,
        pair_count,
        batch_blob,
        event_type,
        object_type,
        object_id,
        basis_blob,
        receipt_sha,
    ) in rows:
        if basis_blob is None or receipt_sha is None:
            raise CaptureFormatError("PROJECTION_AUDIT_BASIS_MISSING")
        basis = _typed_unblob(basis_blob)
        batch = _typed_unblob(batch_blob)
        if not isinstance(basis, dict) or not isinstance(batch, dict):
            raise CaptureFormatError("PROJECTION_AUDIT_BASIS_INVALID")
        decisions = [
            _jsonable(_typed_unblob(item[0]))
            for item in database.execute(
                "SELECT row_value FROM projection_decisions WHERE company_id=? AND batch_id=? "
                "ORDER BY purchase_number, version_number",
                (company, batch_id),
            )
        ]
        expected_batch = {key: value for key, value in batch.items() if key != "payload_sha256"}
        basis_without_sha = {key: value for key, value in basis.items() if key != "payload_sha256"}
        if (
            event_type != "EIS_NOTICE_PROJECTION_RECORDED"
            or object_type != "eis_notice_projection_batch"
            or object_id != batch_id
            or basis.get("payload_sha256") != payload_sha
            or _projection_sha(basis_without_sha) != payload_sha
            or basis.get("batch_id") != batch_id
            or basis.get("batch") != _jsonable(expected_batch)
            or basis.get("decisions") != decisions
            or basis.get("receipt_sha256") != receipt_sha
            or len(decisions) != pair_count
        ):
            raise CaptureFormatError("PROJECTION_AUDIT_BASIS_INVALID")


def _current_membership(
    database: sqlite3.Connection,
) -> tuple[CurrentMembership, CurrentMembership]:
    result = []
    for law in ("44", "223"):
        digest = hashlib.sha256()
        count = 0
        for number, version, source_sha in database.execute(
            "SELECT purchase_number, version_number, source_sha FROM current_versions "
            "WHERE law=? ORDER BY purchase_number",
            (law,),
        ):
            line = canonical_bytes([law, number, version, source_sha]) + b"\n"
            digest.update(len(line).to_bytes(8, "big"))
            digest.update(line)
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


def iter_encoded_rows(path: Path, spec: RelationSpec, cap: int) -> Iterable[dict[str, object]]:
    """Test/restore helper: decode one bounded shard without database access."""
    for line in _iter_lines(path, cap):
        _, row = decode_row(spec, line)
        yield row
