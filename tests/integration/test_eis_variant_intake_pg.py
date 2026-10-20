"""Automatic source conflict progress never closes an ordinary checkpoint."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_eis_notice_index_pg import storage as storage_fixture

from procurement.sources import eis_corpus, eis_feed_sync, eis_freshness, eis_variant_intake
from procurement.sources.eis_feed_sync import EisDateSelection, EisRejectedWindowError
from procurement.sources.eis_freshness import EisFreshnessScope, FreshnessTarget
from procurement.sources.eis_freshness_status import EisWindowObservation
from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_notice_hold import read_notice_source_hold
from procurement.storage.eis_notice_index import (
    EisReadyWindow,
    has_ingested_window,
    ingest_ready_window,
)
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.models import (
    audit_events,
    eis_feed_windows,
    eis_notice_projection_batches,
    eis_notice_projection_decisions,
    eis_notice_variant_receipts,
    eis_notice_versions,
    eis_sync_attempts,
)
from test_eis_feed_sync import TOKEN, FakeTransport
from test_eis_notice_conflicts import bundle, notice

SELECTION = EisDateSelection("50", date(2026, 9, 25), 3)
NUMBER = "0373100047426001450"
OTHER = "0373100047426001451"


@pytest.fixture(scope="module")
def storage():
    yield from storage_fixture.__wrapped__()


class RetainedTransport(FakeTransport):
    def __init__(self, archives):
        super().__init__(expect_date=True)
        self.archives = archives

    async def download(self, url, token):
        assert (url, token) == (self.prepared_url, TOKEN)
        self.downloads += 1
        return 200, self.archives


def setup_source(monkeypatch, tmp_path):
    monkeypatch.setenv("EIS_REJECTED_EVIDENCE_DIR", str(tmp_path))
    monkeypatch.setattr(
        eis_feed_sync, "uuid4", lambda: UUID("33333333-3333-4333-8333-333333333333")
    )
    return bundle(
        ("first.xml", notice(title="Бумага")),
        ("second.xml", notice(title="Бумага", start="2026-10-01T10:01:00+03:00")),
        ("other.xml", notice(title="Бумага").replace(NUMBER.encode(), OTHER.encode())),
    )


def tenant_counts(storage, company):
    tables = (
        eis_feed_windows,
        eis_notice_versions,
        eis_notice_variant_receipts,
        eis_notice_projection_batches,
        eis_notice_projection_decisions,
        eis_sync_attempts,
        audit_events,
    )
    with storage.transaction(company, consistent_read=True) as conn:
        return {
            table.name: conn.scalar(select(func.count()).select_from(table)) for table in tables
        }


def test_real_sync_refresh_persists_partial_observation_and_exact_replay(
    storage, monkeypatch, tmp_path
):
    archives = setup_source(monkeypatch, tmp_path)
    company = "automatic-" + str(uuid4())
    journal = EisSyncJournal(storage, company, "test")
    journal.plan((SELECTION,))
    target = FreshnessTarget(SELECTION, "RECONCILE_DAY", timedelta(hours=24))
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: (target,))
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(eis_freshness.asyncio, "sleep", AsyncMock())
    scope = EisFreshnessScope(("50",))
    transport = RetainedTransport(archives)
    first = asyncio.run(
        eis_freshness.run_freshness(
            journal, TOKEN, scope, now=datetime.now(UTC), transport=transport
        )
    )
    intake = first.observations[0].variant_intake
    assert intake.status == "PARTIAL" and intake.projection.held_count == 1
    assert first.synced == 0 and first.partial_windows == first.failed == first.new_versions == 1
    assert not has_ingested_window(storage, company, SELECTION.window_key)
    assert len(journal.gaps()) == 1 and journal.gaps()[0].last_outcome == "FAILED"
    assert read_notice_source_hold(storage, company, NUMBER, 1).status == "HOLD"
    assert read_notice_source_hold(storage, company, OTHER, 1).status == "NO_HOLD"
    assert search_eis_index(storage, company, "бумага", now=datetime.now(UTC)).matched_count == 1
    with storage.transaction(company) as conn:
        basis = conn.execute(
            select(audit_events.c.basis).where(
                audit_events.c.event_type == "EIS_SYNC_ATTEMPT_RECORDED"
            )
        ).scalar_one()
        assert EisWindowObservation.model_validate(basis["observation"]) == first.observations[0]
        assert conn.scalar(select(eis_feed_windows.c.intake_kind)) == "VARIANT_TRANSPORT"
    before = tenant_counts(storage, company)
    replay = asyncio.run(
        eis_freshness.run_freshness(
            journal, TOKEN, scope, now=datetime.now(UTC), transport=transport
        )
    )
    assert replay.new_versions == replay.synced == 0 and replay.partial_windows == 1
    assert replay.replayed_projection_batches == 1 and replay.held_pairs == 1
    after = tenant_counts(storage, company)
    for table in (
        eis_feed_windows,
        eis_notice_versions,
        eis_notice_variant_receipts,
        eis_notice_projection_batches,
        eis_notice_projection_decisions,
    ):
        assert before[table.name] == after[table.name]
    assert after[eis_sync_attempts.name] - before[eis_sync_attempts.name] == 1
    assert after[audit_events.name] - before[audit_events.name] == 1
    assert transport.posts == 4 and transport.downloads == 2


def test_interrupted_projection_leaves_ledger_hold_and_recovers(storage, monkeypatch, tmp_path):
    archives = setup_source(monkeypatch, tmp_path)
    company = "interrupted-" + str(uuid4())
    transport = RetainedTransport(archives)
    writer = eis_variant_intake.project_retained_notice_variants
    monkeypatch.setattr(
        eis_variant_intake,
        "project_retained_notice_variants",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("SECRET late failure")),
    )
    with pytest.raises(EisRejectedWindowError) as caught:
        asyncio.run(
            eis_feed_sync.sync_eis_window(storage, company, "test", SELECTION, TOKEN, transport)
        )
    failed = caught.value.variant_intake
    assert failed.status == "FAILED" and failed.stage == "PROJECTION"
    assert failed.ledger_receipt_id is not None and "SECRET" not in str(
        caught.value.safe_metadata()
    )
    assert read_notice_source_hold(storage, company, OTHER, 1).status == "HOLD"
    before = tenant_counts(storage, company)
    assert before[eis_notice_versions.name] == before[eis_notice_projection_batches.name] == 0
    monkeypatch.setattr(eis_variant_intake, "project_retained_notice_variants", writer)
    with pytest.raises(EisRejectedWindowError) as retried:
        asyncio.run(
            eis_feed_sync.sync_eis_window(storage, company, "test", SELECTION, TOKEN, transport)
        )
    assert retried.value.variant_intake.status == "PARTIAL"
    assert retried.value.variant_intake.ledger_receipt_id == failed.ledger_receipt_id
    assert tenant_counts(storage, company)[eis_notice_variant_receipts.name] == 1
    assert read_notice_source_hold(storage, company, OTHER, 1).status == "NO_HOLD"
    assert not has_ingested_window(storage, company, SELECTION.window_key)


def test_transport_only_retry_without_internal_duplicate_remains_explicit(
    storage, monkeypatch, tmp_path
):
    setup_source(monkeypatch, tmp_path)
    company = "transport-retry-" + str(uuid4())
    original = bundle(("original.xml", notice(title="Бумага original")))
    ingest_ready_window(
        storage,
        company,
        EisReadyWindow("getDocsIP/PRIZ/50/2026-09-24+03:00", "a" * 64, 1, (original,)),
        actor_id="test",
    )
    transport = RetainedTransport(bundle(("changed.xml", notice(title="Бумага changed"))))
    for expected_reason in ("NOTICE_VERSION_CONFLICT", "TRANSPORT_WINDOW_NOT_CANONICAL"):
        with pytest.raises(EisRejectedWindowError, match=expected_reason) as caught:
            asyncio.run(
                eis_feed_sync.sync_eis_window(storage, company, "test", SELECTION, TOKEN, transport)
            )
        assert caught.value.variant_intake.status == "PARTIAL"
        assert caught.value.variant_intake.projection.held_count == 1
        assert caught.value.variant_intake.new_versions == 0
        assert not has_ingested_window(storage, company, SELECTION.window_key)
    assert read_notice_source_hold(storage, company, NUMBER, 1).status == "HOLD"


def test_all_singleton_corpus_still_failed_and_partial_audit_is_durable(
    storage, monkeypatch, tmp_path
):
    setup_source(monkeypatch, tmp_path)
    company = "all-singleton-" + str(uuid4())
    journal = EisSyncJournal(storage, company, "test")
    journal.plan((SELECTION,))
    monkeypatch.setattr(eis_corpus, "eligible_windows", lambda *a, **k: (SELECTION.window_key,))
    monkeypatch.setattr(eis_corpus, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(eis_corpus.asyncio, "sleep", AsyncMock())
    xml = notice(title="Бумага")
    transport = RetainedTransport(bundle(("a.xml", xml), ("b.xml", xml)))
    result = asyncio.run(
        eis_corpus.run_corpus(journal, TOKEN, now=datetime.now(UTC), transport=transport)
    )
    assert result["partial_windows"] == result["new_versions"] == 1
    assert result["synced"] == result["held_pairs"] == 0
    assert not has_ingested_window(storage, company, SELECTION.window_key)
    assert journal.gaps()[0].last_outcome == "FAILED"
    with storage.transaction(company) as conn:
        basis = conn.execute(
            select(audit_events.c.basis).where(
                audit_events.c.event_type == "EIS_SYNC_ATTEMPT_RECORDED"
            )
        ).scalar_one()
        assert basis["variant_intake"]["projection"]["held_count"] == 0
        assert basis["variant_intake"]["status"] == "PARTIAL"
        assert basis["outcome"] == "FAILED" and basis["source_response_sha256"] is not None
    from procurement.sources.eis_variant_intake import EisVariantIntakeReport

    intake = EisVariantIntakeReport.model_validate(basis["variant_intake"])
    for bad in (
        dict(outcome="SYNCED", source_response_sha256=basis["source_response_sha256"]),
        dict(outcome="FAILED", reason_code="DUPLICATE_NOTICE_VERSION", source_response_sha256=None),
    ):
        with pytest.raises(ValueError, match="JOURNAL_VARIANT_INTAKE_MISMATCH"):
            journal.record(SELECTION.window_key, variant_intake=intake, **bad)
