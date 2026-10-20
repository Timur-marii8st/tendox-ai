"""Bound retention, reject credential reflection and distinguish source reply from absence."""

import importlib.util
import json
import os
import sqlite3
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from procurement.sources import eis_no_data_evidence as m
from procurement.sources.eis_feed import parse_get_docs_ip_response

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
TOKEN = "synthetic-credential-0000"
REQUEST = "00000000-0000-0000-0000-000000000001"
KEY = "getDocsIP/PRIZ/50/2026-09-27+03:00"


def raw_reply(extra="", request=REQUEST, mode="PROD", branch="<noData>true</noData>"):
    return (
        f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        f'<ip:getDocsByOrgRegionResponse xmlns:ip="http://zakupki.gov.ru/fz44/get-docs-ip/ws">'
        "<index><id>00000000-0000-0000-0000-000000000002</id>"
        f"<refId>{request}</refId><createDateTime>2026-10-05T15:00:00+03:00</createDateTime>"
        f"<mode>{mode}</mode></index><dataInfo>{branch}</dataInfo>{extra}"
        "</ip:getDocsByOrgRegionResponse></s:Body></s:Envelope>"
    ).encode()


def retain(root, raw=None, **changes):
    raw = raw or raw_reply()
    args = dict(
        company_id="tenant-a",
        actor_id="worker",
        window_key=KEY,
        request_id=REQUEST,
        observed_at=NOW,
        token=TOKEN,
        root=root,
    )
    return m.retain_no_data_reply(raw, parse_get_docs_ip_response(raw), **(args | changes))


def usage(root):
    with sqlite3.connect(root / m.FILE) as conn:
        return conn.execute("SELECT records,bytes FROM usage WHERE id=1").fetchone()


def test_full_store_continues_in_bounded_overflow_and_keeps_old_references(tmp_path, monkeypatch):
    root = tmp_path / "private"
    first = retain(root)
    before = (root / m.FILE).read_bytes()
    monkeypatch.setattr(m, "MAX_RECORDS", 1)
    second = retain(root, company_id="tenant-b")
    assert second.status == "RETAINED"
    assert second.relative_store_path == "no-data-overflow.sqlite3"
    assert (root / m.FILE).read_bytes() == before
    for company, receipt in (("tenant-a", first), ("tenant-b", second)):
        verified = m.verify_no_data_reply(root, company, KEY, receipt.source_response_sha256)
        assert verified.status == "PASS" and verified.manifest_sha256 == receipt.manifest_sha256
        replay = retain(root, company_id=company)
        assert replay.replayed and replay.manifest_sha256 == receipt.manifest_sha256
    blocked = retain(root, company_id="tenant-c")
    assert (blocked.status, blocked.reason) == ("FAILED", "QUOTA_REACHED")
    assert sorted(p.name for p in root.iterdir()) == [
        "no-data-overflow.sqlite3",
        "no-data.lock",
        m.FILE,
    ]
    assert (
        m.verify_no_data_reply(root, "tenant-c", KEY, first.source_response_sha256).status
        == "UNKNOWN"
    )


def test_corrupt_archive_is_not_hidden_by_overflow(tmp_path, monkeypatch):
    root = tmp_path / "private"
    first = retain(root)
    monkeypatch.setattr(m, "MAX_RECORDS", 1)
    assert retain(root, company_id="tenant-b").status == "RETAINED"
    with sqlite3.connect(root / m.FILE) as conn:
        conn.execute("DROP TRIGGER immutable_update")
        conn.execute("UPDATE replies SET raw=?", (b"corrupt",))
    assert (
        m.verify_no_data_reply(root, "tenant-a", KEY, first.source_response_sha256).status == "FAIL"
    )
    assert retain(root).status == "FAILED"


def test_overflow_is_sticky_and_archive_is_only_read_after_switch(tmp_path, monkeypatch):
    root = tmp_path / "private"
    retain(root)
    with monkeypatch.context() as patch:
        patch.setattr(m, "MAX_RECORDS", 1)
        assert retain(root, company_id="tenant-b").status == "RETAINED"
    before = (root / m.FILE).read_bytes()
    third = retain(root, company_id="tenant-c")
    assert third.status == "RETAINED" and third.relative_store_path == m.OVERFLOW_FILE
    assert (root / m.FILE).read_bytes() == before
    assert usage(root)[0] == 1


