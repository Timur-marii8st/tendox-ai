"""General family migration, immutable intake and tenant-bound consumers on isolated PG."""

from uuid import uuid4

import pytest
from migration_support import assert_direct_downgrade_guard
from sqlalchemy import select
from test_eis_223_index_pg import counts
from test_eis_223_index_pg import storage as pg_storage

from procurement.sources.eis_223_documents import Notice223DocumentRef
from procurement.storage.eis_223_comparison import read_comparison223_row
from procurement.storage.eis_223_index import ingest_notice223_window, search_notice223_index
from procurement.storage.eis_223_sync import record_attempt
from procurement.storage.models import eis_223_notice_versions, eis_223_sync_attempts
from test_eis_223_general_archive import archive, general_xml
from test_eis_223_index import NOW, window


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
