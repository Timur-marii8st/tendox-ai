"""Never turn missing retention visibility or inconsistent quota counters into PASS."""

import hashlib
import importlib.util
import os
import sqlite3
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from procurement.sources import eis_no_data_evidence as evidence
from test_eis_no_data_evidence import NOW, raw_reply, retain

spec = importlib.util.spec_from_file_location(
    "no_data_store_report", Path(__file__).parents[1] / "scripts/server-eis-no-data-store-report.py"
)
report = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = report
spec.loader.exec_module(report)


def digest(root):
    return hashlib.sha256((root / evidence.FILE).read_bytes()).hexdigest()


def test_exact_metadata_headroom_and_tenant_age_without_writes(tmp_path):
    root = tmp_path / "private"
    retain(root, company_id=report.COMPANY, observed_at=NOW - timedelta(days=30))
    retain(root, company_id="foreign-tenant", observed_at=NOW - timedelta(days=100))
    retain(
        root,
        raw_reply(request=str(uuid.UUID(int=3))),
        company_id=report.COMPANY,
        request_id=str(uuid.UUID(int=3)),
        observed_at=NOW - timedelta(hours=1),
    )
    before = digest(root)
    result = report.read_store(root, NOW)
    assert result.status == "PASS" and result.rows.used == 3
    assert result.tenant_rows == 2 and result.tenant_review_age_rows == 1
    assert result.tenant_oldest_at == NOW - timedelta(days=30)
    assert result.tenant_newest_at == NOW - timedelta(hours=1)
    assert result.payload.remaining == evidence.MAX_PAYLOAD_BYTES - result.payload.used
    assert result.database.remaining == evidence.MAX_DATABASE_BYTES - result.database.used
    assert result.rows.remaining == evidence.MAX_RECORDS - 3
    assert "foreign-tenant" not in result.model_dump_json()
    assert "raw" not in result.model_dump_json()
    assert digest(root) == before
    assert not Path(str(root / evidence.FILE) + "-journal").exists()
    assert report.action_for(result, 0, 0) == "PLAN_ARCHIVE"


def test_missing_and_disabled_are_unknown_without_filesystem_writes(tmp_path):
    assert report.read_store(None, NOW).reason == "DISABLED"
    result = report.read_store(tmp_path / "absent", NOW)
    assert result.status == "UNKNOWN" and result.reason == "STORE_MISSING"
    assert result.rows is result.tenant_rows is None
    assert not (tmp_path / "absent").exists()
    assert report.action_for(result, 0, 0) == "RESTORE_VISIBILITY"