def test_concurrent_overflow_writers_preserve_single_receipt(tmp_path, monkeypatch):
    root = tmp_path / "private"
    retain(root)
    monkeypatch.setattr(m, "MAX_RECORDS", 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: retain(root, company_id="tenant-b"), range(2)))
    assert all(r.status == "RETAINED" for r in results)
    assert {r.relative_store_path for r in results} == {m.OVERFLOW_FILE}
    assert sum(not r.replayed for r in results) == 1
    assert len({r.manifest_sha256 for r in results}) == 1


def test_rotation_lock_is_bounded_and_does_not_modify_archive(tmp_path):
    root = tmp_path / "private"
    retain(root)
    before = (root / m.FILE).read_bytes()
    with m._retention_lock(root):
        result = retain(root, company_id="tenant-b")
    assert (result.status, result.reason) == ("FAILED", "STORE_BUSY")
    assert (root / m.FILE).read_bytes() == before
    assert not (root / m.OVERFLOW_FILE).exists()


def test_allocated_page_budget_full_rotates_before_reusing_free_cells(tmp_path, monkeypatch):
    root = tmp_path / "private"
    retain(root, raw_reply(extra="<padding>" + "x" * 16000 + "</padding>"))
    archive = root / m.FILE
    before = archive.read_bytes()
    monkeypatch.setattr(m, "MAX_DATABASE_BYTES", archive.stat().st_size)
    result = retain(root, company_id="tenant-b")
    assert result.status == "RETAINED" and result.relative_store_path == m.OVERFLOW_FILE
    assert archive.read_bytes() == before


def test_retained_exact_bytes_offline_parser_and_duplicate_replay(tmp_path):
    root = tmp_path / "private"
    result = retain(root)
    assert result.status == "RETAINED" and not result.replayed
    with sqlite3.connect(root / m.FILE) as conn:
        raw, metadata = conn.execute("SELECT raw,manifest FROM replies").fetchone()
    assert raw == raw_reply() and TOKEN.encode() not in raw + metadata
    assert "raw" not in json.loads(metadata)
    before = usage(root)
    replay = retain(root, observed_at=NOW + timedelta(seconds=1))
    assert replay.replayed and replay.manifest == result.manifest
    assert replay.manifest_sha256 == result.manifest_sha256 and usage(root) == before
    verified = m.verify_no_data_reply(root, "tenant-a", KEY, result.source_response_sha256)
    assert verified.status == "PASS" and verified.manifest == result.manifest
    assert (
        verified.coverage
        == verified.source_absence
        == verified.independent_corroboration
        == "UNKNOWN"
    )
    if os.name != "nt":
        assert (root / m.FILE).stat().st_mode & 0o777 == 0o600
        assert root.stat().st_mode & 0o777 == 0o700


def test_tenant_scoped_identity_and_missing_artifact_is_unknown(tmp_path):
    root = tmp_path / "private"
    first = retain(root)
    assert (
        m.verify_no_data_reply(root, "tenant-b", KEY, first.source_response_sha256).status
        == "UNKNOWN"
    )
    second = retain(root, company_id="tenant-b")
    assert first.record_key != second.record_key and usage(root)[0] == 2
    assert (
        m.verify_no_data_reply(
            tmp_path / "absent", "tenant-a", KEY, first.source_response_sha256
        ).status
        == "UNKNOWN"
    )
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize(
    "encoded",
    [
        TOKEN,
        TOKEN.replace("s", "&#115;", 1),
        "".join(f"&#{ord(c)};" for c in TOKEN),
        f"{TOKEN[:10]}<split/>{TOKEN[10:]}",
    ],
)
def test_plain_entity_and_split_reflection_never_touch_store(tmp_path, encoded):
    root = tmp_path / "private"
    result = retain(root, raw_reply(f"<sourceNote>{encoded}</sourceNote>"))
    assert (result.status, result.reason) == ("FAILED", "RESPONSE_UNSAFE")
    assert not root.exists() and TOKEN not in result.model_dump_json()


@pytest.mark.parametrize("change", [{"company_id": TOKEN}, {"actor_id": TOKEN}, {"token": ""}])
def test_config_reflection_is_rejected_before_metadata(tmp_path, change):
    with pytest.raises(ValueError, match="RETENTION_CONFIG"):
        retain(tmp_path / "private", **change)
    assert not (tmp_path / "private").exists()


@pytest.mark.parametrize(
    "raw,changes",
    [
        (raw_reply(mode="TEST"), {}),
        (raw_reply(), {"request_id": str(uuid.uuid4())}),
        (raw_reply(extra="<padding>" + "x" * 65536 + "</padding>"), {}),
        (
            raw_reply().replace(
                b"<s:Body>", b"<s:Header><credential>opaque</credential></s:Header><s:Body>"
            ),
            {},
        ),
        (raw_reply().decode().encode("utf-16"), {}),
    ],
    ids=["test-mode", "wrong-request", "oversize", "soap-header", "utf16"],
)
def test_nonproduction_wrong_request_oversize_header_and_encoding_not_retained(
    tmp_path, raw, changes
):
    assert retain(tmp_path / "private", raw, **changes).status == "FAILED"
    assert not (tmp_path / "private").exists()


