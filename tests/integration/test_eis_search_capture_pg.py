"""Real PostgreSQL acceptance for the bounded frozen-search collector."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import TypeAdapter
from sqlalchemy import Connection, Text, create_engine, func, insert, literal, or_, select, text
from sqlalchemy import cast as sql_cast
from sqlalchemy.engine import make_url
from test_eis_notice_projection_pg import NUMBER, prepare

import procurement.storage.eis_search_capture as capture_module
from procurement.sources.eis_223_archive import Eis223NoticeSnapshot
from procurement.sources.eis_feed_archive import EisNoticeSnapshot
from procurement.sources.eis_notice_conflicts import diagnose_notice_conflicts
from procurement.sources.eis_notice_projection import (
    _snapshot_payload_bytes,
    prepare_notice_projection,
)
from procurement.sources.eis_search_capture import (
    V3_FRAGMENT_RELATIONS,
    CaptureManifest,
    CaptureManifestV2,
    CapturePlanAny,
    CapturePlanV2,
    CapturePlanV3,
    RelationDescriptor,
    RelationDescriptorV2,
    RelationDescriptorV3,
    canonical_bytes,
    encode_value,
    iter_encoded_row,
    iter_encoded_rows,
    load_capture_plan,
    verify_capture_package,
)
from procurement.storage.eis_223_index import _notice_keys, ingest_notice223_window
from procurement.storage.eis_notice_hold import read_notice_source_hold
from procurement.storage.eis_notice_projection import project_retained_notice_variants
from procurement.storage.eis_search_capture import (
    CaptureCollectionError,
    _PackageBudget,
    _selection,
    _source_count_and_max_row_bytes,
    _validate_schema,
    build_storage,
    capture_search_projection,
)
from procurement.storage.models import (
    eis_223_archive_sources,
    eis_223_blobs,
    eis_223_windows,
    eis_feed_archives,
    eis_feed_windows,
    eis_notice_versions,
    eis_procedure_events,
    eis_sync_targets,
)
from procurement.storage.repository import PostgresStorage
from test_eis_223_archive import xml as xml223
from test_eis_223_archive import zip_bytes as zip_bytes223
from test_eis_223_index import window as window223
from test_eis_notice_conflicts import bundle, notice

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "scripts/benchmarks/eis-search-capture-plan.v1.json"
PRODUCTION_PLAN_PATH = (
    ROOT / "scripts/benchmarks/eis-search-capture-plan.production-20261006_08.json"
)
PLAN_V2_PATH = ROOT / "scripts/benchmarks/eis-search-capture-plan.v2.json"
PLAN_V3_PATH = ROOT / "scripts/benchmarks/eis-search-capture-plan.v3.json"
TENANT = "local-eis-supplier"
OTHER_TENANT = "capture-foreign-tenant"
CLOCK = datetime(2026, 10, 7, 12, tzinfo=UTC)
MEMORY_LIMIT_BYTES = 2 * 1024**3
LARGE_PROJECTION_MEMBERS = 450
LARGE_PROJECTION_TITLE_PADDING = 3_000
LARGE_PROJECTION_ATTACHMENTS = 14
LARGE_PROJECTION_FILENAME_PADDING = 850
LARGE_PROJECTION_GROUPS_V3 = 8
V3_SEED_RECEIPT = Path("/reports/capture-v3-seed-ready.json")
V3_SEED_PENDING = Path("/reports/.capture-v3-seed-ready.pending")


def _v3_seed_export_nonce() -> str | None:
    flag = os.environ.get("EIS_CAPTURE_V3_SEED_EXPORT")
    if flag is None:
        return None
    if flag != "1":
        raise AssertionError("EIS_CAPTURE_V3_SEED_EXPORT_INVALID")
    nonce = os.environ.get("EIS_CAPTURE_V3_SEED_NONCE")
    if nonce is None or re.fullmatch(r"[0-9a-f]{24}", nonce) is None:
        raise AssertionError("EIS_CAPTURE_V3_SEED_NONCE_INVALID")
    return nonce


def _write_all(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        try:
            written = os.write(descriptor, content[offset:])
        except InterruptedError:
            continue
        if written <= 0:
            raise AssertionError("SEED_RECEIPT_WRITE_INVALID")
        offset += written


def _publish_v3_seed_receipt(receipt: dict[str, object]) -> None:
    if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 1_000:
        raise AssertionError("SEED_RECEIPT_PLATFORM_INVALID")
    reports = V3_SEED_RECEIPT.parent
    facts = reports.lstat()
    if (
        reports.is_symlink()
        or not stat.S_ISDIR(facts.st_mode)
        or facts.st_uid != 1_000
        or stat.S_IMODE(facts.st_mode) & 0o077
        or V3_SEED_RECEIPT.exists()
        or V3_SEED_PENDING.exists()
    ):
        raise AssertionError("SEED_RECEIPT_PATH_INVALID")
    content = canonical_bytes(receipt) + b"\n"
    if len(content) > 65_536:
        raise AssertionError("SEED_RECEIPT_SIZE_LIMIT")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(V3_SEED_PENDING, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)  # type: ignore[attr-defined]
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 1_000
            or before.st_nlink != 1
        ):
            raise AssertionError("SEED_RECEIPT_FILE_INVALID")
        _write_all(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    after = V3_SEED_PENDING.lstat()
    if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
        raise AssertionError("SEED_RECEIPT_IDENTITY_CHANGED")
    os.link(V3_SEED_PENDING, V3_SEED_RECEIPT, follow_symlinks=False)
    linked = V3_SEED_RECEIPT.lstat()
    if (
        not stat.S_ISREG(linked.st_mode)
        or linked.st_uid != 1_000
        or stat.S_IMODE(linked.st_mode) != 0o600
        or linked.st_nlink != 2
        or (linked.st_dev, linked.st_ino) != (before.st_dev, before.st_ino)
    ):
        raise AssertionError("SEED_RECEIPT_LINK_INVALID")
    pending_linked = V3_SEED_PENDING.lstat()
    if (pending_linked.st_dev, pending_linked.st_ino) != (
        before.st_dev,
        before.st_ino,
    ):
        raise AssertionError("SEED_RECEIPT_PENDING_CHANGED")
    V3_SEED_PENDING.unlink()
    final = V3_SEED_RECEIPT.lstat()
    if (
        not stat.S_ISREG(final.st_mode)
        or final.st_uid != 1_000
        or stat.S_IMODE(final.st_mode) != 0o600
        or final.st_nlink != 1
        or (final.st_dev, final.st_ino) != (before.st_dev, before.st_ino)
    ):
        raise AssertionError("SEED_RECEIPT_FINAL_INVALID")
    directory_descriptor = os.open(
        reports,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _insert_feed_archive_selection_fixture(connection: Connection) -> dict[str, tuple[str, ...]]:
    response = "b" * 64
    window = "capture-union-selection"
    payloads = {name: ("archive-" + name).encode() for name in (
        "notice-only",
        "event-only",
        "both",
        "duplicate",
        "orphan",
        "single-component-mismatch",
    )}
    keys = {
        name: (TENANT, window, response, hashlib.sha256(payload).hexdigest())
        for name, payload in payloads.items()
    }
    foreign_payload = b"archive-foreign"
    foreign_key = (
        OTHER_TENANT,
        window,
        response,
        hashlib.sha256(foreign_payload).hexdigest(),
    )
    connection.execute(
        insert(eis_feed_windows),
        [
            {
                "company_id": TENANT,
                "window_key": window,
                "response_sha256": response,
                "manifest_sha256": "c" * 64,
                "archive_count": len(payloads),
                "notice_count": 4,
                "intake_kind": "LEGACY_CANONICAL",
                "coverage": "UNKNOWN",
                "ingested_at": CLOCK,
            },
            {
                "company_id": OTHER_TENANT,
                "window_key": window,
                "response_sha256": response,
                "manifest_sha256": "d" * 64,
                "archive_count": 1,
                "notice_count": 1,
                "intake_kind": "LEGACY_CANONICAL",
                "coverage": "UNKNOWN",
                "ingested_at": CLOCK,
            },
        ],
    )
    connection.execute(
        insert(eis_feed_archives),
        [
            {
                "company_id": key[0],
                "window_key": key[1],
                "response_sha256": key[2],
                "archive_sha256": key[3],
                "content": payloads[name],
                "record_count": 1,
            }
            for name, key in keys.items()
        ]
        + [
            {
                "company_id": foreign_key[0],
                "window_key": foreign_key[1],
                "response_sha256": foreign_key[2],
                "archive_sha256": foreign_key[3],
                "content": foreign_payload,
                "record_count": 1,
            }
        ],
    )

    def notice(number: int, key: tuple[str, ...]) -> dict[str, object]:
        return {
            "company_id": key[0],
            "purchase_number": f"{number:019d}",
            "version_number": 1,
            "xml_sha256": f"{number % 16:x}" * 64,
            "window_key": key[1],
            "response_sha256": key[2],
            "archive_sha256": key[3],
            "source_member": f"notice-{number}.xml",
            "document_type": "epNotificationEF2020",
            "title": f"Selection fixture {number}",
            "published_at": CLOCK,
            "deadline": None,
            "nmck_rub": None,
            "lot_parse_status": "UNKNOWN",
            "lot_items": [],
            "attachments": [],
            "ingested_at": CLOCK,
        }

    connection.execute(
        insert(eis_notice_versions),
        [
            notice(91_000_000_000_000_000_001, keys["notice-only"]),
            notice(91_000_000_000_000_000_002, keys["both"]),
            notice(91_000_000_000_000_000_003, keys["duplicate"]),
            notice(91_000_000_000_000_000_004, keys["duplicate"]),
            notice(91_000_000_000_000_000_005, foreign_key),
        ],
    )

    def event(document_id: str, key: tuple[str, ...]) -> dict[str, object]:
        return {
            "company_id": key[0],
            "document_type": "epNotificationCancel",
            "document_id": document_id,
            "purchase_number": "9100000000000000001",
            "published_at": CLOCK,
            "recovery_stage": None,
            "xml_sha256": hashlib.sha256(document_id.encode()).hexdigest(),
            "source_member": document_id + ".xml",
            "locator": "synthetic:" + document_id,
            "parser_version": "eis-procedure-event-v1",
            "window_key": key[1],
            "response_sha256": key[2],
            "archive_sha256": key[3],
            "ingested_at": CLOCK,
        }

    connection.execute(
        insert(eis_procedure_events),
        [
            event("selection-event-only", keys["event-only"]),
            event("selection-both", keys["both"]),
            event("selection-foreign", foreign_key),
        ],
    )
    return {**keys, "foreign": foreign_key}


def _large_attachment_metadata(group: int, index: int) -> bytes:
    entries = []
    for ordinal in range(LARGE_PROJECTION_ATTACHMENTS):
        uid = f"{group * 100_000 + index * 100 + ordinal + 1:032X}"
        filename = (
            f"bounded-{group}-{index}-{ordinal}-"
            + "n" * LARGE_PROJECTION_FILENAME_PADDING
            + ".pdf"
        )
        entries.append(
            "<ep:attachmentInfo>"
            f"<ep:publishedContentId>{uid}</ep:publishedContentId>"
            f"<ep:fileName>{filename}</ep:fileName>"
            f"<ep:fileSize>{ordinal + 1}</ep:fileSize>"
            "<ep:url>https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/"
            f"file.html?uid={uid}</ep:url>"
            "<ep:docKindInfo><ep:code>POD</ep:code></ep:docKindInfo>"
            "</ep:attachmentInfo>"
        )
    return ("<ep:attachmentsInfo>" + "".join(entries) + "</ep:attachmentsInfo>").encode()


def _large_projection_members(group: int) -> tuple[tuple[str, bytes], ...]:
    def content(index: int) -> bytes:
        source = notice(
            document_id=str(70_000_000 + group * 1_000 + index),
            title=(
                f"bounded-{group}-{index}-"
                + "x" * LARGE_PROJECTION_TITLE_PADDING
            ),
        )
        source = source.replace(
            b"<ep:notificationInfo>",
            _large_attachment_metadata(group, index) + b"<ep:notificationInfo>",
        )
        return source.replace(
            NUMBER.encode(),
            str(8_000_000_000_000_000_000 + group * 1_000 + index).encode(),
        )

    return tuple(
        (
            f"large-{group}-{index:04d}.xml",
            content(index),
        )
        for index in range(LARGE_PROJECTION_MEMBERS)
    )


def _v3_large_223_snapshot(
    raw_snapshot: dict[str, object], purchase_number: str, xml_sha256: str
) -> Eis223NoticeSnapshot:
    """Synthetic model-valid stress data, not parsed XML or official origin evidence."""
    original = Eis223NoticeSnapshot.model_validate(raw_snapshot)
    snapshot = original.model_dump(mode="json")

    def rebind(value: object) -> None:
        if isinstance(value, dict):
            if "document_id" in value:
                assert value["document_id"] == original.xml_sha256
                value["document_id"] = xml_sha256
            for child in value.values():
                rebind(child)
        elif isinstance(value, list):
            for child in value:
                rebind(child)

    rebind(snapshot)
    snapshot["purchase_number"] = purchase_number
    snapshot["version_number"] = 1
    snapshot["xml_sha256"] = xml_sha256
    snapshot["source_member"] = "capture-v3-large-ordinary.xml"
    base = f"{original.document_type}/p:body/p:item/p:{original.document_type}Data"
    attachments = []
    for index in range(6_500):
        attachment = {}
        for name, element in (
            ("filename", "fileName"), ("content_uid", "contentUid"), ("url", "url")
        ):
            # Retain the existing tiny synthetic text; use the exact field locator.
            fact = dict(snapshot["title"])
            fact["provenance"] = {
                **fact["provenance"],
                "locator": base + f"/p:attachments/t:document[{index + 1}]/t:{element}",
            }
            attachment[name] = fact
        attachment["not_placement_raw"] = None
        attachments.append(attachment)
    snapshot["attachments"] = attachments
    snapshot["manifest_count"] = {
        **snapshot["manifest_count"], "value": str(len(attachments)), "raw": str(len(attachments))
    }
    snapshot["manifest_status"] = "COUNT_CONSISTENT"
    return Eis223NoticeSnapshot.model_validate(snapshot)


def _insert_v3_large_ordinary_rows(connection: Connection) -> list[tuple[str, tuple[object, ...]]]:
    cohort: list[tuple[str, tuple[object, ...]]] = []
    definitions = (
        ("eis_notice_versions", "9800000000000000001"),
        ("eis_223_notice_versions", "98000000002"),
    )
    for relation, purchase_number in definitions:
        table = capture_module._table(relation)
        source = connection.execute(
            select(table)
            .where(table.c.company_id == TENANT)
            .order_by(*table.primary_key.columns)
            .limit(1)
        ).mappings().one()
        row = dict(source)
        row["purchase_number"] = purchase_number
        row["version_number"] = 1
        row["xml_sha256"] = hashlib.sha256(relation.encode()).hexdigest()
        row["ingested_at"] = CLOCK
        if relation == "eis_notice_versions":
            row["source_member"] = "capture-v3-large-ordinary.xml"
            row["title"] = "V3 large ordinary row"
            row["attachments"] = [
                {
                    "content_uid": f"capture-v3-{index}",
                    "filename": f"capture-v3-{index}.pdf",
                    "byte_count": 1,
                    "url": f"https://example.invalid/capture-v3/{index}",
                    "kind_code": "POD",
                    "locator": f"synthetic:capture-v3:{index}",
                }
                for index in range(32_000)
            ]
            snapshot_fields = {
                name: row[name] for name in EisNoticeSnapshot.__dataclass_fields__
            }
            TypeAdapter(EisNoticeSnapshot).validate_python(snapshot_fields)
        else:
            raw_snapshot = row["snapshot"]
            assert isinstance(raw_snapshot, dict)
            validated = _v3_large_223_snapshot(raw_snapshot, purchase_number, row["xml_sha256"])
            row["snapshot"] = validated.model_dump(mode="json")
            row["search_keys"] = _notice_keys(validated)
        connection.execute(insert(table).values(**row))
        cohort.append((relation, (TENANT, purchase_number, 1)))
    return cohort


def _insert_v3_seed_after_legacy_capture(
    connection: Connection,
    seed_nonce: str | None,
    *,
    legacy_capture_verified: bool,
) -> list[tuple[str, tuple[object, ...]]]:
    if seed_nonce is None:
        return []
    if not legacy_capture_verified:
        raise AssertionError("V3_SEED_BEFORE_LEGACY_CAPTURE")
    return _insert_v3_large_ordinary_rows(connection)


def _v3_seed_readback(
    storage: PostgresStorage,
    plan: CapturePlanV3,
    nonce: str,
    cohort: list[tuple[str, tuple[object, ...]]],
) -> dict[str, object]:
    assert plan.tenant == TENANT
    assert plan.schema_revision == "20261006_12"
    assert len(plan.relations) == 25
    assert 4 <= len(cohort) <= 32
    assert len(cohort) == len(set(cohort))
    assert sum(relation == "audit_events" for relation, _ in cohort) >= 2
    assert sum(relation != "audit_events" for relation, _ in cohort) >= 2
    assert all(relation in V3_FRAGMENT_RELATIONS for relation, _ in cohort)
    relation_counts: list[dict[str, object]] = []
    large_rows: list[dict[str, object]] = []
    with storage.transaction(TENANT, consistent_read=True) as connection:
        runtime = connection.execute(
            text(
                "SELECT current_database() AS database, current_user AS role, "
                "current_setting('transaction_read_only') AS read_only, "
                "current_setting('transaction_isolation') AS isolation, "
                "current_setting('app.company_id') AS tenant, "
                "current_setting('row_security') AS row_security, "
                "r.rolsuper AS superuser, r.rolbypassrls AS bypass_rls, "
                "transaction_timestamp() AS transaction_timestamp, "
                "txid_current_snapshot()::text AS snapshot_id "
                "FROM pg_roles r WHERE r.rolname=current_user"
            )
        ).mappings().one()
        assert runtime["read_only"] == "on"
        assert runtime["isolation"] == "repeatable read"
        assert runtime["tenant"] == TENANT
        assert runtime["row_security"] == "on"
        assert runtime["superuser"] is False
        assert runtime["bypass_rls"] is False
        assert isinstance(runtime["database"], str)
        assert re.fullmatch(r"procurement_eis_test_[a-z0-9_]+", runtime["database"])
        assert isinstance(runtime["role"], str) and 1 <= len(runtime["role"]) <= 128
        assert runtime["role"] != "procurement_owner"
        assert isinstance(runtime["snapshot_id"], str)
        assert 1 <= len(runtime["snapshot_id"]) <= 200
        for spec in sorted(plan.relations, key=lambda item: item.name):
            source_count, _ = _source_count_and_max_row_bytes(
                connection, _selection(spec, TENANT), spec
            )
            relation_counts.append({"name": spec.name, "source_count": source_count})
        specs = {spec.name: spec for spec in plan.relations}
        for relation, primary_key in cohort:
            spec = specs[relation]
            table = capture_module._table(relation)
            predicate = [
                table.c[name] == value
                for name, value in zip(spec.primary_key, primary_key, strict=True)
            ]
            raw = connection.execute(_selection(spec, TENANT).where(*predicate)).mappings().one()
            raw_bytes = sum(capture_module._raw_size(raw[column.name]) for column in spec.columns)
            normalized = capture_module._normalize_row(spec, raw)
            digest = hashlib.sha256()
            encoded_bytes = 0
            for chunk in iter_encoded_row(spec, normalized):
                encoded_bytes += len(chunk)
                assert encoded_bytes <= plan.fragmentation.encoded_row_bytes
                digest.update(chunk)
            raw_cap = (
                plan.fragmentation.audit_raw_row_bytes
                if relation == "audit_events"
                else plan.fragmentation.ordinary_raw_row_bytes
            )
            assert 1 <= raw_bytes <= raw_cap
            assert (
                plan.fragmentation.fragment_bytes
                < encoded_bytes
                <= plan.fragmentation.encoded_row_bytes
            )
            columns = {column.name: column for column in spec.columns}
            typed_key = tuple(
                encode_value(normalized[name], columns[name].kind) for name in spec.primary_key
            )
            assert len(typed_key) <= 16
            for name, value in zip(spec.primary_key, primary_key, strict=True):
                kind = columns[name].kind
                assert kind in {"TEXT", "INTEGER"}
                if kind == "TEXT":
                    assert isinstance(value, str)
                    assert len(value.encode("utf-8")) <= 2_048
                else:
                    assert isinstance(value, int) and not isinstance(value, bool)
            large_rows.append(
                {
                    "relation": relation,
                    "typed_primary_key": typed_key,
                    "sql_raw_bytes": raw_bytes,
                    "canonical_encoded_bytes": encoded_bytes,
                    "canonical_encoded_sha256": digest.hexdigest(),
                }
            )
    transaction_timestamp = cast(datetime, runtime["transaction_timestamp"])
    assert transaction_timestamp.utcoffset() is not None
    large_rows.sort(
        key=lambda item: (
            cast(str, item["relation"]),
            canonical_bytes(item["typed_primary_key"]),
        )
    )
    assert 4 <= len(large_rows) <= 32
    unique_keys = {
        (item["relation"], canonical_bytes(item["typed_primary_key"]))
        for item in large_rows
    }
    assert len(unique_keys) == len(large_rows)
    assert [item["name"] for item in relation_counts] == sorted(
        item["name"] for item in relation_counts
    )
    return {
        "version": "eis-capture-v3-pg-seed-receipt-v1",
        "status": "SEED_READY",
        "diagnostic_nonce": nonce,
        "capture_id": "pg-v3-layout-" + nonce,
        "tenant": TENANT,
        "schema_revision": "20261006_12",
        "seed_retained": True,
        "fixture_writers_joined": True,
        "readback": {
            "database": runtime["database"],
            "role": runtime["role"],
            "read_only": runtime["read_only"],
            "isolation": runtime["isolation"],
            "tenant": runtime["tenant"],
            "row_security": runtime["row_security"],
            "superuser": runtime["superuser"],
            "bypass_rls": runtime["bypass_rls"],
            "transaction_timestamp": transaction_timestamp.astimezone(UTC).isoformat(),
            "snapshot_id": runtime["snapshot_id"],
        },
        "relation_counts": tuple(relation_counts),
        "large_rows": tuple(large_rows),
        "semantic_stress_requirement": "VERIFIER_MAIN_FILE_GT_67108864_BYTES",
    }


def test_large_projection_fixture_retains_bounded_titles_above_one_shard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EIS_CAPTURE_V3_SEED_EXPORT", raising=False)
    monkeypatch.delenv("EIS_CAPTURE_V3_SEED_NONCE", raising=False)
    assert _v3_seed_export_nonce() is None
    monkeypatch.setenv("EIS_CAPTURE_V3_SEED_EXPORT", "true")
    with pytest.raises(AssertionError, match="SEED_EXPORT_INVALID"):
        _v3_seed_export_nonce()
    monkeypatch.setenv("EIS_CAPTURE_V3_SEED_EXPORT", "1")
    monkeypatch.setenv("EIS_CAPTURE_V3_SEED_NONCE", "A" * 24)
    with pytest.raises(AssertionError, match="SEED_NONCE_INVALID"):
        _v3_seed_export_nonce()
    monkeypatch.setenv("EIS_CAPTURE_V3_SEED_NONCE", "a" * 24)
    assert _v3_seed_export_nonce() == "a" * 24

    seed_calls: list[object] = []

    def insert_seed(connection: object) -> list[tuple[str, tuple[object, ...]]]:
        seed_calls.append(connection)
        return [("eis_notice_versions", (TENANT, "seed", 1))]

    monkeypatch.setattr(sys.modules[__name__], "_insert_v3_large_ordinary_rows", insert_seed)
    marker = object()
    assert _insert_v3_seed_after_legacy_capture(
        marker,  # type: ignore[arg-type]
        None,
        legacy_capture_verified=False,
    ) == []
    with pytest.raises(AssertionError, match="V3_SEED_BEFORE_LEGACY_CAPTURE"):
        _insert_v3_seed_after_legacy_capture(
            marker,  # type: ignore[arg-type]
            "a" * 24,
            legacy_capture_verified=False,
        )
    assert seed_calls == []
    assert _insert_v3_seed_after_legacy_capture(
        marker,  # type: ignore[arg-type]
        "a" * 24,
        legacy_capture_verified=True,
    ) == [("eis_notice_versions", (TENANT, "seed", 1))]
    assert seed_calls == [marker]

    written = bytearray()
    interrupted = True

    def short_write(_descriptor: int, value: bytes) -> int:
        nonlocal interrupted
        if interrupted:
            interrupted = False
            raise InterruptedError
        count = min(3, len(value))
        written.extend(value[:count])
        return count

    monkeypatch.setattr(os, "write", short_write)
    _write_all(7, b"bounded-write")
    assert written == b"bounded-write"

    members = _large_projection_members(0)
    assert len(members) == LARGE_PROJECTION_MEMBERS
    assert max(len(content) for _, content in members) < 64 * 1024
    archives = (bundle(*members),)
    diagnosis = diagnose_notice_conflicts(archives, "capture-large-fixture")
    prepared = prepare_notice_projection(archives, diagnosis)
    snapshots = [item.snapshot for item in prepared.candidates]
    assert len(snapshots) == LARGE_PROJECTION_MEMBERS
    assert all(snapshot is not None for snapshot in snapshots)
    snapshot_bytes = sum(
        _snapshot_payload_bytes(snapshot)
        for snapshot in snapshots
        if snapshot is not None
    )
    assert 8 * 1024**2 < snapshot_bytes < 16 * 1024**2


def _rebound_test_plan(source: Path, destination: Path) -> Path:
    raw = json.loads(source.read_text(encoding="utf-8"))
    # Rebind only this synthetic copy; production plans keep their immutable pins.
    paths = tuple(pin["path"] for pin in raw["source_pins"])
    assert len(paths) == len(set(paths)) == 18
    for pin in raw["source_pins"]:
        pin["sha256"] = hashlib.sha256((ROOT / pin["path"]).read_bytes()).hexdigest()
    assert tuple(pin["path"] for pin in raw["source_pins"]) == paths
    destination.write_bytes(canonical_bytes(raw) + b"\n")
    return destination


_MEMORY_CHILD = r"""
import json
import resource
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from procurement.sources.eis_search_capture import verify_capture_package
from procurement.storage.eis_search_capture import build_storage, capture_search_projection