def test_overflow_has_independent_quota_and_missing_archive_blocks_visibility(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    retain(root, company_id=report.COMPANY)
    with monkeypatch.context() as patch:
        patch.setattr(evidence, "MAX_RECORDS", 1)
        second = retain(root, company_id="foreign-tenant")
        assert second.status == "RETAINED"
    first = report.read_store(root, NOW)
    overflow = report.read_store(root, NOW, store_file=evidence.OVERFLOW_FILE)
    assert first.rows.used == overflow.rows.used == 1
    assert overflow.tenant_rows == 0
    assert "foreign-tenant" not in overflow.model_dump_json()
    full = first.model_copy(
        update={"database": report.quota(evidence.MAX_DATABASE_BYTES, evidence.MAX_DATABASE_BYTES)}
    )
    assert report.action_for(full, 0, 0, overflow) == "OBSERVE"
    assert report.action_for(full, 1, 0, overflow) == "INVESTIGATE_FAILURES"
    unavailable = report.read_store(tmp_path / "missing", NOW)
    assert report.action_for(unavailable, 0, 0, overflow) == "RESTORE_VISIBILITY"
    assert report.action_for(full, 0, 0, unavailable) == "RESTORE_VISIBILITY"


@pytest.mark.parametrize(
    "corruption", ["counter", "size", "future", "naive", "tenant", "json", "schema", "blob"]
)
def test_inconsistent_store_is_fail_not_empty_success(tmp_path, corruption):
    root = tmp_path / "private"
    retain(root, company_id=report.COMPANY)
    with sqlite3.connect(root / evidence.FILE) as conn:
        if corruption == "counter":
            conn.execute("UPDATE usage SET records=records+1")
        elif corruption == "schema":
            conn.execute("PRAGMA user_version=2")
        else:
            conn.execute("DROP TRIGGER immutable_update")
            if corruption == "size":
                conn.execute("UPDATE replies SET payload_bytes=payload_bytes+1")
            elif corruption == "blob":
                conn.execute("UPDATE replies SET raw='bad'")
            else:
                import json

                data = json.loads(conn.execute("SELECT manifest FROM replies").fetchone()[0])
                if corruption == "future":
                    data["captured_at"] = (NOW + timedelta(seconds=1)).isoformat()
                if corruption == "naive":
                    data["captured_at"] = "2026-10-05T12:00:00"
                if corruption == "tenant":
                    data["company_id"] = "foreign-tenant"
                blob = b"invalid" if corruption == "json" else json.dumps(data).encode()
                conn.execute(
                    "UPDATE replies SET manifest=?,payload_bytes=length(raw)+?", (blob, len(blob))
                )
                conn.execute("UPDATE usage SET bytes=(SELECT SUM(payload_bytes) FROM replies)")
    before = digest(root)
    result = report.read_store(root, NOW)
    assert result.status == "FAIL" and result.reason == "STORE_INVALID"
    assert result.rows is None and digest(root) == before


def test_busy_timeout_is_unknown_and_preserves_store(tmp_path):
    root = tmp_path / "private"
    retain(root, company_id=report.COMPANY)
    conn = sqlite3.connect(root / evidence.FILE, isolation_level=None)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        result = report.read_store(root, NOW)
        assert result.status == "UNKNOWN" and result.reason == "STORE_UNAVAILABLE"
    finally:
        conn.close()
    assert report.read_store(root, NOW).status == "PASS"


def test_manifest_processing_deadline_is_unknown(tmp_path, monkeypatch):
    root = tmp_path / "private"
    retain(root, company_id=report.COMPANY)
    ticks = iter((0, 3))
    monkeypatch.setattr(report.time, "monotonic", lambda: next(ticks, 3))
    assert report.read_store(root, NOW).reason == "STORE_UNAVAILABLE"


def test_quota_threshold_and_failure_actions_are_exact(tmp_path):
    root = tmp_path / "private"
    retain(root, company_id=report.COMPANY)
    result = report.read_store(root, NOW)
    assert report.action_for(result, 0, 0) == "OBSERVE"
    low = evidence.MAX_RECORDS * 80 // 100
    below = result.model_copy(update={"rows": report.quota(low, evidence.MAX_RECORDS)})
    at = result.model_copy(update={"rows": report.quota(low + 1, evidence.MAX_RECORDS)})
    assert report.action_for(below, 0, 0) == "OBSERVE"
    assert report.action_for(at, 0, 0) == "PLAN_ARCHIVE"
    assert report.action_for(at, 1, 0) == report.action_for(at, 0, 1) == "INVESTIGATE_FAILURES"
    with pytest.raises(ValidationError):
        report.Quota(used=1, limit=2, remaining=2)
    with pytest.raises(ValidationError):
        report.quota(evidence.MAX_RECORDS + 1, evidence.MAX_RECORDS)


@pytest.mark.parametrize(
    "since",
    [
        NOW.replace(tzinfo=None),
        NOW - timedelta(days=7, microseconds=1),
        NOW + timedelta(microseconds=1),
    ],
)
def test_period_bounds_fail_before_connection(since):
    with pytest.raises(ValueError):
        report.validate_since(since, NOW)


def test_snapshot_guard_before_query():
    class NotReadonly:
        def scalar(self, query):
            return "off"

    with pytest.raises(ValueError, match="SNAPSHOT_INVALID"):
        report.read_report(NotReadonly(), NOW)


def test_isolated_pg_failure_and_missing_audit_are_tenant_scoped(tmp_path, monkeypatch):
    app_url, admin_url = os.getenv("DATABASE_URL"), os.getenv("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL required")
    if any("procurement_eis_test_" not in url for url in (app_url, admin_url)):
        pytest.fail("explicit isolated database required")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, func, insert, select, text

    from procurement.sources.eis_feed_sync import EisDateSelection
    from procurement.storage.eis_no_data_evidence import record_no_data_evidence
    from procurement.storage.eis_sync_journal import EisSyncJournal
    from procurement.storage.models import audit_events, eis_sync_attempts
    from procurement.storage.repository import PostgresStorage

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", admin_url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(app_url)
    storage = PostgresStorage(engine)
    root = tmp_path / "private"
    monkeypatch.setenv("EIS_NO_DATA_EVIDENCE_DIR", str(root))
    try:
        with storage.transaction(report.COMPANY, consistent_read=True) as conn:
            now = conn.scalar(text("SELECT clock_timestamp()"))
        since = now
        key = "getDocsIP/PRIZ/50/2026-10-03+03:00"
        kept = retain(root, company_id=report.COMPANY, window_key=key, observed_at=now)
        record_no_data_evidence(storage, report.COMPANY, kept, actor_id="worker")

        def attempt(company, window, sha):
            journal = EisSyncJournal(storage, company, "worker")
            journal.plan((EisDateSelection("50", date(2026, 10, 3), 3),))
            journal.record(window, "NO_DATA", source_response_sha256=sha)

        attempt(report.COMPANY, key, kept.source_response_sha256)
        attempt(report.COMPANY, key, "f" * 64)  # same window, different SHA is not corroboration
        foreign = retain(root, company_id="foreign-tenant", window_key=key, observed_at=now)
        record_no_data_evidence(storage, "foreign-tenant", foreign, actor_id="worker")
        attempt("foreign-tenant", key, foreign.source_response_sha256)
        failed = evidence.NoDataRetention(
            status="FAILED",
            reason="QUOTA_REACHED",
            company_id=report.COMPANY,
            window_key=key,
            observed_at=now,
            source_response_sha256="c" * 64,
        )
        record_no_data_evidence(storage, report.COMPANY, failed, actor_id="worker")
        attempt(report.COMPANY, key, "c" * 64)
        with storage.transaction(report.COMPANY, consistent_read=True) as conn:
            before = tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (audit_events, eis_sync_attempts)
            )
            result = report.read_report(conn, since)
            after = tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (audit_events, eis_sync_attempts)
            )
        assert before == after
        assert result.retained_events == result.failed_events == 1
        assert result.failure_counts == {"QUOTA_REACHED": 1} and len(result.failure_samples) == 1
        assert result.no_data_attempts == 3 and result.attempts_without_capture_audit == 1
        assert result.audit_completeness == "UNKNOWN" and result.action == "INVESTIGATE_FAILURES"
        assert result.store.tenant_rows == 1 and result.store.rows.used == 2
        assert result.coverage == result.source_absence == "UNKNOWN"
        assert "foreign-tenant" not in result.model_dump_json()

        # A busy window has many distinct replies and duplicate capture events.
        # Capture duplicates must not multiply attempts; wrong actor and late
        # capture must not conceal missing evidence.
        with storage.transaction(report.COMPANY) as conn:
            at = conn.scalar(text("SELECT clock_timestamp()"))
            audit_rows, attempt_rows = [], []
            for index in range(2000):
                sha = f"{index + 1000:064x}"
                receipt = failed.model_copy(
                    update={"source_response_sha256": sha, "observed_at": at}
                )
                for _ in range(2):
                    audit_rows.append(
                        dict(
                            company_id=report.COMPANY,
                            event_id=str(uuid.uuid4()),
                            actor_id="bulk-worker",
                            event_type="EIS_NO_DATA_RESPONSE_EVIDENCE",
                            object_type="eis_sync_target",
                            object_id=key,
                            occurred_at=at,
                            basis={"evidence": receipt.model_dump(mode="json")},
                        )
                    )
                attempt_rows.append(
                    dict(
                        company_id=report.COMPANY,
                        attempt_id=str(uuid.uuid4()),
                        window_key=key,
                        actor_id="bulk-worker",
                        outcome="NO_DATA",
                        source_response_sha256=sha,
                        attempted_at=at,
                    )
                )
            wrong_actor = dict(attempt_rows[0], attempt_id=str(uuid.uuid4()), actor_id="other")
            before_capture = dict(
                attempt_rows[1],
                attempt_id=str(uuid.uuid4()),
                attempted_at=at - timedelta(microseconds=1),
            )
            conn.execute(insert(audit_events), audit_rows)
            conn.execute(insert(eis_sync_attempts), [*attempt_rows, wrong_actor, before_capture])
        with storage.transaction(report.COMPANY, consistent_read=True) as conn:
            bulk = report.read_report(conn, since)
        assert bulk.no_data_attempts == 2005
        assert bulk.attempts_without_capture_audit == 3
        assert bulk.failed_events == 4001
        assert bulk.audit_completeness == "UNKNOWN"
        assert bulk.coverage == bulk.source_absence == "UNKNOWN"
    finally:
        engine.dispose()