def test_body_must_match_parsed_response_hash(tmp_path):
    raw = raw_reply()
    reply = replace(parse_get_docs_ip_response(raw), source_sha256="f" * 64)
    result = m.retain_no_data_reply(
        raw,
        reply,
        company_id="tenant-a",
        actor_id="worker",
        window_key=KEY,
        request_id=REQUEST,
        observed_at=NOW,
        token=TOKEN,
        root=tmp_path / "private",
    )
    assert result.reason == "BINDING_REJECTED" and not (tmp_path / "private").exists()


def test_dtd_is_rejected_before_untrusted_elementtree_expansion(tmp_path, monkeypatch):
    raw = raw_reply()
    valid = parse_get_docs_ip_response(raw)
    hostile = b'<!DOCTYPE x [<!ENTITY s "boom">]>' + raw
    monkeypatch.setattr(m.ET, "fromstring", lambda *_: pytest.fail("DTD reached ElementTree"))
    result = m.retain_no_data_reply(
        hostile,
        valid,
        company_id="tenant-a",
        actor_id="worker",
        window_key=KEY,
        request_id=REQUEST,
        observed_at=NOW,
        token=TOKEN,
        root=tmp_path / "private",
    )
    assert result.status == "FAILED" and not (tmp_path / "private").exists()


@pytest.mark.parametrize("quota", ["MAX_RECORDS", "MAX_PAYLOAD_BYTES"])
def test_quota_preserves_existing_record_and_replay(tmp_path, monkeypatch, quota):
    root = tmp_path / "private"
    original = retain(root)
    old_usage = usage(root)
    monkeypatch.setattr(m, quota, old_usage[0] if quota == "MAX_RECORDS" else old_usage[1])
    assert retain(root, observed_at=NOW + timedelta(seconds=1)).status == "RETAINED"
    overflow = retain(root, company_id="tenant-b")
    assert overflow.status == "RETAINED" and overflow.relative_store_path == m.OVERFLOW_FILE
    rejected = retain(root, company_id="tenant-c")
    assert (rejected.status, rejected.reason) == ("FAILED", "QUOTA_REACHED")
    assert usage(root) == old_usage
    assert (
        m.verify_no_data_reply(root, "tenant-a", KEY, original.source_response_sha256).status
        == "PASS"
    )


def test_physical_page_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MAX_DATABASE_BYTES", 4096)
    result = retain(tmp_path / "private")
    assert (result.status, result.reason) == ("FAILED", "QUOTA_REACHED")
    assert (tmp_path / "private" / m.FILE).stat().st_size <= 4096


def test_sqlite_writes_are_immutable_and_tampering_fails_verification(tmp_path):
    root = tmp_path / "private"
    original = retain(root)
    with sqlite3.connect(root / m.FILE) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
            conn.execute("UPDATE replies SET raw=?", (b"changed",))
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
            conn.execute("DELETE FROM replies")
        # Simulate privileged corruption; application never drops its triggers.
        conn.execute("DROP TRIGGER immutable_update")
        conn.execute("UPDATE replies SET raw=?", (raw_reply(request=str(uuid.uuid4())),))
    assert (
        m.verify_no_data_reply(root, "tenant-a", KEY, original.source_response_sha256).status
        == "FAIL"
    )
    assert retain(root).status == "FAILED"


def test_transaction_failure_rolls_back_blob_and_quota(tmp_path, monkeypatch):
    root = tmp_path / "private"
    retain(root)
    before = usage(root)
    original = m._writer

    class Broken:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            if sql.startswith("UPDATE usage"):
                raise sqlite3.OperationalError("synthetic failure")
            return self.conn.execute(sql, *args)

        def close(self):
            self.conn.close()

        def commit(self):
            self.conn.commit()

    monkeypatch.setattr(m, "_writer", lambda p: Broken(original(p)))
    result = retain(root, company_id="tenant-b")
    assert result.status == "FAILED" and usage(root) == before
    assert (
        m.verify_no_data_reply(root, "tenant-b", KEY, result.source_response_sha256).status
        == "UNKNOWN"
    )


