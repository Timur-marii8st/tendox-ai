from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import DateTime, Numeric
from sqlalchemy.dialects import postgresql

from procurement.sources.eis_search_capture import (
    CaptureFormatError,
    CaptureManifest,
    CaptureManifestV2,
    CapturePlan,
    CapturePlanV2,
    CurrentMembership,
    FutureVersionDiagnostic,
    IncompleteCaptureV2,
    RelationDescriptor,
    RelationDescriptorV2,
    RelationSpec,
    RuntimeIdentity,
    ShardDescriptor,
    _decoded_string_utf8_lower_bound,
    canonical_bytes,
    decode_row,
    encode_row,
    iter_encoded_row,
    load_capture_plan,
    sha256_bytes,
    verify_capture_package,
)
from procurement.storage.eis_search_capture import (
    CaptureCollectionError,
    _bounded_database_call,
    _capture_relations,
    _PackageBudget,
    _publish_manifest,
    _RelationWriter,
    _RelationWriterV2,
    _runtime_identity,
    _selection,
    _validate_schema,
    capture_search_projection,
)
from procurement.storage.models import metadata

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "scripts/benchmarks/eis-search-capture-plan.v1.json"
PRODUCTION_PLAN_PATH = (
    ROOT / "scripts/benchmarks/eis-search-capture-plan.production-20261006_08.json"
)
PLAN_V2_PATH = ROOT / "scripts/benchmarks/eis-search-capture-plan.v2.json"
PRODUCTION_PLAN_V2_PATH = (
    ROOT / "scripts/benchmarks/eis-search-capture-plan.production-20261006_08.v2.json"
)
CLOCK = datetime(2026, 10, 7, 12, tzinfo=UTC)


def test_feed_archive_selection_uses_distinct_tenant_key_union_join() -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_feed_archives")
    statement = _selection(spec, "local-eis-supplier")
    compiled = str(
        statement.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        )
    )
    normalized = " ".join(compiled.split())
    assert " UNION " in normalized and " UNION ALL " not in normalized
    assert "linked_feed_archive_keys" in normalized
    assert "EXISTS" not in normalized and " OR " not in normalized
    assert normalized.count("company_id = 'local-eis-supplier'") == 3
    for column in ("company_id", "window_key", "response_sha256", "archive_sha256"):
        assert (
            f"linked_feed_archive_keys.{column} = public.eis_feed_archives.{column}"
            in normalized
        )
    assert "public.eis_feed_archives.content" not in normalized


def _sample_value(kind: str, name: str, ordinal: int) -> object:
    if name == "company_id":
        return "local-eis-supplier"
    if name == "purchase_number":
        return f"{ordinal:011d}"
    if name == "version_number":
        return ordinal
    if name == "ingested_at":
        return CLOCK - timedelta(days=1)
    if kind == "TEXT":
        return f"{name}-{ordinal}"
    if kind == "INTEGER":
        return ordinal
    if kind == "DECIMAL":
        return Decimal(f"{ordinal}.25")
    if kind == "BOOLEAN":
        return ordinal % 2 == 0
    if kind == "DATETIME":
        return CLOCK - timedelta(days=1)
    if kind == "DATE":
        return date(2026, 10, 6)
    if kind == "UUID":
        return uuid4()
    if kind == "JSON":
        return {"decimal": Decimal("1.25"), "nested": [ordinal, None]}
    if kind == "ARRAY":
        return [f"key-{ordinal}"]
    raise AssertionError(kind)


def _row(spec: RelationSpec, ordinal: int) -> dict[str, object]:
    return {
        column.name: _sample_value(column.kind, column.name, ordinal) for column in spec.columns
    }


def _runtime() -> RuntimeIdentity:
    return RuntimeIdentity(
        current_user="app",
        session_user="app",
        server_version_num="160004",
        transaction_isolation="repeatable read",
        transaction_read_only="on",
        row_security="on",
        app_company_id="local-eis-supplier",
        schema_revision="20261006_12",
        snapshot_id="1:1:",
        transaction_timestamp=CLOCK,
        clock_mode="SYNTHETIC_OVERRIDE",
        timezone="UTC",
        search_path='"$user", public',
        database_collation="C.UTF-8",
        database_ctype="C.UTF-8",
        rls_policy_sha256="1" * 64,
        role_grants_sha256="2" * 64,
        role_superuser=False,
        role_bypassrls=False,
        external={"origin": "synthetic-test"},
    )


def _membership(rows: dict[str, list[dict[str, object]]]) -> tuple[CurrentMembership, ...]:
    result = []
    for law, relation in (("44", "eis_notice_versions"), ("223", "eis_223_notice_versions")):
        current: dict[str, tuple[int, str]] = {}
        for row in rows.get(relation, []):
            ingested_at = row["ingested_at"]
            version_number = row["version_number"]
            assert isinstance(ingested_at, datetime)
            assert isinstance(version_number, int)
            if ingested_at > CLOCK:
                continue
            number = str(row["purchase_number"])
            candidate = (version_number, str(row["xml_sha256"]))
            if number not in current or candidate[0] > current[number][0]:
                current[number] = candidate
        digest = hashlib.sha256()
        for number, (version, source_sha) in sorted(current.items()):
            line = canonical_bytes([law, number, version, source_sha]) + b"\n"
            digest.update(len(line).to_bytes(8, "big") + line)
        result.append(
            CurrentMembership(
                law=law, rows=len(current), ordered_identity_sha256=digest.hexdigest()
            )
        )
    return tuple(result)


def _future(rows: dict[str, list[dict[str, object]]]) -> tuple[FutureVersionDiagnostic, ...]:
    result = []
    for law, relation in (("44", "eis_notice_versions"), ("223", "eis_223_notice_versions")):
        digest = hashlib.sha256()
        count = 0
        future = []
        for row in rows.get(relation, []):
            ingested_at = row["ingested_at"]
            assert isinstance(ingested_at, datetime)
            if ingested_at > CLOCK:
                future.append(row)

        def order_key(item: dict[str, object]) -> tuple[str, int]:
            version = item["version_number"]
            assert isinstance(version, int)
            return str(item["purchase_number"]), version

        for row in sorted(future, key=order_key):
            ingested_at = row["ingested_at"]
            assert isinstance(ingested_at, datetime)
            line = (
                canonical_bytes(
                    [
                        law,
                        row["purchase_number"],
                        row["version_number"],
                        row["xml_sha256"],
                        ingested_at.isoformat(),
                    ]
                )
                + b"\n"
            )
            digest.update(len(line).to_bytes(8, "big") + line)
            count += 1
        result.append(
            FutureVersionDiagnostic(law=law, rows=count, ordered_identity_sha256=digest.hexdigest())
        )
    return tuple(result)


