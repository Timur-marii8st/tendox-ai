"""Retained projection never closes coverage or overrides conflicting source evidence."""

import hashlib
import os
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from migration_support import assert_direct_downgrade_guard, historical_database
from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from test_eis_document_queue_pg import admit
from test_eis_notice_index_pg import storage as storage_fixture
from test_eis_notice_variants_pg import batch

from procurement.domain.discovery_economics import DiscoveryCostInput
from procurement.sources.eis_corpus import eligible_windows
from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.storage.eis_comparison import EisComparisonRequest, get_eis_comparison
from procurement.storage.eis_document_store import NoticeDocumentRef, get_document_status
from procurement.storage.eis_evidence_bridge import estimate_eis_notice, get_eis_evidence_bridge
from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_notice_hold import notice_variant_hold_clause, read_notice_source_hold
from procurement.storage.eis_notice_index import (
    EisIndexConflict,
    EisReadyWindow,
    has_ingested_window,
    ingest_ready_window,
)
from procurement.storage.eis_notice_projection import project_retained_notice_variants
from procurement.storage.eis_notice_variants import store_notice_variants
from procurement.storage.eis_position_projection import project_notice_positions
from procurement.storage.eis_sync_journal import EisSyncJournal
from procurement.storage.models import (
    audit_events,
    eis_feed_archives,
    eis_feed_windows,
    eis_notice_projection_batches,
    eis_notice_projection_decisions,
    eis_notice_search_keys,
    eis_notice_versions,
    eis_sync_attempts,
)
from test_eis_notice_conflicts import bundle, notice

NOW = datetime(2026, 10, 4, tzinfo=UTC)
NUMBER = "0373100047426001450"
OTHER = "0373100047426001451"
TABLES = (
    eis_feed_windows,
    eis_feed_archives,
    eis_notice_versions,
    eis_notice_search_keys,
    eis_notice_projection_batches,
    eis_notice_projection_decisions,
    eis_sync_attempts,
    audit_events,
)


@pytest.fixture(scope="module")
def storage():
    yield from storage_fixture.__wrapped__()


def counts(storage, company):
    with storage.transaction(company, consistent_read=True) as conn:
        return {t.name: conn.scalar(select(func.count()).select_from(t)) for t in TABLES}


def _assert_search_matches_installed_baseline(storage, company, *, now=None):
    # Freeze the complete installed query, not just the optimized hold helper.
    import importlib.util
    import sys
    from pathlib import Path

    from procurement.storage.eis_search_pagination import PAGE_COMPARISONS

    name = "_history_admission_eis_index_query"
    module = sys.modules.get(name)
    if module is None:
        path = (
            Path(__file__).parents[1]
            / "fixtures/eis_release_baselines/history_admission_eis_index_query.py"
        )
        assert hashlib.sha256(path.read_bytes()).hexdigest() == (
            "a9c4705b4cc7c11d8338a297908c46c63c458fd967ed25b373b77a419ab94426"
        )
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    clock = now or datetime.now(UTC)
    before = counts(storage, company)
    for scope in ("ALL_CACHED", "NOT_EXPIRED_OR_UNKNOWN"):
        for paginate in (False, True):
            for tenant in (company, "other-" + company):
                kwargs = dict(now=clock, search_scope=scope, paginate=paginate, batch_size=1)
                # Cold-cache parity here; warm reuse is covered by pagination PG tests.
                PAGE_COMPARISONS.clear()
                try:
                    actual = search_eis_index(storage, tenant, "бумага", **kwargs)
                    expected = module.search_eis_index(storage, tenant, "бумага", **kwargs)
                    assert actual.reused_candidate_notices == 0  # Every call starts a fresh page.
                    assert actual.compared_candidate_notices == expected.evaluated_candidate_notices
                    actual_payload = actual.model_dump(
                        exclude={
                            "search_elapsed_ms",
                            "compared_candidate_notices",
                            "reused_candidate_notices",
                        }
                    )
                    for lead in actual_payload["matched"]:
                        assert lead.pop("position_set") is None
                    assert actual_payload == expected.model_dump(exclude={"search_elapsed_ms"})
                finally:
                    PAGE_COMPARISONS.clear()
    assert counts(storage, company) == before


def prepare(storage, company, tmp_path, *, members=None, day="29", response="a"):
    members = members or (("a.xml", notice(title="Бумага")),)
    evidence, diagnosis = batch(
        storage, company, tmp_path, members=members, day=day, response=response, observed=NOW
    )
    receipt = store_notice_variants(storage, company, evidence, diagnosis, actor_id="test")
    archives = tuple(
        (tmp_path / company / "blobs" / (sha + ".zip")).read_bytes()
        for sha in evidence.archive_sha256s
    )
    return receipt, archives, evidence


