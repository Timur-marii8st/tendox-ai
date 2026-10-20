"""Real PostgreSQL acceptance for the bounded frozen-search collector."""

from __future__ import annotations

import hashlib
import json
import os
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
from sqlalchemy import Connection, Text, create_engine, func, insert, literal, or_, select, text
from sqlalchemy import cast as sql_cast
from sqlalchemy.engine import make_url
from test_eis_notice_projection_pg import NUMBER, prepare

import procurement.storage.eis_search_capture as capture_module
from procurement.sources.eis_notice_conflicts import diagnose_notice_conflicts
from procurement.sources.eis_notice_projection import (
    _snapshot_payload_bytes,
    prepare_notice_projection,
)
from procurement.sources.eis_search_capture import (
    CaptureManifest,
    CaptureManifestV2,
    CapturePlan,
    CapturePlanV2,
    RelationDescriptor,
    RelationDescriptorV2,
    canonical_bytes,
    iter_encoded_rows,
    load_capture_plan,
    verify_capture_package,
)
from procurement.storage.eis_223_index import ingest_notice223_window
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
TENANT = "local-eis-supplier"
OTHER_TENANT = "capture-foreign-tenant"
CLOCK = datetime(2026, 10, 7, 12, tzinfo=UTC)
MEMORY_LIMIT_BYTES = 2 * 1024**3
LARGE_PROJECTION_MEMBERS = 450
LARGE_PROJECTION_TITLE_PADDING = 3_000
LARGE_PROJECTION_ATTACHMENTS = 14
LARGE_PROJECTION_FILENAME_PADDING = 850


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


def test_large_projection_fixture_retains_bounded_titles_above_one_shard() -> None:
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
    current = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in (
            "src/procurement/sources/eis_search_capture.py",
            "src/procurement/storage/eis_search_capture.py",
        )
    }
    for pin in raw["source_pins"]:
        if pin["path"] in current:
            pin["sha256"] = current[pin["path"]]
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
    return cast(str, app_url), cast(str, admin_url)


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
    try:
        with admin_engine.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == "procurement_owner"
        plan, _ = load_capture_plan(test_plan_path)
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
            plan: CapturePlan | CapturePlanV2,
            root: Path,
            clock: datetime,
            budget: _PackageBudget,
            current_database: Any,
        ) -> tuple[
            tuple[RelationDescriptor | RelationDescriptorV2, ...], dict[str, int]
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
            return original(connection, plan, root, clock, budget, current_database)  # type: ignore[no-any-return]

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
        v2_plan_for_selection, _ = load_capture_plan(PLAN_V2_PATH)
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

        # Build three projection batches from many individually small variants.
        # Their exact aggregate projection audit bases exceed one physical shard,
        # matching the observed production shape without creating an oversized
        # row in any non-audit relation.
        large_audit_event_ids: list[str] = []
        for group in range(3):
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

        v2_plan, _ = load_capture_plan(PLAN_V2_PATH)
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
            assert int(oversized_count) == len(large_audit_event_ids) == 3
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
            PLAN_V2_PATH,
            v2_package,
            tmp_path / "collector-memory.json",
            runtime=runtime_path,
        )
        verifier_memory = _run_measured_child(
            "verify",
            PLAN_V2_PATH,
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
    finally:
        if shadow_schema is not None:
            with admin_engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA IF EXISTS {shadow_schema} CASCADE"))
        app_engine.dispose()
        admin_engine.dispose()