def _build_package(
    root: Path,
    rows: dict[str, list[dict[str, object]]] | None = None,
    *,
    shards_per_relation: int = 1,
    plan_path: Path = PLAN_PATH,
) -> Path:
    rows = rows or {}
    plan, plan_content = load_capture_plan(plan_path)
    root.mkdir()
    (root / "relations").mkdir()
    (root / "plan.json").write_bytes(plan_content)
    descriptors: list[RelationDescriptor | RelationDescriptorV2] = []
    files = ["plan.json"]
    total_bytes = 0
    total_shards = 0
    if isinstance(plan, CapturePlanV2):
        budget = _PackageBudget(plan, time.monotonic())
        descriptors_v2: list[RelationDescriptorV2] = []
        for spec in plan.relations:
            relation_rows = rows.get(spec.name, [])
            writer = _RelationWriterV2(root, spec, budget, plan)
            for row in relation_rows:
                writer.write(row)
            descriptors_v2.append(writer.finish(len(relation_rows)))
        descriptors.extend(descriptors_v2)
        files = [
            "plan.json",
            *[
                shard.path
                for descriptor in descriptors_v2
                for shard in descriptor.shards
            ],
            *[
                fragment.path
                for descriptor in descriptors_v2
                for row in descriptor.fragmented_rows
                for fragment in row.fragments
            ],
        ]
        total_bytes = budget.payload_bytes
        total_shards = budget.shards
    else:
        for spec in plan.relations:
            relation_rows = rows.get(spec.name, [])
            chunks: list[list[dict[str, object]]] = (
                [[] for _ in range(shards_per_relation)] if relation_rows else []
            )
            for index, row in enumerate(relation_rows):
                chunks[index % shards_per_relation].append(row)
            chunks = [chunk for chunk in chunks if chunk]
            shard_descriptors = []
            relation_digest = hashlib.sha256()
            for index, chunk in enumerate(chunks, 1):
                content = b"".join(encode_row(spec, row) for row in chunk)
                ordered = hashlib.sha256()
                for line in content.splitlines(keepends=True):
                    ordered.update(len(line).to_bytes(8, "big") + line)
                    relation_digest.update(len(line).to_bytes(8, "big") + line)
                path = f"relations/{spec.name}-{index:05d}.jsonl"
                (root / path).write_bytes(content)
                files.append(path)
                total_bytes += len(content)
                total_shards += 1
                shard_descriptors.append(
                    ShardDescriptor(
                        path=path,
                        sha256=sha256_bytes(content),
                        bytes=len(content),
                        rows=len(chunk),
                        first_primary_key=tuple(chunk[0][name] for name in spec.primary_key),
                        last_primary_key=tuple(chunk[-1][name] for name in spec.primary_key),
                        ordered_rows_sha256=ordered.hexdigest(),
                    )
                )
            descriptors.append(
                RelationDescriptor(
                    name=spec.name,
                    rows=len(relation_rows),
                    shards=tuple(shard_descriptors),
                    ordered_rows_sha256=relation_digest.hexdigest(),
                    source_count=len(relation_rows),
                )
            )
    pins = {pin.path: pin.sha256 for pin in plan.source_pins}
    manifest = (
        CaptureManifestV2(
            version="eis-search-capture-manifest-v2",
            status="COMPLETE",
            capture_id="synthetic-unit",
            tenant=plan.tenant,
            clock=CLOCK,
            plan_sha256=sha256_bytes(plan_content),
            collector_sha256=pins["src/procurement/storage/eis_search_capture.py"],
            verifier_sha256=pins["src/procurement/sources/eis_search_capture.py"],
            runtime=_runtime(),
            relations=tuple(
                item for item in descriptors if isinstance(item, RelationDescriptorV2)
            ),
            current_membership=_membership(rows),
            future_versions=_future(rows),
            total_payload_bytes=total_bytes,
            total_shards=total_shards,
            files=tuple(files),
        )
        if isinstance(plan, CapturePlanV2)
        else CaptureManifest(
            version="eis-search-capture-manifest-v1",
            status="COMPLETE",
            capture_id="synthetic-unit",
            tenant=plan.tenant,
            clock=CLOCK,
            plan_sha256=sha256_bytes(plan_content),
            collector_sha256=pins["src/procurement/storage/eis_search_capture.py"],
            verifier_sha256=pins["src/procurement/sources/eis_search_capture.py"],
            runtime=_runtime(),
            relations=tuple(
                item for item in descriptors if not isinstance(item, RelationDescriptorV2)
            ),
            current_membership=_membership(rows),
            future_versions=_future(rows),
            total_payload_bytes=total_bytes,
            total_shards=total_shards,
            files=tuple(files),
        )
    )
    (root / "manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
    return root


def _rewrite_manifest(package: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    value = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    mutate(value)
    (package / "manifest.json").write_bytes(canonical_bytes(value) + b"\n")


def _projection_fixture_rows(
    *, plan_path: Path, projection_padding: str = "", wrong_event_type: bool = False
) -> dict[str, list[dict[str, object]]]:
    plan, _ = load_capture_plan(plan_path)
    specs = {item.name: item for item in plan.relations}
    receipt = _row(specs["eis_notice_variant_receipts"], 1)
    variant = _row(specs["eis_notice_variants"], 1)
    variant["facts"] = {
        "purchase_number": variant["purchase_number"],
        "version_number": variant["version_number"],
        "document_type": variant["document_type"],
        "xml_sha256": variant["xml_sha256"],
    }
    variant["facts_sha256"] = hashlib.sha256(
        json.dumps(variant["facts"], sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    origin = _row(specs["eis_notice_variant_origins"], 1)
    origin["receipt_id"] = receipt["receipt_id"]
    for key in ("purchase_number", "version_number", "document_type", "xml_sha256"):
        origin[key] = variant[key]
    receipt["occurrence_count"] = 1
    receipt["variant_count"] = 1
    receipt_payload = {
        key: value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value
        for key, value in receipt.items()
        if key not in {"company_id", "receipt_sha256"}
    }
    receipt_payload = json.loads(json.dumps(receipt_payload, default=str))
    variants = [json.loads(json.dumps(variant["facts"], default=str))]
    origins = [
        json.loads(
            json.dumps(
                {key: value for key, value in origin.items() if key != "company_id"},
                default=str,
            )
        )
    ]
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(
            {"receipt": receipt_payload, "variants": variants, "origins": origins},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    window = _row(specs["eis_feed_windows"], 1)
    batch = _row(specs["eis_notice_projection_batches"], 1)
    decision = _row(specs["eis_notice_projection_decisions"], 1)
    batch["receipt_id"] = receipt["receipt_id"]
    batch["window_key"] = window["window_key"]
    batch["response_sha256"] = window["response_sha256"]
    decision["batch_id"] = batch["batch_id"]
    expected_batch = {
        key: value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value
        for key, value in batch.items()
        if key != "payload_sha256"
    }
    expected_decision = {
        key: value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value
        for key, value in decision.items()
    }
    basis = {
        "batch_id": batch["batch_id"],
        "batch": json.loads(json.dumps(expected_batch, default=str)),
        "decisions": [json.loads(json.dumps(expected_decision, default=str))],
        "inputs": ([{"bounded_fixture_padding": projection_padding}] if projection_padding else []),
        "receipt_sha256": receipt["receipt_sha256"],
    }
    payload_sha = hashlib.sha256(
        json.dumps(basis, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    batch["payload_sha256"] = payload_sha
    basis["payload_sha256"] = payload_sha
    projection_audit = _row(specs["audit_events"], 4)
    projection_audit.update(
        event_id=batch["audit_event_id"],
        event_type=("UNRELATED_EVENT" if wrong_event_type else "EIS_NOTICE_PROJECTION_RECORDED"),
        object_type="eis_notice_projection_batch",
        object_id=batch["batch_id"],
        basis=basis,
    )
    receipt_audits = []
    for index, field in enumerate(
        ("retention_audit_event_id", "diagnosis_audit_event_id", "ledger_audit_event_id"), 1
    ):
        audit = _row(specs["audit_events"], index)
        audit["event_id"] = receipt[field]
        if field == "retention_audit_event_id":
            audit.update(
                event_type="EIS_REJECTED_WINDOW_EVIDENCE",
                object_type="eis_sync_target",
                object_id=receipt["window_key"],
                basis={"evidence": receipt["evidence"], "coverage": "UNKNOWN"},
            )
        elif field == "diagnosis_audit_event_id":
            audit.update(
                event_type="EIS_NOTICE_CONFLICT_DIAGNOSIS",
                object_type="eis_sync_target",
                object_id=receipt["window_key"],
                basis={
                    "evidence": receipt["evidence"],
                    "diagnosis": {"sha256": receipt["diagnosis_sha256"]},
                },
            )
        else:
            audit.update(
                event_type="EIS_NOTICE_VARIANT_LEDGER_RECORDED",
                object_type="eis_notice_variant_receipt",
                object_id=receipt["receipt_id"],
                basis={
                    "receipt": receipt_payload | {"receipt_sha256": receipt["receipt_sha256"]},
                    "variants": variants,
                    "origins": origins,
                    "evidence_status": "EVIDENCE_ONLY",
                    "resolution": "UNKNOWN",
                    "canonical_admission": "NOT_ENABLED",
                },
            )
        receipt_audits.append(audit)
    audits = sorted(
        [*receipt_audits, projection_audit],
        key=lambda item: str(item["event_id"]),
    )
    return {
        "audit_events": audits,
        "eis_feed_windows": [window],
        "eis_notice_variant_receipts": [receipt],
        "eis_notice_variants": [variant],
        "eis_notice_variant_origins": [origin],
        "eis_notice_projection_batches": [batch],
        "eis_notice_projection_decisions": [decision],
    }


def test_typed_row_roundtrip_is_lossless_and_null_is_typed() -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_notice_versions")
    row = _row(spec, 1)
    row["published_at"] = None
    _, decoded = decode_row(spec, encode_row(spec, row))
    assert decoded == row
    assert isinstance(decoded["nmck_rub"], Decimal)


def test_plan_is_exact_bounded_closure_and_pins_tools() -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    assert len(plan.relations) == 25
    assert sum(item.role == "RUNTIME_44" for item in plan.relations) == 11
    assert sum(item.role == "RUNTIME_223" for item in plan.relations) == 7
    assert sum(item.role == "FK_PARENT" for item in plan.relations) == 7
    omissions = {
        item.name: item.omitted_source_columns
        for item in plan.relations
        if item.omitted_source_columns
    }
    assert omissions == {"eis_223_blobs": ("content",), "eis_feed_archives": ("content",)}
    pins = {pin.path: pin.sha256 for pin in plan.source_pins}
    for path in (
        "src/procurement/sources/eis_search_capture.py",
        "src/procurement/storage/eis_search_capture.py",
    ):
        assert pins[path] == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def test_plans_allow_only_two_known_exact_schema_revisions(tmp_path: Path) -> None:
    synthetic, _ = load_capture_plan(PLAN_PATH)
    production, _ = load_capture_plan(PRODUCTION_PLAN_PATH)
    assert synthetic.schema_revision == "20261006_12"
    assert production.schema_revision == "20261006_08"
    synthetic_body = synthetic.model_dump(mode="json")
    production_body = production.model_dump(mode="json")
    synthetic_body["schema_revision"] = production_body["schema_revision"]
    assert synthetic_body == production_body

    raw = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    for value in ("20261006_07", "20261006_09", "20261006_13", None):
        candidate = dict(raw)
        if value is None:
            candidate.pop("schema_revision")
        else:
            candidate["schema_revision"] = value
        path = tmp_path / f"unsupported-{value}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        with pytest.raises(ValidationError):
            load_capture_plan(path)


@pytest.mark.parametrize("actual_revision", ["20261006_12", "20261006_07", None])
def test_runtime_revision_must_exactly_match_selected_plan(
    actual_revision: str | None,
) -> None:
    plan, _ = load_capture_plan(PRODUCTION_PLAN_PATH)

    class Result:
        def __init__(self, value: object) -> None:
            self.value = value

        def mappings(self) -> Result:
            return self

        def one(self) -> object:
            return self.value

        def scalar_one(self) -> object:
            return self.value

        def all(self) -> object:
            return self.value

    class Connection:
        def execute(self, statement: object, *_: object, **__: object) -> Result:
            sql = str(statement)
            if "FROM pg_roles r WHERE" in sql:
                return Result(
                    {
                        "current_user": "procurement_app",
                        "session_user": "procurement_app",
                        "server_version_num": "160004",
                        "transaction_isolation": "repeatable read",
                        "transaction_read_only": "on",
                        "row_security": "on",
                        "app_company_id": plan.tenant,
                        "txid_current_snapshot": "1:1:",
                        "transaction_timestamp": CLOCK,
                        "timezone": "UTC",
                        "search_path": '"$user", public',
                        "rolsuper": False,
                        "rolbypassrls": False,
                    }
                )
            if "FROM public.alembic_version" in sql:
                return Result(actual_revision)
            if "FROM pg_database" in sql:
                return Result(SimpleNamespace(datcollate="C.UTF-8", datctype="C.UTF-8"))
            if "FROM pg_policies" in sql or "role_table_grants" in sql:
                return Result([])
            raise AssertionError(sql)

    external = {
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
    with pytest.raises(CaptureCollectionError, match="SCHEMA_REVISION_MISMATCH"):
        _runtime_identity(
            Connection(),  # type: ignore[arg-type]
            plan,
            external,
            clock_mode="DB_TRANSACTION",
        )


def test_offline_verifier_accepts_content_but_never_origin_trust(tmp_path: Path) -> None:
    package = _build_package(tmp_path / "package")
    manifest_sha = sha256_bytes((package / "manifest.json").read_bytes())
    report = verify_capture_package(package, PLAN_PATH, expected_manifest_sha256=manifest_sha)
    assert report.status == "CAPTURE_CONTENT_VERIFIED"
    assert report.capture_origin_trust == "UNKNOWN"
    assert report.external_manifest_digest_match is True


@pytest.mark.parametrize("mutation", ["byte", "missing", "extra", "count", "tenant"])
def test_verifier_rejects_tamper_missing_extra_count_and_tenant(
    tmp_path: Path, mutation: str
) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_sync_targets")
    package = _build_package(tmp_path / "package", {spec.name: [_row(spec, 1)]})
    shard = next((package / "relations").iterdir())
    if mutation == "byte":
        shard.write_bytes(shard.read_bytes().replace(b"planned_by", b"planned_bx", 1))
    elif mutation == "missing":
        shard.unlink()
    elif mutation == "extra":
        (package / "unlisted.txt").write_text("x", encoding="utf-8")
    elif mutation == "count":
        _rewrite_manifest(package, lambda value: value["relations"][-1].update(rows=2))
    else:
        content = shard.read_bytes().replace(b"local-eis-supplier", b"foreign-eis-supplier")
        shard.write_bytes(content)
        _rewrite_manifest(
            package,
            lambda value: value["relations"][-1]["shards"][0].update(
                sha256=sha256_bytes(content), bytes=len(content)
            ),
        )
    assert verify_capture_package(package, PLAN_PATH).status == "FAIL"


def test_duplicate_or_out_of_order_primary_key_fails_even_with_rebound_hashes(
    tmp_path: Path,
) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_sync_targets")
    duplicate = _row(spec, 1)
    package = _build_package(tmp_path / "package", {spec.name: [duplicate, duplicate]})
    assert "ROW_ORDER_OR_DUPLICATE_INVALID" in verify_capture_package(package, PLAN_PATH).reasons[0]


def test_missing_transitive_parent_fails(tmp_path: Path) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_notice_versions")
    package = _build_package(tmp_path / "package", {spec.name: [_row(spec, 1)]})
    assert "FOREIGN_KEY_DEPENDENCY_MISSING" in verify_capture_package(package, PLAN_PATH).reasons[0]


def test_unreferenced_transitive_parent_fails(tmp_path: Path) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_223_blobs")
    package = _build_package(tmp_path / "package", {spec.name: [_row(spec, 1)]})
    report = verify_capture_package(package, PLAN_PATH)
    assert report.status == "FAIL"
    assert "FK_PARENT_SET_NOT_EXACT:eis_223_blobs" in report.reasons[0]


def test_projection_audit_semantics_cannot_be_replaced_by_wrong_event(tmp_path: Path) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    specs = {item.name: item for item in plan.relations}
    receipt = _row(specs["eis_notice_variant_receipts"], 1)
    variant = _row(specs["eis_notice_variants"], 1)
    variant["facts"] = {
        "purchase_number": variant["purchase_number"],
        "version_number": variant["version_number"],
        "document_type": variant["document_type"],
        "xml_sha256": variant["xml_sha256"],
    }
    variant["facts_sha256"] = hashlib.sha256(
        json.dumps(variant["facts"], sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    origin = _row(specs["eis_notice_variant_origins"], 1)
    origin["receipt_id"] = receipt["receipt_id"]
    for key in ("purchase_number", "version_number", "document_type", "xml_sha256"):
        origin[key] = variant[key]
    receipt["occurrence_count"] = 1
    receipt["variant_count"] = 1
    receipt_payload = {
        key: value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value
        for key, value in receipt.items()
        if key not in {"company_id", "receipt_sha256"}
    }
    receipt_payload = json.loads(json.dumps(receipt_payload, default=str))
    variants = [json.loads(json.dumps(variant["facts"], default=str))]
    origins = [
        json.loads(
            json.dumps(
                {key: value for key, value in origin.items() if key != "company_id"}, default=str
            )
        )
    ]
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(
            {"receipt": receipt_payload, "variants": variants, "origins": origins},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    window = _row(specs["eis_feed_windows"], 1)
    batch = _row(specs["eis_notice_projection_batches"], 1)
    decision = _row(specs["eis_notice_projection_decisions"], 1)
    batch["receipt_id"] = receipt["receipt_id"]
    batch["window_key"] = window["window_key"]
    batch["response_sha256"] = window["response_sha256"]
    decision["batch_id"] = batch["batch_id"]
    expected_batch = {
        key: value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value
        for key, value in batch.items()
        if key != "payload_sha256"
    }
    expected_decision = {
        key: value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value
        for key, value in decision.items()
    }
    expected_batch = json.loads(json.dumps(expected_batch, default=str))
    expected_decision = json.loads(json.dumps(expected_decision, default=str))
    basis = {
        "batch_id": batch["batch_id"],
        "batch": expected_batch,
        "decisions": [expected_decision],
        "inputs": [],
        "receipt_sha256": receipt["receipt_sha256"],
    }
    payload_sha = hashlib.sha256(
        json.dumps(basis, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    batch["payload_sha256"] = payload_sha
    basis["payload_sha256"] = payload_sha
    projection_audit = _row(specs["audit_events"], 4)
    projection_audit.update(
        event_id=batch["audit_event_id"],
        event_type="EIS_NOTICE_PROJECTION_RECORDED",
        object_type="eis_notice_projection_batch",
        object_id=batch["batch_id"],
        basis=basis,
    )
    receipt_audits = []
    for index, field in enumerate(
        (
            "retention_audit_event_id",
            "diagnosis_audit_event_id",
            "ledger_audit_event_id",
        ),
        1,
    ):
        audit = _row(specs["audit_events"], index)
        audit["event_id"] = receipt[field]
        if field == "retention_audit_event_id":
            audit.update(
                event_type="EIS_REJECTED_WINDOW_EVIDENCE",
                object_type="eis_sync_target",
                object_id=receipt["window_key"],
                basis={"evidence": receipt["evidence"], "coverage": "UNKNOWN"},
            )
        elif field == "diagnosis_audit_event_id":
            audit.update(
                event_type="EIS_NOTICE_CONFLICT_DIAGNOSIS",
                object_type="eis_sync_target",
                object_id=receipt["window_key"],
                basis={
                    "evidence": receipt["evidence"],
                    "diagnosis": {"sha256": receipt["diagnosis_sha256"]},
                },
            )
        else:
            ledger_receipt = receipt_payload | {"receipt_sha256": receipt["receipt_sha256"]}
            audit.update(
                event_type="EIS_NOTICE_VARIANT_LEDGER_RECORDED",
                object_type="eis_notice_variant_receipt",
                object_id=receipt["receipt_id"],
                basis={
                    "receipt": ledger_receipt,
                    "variants": variants,
                    "origins": origins,
                    "evidence_status": "EVIDENCE_ONLY",
                    "resolution": "UNKNOWN",
                    "canonical_admission": "NOT_ENABLED",
                },
            )
        receipt_audits.append(audit)

    def audit_key(item: dict[str, object]) -> str:
        value = item["event_id"]
        assert isinstance(value, str)
        return value

    audits = sorted([*receipt_audits, projection_audit], key=audit_key)
    package = _build_package(
        tmp_path / "package",
        {
            "audit_events": audits,
            "eis_feed_windows": [window],
            "eis_notice_variant_receipts": [receipt],
            "eis_notice_variants": [variant],
            "eis_notice_variant_origins": [origin],
            "eis_notice_projection_batches": [batch],
            "eis_notice_projection_decisions": [decision],
        },
    )
    valid_report = verify_capture_package(package, PLAN_PATH)
    assert valid_report.status == "CAPTURE_CONTENT_VERIFIED", valid_report.reasons
    projection_audit["event_type"] = "UNRELATED_EVENT"
    rebound = _build_package(
        tmp_path / "rebound",
        {
            "audit_events": sorted([*receipt_audits, projection_audit], key=audit_key),
            "eis_feed_windows": [window],
            "eis_notice_variant_receipts": [receipt],
            "eis_notice_variants": [variant],
            "eis_notice_variant_origins": [origin],
            "eis_notice_projection_batches": [batch],
            "eis_notice_projection_decisions": [decision],
        },
    )
    assert "PROJECTION_AUDIT_BASIS_INVALID" in verify_capture_package(rebound, PLAN_PATH).reasons[0]


def test_future_notice_is_excluded_from_current_at_clock(tmp_path: Path) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_223_notice_versions")
    row = _row(spec, 1)
    row["ingested_at"] = CLOCK + timedelta(seconds=1)
    source = next(item for item in plan.relations if item.name == "eis_223_archive_sources")
    blob = next(item for item in plan.relations if item.name == "eis_223_blobs")
    window = next(item for item in plan.relations if item.name == "eis_223_windows")
    source_row = _row(source, 1)
    blob_row = _row(blob, 1)
    window_row = _row(window, 1)
    for key in ("window_key", "response_sha256", "archive_sha256"):
        source_row[key] = row[key]
    blob_row["archive_sha256"] = row["archive_sha256"]
    for key in ("window_key", "response_sha256"):
        window_row[key] = row[key]
    package = _build_package(
        tmp_path / "package",
        {
            spec.name: [row],
            source.name: [source_row],
            blob.name: [blob_row],
            window.name: [window_row],
        },
    )
    report = verify_capture_package(package, PLAN_PATH)
    assert report.status == "CAPTURE_CONTENT_VERIFIED"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert (
        next(item for item in manifest["current_membership"] if item["law"] == "223")["rows"] == 0
    )
    assert next(item for item in manifest["future_versions"] if item["law"] == "223")["rows"] == 1


def test_writer_splits_shards_and_timeout_fails_closed(tmp_path: Path) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_sync_targets")
    budget = _PackageBudget(plan, time.monotonic())
    writer = _RelationWriter(tmp_path, spec, budget)
    writer.write(_row(spec, 1))
    descriptor = writer.finish(1)
    assert descriptor.rows == 1
    expired = _PackageBudget(plan, time.monotonic() - plan.limits.capture_timeout_seconds - 1)
    with pytest.raises(CaptureCollectionError, match="CAPTURE_TIMEOUT"):
        expired.check_time()


def test_disk_gate_prevents_database_access_and_complete_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Storage:
        def transaction(self, *_: object, **__: object) -> object:
            raise AssertionError("database must not be opened")

    monkeypatch.setattr(
        "procurement.storage.eis_search_capture._verify_source_pins", lambda _: None
    )
    with pytest.raises(CaptureCollectionError, match="FREE_DISK_LIMIT"):
        capture_search_projection(
            Storage(),  # type: ignore[arg-type]
            PLAN_PATH,
            tmp_path / "package",
            capture_id="disk-negative",
            clock=CLOCK,
            synthetic_clock=True,
            external_runtime={"not": "reached"},
            disk_usage=lambda _: SimpleNamespace(free=0),
        )
    assert not (tmp_path / "package/manifest.json").exists()


def test_cli_writes_utf8_report_and_ascii_safe_completion(tmp_path: Path) -> None:
    package = _build_package(tmp_path / "пакет")
    report = tmp_path / "отчёт.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/eis-search-capture.py"),
            "verify",
            "--plan",
            str(PLAN_PATH),
            "--package",
            str(package),
            "--report",
            str(report),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    completed.stdout.decode("ascii")
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "CAPTURE_CONTENT_VERIFIED"


def test_false_external_manifest_anchor_fails_and_cannot_set_trust(tmp_path: Path) -> None:
    package = _build_package(tmp_path / "package")
    report = verify_capture_package(package, PLAN_PATH, expected_manifest_sha256="0" * 64)
    assert report.status == "FAIL"
    assert report.capture_origin_trust == "UNKNOWN"


def test_float_and_oversize_row_are_rejected(tmp_path: Path) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    notice = next(item for item in plan.relations if item.name == "eis_notice_versions")
    row = _row(notice, 1)
    row["lot_items"] = {"unsafe": 1.1}
    with pytest.raises(CaptureFormatError, match="FLOAT_VALUE_FORBIDDEN"):
        encode_row(notice, row)
    row = _row(notice, 1)
    row["title"] = "x" * plan.limits.shard_bytes
    writer = _RelationWriter(tmp_path, notice, _PackageBudget(plan, time.monotonic()))
    with pytest.raises(CaptureCollectionError, match="ROW_EXCEEDS_SHARD_LIMIT"):
        writer.write(row)


def test_manifest_cannot_authorize_extra_file_or_incomplete_marker(tmp_path: Path) -> None:
    for name in ("extra", "incomplete", "duplicate"):
        package = _build_package(tmp_path / name)
        if name == "duplicate":
            _rewrite_manifest(package, lambda value: value["files"].append("plan.json"))
        else:
            filename = "arbitrary.bin" if name == "extra" else "incomplete.json"
            (package / filename).write_bytes(b"{}")
            def append_file(value: dict[str, Any], item: str = filename) -> None:
                value["files"].append(item)

            _rewrite_manifest(package, append_file)
        assert verify_capture_package(package, PLAN_PATH).status == "FAIL"


def test_plan_and_runtime_identity_require_bounded_regular_files(tmp_path: Path) -> None:
    with pytest.raises(CaptureFormatError, match="PLAN_FILETYPE_INVALID"):
        load_capture_plan(tmp_path)
    spec = importlib.util.spec_from_file_location(
        "capture_cli", ROOT / "scripts/eis-search-capture.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    oversized = tmp_path / "runtime.json"
    oversized.write_bytes(b"x" * 16_777_217)
    with pytest.raises(ValueError, match="metadata cap"):
        module._read_runtime(oversized)


@pytest.mark.parametrize("drift", ["numeric", "timestamp", "index", "owner"])
def test_schema_detail_and_effective_rls_drift_are_rejected(
    monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)

    class Inspector:
        def spec(self, name: str) -> RelationSpec:
            return next(item for item in plan.relations if item.name == name)

        def get_columns(self, name: str, **_: object) -> list[dict[str, object]]:
            spec = self.spec(name)
            result = []
            for column in spec.columns:
                kind: object = metadata.tables[name].c[column.name].type
                if (
                    drift == "numeric"
                    and name == "eis_notice_versions"
                    and column.name == "nmck_rub"
                ):
                    kind = Numeric(2, 1)
                if (
                    drift == "timestamp"
                    and name == "eis_notice_versions"
                    and column.name == "ingested_at"
                ):
                    kind = DateTime(timezone=False)
                result.append({"name": column.name, "type": kind, "nullable": column.nullable})
            result.extend({"name": item} for item in spec.omitted_source_columns)
            return result

        def get_pk_constraint(self, name: str, **_: object) -> dict[str, object]:
            return {"constrained_columns": self.spec(name).primary_key}

        def get_indexes(self, name: str, **_: object) -> list[dict[str, object]]:
            values = []
            for item in self.spec(name).indexes:
                model_index = next(
                    (
                        index
                        for index in metadata.tables[name].indexes
                        if index.name == item.name
                    ),
                    None,
                )
                if model_index is None:
                    continue
                using = model_index.dialect_options["postgresql"].get("using") or "btree"
                if drift == "index":
                    using = "hash"
                values.append(
                    {
                        "name": item.name,
                        "column_names": item.columns,
                        "unique": item.unique,
                        "dialect_options": {
                            "postgresql_using": using,
                            "postgresql_where": "FALSE" if drift == "index" else None,
                        },
                    }
                )
            return values

        def get_unique_constraints(self, name: str, **_: object) -> list[dict[str, object]]:
            index_names = {index.name for index in metadata.tables[name].indexes}
            return [
                {"name": item.name, "column_names": item.columns}
                for item in self.spec(name).indexes
                if item.name not in index_names
            ]

        def get_foreign_keys(self, name: str, **_: object) -> list[dict[str, object]]:
            return [
                {
                    "constrained_columns": item.columns,
                    "referred_table": item.target_relation,
                    "referred_columns": item.target_columns,
                }
                for item in self.spec(name).foreign_keys
            ]

    class Connection:
        def execute(self, *_: object, **__: object) -> object:
            return SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        relname=item.name,
                        relrowsecurity=True,
                        relforcerowsecurity=False,
                        relkind="r",
                        owner_membership=drift == "owner",
                    )
                    for item in plan.relations
                ]
            )

    monkeypatch.setattr("procurement.storage.eis_search_capture.inspect", lambda _: Inspector())
    with pytest.raises(CaptureCollectionError, match=r"SCHEMA_(RLS|TYPE_DETAIL|INDEX)_DRIFT"):
        _validate_schema(Connection(), plan)  # type: ignore[arg-type]


def test_empty_capture_checks_terminal_timeout_and_records_partial_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def transaction(*_: object, **__: object) -> Any:
        class Connection:
            def execute(self, *_: object, **__: object) -> object:
                return SimpleNamespace(
                    scalar_one=lambda: 0,
                    mappings=lambda: SimpleNamespace(partitions=lambda _: iter(())),
                )

            def execution_options(self, **_: object) -> Connection:
                return self

        yield Connection()

    monkeypatch.setattr(
        "procurement.storage.eis_search_capture._verify_source_pins", lambda _: None
    )
    monkeypatch.setattr(
        "procurement.storage.eis_search_capture._runtime_identity",
        lambda *_a, **_k: _runtime(),
    )
    monkeypatch.setattr("procurement.storage.eis_search_capture._validate_schema", lambda *_: None)
    ticks = iter((0.0, 0.0, 901.0, 901.0))
    monkeypatch.setattr(
        "procurement.storage.eis_search_capture.time.monotonic",
        lambda: next(ticks, 901.0),
    )
    timed_out = capture_search_projection(
        SimpleNamespace(transaction=transaction),  # type: ignore[arg-type]
        PLAN_PATH,
        tmp_path / "timeout",
        capture_id="timeout",
        external_runtime={},
        disk_usage=lambda _: SimpleNamespace(free=6 * 1024**3),
    )
    assert timed_out.status == "INCOMPLETE"
    assert "CAPTURE_TIMEOUT" in timed_out.reasons[0]
    assert not (tmp_path / "timeout/manifest.json").exists()

    def fail_after_one(
        _connection: object,
        actual_plan: CapturePlan | CapturePlanV2,
        root: Path,
        _clock: object,
        budget: _PackageBudget,
        _database: object,
    ) -> None:
        spec = next(item for item in actual_plan.relations if item.name == "eis_sync_targets")
        writer = _RelationWriter(root, spec, budget)
        writer.write(_row(spec, 1))
        writer.finish(1)
        raise CaptureCollectionError("SIMULATED_FAILURE")

    monkeypatch.setattr("procurement.storage.eis_search_capture.time.monotonic", lambda: 0.0)
    monkeypatch.setattr("procurement.storage.eis_search_capture._capture_relations", fail_after_one)
    partial = capture_search_projection(
        SimpleNamespace(transaction=transaction),  # type: ignore[arg-type]
        PLAN_PATH,
        tmp_path / "partial",
        capture_id="partial",
        external_runtime={},
        disk_usage=lambda _: SimpleNamespace(free=6 * 1024**3),
    )
    assert partial.status == "INCOMPLETE"
    assert partial.actual_relation_rows == {"eis_sync_targets": 1}


def test_variant_facts_hash_is_verified(tmp_path: Path) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_notice_variants")
    row = _row(spec, 1)
    row["facts"] = {"purchase_number": row["purchase_number"]}
    row["facts_sha256"] = "0" * 64
    package = _build_package(tmp_path / "package", {spec.name: [row]})
    report = verify_capture_package(package, PLAN_PATH)
    assert report.status == "FAIL"
    assert "VARIANT_FACTS_HASH_MISMATCH" in report.reasons[0]


def test_server_row_size_preflight_refuses_before_stream_fetch(tmp_path: Path) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)

    class Connection:
        def execute(self, *_: object, **__: object) -> object:
            return SimpleNamespace(one=lambda: (1, plan.limits.shard_bytes + 1))

        def execution_options(self, **_: object) -> object:
            raise AssertionError("oversized row must not be transferred")

    current = sqlite3.connect(":memory:")
    current.execute(
        "CREATE TABLE current_versions (law TEXT, purchase_number TEXT, "
        "version_number INTEGER, source_sha TEXT, PRIMARY KEY (law, purchase_number))"
    )
    current.execute(
        "CREATE TABLE future_versions (law TEXT, purchase_number TEXT, "
        "version_number INTEGER, source_sha TEXT, ingested_at TEXT, "
        "PRIMARY KEY (law, purchase_number, version_number))"
    )
    try:
        with pytest.raises(CaptureCollectionError, match="RAW_ROW_EXCEEDS_SHARD_LIMIT"):
            _capture_relations(
                Connection(),  # type: ignore[arg-type]
                plan,
                tmp_path,
                CLOCK,
                _PackageBudget(plan, time.monotonic()),
                current,
            )
    finally:
        current.close()


def test_declared_payload_limit_rejects_before_shard_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_sync_targets")
    package = _build_package(tmp_path / "package", {spec.name: [_row(spec, 1)]})

    def enlarge(value: dict[str, Any]) -> None:
        descriptor = next(item for item in value["relations"] if item["name"] == spec.name)
        descriptor["shards"][0]["bytes"] = plan.limits.shard_bytes + 1
        value["total_payload_bytes"] = plan.limits.shard_bytes + 1

    _rewrite_manifest(package, enlarge)
    monkeypatch.setattr(
        "procurement.sources.eis_search_capture._iter_lines",
        lambda *_: (_ for _ in ()).throw(AssertionError("shard read reached")),
    )
    report = verify_capture_package(package, PLAN_PATH)
    assert report.status == "FAIL"
    assert "SHARD_DECLARED_LIMIT" in report.reasons[0]


def test_cumulative_metadata_deadline_and_manifest_publication_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _ = load_capture_plan(PLAN_PATH)
    now = [0.0]
    monkeypatch.setattr(
        "procurement.storage.eis_search_capture.time.monotonic", lambda: now[0]
    )

    class Connection:
        def execute(self, *_: object, **__: object) -> object:
            return object()

    budget = _PackageBudget(plan, 0.0)

    def metadata_operation() -> None:
        now[0] += 10.0

    with pytest.raises(CaptureCollectionError, match="CAPTURE_TIMEOUT"):
        for _ in range(100):
            _bounded_database_call(
                Connection(),  # type: ignore[arg-type]
                budget,
                metadata_operation,
            )
    assert now[0] == 900.0

    fixture = _build_package(tmp_path / "fixture")
    manifest = CaptureManifest.model_validate_json((fixture / "manifest.json").read_bytes())
    terminal = tmp_path / "terminal"
    terminal.mkdir()
    now[0] = 901.0
    with pytest.raises(CaptureCollectionError, match="CAPTURE_TIMEOUT"):
        _publish_manifest(terminal, manifest, plan.limits.metadata_bytes, budget)
    assert not (terminal / "manifest.json").exists()
    assert not (terminal / ".manifest.pending").exists()


def test_v2_plans_preserve_v1_closure_and_add_only_exact_fragment_limits() -> None:
    for old_path, new_path in (
        (PLAN_PATH, PLAN_V2_PATH),
        (PRODUCTION_PLAN_PATH, PRODUCTION_PLAN_V2_PATH),
    ):
        old, _ = load_capture_plan(old_path)
        new, _ = load_capture_plan(new_path)
        old_body = old.model_dump(mode="json")
        new_body = new.model_dump(mode="json")
        assert new_body.pop("version") == "eis-search-capture-plan-v2"
        assert new_body.pop("plan_id") == "m2b1-full-tenant-search-projection-v2"
        limits = new_body["limits"]
        assert limits.pop("audit_raw_row_bytes") == 33_554_432
        assert limits.pop("audit_typed_row_bytes") == 67_108_864
        assert limits.pop("audit_max_fragments") == 8
        old_body.pop("version")
        old_body.pop("plan_id")
        old_pins = {item["path"]: item["sha256"] for item in old_body.pop("source_pins")}
        new_pins = {item["path"]: item["sha256"] for item in new_body.pop("source_pins")}
        assert old_pins.keys() == new_pins.keys()
        changed_pins = {
            "src/procurement/sources/eis_search_capture.py",
            "src/procurement/storage/eis_search_capture.py",
        }
        assert {path for path in old_pins if old_pins[path] != new_pins[path]} == changed_pins
        for path in changed_pins:
            assert new_pins[path] == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        assert new_body == old_body


def test_streaming_canonical_encoder_is_byte_identical_for_nested_typed_values() -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    assert isinstance(plan, CapturePlanV2)
    spec = next(item for item in plan.relations if item.name == "audit_events")
    row = _row(spec, 1)
    row["basis"] = {
        "unicode": "бумага/\n/\u0001/😀",
        "decimal": Decimal("100.2500"),
        "nullable": None,
        "nested": [{"flag": True, "number": 7}],
    }
    assert b"".join(iter_encoded_row(spec, row)) == encode_row(spec, row)


def test_v2_writer_preserves_small_bytes_and_fragments_one_exact_large_row(
    tmp_path: Path,
) -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    assert isinstance(plan, CapturePlanV2)
    spec = next(item for item in plan.relations if item.name == "audit_events")
    small = _row(spec, 1)
    small_line = encode_row(spec, small)
    large = _row(spec, 2)
    large["basis"] = {"large": "я" * (plan.limits.shard_bytes // 2 + 512)}
    large_line = encode_row(spec, large)
    assert len(small_line) < plan.limits.shard_bytes < len(large_line)
    writer = _RelationWriterV2(tmp_path, spec, _PackageBudget(plan, time.monotonic()), plan)
    writer.write(small)
    writer.write(large)
    descriptor = writer.finish(2)
    assert descriptor.rows == descriptor.source_count == 2
    assert sum(item.rows for item in descriptor.shards) == 1
    assert len(descriptor.fragmented_rows) == 1
    fragmented = descriptor.fragmented_rows[0]
    assert fragmented.logical_ordinal == 1
    assert fragmented.whole_bytes == len(large_line)
    assert fragmented.whole_sha256 == sha256_bytes(large_line)
    assert b"".join((tmp_path / item.path).read_bytes() for item in fragmented.fragments) == (
        large_line
    )
    assert (tmp_path / descriptor.shards[0].path).read_bytes() == small_line
    relation_digest = hashlib.sha256()
    for line in (small_line, large_line):
        relation_digest.update(len(line).to_bytes(8, "big") + line)
    assert descriptor.ordered_rows_sha256 == relation_digest.hexdigest()


def test_v2_offline_verifier_reassembles_large_semantic_audit_row(tmp_path: Path) -> None:
    rows = _projection_fixture_rows(
        plan_path=PLAN_V2_PATH,
        projection_padding="x" * (8_388_608 + 1024),
    )
    package = _build_package(
        tmp_path / "package", rows, plan_path=PLAN_V2_PATH
    )
    report = verify_capture_package(package, PLAN_V2_PATH)
    assert report.status == "CAPTURE_CONTENT_VERIFIED", report.reasons
    manifest = CaptureManifestV2.model_validate_json((package / "manifest.json").read_bytes())
    audit = next(item for item in manifest.relations if item.name == "audit_events")
    assert audit.rows == 4
    assert len(audit.fragmented_rows) == 1
    assert sum(item.rows for item in audit.shards) == 3
    assert manifest.total_shards == sum(
        len(item.shards) + sum(row.fragment_count for row in item.fragmented_rows)
        for item in manifest.relations
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("tenant", "FRAGMENT_ROW_BINDING_INVALID"),
        ("relation", "validation error for CaptureManifestV2"),
        ("offset", "FRAGMENT_SEQUENCE_INVALID"),
        ("ordinal", "FRAGMENT_SEQUENCE_INVALID"),
        ("count", "FRAGMENT_COUNT_INVALID"),
        ("logical", "FRAGMENT_LOGICAL_ORDINAL_INVALID"),
        ("reuse", "PACKAGE_FILE_DECLARATION_DUPLICATE"),
    ],
)
def test_v2_fragment_descriptor_corruption_is_rejected_before_row_reassembly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    reason: str,
) -> None:
    package = _build_package(
        tmp_path / "package",
        _projection_fixture_rows(
            plan_path=PLAN_V2_PATH,
            projection_padding="x" * (8_388_608 + 1024),
        ),
        plan_path=PLAN_V2_PATH,
    )

    def mutate(value: dict[str, Any]) -> None:
        audit = next(item for item in value["relations"] if item["name"] == "audit_events")
        row = audit["fragmented_rows"][0]
        if mutation == "tenant":
            row["tenant"] = "foreign"
        elif mutation == "relation":
            row["relation"] = "eis_sync_targets"
        elif mutation == "offset":
            row["fragments"][1]["offset"] += 1
        elif mutation == "ordinal":
            row["fragments"][0]["ordinal"] = 1
        elif mutation == "count":
            row["fragment_count"] += 1
        elif mutation == "logical":
            row["logical_ordinal"] = audit["rows"]
        else:
            row["fragments"][1]["path"] = row["fragments"][0]["path"]

    _rewrite_manifest(package, mutate)
    monkeypatch.setattr(
        "procurement.sources.eis_search_capture._read_fragmented_row",
        lambda *_: (_ for _ in ()).throw(AssertionError("row reassembly reached")),
    )
    report = verify_capture_package(package, PLAN_V2_PATH)
    assert report.status == "FAIL"
    assert reason in report.reasons[0]


def test_v2_fragment_byte_tamper_and_hash_consistent_semantic_tamper_fail(
    tmp_path: Path,
) -> None:
    rows = _projection_fixture_rows(
        plan_path=PLAN_V2_PATH,
        projection_padding="x" * (8_388_608 + 1024),
    )
    package = _build_package(tmp_path / "byte", rows, plan_path=PLAN_V2_PATH)
    manifest = CaptureManifestV2.model_validate_json((package / "manifest.json").read_bytes())
    audit = next(item for item in manifest.relations if item.name == "audit_events")
    fragment = audit.fragmented_rows[0].fragments[-1]
    path = package / fragment.path
    content = path.read_bytes()
    path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
    report = verify_capture_package(package, PLAN_V2_PATH)
    assert report.status == "FAIL"
    assert "FRAGMENT_CONTENT_MISMATCH" in report.reasons[0]

    rebound = _build_package(
        tmp_path / "semantic",
        _projection_fixture_rows(
            plan_path=PLAN_V2_PATH,
            projection_padding="x" * (8_388_608 + 1024),
            wrong_event_type=True,
        ),
        plan_path=PLAN_V2_PATH,
    )
    report = verify_capture_package(rebound, PLAN_V2_PATH)
    assert report.status == "FAIL"
    assert "PROJECTION_AUDIT_BASIS_INVALID" in report.reasons[0]


def test_v2_adaptive_prefetch_is_bound_before_stream_execute(tmp_path: Path) -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    assert isinstance(plan, CapturePlanV2)
    audit = next(item for item in plan.relations if item.name == "audit_events")
    one_relation = plan.model_copy(update={"relations": (audit,)})
    observed: list[int] = []

    class Result:
        def one(self) -> tuple[int, int]:
            return 0, 16_777_216

        def mappings(self) -> Result:
            return self

        def partitions(self, size: int) -> tuple[()]:
            observed.append(size)
            return ()

    class Connection:
        def execute(self, *_: object, **__: object) -> Result:
            return Result()

        def execution_options(self, *, stream_results: bool, yield_per: int) -> Connection:
            assert stream_results is True
            observed.append(yield_per)
            return self

    current = sqlite3.connect(":memory:")
    current.execute(
        "CREATE TABLE current_versions (law TEXT, purchase_number TEXT, "
        "version_number INTEGER, source_sha TEXT, PRIMARY KEY (law, purchase_number))"
    )
    current.execute(
        "CREATE TABLE future_versions (law TEXT, purchase_number TEXT, "
        "version_number INTEGER, source_sha TEXT, ingested_at TEXT, "
        "PRIMARY KEY (law, purchase_number, version_number))"
    )
    try:
        descriptors, counts = _capture_relations(
            Connection(),  # type: ignore[arg-type]
            one_relation,
            tmp_path,
            CLOCK,
            _PackageBudget(one_relation, time.monotonic()),
            current,
        )
    finally:
        current.close()
    assert observed == [4, 4]
    assert descriptors[0].rows == counts["audit_events"] == 0


def test_v2_raw_audit_limit_refuses_before_stream_and_typed_limit_is_incremental(
    tmp_path: Path,
) -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    assert isinstance(plan, CapturePlanV2)
    audit = next(item for item in plan.relations if item.name == "audit_events")
    one_relation = plan.model_copy(update={"relations": (audit,)})
    raw_limit = plan.limits.audit_raw_row_bytes

    class OversizedConnection:
        def execute(self, *_: object, **__: object) -> object:
            return SimpleNamespace(one=lambda: (1, raw_limit + 1))

        def execution_options(self, **_: object) -> object:
            raise AssertionError("raw-oversized row must not start a stream")

    current = sqlite3.connect(":memory:")
    current.execute(
        "CREATE TABLE current_versions (law TEXT, purchase_number TEXT, "
        "version_number INTEGER, source_sha TEXT, PRIMARY KEY (law, purchase_number))"
    )
    current.execute(
        "CREATE TABLE future_versions (law TEXT, purchase_number TEXT, "
        "version_number INTEGER, source_sha TEXT, ingested_at TEXT, "
        "PRIMARY KEY (law, purchase_number, version_number))"
    )
    try:
        with pytest.raises(CaptureCollectionError, match="RAW_ROW_EXCEEDS_SHARD_LIMIT"):
            _capture_relations(
                OversizedConnection(),  # type: ignore[arg-type]
                one_relation,
                tmp_path,
                CLOCK,
                _PackageBudget(one_relation, time.monotonic()),
                current,
            )
    finally:
        current.close()

    row = _row(audit, 1)
    # Each control character expands to six JSON bytes. The source string is
    # within the 32 MiB raw cap, while the typed encoding crosses 64 MiB.
    # The custom encoder yields bounded chunks, so refusal happens during the
    # spool instead of after one fully expanded JSON string allocation.
    row["basis"] = {"control": "\u0001" * 11_200_000}
    writer = _RelationWriterV2(
        tmp_path / "typed", audit, _PackageBudget(plan, time.monotonic()), plan
    )
    (tmp_path / "typed").mkdir()
    with pytest.raises(CaptureCollectionError, match="TYPED_AUDIT_ROW_LIMIT"):
        writer.write(row)
    assert not (tmp_path / "typed/.audit-row.pending").exists()


def test_v2_incomplete_separates_host_attempt_from_observed_database_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def transaction(*_: object, **__: object) -> Any:
        yield SimpleNamespace(execute=lambda *_a, **_k: None)

    monkeypatch.setattr(
        "procurement.storage.eis_search_capture._runtime_identity",
        lambda *_a, **_k: _runtime(),
    )
    monkeypatch.setattr("procurement.storage.eis_search_capture._validate_schema", lambda *_: None)
    monkeypatch.setattr(
        "procurement.storage.eis_search_capture._capture_relations",
        lambda *_: (_ for _ in ()).throw(CaptureCollectionError("AFTER_RUNTIME")),
    )
    result = capture_search_projection(
        SimpleNamespace(transaction=transaction),  # type: ignore[arg-type]
        PLAN_V2_PATH,
        tmp_path / "incomplete-v2",
        capture_id="incomplete-v2",
        external_runtime={},
        disk_usage=lambda _: SimpleNamespace(free=6 * 1024**3),
    )
    assert isinstance(result, IncompleteCaptureV2)
    assert result.attempted_at.tzinfo is not None
    assert result.transaction_timestamp == CLOCK
    assert result.snapshot_id == _runtime().snapshot_id
    assert result.runtime == _runtime()
    assert "AFTER_RUNTIME" in result.reasons[0]


def test_v2_offline_raw_width_lower_bound_rejects_large_valid_audit_row(
    tmp_path: Path,
) -> None:
    padding = "x" * 33_554_433
    package = _build_package(
        tmp_path / "raw-over-cap",
        _projection_fixture_rows(plan_path=PLAN_V2_PATH, projection_padding=padding),
        plan_path=PLAN_V2_PATH,
    )
    manifest_sha = sha256_bytes((package / "manifest.json").read_bytes())
    report = verify_capture_package(package, PLAN_V2_PATH, expected_manifest_sha256=manifest_sha)
    assert report.status == "FAIL"
    assert "DECODED_RAW_WIDTH_LOWER_BOUND_LIMIT" in report.reasons[0]
    assert report.model_dump()["raw_width_validation"] == "DECODED_LOWER_BOUND_ONLY"
    assert report.model_dump()["source_raw_width_attestation"] == "UNKNOWN"


def test_v2_decoded_lower_bound_counts_only_selected_string_occurrences() -> None:
    values: list[object] = [
        "top",
        {"key": ["array", "array"], "number": Decimal("1000000000000000000")},
        CLOCK,
        99,
    ]
    expected = sum(
        len(value.encode("utf-8")) for value in ("top", "key", "array", "array", "number")
    )
    assert _decoded_string_utf8_lower_bound(values, expected) == expected
    with pytest.raises(CaptureFormatError, match="DECODED_RAW_WIDTH_LOWER_BOUND_LIMIT"):
        _decoded_string_utf8_lower_bound(values, expected - 1)


def test_v2_report_attestation_is_fixed_for_success_mismatch_and_incomplete(
    tmp_path: Path,
) -> None:
    package = _build_package(tmp_path / "complete-v2", plan_path=PLAN_V2_PATH)
    manifest_sha = sha256_bytes((package / "manifest.json").read_bytes())
    reports = [
        verify_capture_package(package, PLAN_V2_PATH, expected_manifest_sha256=manifest_sha),
        verify_capture_package(package, PLAN_V2_PATH, expected_manifest_sha256="0" * 64),
    ]
    incomplete = tmp_path / "incomplete-v2-report"
    incomplete.mkdir()
    (incomplete / "plan.json").write_bytes(PLAN_V2_PATH.read_bytes())
    plan, plan_content = load_capture_plan(PLAN_V2_PATH)
    (incomplete / "incomplete.json").write_bytes(
        canonical_bytes(
            IncompleteCaptureV2(
                version="eis-search-capture-incomplete-v2",
                status="INCOMPLETE",
                capture_id="report-fields",
                tenant=plan.tenant,
                attempted_at=CLOCK,
                transaction_timestamp=None,
                snapshot_id=None,
                runtime=None,
                plan_sha256=sha256_bytes(plan_content),
                reasons=("SYNTHETIC",),
                actual_relation_rows={},
                files=("plan.json",),
            )
        )
        + b"\n"
    )
    reports.append(verify_capture_package(incomplete, PLAN_V2_PATH))
    assert [report.status for report in reports] == [
        "CAPTURE_CONTENT_VERIFIED",
        "FAIL",
        "INCOMPLETE",
    ]
    for report in reports:
        assert report.model_dump()["raw_width_validation"] == "DECODED_LOWER_BOUND_ONLY"
        assert report.model_dump()["source_raw_width_attestation"] == "UNKNOWN"
    v1 = verify_capture_package(_build_package(tmp_path / "complete-v1"), PLAN_PATH)
    assert "raw_width_validation" not in v1.model_dump()
    assert "source_raw_width_attestation" not in v1.model_dump()


@pytest.mark.parametrize("exhausted", ["files", "bytes"])
def test_payload_budget_refuses_fragment_before_any_payload_emission(
    tmp_path: Path, exhausted: str
) -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    assert isinstance(plan, CapturePlanV2)
    audit = next(item for item in plan.relations if item.name == "audit_events")
    budget = _PackageBudget(plan, time.monotonic())
    if exhausted == "files":
        budget.shards = plan.limits.max_shards
    else:
        budget.payload_bytes = plan.limits.total_payload_bytes
    row = _row(audit, 1)
    row["basis"] = {"padding": "x" * (plan.limits.shard_bytes + 1)}
    writer = _RelationWriterV2(tmp_path, audit, budget, plan)
    with pytest.raises(
        CaptureCollectionError,
        match="SHARD_COUNT_LIMIT" if exhausted == "files" else "PAYLOAD_SIZE_LIMIT",
    ):
        writer.write(row)
    assert not list((tmp_path / "fragments").glob("*.bin"))
    assert writer.logical_rows == 0


@pytest.mark.parametrize("exhausted", ["files", "bytes"])
def test_payload_budget_refuses_non_audit_inline_before_file_open(
    tmp_path: Path, exhausted: str
) -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    assert isinstance(plan, CapturePlanV2)
    spec = next(item for item in plan.relations if item.name == "eis_sync_targets")
    budget = _PackageBudget(plan, time.monotonic())
    if exhausted == "files":
        budget.shards = plan.limits.max_shards
    else:
        budget.payload_bytes = plan.limits.total_payload_bytes
    writer = _RelationWriterV2(tmp_path, spec, budget, plan)
    with pytest.raises(
        CaptureCollectionError,
        match="SHARD_COUNT_LIMIT" if exhausted == "files" else "PAYLOAD_SIZE_LIMIT",
    ):
        writer.write(_row(spec, 1))
    assert not list((tmp_path / "relations").glob("*.jsonl"))


def test_payload_budget_boundary_and_failed_write_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_sync_targets")
    line = encode_row(spec, _row(spec, 1))
    budget = _PackageBudget(plan, time.monotonic())
    budget.shards = plan.limits.max_shards - 1
    budget.payload_bytes = plan.limits.total_payload_bytes - len(line)
    writer = _RelationWriter(tmp_path / "boundary", spec, budget)
    (tmp_path / "boundary").mkdir()
    writer.write_encoded(line, tuple(_row(spec, 1)[name] for name in spec.primary_key))
    writer.finish(1)
    assert budget.shards == plan.limits.max_shards
    assert budget.payload_bytes == plan.limits.total_payload_bytes

    partial_root = tmp_path / "partial-write"
    partial_root.mkdir()
    partial_budget = _PackageBudget(plan, time.monotonic())

    class PartialStream:
        def write(self, value: bytes) -> int:
            return len(value) - 1

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    original_open = Path.open

    def partial_open(path: Path, *args: object, **kwargs: object) -> Any:
        if path.name.endswith(".jsonl"):
            return PartialStream()
        return original_open(path, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(Path, "open", partial_open)
    partial_writer = _RelationWriter(partial_root, spec, partial_budget)
    with pytest.raises(CaptureCollectionError, match="PAYLOAD_PARTIAL_WRITE"):
        partial_writer.write(_row(spec, 2))
    assert partial_budget.shards == 1
    assert partial_budget.payload_bytes == len(encode_row(spec, _row(spec, 2)))
    assert partial_writer.total_rows == 0


@pytest.mark.parametrize("failure", ["deadline", "disk"])
def test_payload_deadline_and_disk_are_checked_before_file_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    plan, _ = load_capture_plan(PLAN_V2_PATH)
    spec = next(item for item in plan.relations if item.name == "eis_sync_targets")
    started = time.monotonic()
    if failure == "deadline":
        started -= plan.limits.capture_timeout_seconds + 1
    else:
        monkeypatch.setattr(
            "procurement.storage.eis_search_capture.shutil.disk_usage",
            lambda _: SimpleNamespace(free=0),
        )
    budget = _PackageBudget(plan, started)
    writer = _RelationWriter(tmp_path, spec, budget)
    with pytest.raises(
        CaptureCollectionError,
        match="CAPTURE_TIMEOUT" if failure == "deadline" else "FREE_DISK_LIMIT_DURING_ROW",
    ):
        writer.write(_row(spec, 1))
    assert not list((tmp_path / "relations").glob("*.jsonl"))
    assert budget.shards == 1
    assert budget.payload_bytes > 0
