"""General family migration, immutable intake and tenant-bound consumers on isolated PG."""

import os
from uuid import uuid4

import pytest
from migration_support import assert_direct_downgrade_guard
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from test_eis_223_index_pg import counts
from test_eis_223_index_pg import storage as pg_storage

from procurement.sources.eis_223_documents import Notice223DocumentRef
from procurement.storage.eis_223_comparison import read_comparison223_row
from procurement.storage.eis_223_index import ingest_notice223_window, search_notice223_index
from procurement.storage.eis_223_sync import record_attempt
from procurement.storage.models import eis_223_notice_versions, eis_223_sync_attempts
from test_eis_223_general_archive import archive, general_xml
from test_eis_223_index import NOW, window
from test_eis_223_targeted_kesmbo import KEY, kesmbo_xml, targeted_window


@pytest.fixture(scope="module")
def storage():
    yield from pg_storage.__wrapped__()


def ready(raw):
    return window(archive(raw)).model_copy(
        update={
            "window_key": "getDocsIP/RI223/50/2026-10-02+03:00/purchaseNotice",
        }
    )


def test_general_atomic_retention_replay_search_and_exact_read(storage):
    company = "test-general-" + uuid4().hex
    prepared = ready(general_xml(price="<t:maxContractPrice>9999999</t:maxContractPrice>"))
    report = ingest_notice223_window(storage, company, prepared, actor_id="test", now=NOW)
    assert report.record_count == report.new_versions == 1
    before = counts(storage, company)
    replay = ingest_notice223_window(storage, company, prepared, actor_id="test", now=NOW)
    assert replay.replayed and counts(storage, company) == before
    result = search_notice223_index(storage, company, "бумага", now=NOW)
    assert len(result.matched) == 1
    notice = result.matched[0].notice
    assert notice.document_type == "purchaseNotice"
    assert notice.lots[0].source_amount.value is not None
    assert notice.lots[0].initial_sum_rub is None
    ref = Notice223DocumentRef(
        purchase_number=notice.purchase_number,
        version_number=notice.version_number,
        notice_xml_sha256=notice.xml_sha256,
    )
    with storage.transaction(company, consistent_read=True) as conn:
        row = read_comparison223_row(conn, company, ref, now=NOW)
    assert row.source_schema_status == "UNKNOWN" and row.eligibility == "UNKNOWN"
    assert counts(storage, company) == before
    assert search_notice223_index(storage, "other-" + company, "бумага", now=NOW).matched == ()
    with storage.transaction("other-" + company, consistent_read=True) as conn:
        assert conn.execute(select(eis_223_notice_versions)).first() is None
        with pytest.raises(LookupError):
            read_comparison223_row(conn, "other-" + company, ref, now=NOW)


def test_general_downgrade_preserves_history(storage):
    company = "test-general-history-" + uuid4().hex
    record_attempt(
        storage,
        company,
        "getDocsIP/RI223/50/2026-10-02+03:00/purchaseNotice",
        "NO_DATA",
        actor_id="test",
        checked_at=NOW,
        response_sha256="a" * 64,
    )
    with storage.transaction(company, consistent_read=True) as conn:
        attempt_id = conn.scalar(
            select(eis_223_sync_attempts.c.attempt_id).where(
                eis_223_sync_attempts.c.company_id == company
            )
        )
    assert attempt_id is not None
    assert_direct_downgrade_guard(
        "20261003_01_eis_223_general_notice",
        expected_database="procurement_eis_test_20261005_s209",
        match="223 general history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(
            select(eis_223_sync_attempts.c.attempt_id).where(
                eis_223_sync_attempts.c.company_id == company
            )
        ) == attempt_id