mode, plan_raw, package_raw, report_raw = sys.argv[1:5]
plan = Path(plan_raw)
package = Path(package_raw)
if mode == "capture":
    runtime = json.loads(Path(sys.argv[5]).read_text(encoding="utf-8"))
    result = capture_search_projection(
        build_storage(__import__("os").environ["DATABASE_URL"]),
        plan,
        package,
        capture_id="pg-v2-large-rows",
        clock=datetime.fromisoformat("2026-10-07T12:00:00+00:00"),
        synthetic_clock=True,
        external_runtime=runtime,
        disk_usage=lambda _: SimpleNamespace(free=6 * 1024**3),
    )
    status = result.status
    raw_width_validation = None
    source_raw_width_attestation = None
else:
    verification = verify_capture_package(package, plan)
    status = verification.status
    raw_width_validation = getattr(verification, "raw_width_validation", None)
    source_raw_width_attestation = getattr(
        verification, "source_raw_width_attestation", None
    )
peak_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
Path(report_raw).write_text(
    json.dumps(
        {
            "mode": mode,
            "peak_rss_bytes": peak_bytes,
            "raw_width_validation": raw_width_validation,
            "source_raw_width_attestation": source_raw_width_attestation,
            "status": status,
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
raise SystemExit(0 if status in {"COMPLETE", "CAPTURE_CONTENT_VERIFIED"} else 2)
"""


def _run_measured_child(
    mode: str,
    plan: Path,
    package: Path,
    report: Path,
    *,
    runtime: Path | None = None,
) -> dict[str, object]:
    command = [
        sys.executable,
        "-B",
        "-c",
        _MEMORY_CHILD,
        mode,
        str(plan),
        str(package),
        str(report),
    ]
    if runtime is not None:
        command.append(str(runtime))
    child_environment = os.environ.copy()
    child_environment.pop("DATABASE_ADMIN_URL", None)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=child_environment,
        capture_output=True,
        check=False,
        timeout=600,
    )
    assert completed.returncode == 0, f"{mode} child failed with code {completed.returncode}"
    loaded: object = json.loads(report.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict) and all(isinstance(key, str) for key in loaded)
    value = {str(key): item for key, item in loaded.items()}
    assert 0 < int(value["peak_rss_bytes"]) < MEMORY_LIMIT_BYTES
    return value


def _gate_urls() -> tuple[str, str]:
    app_url = os.environ.get("DATABASE_URL")
    admin_url = os.environ.get("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("PostgreSQL integration gate requires DATABASE_URL and DATABASE_ADMIN_URL")
    app = make_url(app_url)
    admin = make_url(admin_url)
    if (
        app.database != admin.database
        or not app.database
        or "procurement_eis_test_" not in app.database
    ):
        pytest.fail("capture integration requires one isolated procurement_eis_test_* database")
    return app_url, admin_url


def _external_runtime() -> dict[str, str]:
    return {
        "deployed_source_sha256": "a" * 64,
        "image_id": "sha256:" + "b" * 64,
        "lxml_version": "test",
        "psycopg_version": "test",
        "pydantic_version": "test",
        "python_version": "test",
        "repository_commit": "9dbc82b",
        "snowballstemmer_version": "test",
        "sqlalchemy_version": "test",
        "uv_lock_sha256": "c" * 64,
    }


def test_real_pg_capture_is_tenant_scoped_snapshot_and_offline_verifiable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
) -> None:
    seed_nonce = _v3_seed_export_nonce()
    seed_receipt: dict[str, object] | None = None
    app_url, admin_url = _gate_urls()
    test_plan_path = _rebound_test_plan(PLAN_PATH, tmp_path / "capture-plan-v1.json")
    production_plan_path = _rebound_test_plan(
        PRODUCTION_PLAN_PATH, tmp_path / "capture-plan-production-v1.json"
    )
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", admin_url.replace("%", "%%"))
    command.upgrade(config, "head")
    admin_engine = create_engine(admin_url, pool_pre_ping=True)
    app_engine = create_engine(app_url, pool_pre_ping=True)
    storage = PostgresStorage(app_engine)
    shadow_schema: str | None = None
    original_schema_revision: str | None = None
    try:
        with admin_engine.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == "procurement_owner"
        plan, _ = load_capture_plan(test_plan_path)
        # Frozen capture plans exercise legacy revisions against the full current schema.
        # Change only this disposable fixture's metadata, then restore its actual head.
        # This validates the frozen schema-name contract, not current-head plan compatibility.
        with admin_engine.begin() as connection:
            heads = tuple(
                connection.scalars(text("SELECT version_num FROM public.alembic_version"))
            )
            assert heads == (ScriptDirectory.from_config(config).get_current_head(),)
            updated = connection.execute(
                text(
                    "UPDATE public.alembic_version SET version_num = :fixture "
                    "WHERE version_num = :actual"
                ),
                {"fixture": plan.schema_revision, "actual": heads[0]},
            )
            assert updated.rowcount == 1
            original_schema_revision = heads[0]
        with admin_engine.begin() as owner_connection:
            owner_connection.execute(
                text("ALTER TABLE public.eis_sync_targets NO FORCE ROW LEVEL SECURITY")
            )
            try:
                with pytest.raises(CaptureCollectionError, match="SCHEMA_RLS_DRIFT"):
                    _validate_schema(owner_connection, plan)
            finally:
                owner_connection.execute(
                    text("ALTER TABLE public.eis_sync_targets FORCE ROW LEVEL SECURITY")
                )
        with app_engine.connect() as app_connection:
            app_user = str(app_connection.scalar(text("SELECT current_user")))
        assert app_user != "procurement_owner"
        preparer = admin_engine.dialect.identifier_preparer
        quoted_user = preparer.quote(app_user)
        shadow_schema = quoted_user
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "GRANT SELECT (version_num) ON TABLE "
                    f"public.alembic_version TO {quoted_user}"
                )
            )
            connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted_user} CASCADE"))
            connection.execute(text(f"CREATE SCHEMA {quoted_user} AUTHORIZATION {quoted_user}"))
            connection.execute(
                text(
                    f"CREATE TABLE {quoted_user}.eis_sync_targets "
                    "(company_id text, window_key text, planned_by text, "
                    "planned_at timestamptz, coverage text)"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {quoted_user}.eis_sync_targets VALUES "
                    "(:tenant, 'shadow-row', 'shadow', :clock, 'UNKNOWN')"
                ),
                {"tenant": TENANT, "clock": CLOCK},
            )
            connection.execute(
                text(f"CREATE TABLE {quoted_user}.alembic_version (version_num text NOT NULL)")
            )
            connection.execute(
                text(f"INSERT INTO {quoted_user}.alembic_version VALUES ('WRONG_SHADOW')")
            )
        with app_engine.connect() as app_connection:
            assert app_connection.scalar(
                text("SELECT to_regclass('eis_sync_targets') = to_regclass(:qualified)"),
                {"qualified": f'{quoted_user}.eis_sync_targets'},
            )
        production_plan, _ = load_capture_plan(production_plan_path)
        production_package = tmp_path / "capture-package-production-revision"
        try:
            with admin_engine.begin() as connection:
                updated = connection.execute(
                    text(
                        "UPDATE public.alembic_version SET version_num = '20261006_08' "
                        "WHERE version_num = '20261006_12'"
                    )
                )
                assert updated.rowcount == 1
            production_result = capture_search_projection(
                build_storage(app_url),
                production_plan_path,
                production_package,
                capture_id="pg-production-revision",
                clock=CLOCK,
                synthetic_clock=True,
                external_runtime=_external_runtime(),
                disk_usage=lambda _: SimpleNamespace(free=6 * 1024**3),
            )
            assert isinstance(production_result, CaptureManifest), (
                production_result.model_dump(mode="json")
            )
            assert production_result.runtime.schema_revision == production_plan.schema_revision
            production_report = verify_capture_package(
                production_package, production_plan_path
            )
            assert production_report.status == "CAPTURE_CONTENT_VERIFIED"
        finally:
            with admin_engine.begin() as connection:
                restored = connection.execute(
                    text(
                        "UPDATE public.alembic_version SET version_num = '20261006_12' "
                        "WHERE version_num = '20261006_08'"
                    )
                )
                assert restored.rowcount == 1
        with admin_engine.begin() as connection:
            connection.execute(
                insert(eis_sync_targets),
                [
                    {
                        "company_id": TENANT,
                        "window_key": "before-snapshot",
                        "planned_by": "тест capture",
                        "planned_at": CLOCK,
                        "coverage": "UNKNOWN",
                    },
                    {
                        "company_id": OTHER_TENANT,
                        "window_key": "foreign-before-snapshot",
                        "planned_by": "foreign",
                        "planned_at": CLOCK,
                        "coverage": "UNKNOWN",
                    },
                ],
            )
        receipt, archives, _ = prepare(
            storage,
            TENANT,
            tmp_path / "retained",
            members=(("base.xml", notice(title="Бумага base")),),
        )
        project_retained_notice_variants(
            storage, TENANT, receipt.receipt_id, archives, actor_id="capture-test"
        )
        prepare(
            storage,
            TENANT,
            tmp_path / "retained",
            day="30",
            response="d",
            members=(("hold.xml", notice(title="Бумага conflict")),),
        )
        assert read_notice_source_hold(storage, TENANT, NUMBER, 1).status == "HOLD"
        ingest_notice223_window(
            storage,
            TENANT,
            window223(zip_bytes223((("notice.xml", xml223()),)), response="7" * 64),
            actor_id="capture-test",
            now=CLOCK,
        )
        with admin_engine.begin() as connection:
            window = connection.execute(
                select(
                    eis_223_windows.c.window_key,
                    eis_223_windows.c.response_sha256,
                ).where(eis_223_windows.c.company_id == TENANT)
            ).first()
            assert window is not None
            unused_content = b"unused"
            unused_sha = hashlib.sha256(unused_content).hexdigest()
            connection.execute(
                insert(eis_223_blobs).values(
                    company_id=TENANT,
                    archive_sha256=unused_sha,
                    content=unused_content,
                )
            )
            connection.execute(
                insert(eis_223_archive_sources).values(
                    company_id=TENANT,
                    window_key=window.window_key,
                    response_sha256=window.response_sha256,
                    archive_sha256=unused_sha,
                    source_url="synthetic:unreferenced",
                )
            )
            archive = connection.execute(
                select(
                    eis_feed_archives.c.window_key,
                    eis_feed_archives.c.response_sha256,
                    eis_feed_archives.c.archive_sha256,
                )
                .where(eis_feed_archives.c.company_id == TENANT)
                .limit(1)
            ).one()
            connection.execute(
                insert(eis_procedure_events).values(
                    company_id=TENANT,
                    document_type="epNotificationCancel",
                    document_id="before-event",
                    purchase_number=NUMBER,
                    published_at=CLOCK,
                    recovery_stage=None,
                    xml_sha256="8" * 64,
                    source_member="event-before.xml",
                    locator="synthetic:event-before",
                    parser_version="eis-procedure-event-v1",
                    window_key=archive.window_key,
                    response_sha256=archive.response_sha256,
                    archive_sha256=archive.archive_sha256,
                    ingested_at=CLOCK,
                )
            )
        original = capture_module._capture_relations
        inserted = False

        def insert_after_snapshot(
            connection: Connection,
            plan: CapturePlanAny,
            root: Path,
            clock: datetime,
            budget: _PackageBudget,
            current_database: Any,
        ) -> tuple[
            tuple[RelationDescriptor | RelationDescriptorV2 | RelationDescriptorV3, ...],
            dict[str, int],
            int | None,
        ]:
            nonlocal inserted
            if not inserted:
                inserted = True
                with admin_engine.begin() as later_connection:
                    archive = later_connection.execute(
                        select(
                            eis_feed_archives.c.window_key,
                            eis_feed_archives.c.response_sha256,
                            eis_feed_archives.c.archive_sha256,
                        )
                        .where(eis_feed_archives.c.company_id == TENANT)
                        .limit(1)
                    ).one()
                    later_connection.execute(
                        insert(eis_sync_targets).values(
                            company_id=TENANT,
                            window_key="after-snapshot",
                            planned_by="concurrent",
                            planned_at=CLOCK,
                            coverage="UNKNOWN",
                        )
                    )
                    later_connection.execute(
                        insert(eis_notice_versions).values(
                            company_id=TENANT,
                            purchase_number=NUMBER,
                            version_number=2,
                            xml_sha256="9" * 64,
                            window_key=archive.window_key,
                            response_sha256=archive.response_sha256,
                            archive_sha256=archive.archive_sha256,
                            source_member="notice-after.xml",
                            document_type="epNotificationEF2020",
                            title="Later notice",
                            published_at=CLOCK,
                            deadline=None,
                            nmck_rub=None,
                            lot_parse_status="UNKNOWN",
                            lot_items=[],
                            attachments=[],
                            ingested_at=CLOCK,
                        )
                    )
                    later_connection.execute(
                        insert(eis_procedure_events).values(
                            company_id=TENANT,
                            document_type="epNotificationCancel",
                            document_id="after-event",
                            purchase_number=NUMBER,
                            published_at=CLOCK,
                            recovery_stage=None,
                            xml_sha256="a" * 64,
                            source_member="event-after.xml",
                            locator="synthetic:event-after",
                            parser_version="eis-procedure-event-v1",
                            window_key=archive.window_key,
                            response_sha256=archive.response_sha256,
                            archive_sha256=archive.archive_sha256,
                            ingested_at=CLOCK,
                        )
                    )
                prepare(
                    storage,
                    TENANT,
                    tmp_path / "retained",
                    day="31",
                    response="e",
                    members=(("later-hold.xml", notice(title="Later hold")),),
                )
                raw223 = xml223().replace(b"<p:version>2</p:version>", b"<p:version>3</p:version>")
                ingest_notice223_window(
                    storage,
                    TENANT,
                    window223(zip_bytes223((("later.xml", raw223),)), response="f" * 64),
                    actor_id="capture-later",
                    now=CLOCK,
                )
            return original(connection, plan, root, clock, budget, current_database)

        monkeypatch.setattr(capture_module, "_capture_relations", insert_after_snapshot)
        package = tmp_path / "capture-package"
        result = capture_search_projection(
            build_storage(app_url),
            test_plan_path,
            package,
            capture_id="pg-synthetic",
            clock=CLOCK,
            synthetic_clock=True,
            external_runtime=_external_runtime(),
            disk_usage=lambda _: SimpleNamespace(free=6 * 1024**3),
        )
        assert isinstance(result, CaptureManifest), result.model_dump(mode="json")
        assert result.runtime.schema_revision == plan.schema_revision
        assert str(result.runtime.schema_revision) != "WRONG_SHADOW"
        report = verify_capture_package(package, test_plan_path)
        assert report.status == "CAPTURE_CONTENT_VERIFIED"
        assert report.capture_origin_trust == "UNKNOWN"
        spec = next(item for item in plan.relations if item.name == "eis_sync_targets")
        descriptor = next(item for item in result.relations if item.name == spec.name)
        captured = [
            row
            for shard in descriptor.shards
            for row in iter_encoded_rows(package / shard.path, spec, plan.limits.shard_bytes)
        ]
        assert [(row["window_key"], row["planned_by"]) for row in captured] == [
            ("before-snapshot", "тест capture")
        ]
        by_relation = {item.name: item for item in result.relations}

        def decoded(name: str) -> list[dict[str, object]]:
            relation_spec = next(item for item in plan.relations if item.name == name)
            return [
                row
                for shard in by_relation[name].shards
                for row in iter_encoded_rows(
                    package / shard.path, relation_spec, plan.limits.shard_bytes
                )
            ]

        assert [row["version_number"] for row in decoded("eis_notice_versions")] == [1]
        assert len(decoded("eis_223_notice_versions")) == 1
        assert [row["document_id"] for row in decoded("eis_procedure_events")] == ["before-event"]
        assert len(decoded("eis_notice_variant_receipts")) == 2
        assert len(decoded("eis_notice_variants")) >= 2
        assert all(
            row["archive_sha256"] != unused_sha for row in decoded("eis_223_archive_sources")
        )
        assert all(row["archive_sha256"] != unused_sha for row in decoded("eis_223_blobs"))
        with admin_engine.connect() as connection:
            assert (
                connection.scalar(
                    select(eis_sync_targets.c.window_key).where(
                        eis_sync_targets.c.company_id == TENANT,
                        eis_sync_targets.c.window_key == "after-snapshot",
                    )
                )
                == "after-snapshot"
            )

        with admin_engine.begin() as connection:
            archive_selection_keys = _insert_feed_archive_selection_fixture(connection)
        v2_test_plan_path = _rebound_test_plan(
            PLAN_V2_PATH, tmp_path / "capture-plan-v2.json"
        )
        v2_plan_for_selection, _ = load_capture_plan(v2_test_plan_path)
        archive_spec = next(
            item
            for item in v2_plan_for_selection.relations
            if item.name == "eis_feed_archives"
        )
        archive_key_columns = (
            "company_id",
            "window_key",
            "response_sha256",
            "archive_sha256",
        )
        with storage.transaction(TENANT, consistent_read=True) as connection:
            archive_table = capture_module._table("eis_feed_archives")
            old_selection = capture_module._base_select(archive_table, archive_spec, TENANT).where(
                or_(
                    *(
                        capture_module._matches(
                            archive_table,
                            capture_module._table(child),
                            archive_key_columns,
                            TENANT,
                        )
                        for child in ("eis_notice_versions", "eis_procedure_events")
                    )
                )
            )
            new_selection = _selection(archive_spec, TENANT)

            def selected_keys(statement: Any) -> Any:
                selected = statement.order_by(None).subquery()
                return select(*(selected.c[name] for name in archive_key_columns))

            old_keys = selected_keys(old_selection)
            new_keys = selected_keys(new_selection)
            assert connection.scalar(
                select(func.count()).select_from(old_keys.except_(new_keys).subquery())
            ) == 0
            assert connection.scalar(
                select(func.count()).select_from(new_keys.except_(old_keys).subquery())
            ) == 0
            grouped = new_keys.subquery()
            duplicates = connection.execute(
                select(*(grouped.c[name] for name in archive_key_columns), func.count())
                .group_by(*(grouped.c[name] for name in archive_key_columns))
                .having(func.count() != 1)
            ).all()
            assert duplicates == []
            selected_fixture_keys = {
                tuple(row)
                for row in connection.execute(new_keys)
                if row.window_key == archive_selection_keys["notice-only"][1]
            }
            assert selected_fixture_keys == {
                archive_selection_keys["notice-only"],
                archive_selection_keys["event-only"],
                archive_selection_keys["both"],
                archive_selection_keys["duplicate"],
            }
            assert archive_selection_keys["orphan"] not in selected_fixture_keys
            assert archive_selection_keys["single-component-mismatch"] not in selected_fixture_keys
            assert archive_selection_keys["foreign"] not in selected_fixture_keys
            compiled_selection = new_selection.compile(
                dialect=connection.dialect,
                compile_kwargs={"literal_binds": True},
            )
            explain = connection.scalar(
                text("EXPLAIN (FORMAT JSON, COSTS TRUE) " + str(compiled_selection))
            )
            explain_text = json.dumps(explain, ensure_ascii=True, sort_keys=True)
            assert "SubPlan" not in explain_text
            assert "eis_notice_versions" in explain_text
            assert "eis_procedure_events" in explain_text

        # Build several projection batches from many individually small variants.
        # Their exact aggregate projection audit bases exceed one physical shard,
        # matching the observed production shape without creating an oversized
        # row in any non-audit relation.
        large_audit_event_ids: list[str] = []
        for group in range(LARGE_PROJECTION_GROUPS_V3):
            members = _large_projection_members(group)
            receipt, archives, _ = prepare(
                storage,
                TENANT,
                tmp_path / "large-retained",
                members=members,
                day=str(24 + group),
                response=str(group + 1),
            )
            projection = project_retained_notice_variants(
                storage,
                TENANT,
                receipt.receipt_id,
                archives,
                actor_id="capture-large-test",
            )
            large_audit_event_ids.append(projection.audit_event_id)

        v2_plan, _ = load_capture_plan(v2_test_plan_path)
        assert isinstance(v2_plan, CapturePlanV2)
        audit_spec = next(item for item in v2_plan.relations if item.name == "audit_events")
        with storage.transaction(TENANT, consistent_read=True) as connection:
            selected_audit = _selection(audit_spec, TENANT).order_by(None).subquery()
            audit_row_bytes: Any = literal(0)
            for column in audit_spec.columns:
                audit_row_bytes += func.coalesce(
                    func.octet_length(sql_cast(selected_audit.c[column.name], Text)), 1
                )
            oversized_count, oversized_min_bytes, oversized_max_bytes = connection.execute(
                select(
                    func.count(),
                    func.min(audit_row_bytes),
                    func.max(audit_row_bytes),
                )
                .select_from(selected_audit)
                .where(
                    selected_audit.c.event_id.in_(tuple(large_audit_event_ids)),
                    audit_row_bytes > v2_plan.limits.shard_bytes,
                )
            ).one()
            assert (
                int(oversized_count)
                == len(large_audit_event_ids)
                == LARGE_PROJECTION_GROUPS_V3
            )
            assert int(oversized_min_bytes) > v2_plan.limits.shard_bytes
            assert int(oversized_max_bytes) <= v2_plan.limits.audit_raw_row_bytes
            audit_source_rows, audit_raw_max_bytes = _source_count_and_max_row_bytes(
                connection,
                _selection(audit_spec, TENANT),
                audit_spec,
            )
        audit_prefetch_rows = min(
            v2_plan.limits.batch_rows,
            v2_plan.limits.batch_bytes // max(1, audit_raw_max_bytes),
        )
        record_property("capture_v2_fixture_oversized_audit_rows", int(oversized_count))
        record_property("capture_v2_fixture_oversized_min_bytes", int(oversized_min_bytes))
        record_property("capture_v2_fixture_oversized_max_bytes", int(oversized_max_bytes))

        runtime_path = tmp_path / "runtime-identity.json"
        runtime_path.write_bytes(canonical_bytes(_external_runtime()) + b"\n")
        v2_package = tmp_path / "capture-package-v2"
        collector_memory = _run_measured_child(
            "capture",
            v2_test_plan_path,
            v2_package,
            tmp_path / "collector-memory.json",
            runtime=runtime_path,
        )
        verifier_memory = _run_measured_child(
            "verify",
            v2_test_plan_path,
            v2_package,
            tmp_path / "verifier-memory.json",
        )
        v2_manifest = CaptureManifestV2.model_validate_json(
            (v2_package / "manifest.json").read_bytes()
        )
        audit_descriptor = next(
            item for item in v2_manifest.relations if item.name == "audit_events"
        )
        assert len(audit_descriptor.fragmented_rows) >= 3
        assert audit_descriptor.rows == (
            sum(item.rows for item in audit_descriptor.shards)
            + len(audit_descriptor.fragmented_rows)
        )
        assert collector_memory["status"] == "COMPLETE"
        assert verifier_memory["status"] == "CAPTURE_CONTENT_VERIFIED"
        assert verifier_memory["raw_width_validation"] == "DECODED_LOWER_BOUND_ONLY"
        assert verifier_memory["source_raw_width_attestation"] == "UNKNOWN"
        encoded_max_bytes = max(
            item.whole_bytes for item in audit_descriptor.fragmented_rows
        )
        memory_evidence = {
            "phase": "COLLECTOR_AND_OFFLINE_VERIFIER",
            "units": "bytes",
            "container_limit_bytes": MEMORY_LIMIT_BYTES,
            "collector_peak_rss_bytes": collector_memory["peak_rss_bytes"],
            "verifier_peak_rss_bytes": verifier_memory["peak_rss_bytes"],
            "audit_source_rows": audit_source_rows,
            "fragmented_audit_rows": len(audit_descriptor.fragmented_rows),
            "audit_raw_max_bytes": audit_raw_max_bytes,
            "audit_encoded_max_bytes": encoded_max_bytes,
            "audit_prefetch_rows": audit_prefetch_rows,
            "raw_width_validation": verifier_memory["raw_width_validation"],
            "source_raw_width_attestation": verifier_memory["source_raw_width_attestation"],
        }
        for key, value in memory_evidence.items():
            record_property("capture_v2_" + key, value)
        print(json.dumps({"v2_memory_evidence": memory_evidence}, sort_keys=True))

        if seed_nonce is not None:
            with admin_engine.begin() as connection:
                ordinary_cohort = _insert_v3_seed_after_legacy_capture(
                    connection,
                    seed_nonce,
                    legacy_capture_verified=True,
                )
            v3_plan, _ = load_capture_plan(PLAN_V3_PATH)
            assert isinstance(v3_plan, CapturePlanV3)
            audit_cohort: list[tuple[str, tuple[object, ...]]] = [
                ("audit_events", (TENANT, event_id))
                for event_id in large_audit_event_ids
            ]
            seed_receipt = _v3_seed_readback(
                storage,
                v3_plan,
                seed_nonce,
                ordinary_cohort + audit_cohort,
            )
    finally:
        if original_schema_revision is not None:
            with admin_engine.begin() as connection:
                restored = connection.execute(
                    text(
                        "UPDATE public.alembic_version SET version_num = :actual "
                        "WHERE version_num = :fixture"
                    ),
                    {"actual": original_schema_revision, "fixture": plan.schema_revision},
                )
                assert restored.rowcount == 1
                assert tuple(
                    connection.scalars(text("SELECT version_num FROM public.alembic_version"))
                ) == (original_schema_revision,)
        if shadow_schema is not None:
            with admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA IF EXISTS {shadow_schema} CASCADE"))
        app_engine.dispose()
        admin_engine.dispose()
    if seed_receipt is not None:
        seed_receipt["normal_cleanup_completed"] = True
        _publish_v3_seed_receipt(seed_receipt)
