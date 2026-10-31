import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from procurement.sources.gosplan_discovery import parse_page
from procurement.sources.gosplan_queue import GosplanQueue, Scope
from procurement.sources.gosplan_recovery import recover_one_44

NOW = datetime(2026, 10, 28, tzinfo=UTC)
NUMBER = "0122100003226000063"


def test_recovery_claims_and_records_only_official_result(tmp_path, monkeypatch):
    q = GosplanQueue(tmp_path / "queue.sqlite")
    raw = json.dumps(
        [{"purchase_number": NUMBER, "purchase_type": "epNotificationEF2020"}]
    ).encode()
    page = parse_page(raw, "44", NOW, 100)
    q.record(Scope("tenant", "44", NOW - timedelta(days=1), NOW, 0, 100), page, NOW)

    async def source(*args):
        assert q.conn.execute("SELECT outcome FROM attempts").fetchone() == (None,)
        return SimpleNamespace(
            purchase_number=NUMBER,
            status="SYNCED",
            source_response_sha256="a" * 64,
            latest_version_number=2,
            latest_xml_sha256="b" * 64,
        )

    monkeypatch.setattr("procurement.sources.gosplan_recovery.sync_eis_number", source)
    assert asyncio.run(recover_one_44(q, None, "tenant", NUMBER, "token", None)) == "SYNCED"
    assert q.conn.execute("SELECT outcome,official_sha FROM attempts").fetchone() == (
        "SYNCED",
        "a" * 64,
    )
    q.close()


def test_error_remains_unknown_and_cannot_become_success(tmp_path, monkeypatch):
    q = GosplanQueue(tmp_path / "queue.sqlite")
    raw = json.dumps(
        [{"purchase_number": NUMBER, "purchase_type": "epNotificationEF2020"}]
    ).encode()
    q.record(
        Scope("tenant", "44", NOW - timedelta(days=1), NOW, 0, 100),
        parse_page(raw, "44", NOW, 100),
        NOW,
    )

    async def source(*args):
        raise ValueError("untrusted error")

    monkeypatch.setattr("procurement.sources.gosplan_recovery.sync_eis_number", source)
    assert asyncio.run(recover_one_44(q, None, "tenant", NUMBER, "token", None)) == "UNKNOWN"
    assert q.conn.execute("SELECT outcome,official_sha FROM attempts").fetchone() == (
        "UNKNOWN",
        None,
    )
    q.close()


def test_new_observation_after_success_is_not_lost(tmp_path, monkeypatch):
    q = GosplanQueue(tmp_path / "queue.sqlite")
    raw = json.dumps(
        [{"purchase_number": NUMBER, "purchase_type": "epNotificationEF2020"}]
    ).encode()
    first = q.record(
        Scope("tenant", "44", NOW - timedelta(days=1), NOW, 0, 100),
        parse_page(raw, "44", NOW, 100),
        NOW,
    )

    async def source(*args):
        later = NOW + timedelta(seconds=1)
        q.record(
            Scope("tenant", "44", NOW - timedelta(days=1), NOW, 0, 100),
            parse_page(raw, "44", later, 100),
            later,
        )
        return SimpleNamespace(
            purchase_number=NUMBER,
            status="SYNCED",
            source_response_sha256="a" * 64,
            latest_version_number=2,
            latest_xml_sha256="b" * 64,
        )

    monkeypatch.setattr("procurement.sources.gosplan_recovery.sync_eis_number", source)
    assert asyncio.run(recover_one_44(q, None, "tenant", NUMBER, "token", None)) == "SYNCED"
    assert len(q.pending("tenant")) == 1
    assert q.pending("tenant")[0][2] != first
    q.close()


def test_223_unsupported_family_does_not_claim_or_call_source(tmp_path):
    from procurement.sources.gosplan_recovery import recover_one_223

    q = GosplanQueue(tmp_path / "queue.sqlite")
    raw = json.dumps(
        [{"purchase_number": "32616349722", "purchase_type": "purchaseNotice"}]
    ).encode()
    q.record(
        Scope("tenant", "223", NOW - timedelta(days=1), NOW, 0, 100),
        parse_page(raw, "223", NOW, 100),
        NOW,
    )
    assert (
        asyncio.run(recover_one_223(q, None, "tenant", "32616349722", "token", None))
        == "UNSUPPORTED"
    )
    assert q.conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
    q.close()


def test_223_supported_claims_and_records_official_status(tmp_path, monkeypatch):
    from procurement.sources import eis_223_number_sync
    from procurement.sources.gosplan_recovery import recover_one_223

    q = GosplanQueue(tmp_path / "queue.sqlite")
    raw = json.dumps(
        [{"purchase_number": "32616349722", "purchase_type": "purchaseNoticeZPESMBO"}]
    ).encode()
    q.record(
        Scope("tenant", "223", NOW - timedelta(days=1), NOW, 0, 100),
        parse_page(raw, "223", NOW, 100),
        NOW,
    )

    async def source(*args):
        assert q.conn.execute("SELECT outcome FROM attempts").fetchone() == (None,)
        return SimpleNamespace(
            purchase_number="32616349722",
            status="SYNCED",
            source_response_sha256="a" * 64,
            latest_version_number=6,
            latest_xml_sha256="b" * 64,
        )

    monkeypatch.setattr(eis_223_number_sync, "sync_223_number", source)
    assert asyncio.run(recover_one_223(q, None, "tenant", "32616349722", "token", None)) == "SYNCED"
    assert q.pending("tenant") == []
    q.close()


def test_direct_44_recovery_rejects_unsupported_before_source(tmp_path, monkeypatch):
    q = GosplanQueue(tmp_path / "queue.sqlite")
    raw = json.dumps(
        [{"purchase_number": NUMBER, "purchase_type": "epNotificationEZT2020"}]
    ).encode()
    q.record(
        Scope("tenant", "44", NOW - timedelta(days=1), NOW, 0, 100),
        parse_page(raw, "44", NOW, 100), NOW,
    )

    async def source(*_args):
        raise AssertionError("must not call EIS")

    monkeypatch.setattr("procurement.sources.gosplan_recovery.sync_eis_number", source)
    assert asyncio.run(recover_one_44(q, None, "tenant", NUMBER, "token", None)) == "UNSUPPORTED"
    assert q.conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
    assert len(q.pending("tenant")) == 1
    q.close()
