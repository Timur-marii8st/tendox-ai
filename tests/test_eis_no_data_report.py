"""A source hash and repeated empty responses must not imply absence or completeness."""

import hashlib
import importlib.util
import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "eis_no_data_report", ROOT / "scripts/server-eis-no-data-report.py"
)
r = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r
spec.loader.exec_module(r)
NOW = datetime(2026, 10, 5, 0, tzinfo=UTC)
SHA = "a" * 64


def fixture(**changes):
    recent = r.Cohort(
        day=date(2026, 9, 28),
        document_type=r.KINDS[0],
        no_data=2,
        due=1,
        cooldown=1,
        within_recent_dates=True,
        oldest_attempt_at=NOW - timedelta(hours=24),
        newest_attempt_at=NOW - timedelta(hours=23),
    )
    older = r.Cohort(
        day=date(2026, 9, 27),
        document_type=r.KINDS[0],
        no_data=1,
        due=1,
        cooldown=0,
        within_recent_dates=False,
        oldest_attempt_at=NOW - timedelta(days=4),
        newest_attempt_at=NOW - timedelta(days=4),
    )
    samples = tuple(
        r.Sample(
            window_key=f"getDocsIP/PRIZ/01/{c.day}+03:00",
            attempt_id=uuid.uuid4(),
            attempted_at=c.oldest_attempt_at,
            source_response_sha256=SHA,
            eligible_for_recent_reserve=c.within_recent_dates,
        )
        for c in (recent, older)
    )
    values = dict(
        checked_at=NOW,
        snapshot="synthetic",
        first_day=date(2026, 9, 1),
        last_day=date(2026, 10, 4),
        cohorts=(older, recent),
        samples=samples,
        latest_no_data=3,
        due_recent=1,
        due_older=1,
        cooldown=1,
        oldest_due_age_seconds=4 * 86400,
    )
    return r.Report(**(values | changes))


def test_exact_24h_due_and_seven_completed_msk_dates():
    proof = fixture()
    assert proof.samples[0].attempted_at == NOW - timedelta(hours=24)
    assert proof.cohorts[0].within_recent_dates is False
    assert proof.cohorts[1].within_recent_dates is True
    assert proof.source_absence == proof.coverage == proof.independent_corroboration == "UNKNOWN"


@pytest.mark.parametrize(
    "changes",
    [
        {"due_recent": 0},
        {"due_older": 0},
        {"cooldown": 0},
        {"latest_no_data": 4},
        {"oldest_due_age_seconds": None},
        {"samples": ()},
        {"coverage": "PASS"},
        {"source_requests": 1},
        {"database_writes": 1},
        {"company_id": "another-tenant"},
    ],
)
def test_invalid_proof_cannot_be_persisted(changes):
    with pytest.raises(ValidationError):
        fixture(**changes)


@pytest.mark.parametrize(
    "change",
    [
        {"oldest_attempt_at": NOW - timedelta(hours=24) + timedelta(microseconds=1)},
        {"newest_attempt_at": NOW + timedelta(microseconds=1)},
        {"within_recent_dates": False},
        {"due": 2},
    ],
)
def test_cohort_future_boundary_and_parity_rejected(change):
    base = fixture()
    changed = r.Cohort(**(base.cohorts[1].model_dump() | change))
    with pytest.raises(ValidationError):
        fixture(cohorts=(base.cohorts[0], changed))


@pytest.mark.parametrize(
    "change",
    [
        {"attempted_at": NOW - timedelta(hours=24) + timedelta(microseconds=1)},
        {"window_key": "getDocsIP/PRIZ/01/2026-09-28+03:00/epNotificationEZK2020"},
        {"eligible_for_recent_reserve": False},
    ],
)
def test_sample_cooldown_wrong_scope_and_lane_rejected(change):
    base = fixture()
    sample = r.Sample(**(base.samples[0].model_dump() | change))
    with pytest.raises(ValidationError):
        fixture(samples=(sample, base.samples[1]))


@pytest.mark.parametrize(
    "first,last",
    [
        (date(2026, 7, 6), date(2026, 10, 4)),  # 91 days
        (date(2026, 10, 5), date(2026, 10, 5)),
        (date(2026, 10, 4), date(2026, 10, 3)),
    ],
)
def test_range_is_bounded_and_completed(first, last):
    with pytest.raises(ValueError):
        r.validate_range(first, last, NOW)


def test_90_day_range_and_moscow_midnight():
    r.validate_range(date(2026, 7, 7), date(2026, 10, 4), NOW)
    r.validate_range(date(2026, 10, 4), date(2026, 10, 4), NOW - timedelta(hours=3))
    with pytest.raises(ValueError):
        r.validate_range(
            date(2026, 10, 4), date(2026, 10, 4), NOW - timedelta(hours=3, microseconds=1)
        )
    with pytest.raises(ValueError):
        r.validate_range(date(2026, 10, 4), date(2026, 10, 4), NOW.replace(tzinfo=None))


