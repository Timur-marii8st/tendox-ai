"""Isolated PostgreSQL proof for the source-free V62 observation reader."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, text
from sqlalchemy.exc import DBAPIError
from test_eis_223_index_pg import storage as pg_storage

import procurement.eis_history_reader as reader
from procurement.sources.eis_223_regions import REGION_SELECTOR_URL
from procurement.storage.eis_223_catalog_checks import record_catalog_check
from procurement.storage.eis_223_regions import ensure_region_wave, register_region_catalog
from procurement.storage.models import eis_223_region_targets
from test_eis_223_regions import catalog_html

NOW = datetime(2026, 10, 28, 5, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def storage():
    if os.environ.get("HISTORY_READER_INSTALLED_SCHEMA_TEST") == "1":
        from procurement.storage.repository import PostgresStorage

        url = os.environ["DATABASE_URL"]
        if "procurement_eis_test_" not in url:
            pytest.fail("isolated database required")
        engine = create_engine(url, pool_pre_ping=True)
        yield PostgresStorage(engine)
        engine.dispose()
    else:
        yield from pg_storage.__wrapped__()


@pytest.fixture(autouse=True)
def time_and_resources(monkeypatch):
    monkeypatch.setattr(reader, "_utcnow", lambda: NOW)
    monkeypatch.setattr(
        "procurement.eis_freshness_dispatch_cli.resource_gate", lambda *a, **k: None
    )


def seed(storage, company, *, wave=True):
    record_catalog_check(
        storage,
        company,
        catalog_html(),
        actor_id="test",
        checked_at=NOW,
        http_status=200,
        attempt_id="accepted-1",
    )
    if wave:
        return ensure_region_wave(storage, company, NOW, actor_id="test")
    return None


def test_missing_legacy_catalog_and_missing_wave_fail_closed(storage):
    import hashlib

    missing = "missing-" + uuid4().hex
    assert (
        reader.read_history_demand(storage, missing).classification.reason == "CATALOG_UNAVAILABLE"
    )
    raw = catalog_html()
    register_region_catalog(
        storage,
        missing,
        raw,
        source_url=REGION_SELECTOR_URL,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        observed_at=NOW,
        actor_id="test",
    )
    assert (
        reader.read_history_demand(storage, missing).classification.reason
        == "CATALOG_ACCEPTANCE_MISSING"
    )
    seed(storage, missing, wave=False)
    assert (
        reader.read_history_demand(storage, missing).classification.reason
        == "CURRENT_REGIONAL_WAVE_MISSING"
    )


def test_real_snapshot_proves_due_and_foreign_isolation(storage):
    company = "history-" + uuid4().hex
    wave = seed(storage, company)
    result = reader.read_history_demand(storage, company)
    assert result.classification.status == "READY"
    assert result.snapshot and result.wave_id == wave and result.catalog_check_id == "accepted-1"
    assert result.source_requests == result.writes == 0 and result.coverage == "UNKNOWN"
    assert (
        reader.read_history_demand(storage, company + "-foreign").classification.status == "BLOCKED"
    )
    assert len(result.evidence_sha256) == 64


def test_partial_wave_fails_closed(storage, monkeypatch):
    import procurement.storage.eis_223_regions as regions

    company = "partial-" + uuid4().hex
    real_plan = regions.plan_targets
    monkeypatch.setattr(regions, "plan_targets", lambda *args: real_plan(*args)[:-1])
    seed(storage, company)
    assert reader.read_history_demand(storage, company).classification.reason == (
        "CURRENT_REGIONAL_WAVE_INCOMPLETE"
    )


def test_other_tenant_and_writes_rejected_by_adapter(storage):
    company = "isolation-" + uuid4().hex
    with storage.transaction(company, consistent_read=True) as conn:
        shared = reader._SharedReadStorage(company, conn)
        with pytest.raises(ValueError), shared.transaction(company + "-other"):
            pass
        with pytest.raises(DBAPIError), shared.transaction(company) as shared_conn:
            shared_conn.execute(insert(eis_223_region_targets).values(company_id=company))


def test_deferred_producer_fails_closed(storage, monkeypatch):
    company = "deferred-" + uuid4().hex
    seed(storage, company)
    real_probe = reader.probe_dispatch

    def deferred(*args, **kwargs):
        return real_probe(*args, **kwargs).model_copy(update={"reason": "DEFERRED"})

    monkeypatch.setattr(reader, "probe_dispatch", deferred)
    assert (
        reader.read_history_demand(storage, company).classification.reason
        == "FRESHNESS_DEFERRED_OR_BLOCKED"
    )


def test_snapshot_excludes_concurrent_accepted_check(storage, monkeypatch):
    from procurement.storage.eis_223_catalog_checks import catalog_refresh_due

    company = "snapshot-" + uuid4().hex
    record_catalog_check(
        storage,
        company,
        catalog_html(),
        actor_id="test",
        checked_at=NOW - timedelta(hours=25),
        http_status=200,
        attempt_id="accepted-1",
    )
    ensure_region_wave(storage, company, NOW, actor_id="test")
    real_probe = reader.probe_dispatch

    def concurrent(*args, **kwargs):
        record_catalog_check(
            storage,
            company,
            None,
            actor_id="test",
            checked_at=NOW,
            reason="TIMEOUT",
            attempt_id="later-failure",
        )
        return real_probe(*args, **kwargs)

    monkeypatch.setattr(reader, "probe_dispatch", concurrent)
    result = reader.read_history_demand(storage, company)
    assert result.classification.status == "READY", result.classification.reason
    assert result.evidence["observation"]["catalog_refresh_due"] is True
    assert catalog_refresh_due(storage, company, NOW) is False


def test_real_statement_timeout_blocks(storage, monkeypatch):
    company = "timeout-" + uuid4().hex
    seed(storage, company)

    def slow(shared, company, *args, **kwargs):
        with shared.transaction(company, consistent_read=True) as conn:
            conn.execute(text("SELECT pg_sleep(6)"))

    monkeypatch.setattr(reader, "probe_dispatch", slow)
    result = reader.read_history_demand(storage, company)
    assert result.classification.reason == "READ_UNAVAILABLE"
    assert result.source_requests == result.writes == 0


def test_substituted_target_with_same_count_fails_closed(storage, monkeypatch):
    import procurement.storage.eis_223_regions as regions

    company = "substitute-" + uuid4().hex
    real_plan = regions.plan_targets

    def substitute(*args):
        planned = real_plan(*args)
        key = regions.refresh_window_key(planned[0])
        date = planned[0].day.isoformat()
        replacement = key.replace(date, "2026-10-25")
        return (regions.target_from_key(replacement), *planned[1:])

    monkeypatch.setattr(regions, "plan_targets", substitute)
    seed(storage, company)
    assert reader.read_history_demand(storage, company).classification.reason == (
        "CURRENT_REGIONAL_WAVE_INCOMPLETE"
    )


def test_evidence_hash_can_be_recomputed(storage):
    import hashlib
    import json

    company = "evidence-" + uuid4().hex
    seed(storage, company)
    result = reader.read_history_demand(storage, company)
    assert result.classification.status == "READY"
    assert result.evidence is not None
    assert result.evidence["company_id"] == company
    assert result.evidence["observation"]["reconciliation223"]["coordinates"]
    encoded = json.dumps(result.evidence, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == result.evidence_sha256


def test_new_accepted_catalog_does_not_validate_old_wave(storage):
    company = "catalog-change-" + uuid4().hex
    seed(storage, company)
    record_catalog_check(
        storage,
        company,
        catalog_html(("50", "77", "78", "79")),
        actor_id="test",
        checked_at=NOW,
        http_status=200,
        attempt_id="zz-new-catalog",
    )
    result = reader.read_history_demand(storage, company)
    assert result.classification.reason == "CURRENT_REGIONAL_WAVE_CATALOG_MISMATCH"
    assert result.source_requests == result.writes == 0


def seed_clear(storage, company):
    from procurement.sources.eis_freshness import EisFreshnessScope
    from procurement.storage.eis_223_regions import plan_targets
    from procurement.storage.eis_223_sync import refresh_window_key
    from procurement.storage.models import (
        eis_223_event_sync_attempts,
        eis_223_lot_event_sync_attempts,
        eis_223_sync_attempts,
        eis_sync_attempts,
        eis_sync_targets,
    )

    seed(storage, company)
    earlier = NOW - timedelta(minutes=1)
    scope = EisFreshnessScope(("50", "77", "78"), checkpointed=True, mandatory_only=True)
    keys44 = [item.selection.window_key for item in scope.targets(NOW)]
    today = NOW.date()
    keys223 = [
        refresh_window_key(t) for t in plan_targets(scope.regions, today - timedelta(days=1), today)
    ]
    groups = {
        eis_223_sync_attempts: [],
        eis_223_event_sync_attempts: [],
        eis_223_lot_event_sync_attempts: [],
    }
    for key in keys223:
        table = (
            eis_223_event_sync_attempts
            if key.endswith("/purchaseRejection")
            else eis_223_lot_event_sync_attempts
            if key.endswith("/purchaseLotCancellation")
            else eis_223_sync_attempts
        )
        groups[table].append(
            dict(
                company_id=company,
                attempt_id=uuid4().hex,
                window_key=key,
                status="NO_DATA",
                response_sha256="a" * 64,
                checked_at=earlier,
            )
        )
    with storage.transaction(company) as conn:
        conn.execute(
            insert(eis_sync_targets),
            [
                dict(
                    company_id=company,
                    window_key=key,
                    planned_by="test",
                    planned_at=earlier,
                    coverage="UNKNOWN",
                )
                for key in keys44
            ],
        )
        conn.execute(
            insert(eis_sync_attempts),
            [
                dict(
                    company_id=company,
                    attempt_id=uuid4().hex,
                    window_key=key,
                    actor_id="test",
                    outcome="NO_DATA",
                    source_response_sha256="b" * 64,
                    attempted_at=earlier,
                )
                for key in keys44
            ],
        )
        for table, rows in groups.items():
            conn.execute(insert(table), rows)
    return keys44, keys223


def test_real_terminal_queues_return_idle_without_claiming_coverage(storage):
    company = "idle-" + uuid4().hex
    seed_clear(storage, company)
    result = reader.read_history_demand(storage, company)
    assert result.classification.status == "IDLE", result.classification.reason
    assert result.evidence["observation"]["reconciliation44"]["status"] == "CLEAR"
    assert result.evidence["observation"]["reconciliation223"]["status"] == "CLEAR"
    assert result.coverage == "UNKNOWN" and result.writes == result.source_requests == 0


@pytest.mark.parametrize("law", ["44", "223"])
def test_recent_failed_attempt_is_blocked_even_during_cooldown(storage, law):
    from procurement.storage.models import eis_223_sync_attempts, eis_sync_attempts

    company = "cooldown-" + uuid4().hex
    keys44, keys223 = seed_clear(storage, company)
    with storage.transaction(company) as conn:
        if law == "44":
            key = next(key for key in keys44 if "2026-10-27+03:00" in key)
            conn.execute(
                insert(eis_sync_attempts).values(
                    company_id=company,
                    attempt_id="z-failed",
                    window_key=key,
                    actor_id="test",
                    outcome="FAILED",
                    reason_code="TIMEOUT",
                    attempted_at=NOW,
                )
            )
        else:
            key = next(
                key
                for key in keys223
                if "2026-10-27+03:00" in key and key.endswith("purchaseNotice")
            )
            conn.execute(
                insert(eis_223_sync_attempts).values(
                    company_id=company,
                    attempt_id="z-failed",
                    window_key=key,
                    status="FAILED",
                    reason="TIMEOUT",
                    checked_at=NOW,
                )
            )
    result = reader.read_history_demand(storage, company)
    assert result.classification.reason == "MANDATORY_ATTEMPT_UNRESOLVED"


def test_verified_quarantine_stays_ready_without_becoming_clear(storage, monkeypatch, tmp_path):
    import asyncio
    from datetime import timezone
    from unittest.mock import AsyncMock

    from test_eis_variant_intake_pg import TOKEN, RetainedTransport, setup_source

    import procurement.sources.eis_freshness as freshness
    from procurement.eis_history_demand import _reconciliation_days
    from procurement.sources.eis_feed_sync import EisDateSelection
    from procurement.sources.eis_freshness import EisFreshnessScope, FreshnessTarget
    from procurement.storage.eis_sync_journal import EisSyncJournal

    company = "quarantine-" + uuid4().hex
    now = datetime.now(UTC)
    record_catalog_check(
        storage,
        company,
        catalog_html(("50",)),
        actor_id="test",
        checked_at=now,
        http_status=200,
        attempt_id="accepted-1",
    )
    ensure_region_wave(storage, company, now, actor_id="test")
    day = now.astimezone(timezone(timedelta(hours=3))).date() - timedelta(days=2)
    assert day in _reconciliation_days("44", now)
    selection = EisDateSelection("50", day, 3)
    journal = EisSyncJournal(storage, company, "test")
    journal.plan((selection,))
    target = FreshnessTarget(selection, "RECONCILE_DAY", timedelta(days=1))
    archives = setup_source(monkeypatch, tmp_path)
    monkeypatch.setattr(freshness, "eligible_freshness", lambda *a, **k: (target,))
    monkeypatch.setattr(freshness, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(freshness.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(reader, "_utcnow", lambda: datetime.now(UTC))

    class CurrentDayTransport(RetainedTransport):
        async def post(self, raw):
            return await super().post(
                raw.replace((day.isoformat() + "+03:00").encode(), b"2026-09-25+03:00")
            )

    report = asyncio.run(
        freshness.run_freshness(
            journal,
            TOKEN,
            EisFreshnessScope(("50",)),
            now=now,
            transport=CurrentDayTransport(archives),
        )
    )
    assert report.failed == report.partial_windows == 1
    normal = reader.read_history_demand(storage, company)
    assert normal.classification.reason == "MANDATORY_ATTEMPT_UNRESOLVED"
    result = reader.read_history_demand(storage, company, verify_quarantine=True)
    assert result.classification.status == "READY", result.classification.reason
    assert result.coverage == "UNKNOWN" and result.source_requests == result.writes == 0
    assert len(result.evidence["quarantines"]) == 1
    assert result.evidence["quarantines"][0]["source_admission"] == "NOT_GRANTED"
    from procurement.storage.eis_223_sync import record_attempt

    record_attempt(
        storage,
        company,
        f"getDocsIP/RI223/50/{day.isoformat()}+03:00/purchaseNotice",
        "FAILED",
        actor_id="test",
        checked_at=datetime.now(UTC),
        response_sha256=None,
        reason="SYNC_FAILED",
    )
    blocked = reader.read_history_demand(storage, company, verify_quarantine=True)
    assert blocked.classification.reason == "MANDATORY_ATTEMPT_UNRESOLVED"