def test_two_writers_cannot_duplicate_quota_or_blob(tmp_path):
    root = tmp_path / "private"
    retain(root)  # Schema is committed before two independent writer connections race.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: retain(root, observed_at=NOW + timedelta(seconds=1)), range(2))
        )
    assert all(r.status == "RETAINED" and r.replayed for r in results)
    assert usage(root)[0] == 1


def test_busy_writer_does_not_block_source_indefinitely(tmp_path):
    root = tmp_path / "private"
    retain(root)
    with sqlite3.connect(root / m.FILE) as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = retain(root, company_id="tenant-b")
        assert (result.status, result.reason) == ("FAILED", "STORE_BUSY")


def test_symlink_store_is_rejected(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    foreign = tmp_path / "foreign"
    foreign.write_bytes(b"do not touch")
    try:
        (root / m.FILE).symlink_to(foreign)
    except OSError:
        pytest.skip("symlink permission unavailable")
    assert retain(root).status == "FAILED"
    assert foreign.read_bytes() == b"do not touch"


def test_wrong_application_database_is_not_modified(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    with sqlite3.connect(root / m.FILE) as conn:
        conn.execute("CREATE TABLE other(value)")
    os.chmod(root / m.FILE, 0o600)
    assert retain(root).reason == "STORE_UNSAFE"
    with sqlite3.connect(root / m.FILE) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("other",)
        ]


def test_retention_disabled_keeps_absence_unknown():
    result = retain(None)
    assert result.status == "DISABLED" and result.coverage == "UNKNOWN"
    with pytest.raises(ValidationError):
        m.NoDataRetention(**(result.model_dump() | {"status": "RETAINED"}))


def reporter():
    spec = importlib.util.spec_from_file_location(
        "no_data_offline_report",
        Path(__file__).resolve().parents[1] / "scripts/server-eis-no-data-evidence-report.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_store_configuration_default_override_and_explicit_disable(monkeypatch, tmp_path):
    monkeypatch.delenv("EIS_NO_DATA_EVIDENCE_DIR", raising=False)
    monkeypatch.delenv("EIS_BROWSER_STATE_DIR", raising=False)
    assert m.no_data_evidence_root() is None
    monkeypatch.setenv("EIS_BROWSER_STATE_DIR", str(tmp_path))
    assert m.no_data_evidence_root() == tmp_path / "no-data-evidence"
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", str(tmp_path / "other"))
    assert m.no_data_evidence_root() == tmp_path / "other"
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", "")
    assert m.no_data_evidence_root() is None


def test_offline_reader_time_bound_and_read_only_guard():
    r = reporter()
    for since in (
        NOW.replace(tzinfo=None),
        NOW - timedelta(days=7, microseconds=1),
        NOW + timedelta(seconds=1),
    ):
        with pytest.raises(ValueError):
            r.validate_since(since, NOW)

    class Connection:
        def scalar(self, _):
            return "off"

    with pytest.raises(ValueError, match="SNAPSHOT"):
        r.read_report(Connection(), NOW, 20)


def test_isolated_pg_offline_raw_audit_attempt_binding(tmp_path, monkeypatch):
    app_url, admin_url = os.getenv("DATABASE_URL"), os.getenv("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL required")
    if "procurement_eis_test_" not in app_url or "procurement_eis_test_" not in admin_url:
        pytest.fail("explicit isolated database required")
    from sqlalchemy import create_engine, func, select

    from procurement.sources.eis_feed_sync import EisDateSelection
    from procurement.storage.eis_no_data_evidence import record_no_data_evidence
    from procurement.storage.eis_sync_journal import EisSyncJournal
    from procurement.storage.models import audit_events, eis_sync_attempts
    from procurement.storage.repository import PostgresStorage

    engine = create_engine(app_url)
    storage = PostgresStorage(engine)
    r = reporter()
    company = r.COMPANY
    root = tmp_path / "private"
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", str(root))
    try:
        with storage.transaction(company, consistent_read=True) as conn:
            now = conn.scalar(select(func.clock_timestamp()))
        journal = EisSyncJournal(storage, company, "worker")
        journal.plan((EisDateSelection("50", datetime(2026, 9, 27).date(), 3),))
        receipt = retain(root, company_id=company, observed_at=now)
        event = record_no_data_evidence(storage, company, receipt, actor_id="worker")
        # An audit/raw capture alone is not evidence of a completed journal attempt.
        with storage.transaction(company, consistent_read=True) as conn:
            incomplete = r.read_report(conn, now, 20)
        assert incomplete.records[0].journal_match_status == "UNKNOWN"
        attempt_id = journal.record(
            KEY, "NO_DATA", source_response_sha256=receipt.source_response_sha256
        )
        with storage.transaction(company, consistent_read=True) as conn:
            before = tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (audit_events, eis_sync_attempts)
            )
            proof = r.read_report(conn, now, 20)
            after = tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (audit_events, eis_sync_attempts)
            )
        assert before == after
        assert proof.retention_status_counts == {"RETAINED": 1}
        assert len(proof.records) == 1 and str(proof.records[0].audit_event_id) == event
        assert str(proof.records[0].journal_attempt_id) == attempt_id
        assert (
            proof.records[0].journal_match_status == proof.records[0].verification.status == "PASS"
        )
        assert (
            proof.coverage == proof.source_absence == proof.independent_corroboration == "UNKNOWN"
        )
        next_request = str(uuid.uuid4())
        with storage.transaction(company, consistent_read=True) as conn:
            next_at = conn.scalar(select(func.clock_timestamp()))
        with monkeypatch.context() as patch:
            patch.setattr(m, "MAX_RECORDS", 1)
            overflow = retain(
                root,
                raw_reply(request=next_request),
                request_id=next_request,
                company_id=company,
                observed_at=next_at,
            )
        assert overflow.status == "RETAINED" and overflow.relative_store_path == m.OVERFLOW_FILE
        record_no_data_evidence(storage, company, overflow, actor_id="worker")
        journal.record(KEY, "NO_DATA", source_response_sha256=overflow.source_response_sha256)
        with storage.transaction(company, consistent_read=True) as conn:
            both = r.read_report(conn, now, 20)
        ours = [item for item in both.records if item.receipt.window_key == KEY]
        assert len(ours) == 2
        assert all(item.verification.status == item.journal_match_status == "PASS" for item in ours)
        assert {item.receipt.relative_store_path for item in ours} == set(m.STORE_FILES)
    finally:
        engine.dispose()