def test_targeted_atomic_latest_replay_search_and_foreign_tenant(storage):
    company = "kesmbo-" + uuid4().hex
    initial = targeted_window(
        kesmbo_xml().replace(b"<p:version>2</p:version>", b"<p:version>1</p:version>")
    )
    report = ingest_notice223_window(storage, company, initial, actor_id="test", now=NOW)
    assert report.new_versions == report.record_count == 1
    before = counts(storage, company)
    assert ingest_notice223_window(storage, company, initial, actor_id="test", now=NOW).replayed
    assert counts(storage, company) == before
    revised = targeted_window(kesmbo_xml(version=2)).model_copy(
        update={"response_sha256": "d" * 64}
    )
    revision = ingest_notice223_window(storage, company, revised, actor_id="test", now=NOW)
    assert revision.new_versions == 1
    result = search_notice223_index(storage, company, "бумага", now=NOW)
    assert len(result.matched) == 1
    lead = result.matched[0]
    assert lead.notice.version_number == 2 and lead.source_window == KEY
    assert lead.notice.document_type == "purchaseNoticeKESMBO"
    assert lead.application_status == result.coverage == result.freshness == "UNKNOWN"
    assert search_notice223_index(storage, company + "-foreign", "бумага", now=NOW).matched == ()
    with storage.transaction(company + "-foreign", consistent_read=True) as conn:
        assert conn.execute(select(eis_223_notice_versions)).first() is None



def test_wrong_number_or_mixed_family_never_advances_checkpoint(storage):
    company = "kesmbo-refuse-" + uuid4().hex
    before = counts(storage, company)
    with pytest.raises(ValueError, match="BY_NUMBER_PURCHASE_MISMATCH"):
        ingest_notice223_window(
            storage,
            company,
            targeted_window(kesmbo_xml(number="32600000002")),
            actor_id="test",
            now=NOW,
        )
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        ingest_notice223_window(
            storage,
            company,
            window().model_copy(update={"window_key": KEY}),
            actor_id="test",
            now=NOW,
        )
    assert counts(storage, company) == before



def test_sql_rejects_cross_number_snapshot_identity_without_application_guard(storage):
    company = "kesmbo-sql-" + uuid4().hex
    ingest_notice223_window(storage, company, targeted_window(), actor_id="test", now=NOW)
    # Runtime projections are INSERT-only. Owner SQL verifies the CHECK separately.
    with pytest.raises(DBAPIError, match="permission denied"), storage.transaction(company) as conn:
        conn.execute(
            text(
                "UPDATE eis_223_notice_versions SET purchase_number='32600000002' "
                "WHERE company_id=:company"
            ),
            {"company": company},
        )
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with (
            pytest.raises(DBAPIError, match="ck_eis_223_snapshot_identity"),
            engine.begin() as conn,
        ):
            conn.execute(
                text(
                    "INSERT INTO eis_223_notice_versions "
                    "(company_id,purchase_number,version_number, "
                    "xml_sha256,window_key,response_sha256,archive_sha256,snapshot, "
                    "search_keys,ingested_at) SELECT company_id,'32600000002',version_number, "
                    "xml_sha256,window_key,response_sha256,archive_sha256, "
                    "jsonb_set(snapshot,'{purchase_number}','\"32600000002\"'), "
                    "search_keys,ingested_at FROM eis_223_notice_versions WHERE company_id=:company"
                ),
                {"company": company},
            )
    finally:
        engine.dispose()
    assert (
        search_notice223_index(storage, company, "бумага", now=NOW)
        .matched[0]
        .notice.purchase_number
        == "32600000001"
    )



def test_targeted_downgrade_rejects_hidden_history_and_keeps_exact_schema_head(storage):
    company = "kesmbo-history-" + uuid4().hex
    ingest_notice223_window(storage, company, targeted_window(), actor_id="test", now=NOW)
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with engine.connect() as conn:
            original_head = conn.scalar(text("SELECT version_num FROM alembic_version"))
            assert original_head == "20261021_01"
    finally:
        engine.dispose()
    assert_direct_downgrade_guard(
        "20261013_01_eis_223_targeted_kesmbo",
        expected_database="procurement_eis_test_20261005_s209",
        match="223 targeted KESMBO history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == original_head
    finally:
        engine.dispose()
    assert search_notice223_index(storage, company, "бумага", now=NOW).matched_count == 1