def test_empty_frozen_migration_roundtrip(storage):
    with historical_database(
        expected_database="procurement_eis_test_20261004_s180",
        revision="20261004_03",
    ) as database:
        command.downgrade(database.config, "20261004_02")
        engine = create_engine(database.admin_url)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE eis_feed_windows ADD COLUMN intake_kind TEXT NOT NULL "
                        "DEFAULT 'LEGACY_CANONICAL'"
                    )
                )
                conn.execute(
                    text(
                        "ALTER TABLE eis_feed_windows ADD CONSTRAINT "
                        "ck_eis_feed_windows_intake_kind CHECK (true)"
                    )
                )
            with pytest.raises(DBAPIError, match="unexpected intake kind constraint"):
                command.upgrade(database.config, "20261004_03")
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE eis_feed_windows DROP CONSTRAINT "
                        "ck_eis_feed_windows_intake_kind"
                    )
                )
            command.upgrade(database.config, "20261004_03")
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "20261004_03"
                )
        finally:
            engine.dispose()


def test_transport_only_history_blocks_global_downgrade(storage):
    before = counts(storage, "transport-only")
    with storage.transaction("transport-only") as conn:
        conn.execute(
            insert(eis_feed_windows).values(
                company_id="transport-only",
                window_key="getDocsIP/PRIZ/77/2026-09-29+03:00",
                response_sha256="f" * 64,
                manifest_sha256="e" * 64,
                archive_count=1,
                notice_count=1,
                coverage="UNKNOWN",
                intake_kind="VARIANT_TRANSPORT",
                ingested_at=NOW,
            )
        )
    after_insert = counts(storage, "transport-only")
    assert after_insert[eis_feed_windows.name] == before[eis_feed_windows.name] + 1
    assert_direct_downgrade_guard(
        "20261004_03_eis_notice_projection",
        expected_database="procurement_eis_test_20261004_s180",
        match="notice projection history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    assert counts(storage, "transport-only") == after_insert


def test_all_members_decided_singleton_discharged_conflict_held_and_no_checkpoint(
    storage, tmp_path, monkeypatch
):
    import procurement.storage.eis_sync_journal as journal_module

    class FixedDateTime:
        @staticmethod
        def now(tz):
            assert tz is UTC
            return NOW

    monkeypatch.setattr(journal_module, "datetime", FixedDateTime)
    company = "projection-full-" + uuid4().hex
    members = (
        ("a.xml", notice()),
        ("b.xml", notice(title="Different")),
        (
            "c.xml",
            notice(title="Бумага", extra="<ep:endDT>2099-01-01T00:00:00+03:00</ep:endDT>").replace(
                NUMBER.encode(), OTHER.encode()
            ),
        ),
    )
    receipt, archives, evidence = prepare(storage, company, tmp_path, members=members)
    journal = EisSyncJournal(storage, company, "test")
    journal.plan((EisDateSelection("77", date(2026, 9, 29), 3),))
    journal.record(evidence.window_key, "FAILED", reason_code="DUPLICATE_NOTICE_VERSION")
    before = counts(storage, company)
    report = project_retained_notice_variants(
        storage, company, receipt.receipt_id, archives, actor_id="test"
    )
    assert (report.archive_count, report.occurrence_count, report.pair_count) == (1, 3, 2)
    assert (report.projected_count, report.replayed_count, report.held_count) == (1, 0, 1)
    assert read_notice_source_hold(storage, company, NUMBER, 1).status == "HOLD"
    assert read_notice_source_hold(storage, company, OTHER, 1).status == "NO_HOLD"
    assert not has_ingested_window(storage, company, evidence.window_key)
    assert journal.gaps()[0].window_key == evidence.window_key
    assert evidence.window_key in eligible_windows(journal, now=NOW + timedelta(days=2), limit=10)
    search = search_eis_index(storage, company, "бумага", now=NOW)
    assert search.matched_count == 1 and search.held_current_notices == 0
    assert search.indexed_windows == 0 and search.pending_windows == 1
    _assert_search_matches_installed_baseline(storage, company)
    # Deadline equality is expired; the same installed and optimized scopes agree.
    boundary = datetime(2098, 12, 31, 21, tzinfo=UTC)
    _assert_search_matches_installed_baseline(storage, company, now=boundary)
    active = search_eis_index(
        storage, company, "бумага", now=boundary, search_scope="NOT_EXPIRED_OR_UNKNOWN"
    )
    assert OTHER not in {row.purchase_number for row in active.matched}
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(eis_feed_archives.c.record_count)) == 3
        assert conn.scalar(select(eis_feed_archives.c.content)) == archives[0]
    after = counts(storage, company)
    assert after[eis_sync_attempts.name] == before[eis_sync_attempts.name]
    replay = project_retained_notice_variants(
        storage, company, receipt.receipt_id, archives, actor_id="retry"
    )
    assert replay.replayed and counts(storage, company) == after