def test_isolated_postgres_retention_and_quota_audit_are_tenant_scoped(tmp_path, monkeypatch):
    app_url, admin_url = os.getenv("DATABASE_URL"), os.getenv("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL credentials required")
    if "procurement_eis_test_" not in app_url or "procurement_eis_test_" not in admin_url:
        pytest.fail("explicit isolated database required")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select

    from procurement.storage.eis_no_data_evidence import record_no_data_evidence
    from procurement.storage.models import audit_events, eis_feed_windows
    from procurement.storage.repository import PostgresStorage

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", admin_url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(app_url)
    storage = PostgresStorage(engine)
    try:
        receipt = retain(tmp_path / "private")
        event = record_no_data_evidence(storage, "tenant-a", receipt, actor_id="worker")
        with storage.transaction("tenant-a", consistent_read=True) as conn:
            row = (
                conn.execute(select(audit_events).where(audit_events.c.event_id == event))
                .mappings()
                .one()
            )
            assert row["company_id"] == "tenant-a" and row["actor_id"] == "worker"
            assert row["basis"]["evidence"] == receipt.model_dump(mode="json")
            assert row["basis"]["coverage"] == "UNKNOWN"
            assert not conn.execute(select(eis_feed_windows)).first()
        with storage.transaction("tenant-b", consistent_read=True) as conn:
            assert not conn.execute(
                select(audit_events).where(audit_events.c.event_id == event)
            ).first()
        monkeypatch.setattr(m, "MAX_RECORDS", 1)
        overflow = retain(
            tmp_path / "private",
            raw_reply(request=str(uuid.UUID(int=2))),
            request_id=str(uuid.UUID(int=2)),
        )
        assert overflow.status == "RETAINED" and overflow.relative_store_path == m.OVERFLOW_FILE
        record_no_data_evidence(storage, "tenant-a", overflow, actor_id="worker")
        failed = retain(
            tmp_path / "private",
            raw_reply(request=str(uuid.UUID(int=3))),
            request_id=str(uuid.UUID(int=3)),
        )
        assert failed.status == "FAILED" and failed.reason == "QUOTA_REACHED"
        failed_event = record_no_data_evidence(storage, "tenant-a", failed, actor_id="worker")
        with storage.transaction("tenant-a", consistent_read=True) as conn:
            basis = conn.scalar(
                select(audit_events.c.basis).where(audit_events.c.event_id == failed_event)
            )
            assert basis["evidence"]["status"] == "FAILED" and basis["coverage"] == "UNKNOWN"
        with pytest.raises(ValueError):
            record_no_data_evidence(storage, "tenant-b", receipt, actor_id="worker")
        with pytest.raises(ValueError):
            record_no_data_evidence(storage, "tenant-a", retain(None), actor_id="worker")
    finally:
        engine.dispose()
