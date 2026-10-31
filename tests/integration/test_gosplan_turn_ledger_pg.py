"""Crash-conservative tenant turn ledger; run only on disposable PostgreSQL."""

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.engine import make_url
from test_eis_223_index_pg import storage as pg_storage

from procurement.sources.gosplan_turn_ledger import (
    FINISHED,
    OBJECT,
    STARTED,
    finish_turn,
    start_turn,
)
from procurement.storage.models import audit_events
from procurement.storage.repository import PostgresStorage


@pytest.fixture(scope="module")
def storage():
    url = os.environ.get("DATABASE_URL")
    if os.environ.get("HISTORY_READER_INSTALLED_SCHEMA_TEST") == "1":
        assert url and make_url(url).database == "procurement_eis_test_history"
        engine = create_engine(url, pool_pre_ping=True)
        yield PostgresStorage(engine)
        engine.dispose()
    else:
        yield from pg_storage.__wrapped__()


def start(storage, company):
    return start_turn(
        storage, company, "44", "0122100003226000063", hashlib.sha256(b"{}").hexdigest(), {}
    )


def test_simultaneous_claims_are_serialized_and_crash_blocks(storage):
    company = "turn-" + uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: start(storage, company), range(2)))
    assert sum(bool(v) for v in results) == 1
    turn = next(v for v in results if v)
    assert start(storage, company) is None
    with pytest.raises(ValueError, match="TURN_FINISH_INVALID"):
        finish_turn(storage, company, turn, "UNKNOWN")
    with pytest.raises(ValueError, match="TURN_NOT_ACTIVE"):
        finish_turn(storage, company + "-other", turn, "SYNCED")
    assert start(storage, company) is None
    finish_turn(storage, company, turn, "SYNCED")
    assert start(storage, company) is None
    with pytest.raises(ValueError, match="TURN_NOT_ACTIVE"):
        finish_turn(storage, company, turn, "SYNCED")
    with storage.transaction(company, consistent_read=True) as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.company_id == company, audit_events.c.object_type == OBJECT)
            )
            == 2
        )


def test_old_unfinished_blocks_new_hour_and_other_tenant_isolated(storage):
    company = "old-turn-" + uuid4().hex
    when = datetime.now(UTC) - timedelta(days=2)
    with storage.transaction(company) as conn:
        conn.execute(
            insert(audit_events).values(
                company_id=company,
                event_id=uuid4().hex,
                actor_id="test",
                event_type=STARTED,
                object_type=OBJECT,
                object_id=uuid4().hex,
                occurred_at=when,
                basis={"coverage": "UNKNOWN"},
            )
        )
    assert start(storage, company) is None
    other = company + "-other"
    turn = start(storage, other)
    assert turn
    finish_turn(storage, other, turn, "NO_DATA")


def test_old_completed_allows_new_hour(storage):
    company = "old-done-" + uuid4().hex
    turn = uuid4().hex
    when = datetime.now(UTC) - timedelta(days=2)
    with storage.transaction(company) as conn:
        for kind in (STARTED, FINISHED):
            conn.execute(
                insert(audit_events).values(
                    company_id=company,
                    event_id=uuid4().hex,
                    actor_id="test",
                    event_type=kind,
                    object_type=OBJECT,
                    object_id=turn,
                    occurred_at=when,
                    basis={"coverage": "UNKNOWN"},
                )
            )
    new_turn = start(storage, company)
    assert new_turn and new_turn != turn
    finish_turn(storage, company, new_turn, "PREPARING")


@pytest.mark.parametrize("crash", [False, True])
def test_ready_runtime_records_guarded_turn_and_blocks_repetition(
    storage, tmp_path, monkeypatch, crash
):
    import asyncio
    import json
    import runpy
    from contextlib import asynccontextmanager
    from pathlib import Path
    from types import SimpleNamespace

    from procurement.sources.gosplan_discovery import parse_page
    from procurement.sources.gosplan_queue import GosplanQueue, Scope
    from procurement.storage.eis_223_catalog_checks import record_catalog_check
    from procurement.storage.eis_223_regions import ensure_region_wave
    from test_eis_223_regions import catalog_html

    company = "runtime-" + uuid4().hex
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
    monkeypatch.setattr(
        "procurement.eis_freshness_dispatch_cli.resource_gate", lambda *a, **kw: None
    )
    number = "0122100003226000063"
    path = tmp_path / "queue.sqlite"
    queue = GosplanQueue(path)
    raw = json.dumps(
        [{"purchase_number": number, "purchase_type": "epNotificationEF2020", "updated_at": None}]
    ).encode()
    queue.record(
        Scope(company, "44", now - timedelta(days=1), now, 0, 100),
        parse_page(raw, "44", now, 100),
        now,
    )
    queue.close()
    script = Path(__file__).resolve().parents[2] / "scripts/server-gosplan-recovery.py"
    code = runpy.run_path(str(script))
    namespace = code["run"].__globals__
    namespace["release_guard_active"] = lambda: False
    namespace["COMPANY"] = company
    namespace["QUEUE"] = path
    namespace["STATE_ROOT"] = tmp_path
    namespace["PostgresStorage"] = SimpleNamespace(from_url=lambda *a, **kw: storage)
    namespace["urgent44_status"] = lambda *a: "READY"
    namespace["joint_mandatory_status"] = lambda *a: "READY"
    namespace["shutil"] = SimpleNamespace(disk_usage=lambda *a: SimpleNamespace(free=100 * 1024**3))
    calls = []

    @asynccontextmanager
    async def transport():
        yield object()

    async def recover(*args):
        calls.append(1)
        if crash:
            raise RuntimeError("simulated worker interruption")
        return "NO_DATA"

    namespace["eis_browser_transport"] = transport
    namespace["recover_one_44"] = recover
    monkeypatch.setenv("DATABASE_URL", "unused")
    monkeypatch.setenv("EIS_GETDOCS_IP_TOKEN", "synthetic")
    monkeypatch.setenv("GOSPLAN_IMPORT_LEASE_HELD", "1")
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    if crash:
        with pytest.raises(RuntimeError, match="simulated worker interruption"):
            asyncio.run(code["run"]("44", number))
    else:
        assert asyncio.run(code["run"]("44", number))["status"] == "NO_DATA"
    again = asyncio.run(code["run"]("44", number))
    assert again["reason"] == "TURN_UNRESOLVED_OR_HOURLY_LIMIT"
    assert len(calls) == 1
    with storage.transaction(company, consistent_read=True) as conn:
        events = conn.execute(
            select(audit_events.c.event_type, audit_events.c.basis).where(
                audit_events.c.company_id == company, audit_events.c.object_type == OBJECT
            )
        ).all()
    assert sum(row[0] == STARTED for row in events) == 1
    assert sum(row[0] == FINISHED for row in events) == (0 if crash else 1)
    started = next(row[1] for row in events if row[0] == STARTED)
    assert started["evidence"]["snapshot"] and started["evidence_sha256"]