def test_same_sha_replay_preserves_canonical_origin_and_legacy_cannot_skip_transport(
    storage, tmp_path
):
    company = "projection-same-" + uuid4().hex
    receipt, archives, evidence = prepare(storage, company, tmp_path)
    canonical_window = EisReadyWindow("getDocsIP/PRIZ/77/2026-09-28+03:00", "c" * 64, 1, archives)
    ingest_ready_window(storage, company, canonical_window, actor_id="test")
    report = project_retained_notice_variants(
        storage, company, receipt.receipt_id, archives, actor_id="test"
    )
    assert report.replayed_count == 1 and report.projected_count == report.held_count == 0
    assert read_notice_source_hold(storage, company, NUMBER, 1).status == "NO_HOLD"
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(eis_notice_versions.c.window_key)) == canonical_window.window_key
    with pytest.raises(EisIndexConflict, match="TRANSPORT_WINDOW_NOT_CANONICAL"):
        ingest_ready_window(
            storage,
            company,
            EisReadyWindow(evidence.window_key, evidence.response_sha256, 1, archives),
            actor_id="test",
        )
    assert not has_ingested_window(storage, company, evidence.window_key)


def test_existing_different_sha_holds_and_never_overwrites(storage, tmp_path):
    company = "projection-conflict-" + uuid4().hex
    receipt, archives, _ = prepare(storage, company, tmp_path)
    old = bundle(("old.xml", notice(title="Old")))
    ingest_ready_window(
        storage,
        company,
        EisReadyWindow("getDocsIP/PRIZ/77/2026-09-28+03:00", "c" * 64, 1, (old,)),
        actor_id="test",
    )
    with storage.transaction(company, consistent_read=True) as conn:
        sha = conn.scalar(select(eis_notice_versions.c.xml_sha256))
    report = project_retained_notice_variants(
        storage, company, receipt.receipt_id, archives, actor_id="test"
    )
    assert report.held_count == 1 and report.projected_count == 0
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(eis_notice_versions.c.xml_sha256)) == sha
    assert search_eis_index(storage, company, "Old", now=NOW).held_current_notices == 1


@pytest.mark.parametrize("version", ["1", "2"])
def test_new_evidence_reholds_projected_search_and_cached_consumers(storage, tmp_path, version):
    company = "projection-later-" + uuid4().hex
    receipt, archives, _ = prepare(storage, company, tmp_path)
    report = project_retained_notice_variants(
        storage, company, receipt.receipt_id, archives, actor_id="test"
    )
    _assert_search_matches_installed_baseline(storage, company)
    sha = hashlib.sha256(notice(title="Бумага")).hexdigest()
    ref = NoticeDocumentRef(purchase_number=NUMBER, version_number=1, notice_xml_sha256=sha)
    other = admit(storage, company, 0, number=OTHER, listed=False)
    project_notice_positions(storage, company, ref, actor_id="test")
    get_document_status(storage, company, ref)
    get_eis_evidence_bridge(storage, company, ref, now=NOW)
    costs = DiscoveryCostInput(
        goods="1", expenses="1", vat_rate="0.20", basis="Synthetic", costs_complete_ack=True
    )
    prepare(
        storage,
        company,
        tmp_path,
        day="30",
        response="d",
        members=(("new.xml", notice(title="Changed", version=version)),),
    )
    assert read_notice_source_hold(storage, company, NUMBER, 1).status == "HOLD"
    assert search_eis_index(storage, company, "бумага", now=NOW).held_current_notices == 1
    _assert_search_matches_installed_baseline(storage, company)
    for operation in (
        lambda: get_document_status(storage, company, ref),
        lambda: project_notice_positions(storage, company, ref, actor_id="test"),
        lambda: get_eis_evidence_bridge(storage, company, ref, now=NOW),
        lambda: estimate_eis_notice(storage, company, ref, costs),
        lambda: get_eis_comparison(
            storage, company, EisComparisonRequest(notices=(ref, other)), now=NOW
        ),
    ):
        with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
            operation()
    before = counts(storage, company)
    assert (
        project_retained_notice_variants(storage, company, receipt.receipt_id, archives).batch_id
        == report.batch_id
    )
    assert counts(storage, company) == before
    assert read_notice_source_hold(storage, company, NUMBER, 1).status == "HOLD"