def test_sql_latest_is_chosen_before_outcome_with_exact_tenant_planned_and_canonical():
    query = select(r.pending_query(date(2026, 9, 1), date(2026, 10, 4)))
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "DISTINCT ON" in sql and "attempt_id DESC" in sql
    assert sql.index("attempt_id DESC") < sql.index("outcome = 'NO_DATA'")
    assert "eis_sync_targets.company_id = 'local-eis-supplier'" in sql
    assert "eis_feed_windows.company_id = 'local-eis-supplier'" in sql
    assert "NOT (EXISTS" in sql and "LEGACY_CANONICAL" in sql
    assert "pg_input_is_valid" in sql and "CASE WHEN" in sql
    assert "VARIANT_TRANSPORT" not in sql and "content" not in sql


@pytest.mark.parametrize(
    "readonly,isolation", [("off", "repeatable read"), ("on", "read committed")]
)
def test_bad_snapshot_mode_never_executes_query(readonly, isolation):
    class Connection:
        def scalar(self, query):
            return readonly if str(query) == "SHOW transaction_read_only" else isolation

    with pytest.raises(ValueError, match="READ_ONLY_SNAPSHOT"):
        r.read_report(Connection(), date(2026, 9, 1), date(2026, 10, 4))


def test_immutable_private_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "ROOT", tmp_path)
    monkeypatch.setattr(r.uuid, "uuid4", lambda: uuid.UUID(int=1))
    path, sha = r.save_report(fixture())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    assert r.Report.model_validate_json(path.read_bytes()).source_absence == "UNKNOWN"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        r.save_report(fixture())


def test_actual_pg_latest_tenant_canonical_variant_invalid_date_and_read_only():
    app_url, admin_url = os.getenv("DATABASE_URL"), os.getenv("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL credentials required")
    if "procurement_eis_test_" not in app_url or "procurement_eis_test_" not in admin_url:
        pytest.fail("explicitly isolated database required")
    from alembic import command
    from alembic.config import Config

    from procurement.storage.models import audit_events
    from procurement.storage.models import eis_feed_windows as feed
    from procurement.storage.models import eis_sync_attempts as attempts
    from procurement.storage.models import eis_sync_targets as targets
    from procurement.storage.repository import PostgresStorage

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", admin_url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(app_url)
    storage = PostgresStorage(engine)
    try:
        with storage.transaction(r.COMPANY, consistent_read=True) as conn:
            now = conn.scalar(select(func.clock_timestamp()))
        day = now.astimezone(r.MOSCOW).date() - timedelta(days=2)
        old_day = day - timedelta(days=9)
        keys = [f"getDocsIP/PRIZ/{i:02d}/{day}+03:00" for i in range(1, 8)]
        invalid = "getDocsIP/PRIZ/08/2026-02-30+03:00"
        old_key = f"getDocsIP/PRIZ/09/{old_day}+03:00"

        def target(key, company=r.COMPANY):
            return dict(
                company_id=company,
                window_key=key,
                planned_by="test",
                planned_at=now - timedelta(days=15),
                coverage="UNKNOWN",
            )

        def attempt(key, outcome="NO_DATA", company=r.COMPANY, hours=30, identity=None):
            return dict(
                company_id=company,
                window_key=key,
                actor_id="test",
                attempt_id=identity or str(uuid.uuid4()),
                outcome=outcome,
                reason_code="SOURCE_FAILURE" if outcome == "FAILED" else None,
                source_response_sha256=SHA if outcome == "NO_DATA" else None,
                attempted_at=now - timedelta(hours=hours),
            )

        with storage.transaction(r.COMPANY) as conn:
            conn.execute(insert(targets), [target(k) for k in (*keys, invalid, old_key)])
            rows = [attempt(k) for k in (*keys, invalid, old_key)]
            rows += [attempt(keys[1], "FAILED", hours=29), attempt(keys[2], hours=23)]
            # Exact timestamp tie: UUID DESC selects FAILED, not earlier NO_DATA.
            rows[3] = attempt(keys[3], identity=str(uuid.UUID(int=1)))
            rows += [attempt(keys[3], "FAILED", identity=str(uuid.UUID(int=2)))]
            conn.execute(insert(attempts), rows)
            for key, kind in ((keys[4], "LEGACY_CANONICAL"), (keys[5], "VARIANT_TRANSPORT")):
                conn.execute(
                    insert(feed).values(
                        company_id=r.COMPANY,
                        window_key=key,
                        response_sha256="b" * 64,
                        manifest_sha256="c" * 64,
                        archive_count=1,
                        notice_count=0,
                        coverage="UNKNOWN",
                        ingested_at=now,
                        intake_kind=kind,
                    )
                )
        with storage.transaction("other-tenant") as conn:
            conn.execute(insert(targets), target(keys[0], "other-tenant"))
            conn.execute(insert(attempts), attempt(keys[0], "FAILED", "other-tenant", hours=1))
        with storage.transaction(r.COMPANY, consistent_read=True) as conn:
            before = tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (targets, attempts, feed, audit_events)
            )
            proof = r.read_report(conn, old_day, day)
            after = tuple(
                conn.scalar(select(func.count()).select_from(t))
                for t in (targets, attempts, feed, audit_events)
            )
        assert before == after
        assert (proof.latest_no_data, proof.due_recent, proof.due_older, proof.cooldown) == (
            5,
            3,
            1,
            1,
        )
        assert {s.window_key for s in proof.samples} == {keys[0], keys[5], keys[6], old_key}
        assert proof.source_absence == proof.coverage == "UNKNOWN"
    finally:
        engine.dispose()