def test_cross_tenant_rls_immutable_and_global_downgrade(storage, tmp_path):
    company = "projection-rls-" + uuid4().hex
    receipt, archives, _ = prepare(storage, company, tmp_path)
    report = project_retained_notice_variants(storage, company, receipt.receipt_id, archives)
    with storage.transaction("other", consistent_read=True) as conn:
        for table in (eis_notice_projection_batches, eis_notice_projection_decisions):
            assert conn.scalar(select(func.count()).select_from(table)) == 0
    with pytest.raises(ValueError, match="RECEIPT_NOT_FOUND"):
        project_retained_notice_variants(storage, "other", receipt.receipt_id, archives)
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        for table in (eis_notice_projection_batches, eis_notice_projection_decisions):
            for statement in (update(table).values(company_id="forged"), delete(table)):
                with pytest.raises(DBAPIError), engine.begin() as conn:
                    conn.execute(statement.where(table.c.batch_id == report.batch_id))
    finally:
        engine.dispose()
    before = counts(storage, company)
    assert_direct_downgrade_guard(
        "20261004_03_eis_notice_projection",
        expected_database="procurement_eis_test_20261004_s180",
        match="notice projection history must be preserved",
        tenant_context="other-" + uuid4().hex,
    )
    assert counts(storage, company) == before


def test_late_write_failure_rolls_back_entire_transport_projection(storage, tmp_path, monkeypatch):
    import procurement.storage.eis_notice_projection as writer

    company = "projection-atomic-" + uuid4().hex
    receipt, archives, _ = prepare(storage, company, tmp_path)
    before = counts(storage, company)

    def fail(*args, **kwargs):
        raise ValueError("SYNTHETIC_LATE_FAILURE")

    monkeypatch.setattr(writer, "insert_search_keys", fail)
    with pytest.raises(ValueError, match="SYNTHETIC_LATE_FAILURE"):
        project_retained_notice_variants(storage, company, receipt.receipt_id, archives)
    assert counts(storage, company) == before


def test_exact_decision_must_belong_to_audit_even_when_canonical_sha_matches(storage, tmp_path):
    company = "projection-audit-" + uuid4().hex
    receipt, archives, _ = prepare(storage, company, tmp_path)
    report = project_retained_notice_variants(storage, company, receipt.receipt_id, archives)
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                assert not conn.scalar(select(notice_variant_hold_clause(company, NUMBER, 1)))
                # Fault injection stays in this rolled-back, isolated owner transaction.
                conn.execute(
                    text("ALTER TABLE eis_notice_projection_decisions DISABLE TRIGGER USER")
                )
                conn.execute(
                    update(eis_notice_projection_decisions)
                    .where(
                        eis_notice_projection_decisions.c.company_id == company,
                        eis_notice_projection_decisions.c.batch_id == report.batch_id,
                    )
                    .values(snapshot_sha256="f" * 64)
                )
                assert conn.scalar(select(notice_variant_hold_clause(company, NUMBER, 1)))
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
    assert read_notice_source_hold(storage, company, NUMBER, 1).status == "NO_HOLD"


def test_more_than_twenty_identical_receipts_agree_across_sql_and_metadata(storage, tmp_path):
    company = "projection-many-" + uuid4().hex
    receipt, archives, _ = prepare(storage, company, tmp_path)
    project_retained_notice_variants(storage, company, receipt.receipt_id, archives)
    for index in range(21):
        prepare(storage, company, tmp_path, response=format(index % 16, "x"))
    with storage.transaction(company, consistent_read=True) as conn:
        assert not conn.scalar(select(notice_variant_hold_clause(company, NUMBER, 1)))
    assert read_notice_source_hold(storage, company, NUMBER, 1).status == "NO_HOLD"


@pytest.mark.parametrize("malformed", [None, "not-an-array", []])
def test_malformed_audited_array_fails_closed_without_sql_error(storage, tmp_path, malformed):
    company = "projection-malformed-" + uuid4().hex
    receipt, archives, _ = prepare(storage, company, tmp_path)
    report = project_retained_notice_variants(storage, company, receipt.receipt_id, archives)
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                basis = dict(
                    conn.scalar(
                        select(audit_events.c.basis).where(
                            audit_events.c.event_id == report.audit_event_id
                        )
                    )
                )
                basis["decisions"] = malformed
                conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
                conn.execute(
                    update(audit_events)
                    .where(
                        audit_events.c.company_id == company,
                        audit_events.c.event_id == report.audit_event_id,
                    )
                    .values(basis=basis)
                )
                assert conn.scalar(select(notice_variant_hold_clause(company, NUMBER, 1)))
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
    assert read_notice_source_hold(storage, company, NUMBER, 1).status == "NO_HOLD"
