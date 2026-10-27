"""Run only on an isolated PostgreSQL database; all XML here is synthetic."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from migration_support import assert_direct_downgrade_guard
from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from procurement.storage.eis_223_index import (
    Eis223IndexConflict,
    ingest_notice223_window,
    search_notice223_index,
)
from procurement.storage.models import (
    audit_events,
    eis_223_archive_sources,
    eis_223_blobs,
    eis_223_notice_versions,
    eis_223_windows,
)
from procurement.storage.repository import PostgresStorage
from test_eis_223_archive import xml, zip_bytes
from test_eis_223_index import NOW, window

TABLES = (eis_223_windows, eis_223_blobs, eis_223_archive_sources, eis_223_notice_versions)


@pytest.fixture(scope="module")
def storage():
    app_url, admin_url = os.getenv("DATABASE_URL"), os.getenv("DATABASE_ADMIN_URL")
    if not app_url or not admin_url:
        pytest.skip("isolated PostgreSQL credentials required")
    if "procurement_eis_test_" not in app_url or "procurement_eis_test_" not in admin_url:
        pytest.fail("223 gate requires explicitly isolated test database")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", admin_url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(app_url, pool_pre_ping=True)
    yield PostgresStorage(engine)
    engine.dispose()


def counts(storage, company):
    with storage.transaction(company) as conn:
        return tuple(
            conn.scalar(select(func.count()).select_from(t)) for t in (*TABLES, audit_events)
        )


def test_paper_sense_filters_securities_after_coarse_sql_prefilter(storage):
    company = "paper-sense223-" + uuid4().hex
    financial = xml().decode().replace("Поставка бумаги", "Оценка ценных бумаг")
    financial = financial.replace("Бумага для печати", "Оценка ценных бумаг").replace(
        "Бумага А4 80", "Оценка ценных бумаг"
    )
    paper = xml().replace(b"32600000001", b"32600000002")
    price = xml().decode().replace("32600000001", "32600000003")
    for field in ("Поставка бумаги", "Бумага для печати", "Бумага А4 80"):
        price = price.replace(field, "Мониторинг цен бумаги офисной")
    ingest_notice223_window(
        storage,
        company,
        window(
            zip_bytes(
                [
                    ("financial.xml", financial.encode()),
                    ("paper.xml", paper),
                    ("price.xml", price.encode()),
                ]
            )
        ),
        actor_id="test",
        now=NOW,
    )
    before = counts(storage, company)
    result = search_notice223_index(storage, company, "бумага", now=NOW, paginate=True)
    assert result.evaluated_candidates == 3
    assert [lead.notice.purchase_number for lead in result.matched] == [
        "32600000002",
        "32600000003",
    ]
    assert result.matched[0].match_quality == "STRONG"
    explicit = search_notice223_index(storage, company, "ценные бумаги", now=NOW)
    financial_lead = next(
        lead for lead in explicit.matched if lead.notice.purchase_number == "32600000001"
    )
    assert financial_lead.match_quality == "STRONG"
    assert search_notice223_index(storage, company + "-other", "бумага", now=NOW).matched_count == 0
    assert counts(storage, company) == before


def test_search_global_top100_after_multiple_batches_latest_tenant_and_no_writes(
    storage, monkeypatch
):
    import hashlib

    from procurement.sources import eis_223_archive

    company = "test223-batched-" + uuid4().hex
    for batch in range(3):
        entries = []
        for index in range(batch * 150 + 1, batch * 150 + 151):
            raw = xml().replace(b"32600000001", f"326{index:08d}".encode())
            if index < 421:
                raw = raw.replace("Бумага А4 80".encode(), "Офисная бумага".encode())
            entries.append((f"notice-{index}.xml", raw))
        ready = window(
            zip_bytes(entries), response=hashlib.sha256(f"batch-{batch}".encode()).hexdigest()
        )
        ingest_notice223_window(storage, company, ready, actor_id="test", now=NOW)
    # The old paper version must not enter the candidate set when a newer server version exists.
    newer = xml().replace(b"<p:version>2</p:version>", b"<p:version>3</p:version>")
    newer = newer.replace("бумаги".encode(), "серверов".encode()).replace(
        "Бумага".encode(), "Сервер".encode()
    )
    ingest_notice223_window(
        storage,
        company,
        window(zip_bytes([("newer.xml", newer)]), response="d" * 64),
        actor_id="test",
        now=NOW,
    )
    before = counts(storage, company)

    def forbidden(*args, **kwargs):
        raise AssertionError("Search cannot parse source XML")

    monkeypatch.setattr(eis_223_archive, "parse_notice223_xml", forbidden)
    result = search_notice223_index(storage, company, "бумага а4", now=NOW)
    assert result.indexed_current_notices == 450
    assert result.evaluated_candidates == result.matched_count == 449
    assert len(result.matched) == 100
    assert [r.notice.purchase_number for r in result.matched[:30]] == [
        f"326{i:08d}" for i in range(421, 451)
    ]
    assert all(r.match_quality == "STRONG" for r in result.matched[:30])
    assert all(r.match_quality == "PARTIAL" for r in result.matched[30:])
    assert not any(r.notice.purchase_number == "32600000001" for r in result.matched)
    assert result.coverage == result.economics_status == "UNKNOWN"
    assert (
        search_notice223_index(storage, company + "-other", "бумага а4", now=NOW).matched_count == 0
    )
    assert counts(storage, company) == before


def test_replay_latest_versions_and_read_only_search(storage):
    company = "test223-" + uuid4().hex
    raw1 = xml().replace(b"<p:version>2</p:version>", b"<p:version>1</p:version>")
    raw2 = xml().replace("Поставка бумаги".encode(), "Поставка сервера".encode())
    raw2 = raw2.replace("Бумага для печати".encode(), "Сервер".encode())
    raw2 = raw2.replace("Бумага А4 80".encode(), "Сервер".encode())
    ready = window(zip_bytes([("v1.xml", raw1), ("v2.xml", raw2)]))
    report = ingest_notice223_window(storage, company, ready, actor_id="operator", now=NOW)
    assert report.record_count == report.new_versions == 2
    baseline = counts(storage, company)
    assert baseline == (1, 1, 1, 2, 1)
    assert ingest_notice223_window(storage, company, ready, actor_id="operator").replayed
    assert search_notice223_index(storage, company, "бумага", now=NOW).matched_count == 0
    result = search_notice223_index(storage, company, "сервер", now=NOW)
    assert result.indexed_current_notices == result.matched_count == 1
    assert result.matched[0].notice.version_number == 2
    assert counts(storage, company) == baseline
    assert (
        search_notice223_index(storage, "other-" + company, "сервер").indexed_current_notices == 0
    )
    with storage.transaction("other-" + company) as conn:
        assert all(conn.scalar(select(func.count()).select_from(t)) == 0 for t in TABLES)


def test_new_response_deduplicates_bytes_and_versions_but_audits_window(storage):
    company = "test223-" + uuid4().hex
    ready = window()
    ingest_notice223_window(storage, company, ready, actor_id="operator")
    report = ingest_notice223_window(
        storage,
        company,
        ready.model_copy(
            update={
                "response_sha256": "d" * 64,
            }
        ),
        actor_id="operator",
    )
    assert report.new_versions == 0 and not report.replayed
    assert counts(storage, company) == (2, 1, 2, 1, 2)


def test_conflict_rolls_back_whole_window_including_new_notice_and_audit(storage):
    company = "test223-" + uuid4().hex
    ingest_notice223_window(storage, company, window(), actor_id="operator")
    before = counts(storage, company)
    new = xml().replace(b"32600000001", b"32600000002")
    conflict = xml().replace(b"100.25", b"500.25")
    ready = window(zip_bytes([("new.xml", new), ("conflict.xml", conflict)]), response="d" * 64)
    with pytest.raises(Eis223IndexConflict, match="NOTICE_VERSION_CONFLICT"):
        ingest_notice223_window(storage, company, ready, actor_id="operator")
    assert counts(storage, company) == before
    altered = window(zip_bytes([("other.xml", xml())]))
    with pytest.raises(Eis223IndexConflict, match="WINDOW_REPLAY_CONFLICT"):
        ingest_notice223_window(storage, company, altered, actor_id="operator")
    assert counts(storage, company) == before


def test_concurrent_replay_is_one_atomic_intake(storage):
    company = "test223-" + uuid4().hex
    ready = window()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: ingest_notice223_window(storage, company, ready, actor_id="operator"),
                range(2),
            )
        )
    assert sum(r.replayed for r in results) == 1
    assert counts(storage, company) == (1, 1, 1, 1, 1)


def test_database_hash_identity_rls_and_immutability_guards(storage):
    company = "test223-" + uuid4().hex
    ingest_notice223_window(storage, company, window(), actor_id="operator")
    for table in TABLES:
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(update(table).values(company_id=company))
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(delete(table))
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            insert(eis_223_blobs).values(
                company_id=company, archive_sha256="e" * 64, content=b"fake"
            )
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            insert(eis_223_blobs).values(
                company_id="other", archive_sha256="e" * 64, content=b"fake"
            )
        )
    with storage.transaction(company) as conn:
        row = dict(conn.execute(select(eis_223_notice_versions)).mappings().one())
    row.update(purchase_number="32600000002", snapshot={})
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(insert(eis_223_notice_versions).values(**row))
    with storage._engine.begin() as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_notice_versions)) == 0


def test_downgrade_cannot_erase_history_when_owner_sees_other_tenant(storage):
    company = "test223-downgrade-" + uuid4().hex
    ingest_notice223_window(storage, company, window(), actor_id="operator")
    before = counts(storage, company)
    assert_direct_downgrade_guard(
        "20261002_04_eis_223_index",
        expected_database="procurement_eis_test_20261005_s209",
        match="223 source history must be preserved",
        tenant_context="unrelated-" + uuid4().hex,
    )
    assert counts(storage, company) == before


def test_latest_supplier_serp_guard_remains_active_at_head(storage):
    engine = create_engine(os.environ["DATABASE_ADMIN_URL"])
    constraints = text(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname IN ('ck_eis_supplier_serp_bundle', "
        "'ck_eis_supplier_serp_report_identity', 'ck_eis_supplier_page_identity') "
        "ORDER BY conname"
    )
    try:
        with engine.connect() as conn:
            original_revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
            original_constraints = tuple(conn.execute(constraints))
        with pytest.raises(RuntimeError, match="supplier SERP fallback evidence must be preserved"):
            command.downgrade(Config("alembic.ini"), "20261006_11")
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == original_revision
            assert tuple(conn.execute(constraints)) == original_constraints
    finally:
        engine.dispose()


def test_223_attempts_are_scoped_durable_rate_limited_and_do_not_close_no_data(storage):
    from datetime import timedelta

    from procurement.sources.eis_223_sync import window_key
    from procurement.storage.eis_223_sync import due_windows, record_attempt

    def due_dates(storage, company, now):
        return tuple(
            t.day
            for t in due_windows(storage, company, now)
            if t.document_type == "purchaseNoticeAESMBO"
        )

    from procurement.storage.models import eis_223_sync_attempts

    company = "test223-" + uuid4().hex
    now = NOW + timedelta(hours=10)
    days = due_dates(storage, company, now)
    assert len(days) == 2 and all(d.isoformat() in {"2026-10-02", "2026-10-01"} for d in days)
    record_attempt(
        storage,
        company,
        window_key(days[0]),
        "NO_DATA",
        actor_id="operator",
        checked_at=now,
        response_sha256="a" * 64,
    )
    record_attempt(
        storage,
        company,
        window_key(days[1]),
        "FAILED",
        actor_id="operator",
        checked_at=now,
        response_sha256=None,
        reason="SOURCE_TRANSPORT_FAILED",
    )
    assert due_dates(storage, company, now + timedelta(minutes=59)) == ()
    assert due_dates(storage, company, now + timedelta(hours=1)) == (days[1],)
    assert set(due_dates(storage, company, now + timedelta(hours=6))) == set(days)
    assert len(due_dates(storage, "other-" + company, now)) == 2
    assert counts(storage, company)[:4] == (0, 0, 0, 0)
    with storage.transaction("other-" + company) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_sync_attempts)) == 0
    with pytest.raises(ValueError, match="SYNCED_CHECKPOINT_MISSING"):
        record_attempt(
            storage,
            company,
            window_key(days[1]),
            "SYNCED",
            actor_id="operator",
            checked_at=now,
            response_sha256="a" * 64,
        )
    ingest_notice223_window(storage, company, window(), actor_id="operator")
    record_attempt(
        storage,
        company,
        window_key(days[1]),
        "SYNCED",
        actor_id="operator",
        checked_at=now,
        response_sha256="b" * 64,
    )
    # Equal timestamps cannot order two observations: retain the shorter error backoff.
    assert due_dates(storage, company, now + timedelta(hours=1)) == (days[1],)
    record_attempt(
        storage,
        company,
        window_key(days[1]),
        "SYNCED",
        actor_id="operator",
        checked_at=now + timedelta(seconds=1),
        response_sha256="b" * 64,
    )
    assert due_dates(storage, company, now + timedelta(hours=1)) == ()
    for stmt in (
        update(eis_223_sync_attempts).values(status="FAILED"),
        delete(eis_223_sync_attempts),
    ):
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(stmt)
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            insert(eis_223_sync_attempts).values(
                company_id=company,
                attempt_id=str(uuid4()),
                window_key=window_key(days[0]),
                status="SYNCED",
                response_sha256="a" * 64,
                checkpoint_response_sha256="a" * 64,
                checked_at=now,
            )
        )


def test_223_quotation_intake_preserves_family_and_sql_refuses_relabelled_window(storage):
    company = "test223-" + uuid4().hex
    family = "purchaseNoticeZKESMBO"
    raw = xml().replace(b"purchaseNoticeAESMBO", family.encode())
    selected = window(zip_bytes([("quotation.xml", raw)]))
    selected = selected.model_copy(
        update={"window_key": selected.window_key.replace("purchaseNoticeAESMBO", family)}
    )
    assert (
        ingest_notice223_window(storage, company, selected, actor_id="operator").new_versions == 1
    )
    assert ingest_notice223_window(storage, company, selected, actor_id="operator").replayed
    result = search_notice223_index(storage, company, "бумага")
    assert result.matched[0].notice.document_type == family
    assert result.matched[0].application_status == "UNKNOWN"
    before = counts(storage, company)
    with pytest.raises(Eis223IndexConflict, match="NOTICE_VERSION_CONFLICT"):
        ingest_notice223_window(storage, company, window(), actor_id="operator")
    assert counts(storage, company) == before
    # The immutable source family is enforced even if a direct SQL caller supplies another snapshot.
    with storage.transaction(company) as conn:
        row = dict(conn.execute(select(eis_223_notice_versions)).mappings().one())
    row.update(purchase_number="32600000002")
    row["snapshot"] = {
        **row["snapshot"],
        "purchase_number": "32600000002",
        "document_type": "purchaseNoticeAESMBO",
    }
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(insert(eis_223_notice_versions).values(**row))
    assert_direct_downgrade_guard(
        "20261002_06_eis_223_quotation_type",
        expected_database="procurement_eis_test_20261005_s209",
        match="223 quotation history must be preserved",
    )
    assert counts(storage, company) == before


def test_schema_observations_are_exact_immutable_scoped_and_preserve_fail(storage):
    from datetime import timedelta

    from procurement.storage.eis_223_quality import record_schema_check
    from procurement.storage.models import eis_223_schema_checks
    from test_eis_223_schema import check

    company = "test223-" + uuid4().hex
    ingest_notice223_window(storage, company, window(), actor_id="operator")
    before = counts(storage, company)
    assert (
        search_notice223_index(storage, company, "бумага").matched[0].source_schema_status
        == "UNKNOWN"
    )
    good = check()
    assert record_schema_check(storage, company, good, actor_id="operator")
    assert not record_schema_check(
        storage,
        company,
        good.model_copy(update={"checked_at": good.checked_at + timedelta(minutes=1)}),
        actor_id="operator",
    )
    assert (
        search_notice223_index(storage, company, "бумага").matched[0].source_schema_status
        == "UNKNOWN"
    )
    bad = check(valid=False, release="16.2")
    assert record_schema_check(storage, company, bad, actor_id="operator")
    result = search_notice223_index(storage, company, "бумага")
    lead = result.matched[0]
    assert lead.match_quality == "STRONG" and lead.source_schema_status == "FAIL"
    assert lead.application_status == lead.notice.economics_status == "UNKNOWN"
    assert len(lead.source_schema_checks) == 2
    assert counts(storage, company)[:4] == before[:4]
    assert counts(storage, company)[4] == before[4] + 2
    with storage.transaction("other-" + company) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_schema_checks)) == 0
    with pytest.raises(ValueError, match="SCHEMA_CHECK_CONFLICT"):
        record_schema_check(storage, company, check(valid=False), actor_id="operator")
    with pytest.raises(DBAPIError):
        record_schema_check(storage, "other-" + company, good, actor_id="operator")
    with storage.transaction(company) as conn:
        row = dict(conn.execute(select(eis_223_schema_checks)).mappings().first())
    for stmt in (
        update(eis_223_schema_checks).values(status="FAIL"),
        delete(eis_223_schema_checks),
    ):
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(stmt)
    for changed in (
        {"xml_sha256": "f" * 64},
        {"report": {}},
        {"tree_sha256": "a" * 64},
        {"status": "FAIL"},
    ):
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(
                insert(eis_223_schema_checks).values(
                    **{**row, "validator_version": "different-validator", **changed}
                )
            )
    assert counts(storage, company)[4] == before[4] + 2
    guard_before = counts(storage, company)
    assert_direct_downgrade_guard(
        "20261002_08_eis_223_schema_quality",
        expected_database="procurement_eis_test_20261005_s209",
        match="223 schema evidence must be preserved",
    )
    assert counts(storage, company) == guard_before


def test_quality_queue_latest_exact_policy_fail_is_done_and_tenant_scoped(storage):
    from procurement.storage.eis_223_quality import pending_schema_targets, record_schema_check
    from test_eis_223_schema import check

    company = "test223-" + uuid4().hex
    older = xml().replace(b"<p:version>2</p:version>", b"<p:version>1</p:version>")
    ingest_notice223_window(
        storage,
        company,
        window(zip_bytes([("old.xml", older), ("notice.xml", xml())])),
        actor_id="operator",
    )
    pending = pending_schema_targets(storage, company)
    assert len(pending) == 1 and pending[0].notice.version_number == 2
    assert pending_schema_targets(storage, "other-" + company) == ()
    # Historical validator evidence is not inherited by the current policy.
    record_schema_check(
        storage,
        company,
        check().model_copy(update={"validator_version": "old-validator"}),
        actor_id="worker",
    )
    assert len(pending_schema_targets(storage, company)) == 1
    record_schema_check(storage, company, check(), actor_id="worker")
    assert len(pending_schema_targets(storage, company)) == 1
    record_schema_check(storage, company, check(valid=False, release="16.2"), actor_id="worker")
    assert pending_schema_targets(storage, company) == ()


def test_223_document_receipts_exact_immutable_replay_and_scoped(storage, monkeypatch):
    from procurement.sources.eis_223_documents import manifest223
    from procurement.storage import eis_223_documents as documents
    from procurement.storage.models import eis_223_document_receipts
    from test_eis_223_archive import UID
    from test_eis_223_documents import docx_bytes

    company = "test223-" + uuid4().hex
    selected = window()
    ingest_notice223_window(storage, company, selected, actor_id="operator")
    notice = search_notice223_index(storage, company, "бумага").matched[0].notice
    ref = manifest223(notice).notice
    calls = []
    monkeypatch.setattr(documents, "resource_gate", lambda *a, **k: None)

    def fetch(url, uid):
        calls.append((url, uid))
        return docx_bytes()

    result = documents.collect_document223(
        storage, company, ref, UID, actor_id="operator", downloader=fetch
    )
    assert result.download_status == "COMPLETE_LISTED_SET"
    assert result.review_status == result.eligibility == result.economics_status == "UNKNOWN"
    assert result.documents[0].analysis.status == "PASS" and result.documents[0].analysis.snippets
    baseline = counts(storage, company)
    replay = documents.collect_document223(
        storage, company, ref, UID, actor_id="operator", downloader=fetch
    )
    assert replay.documents == result.documents and replay.download_status == result.download_status
    assert len(calls) == 1 and counts(storage, company) == baseline
    with storage.transaction("other-" + company) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_document_receipts)) == 0
    with pytest.raises(LookupError):
        documents.get_document223_status(storage, "other-" + company, ref)
    with pytest.raises(ValueError, match="NOTICE_DIGEST_CONFLICT"):
        documents.get_document223_status(
            storage, company, ref.model_copy(update={"notice_xml_sha256": "f" * 64})
        )
    with storage.transaction(company) as conn:
        row = dict(conn.execute(select(eis_223_document_receipts)).mappings().one())
    for statement in (
        update(eis_223_document_receipts).values(filename="forged"),
        delete(eis_223_document_receipts),
    ):
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(statement)
    for changed in (
        {"content_uid": "B" * 32},
        {"source_url": "https://evil.invalid"},
        {"sha256": "f" * 64},
        {"analysis": {}},
    ):
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(insert(eis_223_document_receipts).values(**{**row, **changed}))
    assert_direct_downgrade_guard(
        "20261002_09_eis_223_document_receipts",
        expected_database="procurement_eis_test_20261005_s209",
        match="223 document evidence must be preserved",
    )
    assert counts(storage, company) == baseline


def test_223_doc_io_blocked_before_fetch_for_missing_uid_manifest_stale_expired_or_budget(
    storage, monkeypatch
):
    from procurement.sources.eis_223_documents import manifest223
    from procurement.storage import eis_223_documents as documents
    from test_eis_223_archive import UID

    monkeypatch.setattr(documents, "resource_gate", lambda *a, **k: None)

    def no_fetch(*args):
        pytest.fail("blocked source must not fetch")

    for change, error in (
        ("uid", "UNLISTED_DOCUMENT_UID"),
        ("count", "UNKNOWN_MANIFEST"),
        ("stale", "NOTICE_VERSION_STALE"),
        ("expired", "DEADLINE_EXPIRED"),
        ("budget", "DATABASE_BUDGET_REACHED"),
    ):
        company = "test223-" + uuid4().hex
        raw = xml(deadline="2020-01-01T00:00:00+03:00") if change == "expired" else xml()
        if change == "count":
            raw = raw.replace(b"<t:totalDocumentsCount>1", b"<t:totalDocumentsCount>2")
        ingest_notice223_window(
            storage, company, window(zip_bytes([("notice.xml", raw)])), actor_id="operator"
        )
        notice = search_notice223_index(storage, company, "бумага").matched[0].notice
        ref = manifest223(notice).notice
        if change == "stale":
            newer = raw.replace(b"<p:version>2", b"<p:version>3")
            ready = window(zip_bytes([("v3.xml", newer)])).model_copy(
                update={"response_sha256": "d" * 64}
            )
            ingest_notice223_window(storage, company, ready, actor_id="operator")
        if change == "budget":
            monkeypatch.setattr(
                documents, "resource_gate", lambda *a, **k: "DATABASE_BUDGET_REACHED"
            )
        with pytest.raises(ValueError, match=error):
            documents.collect_document223(
                storage,
                company,
                ref,
                "B" * 32 if change == "uid" else UID,
                actor_id="operator",
                downloader=no_fetch,
            )


def test_223_queue_replay_retry_cap_fairness_scope_and_sql_journal(storage, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from procurement.sources.eis_223_documents import manifest223
    from procurement.storage.eis_223_document_queue import (
        next_document223,
        plan_document223_job,
        record_document223_attempt,
    )
    from procurement.storage.eis_223_documents import get_document223_status
    from procurement.storage.models import eis_223_document_attempts, eis_223_document_jobs
    from test_eis_223_archive import UID

    company = "test223-" + uuid4().hex
    second = xml().replace(b"32600000001", b"32600000002")
    ingest_notice223_window(
        storage,
        company,
        window(zip_bytes([("one.xml", xml()), ("two.xml", second)])),
        actor_id="operator",
    )
    notices = search_notice223_index(storage, company, "бумага").matched
    refs = sorted((manifest223(n.notice).notice for n in notices), key=lambda r: r.purchase_number)
    first = plan_document223_job(storage, company, refs[0], actor_id="operator")
    assert first.requested and first.queue_status == "QUEUED"
    baseline = counts(storage, company)
    plan_document223_job(storage, company, refs[0], actor_id="operator")
    assert counts(storage, company) == baseline
    now = datetime.now(UTC)
    assert next_document223(storage, company, now) == (refs[0], UID)
    assert next_document223(storage, "other-" + company, now) is None
    record_document223_attempt(
        storage, company, refs[0], UID, "FAILED", "ROBOTS_CRAWL_DELAY", actor_id="worker", now=now
    )
    assert next_document223(storage, company, now + timedelta(seconds=59)) is None
    assert next_document223(storage, company, now + timedelta(seconds=60)) == (refs[0], UID)
    # A host cooldown is a deferral, not one of the five source failure attempts.
    assert get_document223_status(storage, company, refs[0]).documents[0].attempt_count == 0
    for i in range(5):
        record_document223_attempt(
            storage,
            company,
            refs[0],
            UID,
            "FAILED",
            "ATTACHMENT_UNAVAILABLE",
            actor_id="worker",
            now=now + timedelta(minutes=31 * (i + 1)),
        )
    assert get_document223_status(storage, company, refs[0]).queue_status == "ATTENTION_REQUIRED"
    with pytest.raises(ValueError, match="DOCUMENT_223_ATTEMPT_LIMIT"):
        record_document223_attempt(
            storage,
            company,
            refs[0],
            UID,
            "FAILED",
            "ATTACHMENT_UNAVAILABLE",
            actor_id="worker",
            now=now,
        )
    assert next_document223(storage, company, now + timedelta(days=1)) is None
    plan_document223_job(storage, company, refs[1], actor_id="operator")
    assert next_document223(storage, company, now + timedelta(days=1)) == (refs[1], UID)
    with pytest.raises(DBAPIError):
        record_document223_attempt(
            storage, company, refs[1], UID, "RECEIVED", None, actor_id="worker", now=now
        )
    from procurement.sources import eis_223_document_worker as worker
    from procurement.storage import eis_223_documents as documents
    from test_eis_223_documents import docx_bytes

    monkeypatch.setattr(worker, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(documents, "resource_gate", lambda *a, **k: None)
    calls = []

    def fetch(url, uid):
        calls.append(uid)
        return docx_bytes()

    step = worker.run_document223_step(storage, company, actor_id="worker", downloader=fetch)
    assert step.status == "PROCESSED" and calls == [UID]
    assert get_document223_status(storage, company, refs[1]).queue_status == "COMPLETE"
    before_idle = counts(storage, company)
    idle = worker.run_document223_step(storage, company, actor_id="worker", downloader=fetch)
    assert idle.attempted == 0 and calls == [UID] and counts(storage, company) == before_idle
    with storage.transaction(company) as conn:
        job = dict(conn.execute(select(eis_223_document_jobs)).mappings().first())
        attempt = dict(conn.execute(select(eis_223_document_attempts)).mappings().first())
    for table in (eis_223_document_jobs, eis_223_document_attempts):
        for stmt in (delete(table), update(table).values(company_id=company)):
            with pytest.raises(DBAPIError), storage.transaction(company) as conn:
                conn.execute(stmt)
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            insert(eis_223_document_attempts).values(
                **{**attempt, "attempt_id": str(uuid4()), "content_uid": "B" * 32}
            )
        )
    with pytest.raises(DBAPIError), storage.transaction("other-" + company) as conn:
        conn.execute(
            insert(eis_223_document_jobs).values(**{**job, "company_id": "other-" + company})
        )
    guard_before = counts(storage, company)
    assert_direct_downgrade_guard(
        "20261002_10_eis_223_document_queue",
        expected_database="procurement_eis_test_20261005_s209",
        match="223 document queue history must be preserved",
    )
    assert counts(storage, company) == guard_before


def test_223_queue_bounds_new_requests_and_skips_stale(storage, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from procurement.sources.eis_223_documents import manifest223
    from procurement.storage import eis_223_document_queue as queue
    from procurement.storage.eis_223_documents import get_document223_status

    company = "test223-" + uuid4().hex
    entries = [
        (f"{i}.xml", xml().replace(b"32600000001", str(32600000001 + i).encode()))
        for i in range(11)
    ]
    ingest_notice223_window(storage, company, window(zip_bytes(entries)), actor_id="operator")
    refs = sorted(
        (
            manifest223(n.notice).notice
            for n in search_notice223_index(storage, company, "бумага").matched
        ),
        key=lambda r: r.purchase_number,
    )
    for ref in refs[:10]:
        queue.plan_document223_job(storage, company, ref, actor_id="operator")
    with pytest.raises(ValueError, match="DOCUMENT_223_REQUEST_RATE_LIMIT"):
        queue.plan_document223_job(storage, company, refs[10], actor_id="operator")
    later = datetime.now(UTC) + timedelta(hours=2)
    monkeypatch.setattr(queue, "datetime", SimpleNamespace(now=lambda zone: later))
    with pytest.raises(ValueError, match="DOCUMENT_223_QUEUE_FULL"):
        queue.plan_document223_job(storage, company, refs[10], actor_id="operator")
    raw = entries[0][1].replace(b"<p:version>2", b"<p:version>3")
    ingest_notice223_window(
        storage,
        company,
        window(zip_bytes([("new.xml", raw)])).model_copy(update={"response_sha256": "d" * 64}),
        actor_id="operator",
    )
    assert get_document223_status(storage, company, refs[0]).queue_status == "BLOCKED"
    assert queue.next_document223(storage, company, later)[0] == refs[1]
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        queue.plan_document223_job(storage, company, refs[0], actor_id="operator")


def test_selected223_comparison_exact_snapshot_gates_receipts_and_no_mutation(storage, monkeypatch):
    from procurement.sources.eis_223_documents import manifest223
    from procurement.storage import eis_223_comparison as comparison
    from procurement.storage import eis_223_documents as documents
    from procurement.storage.models import (
        eis_223_document_attempts,
        eis_223_document_jobs,
        eis_223_document_receipts,
    )
    from test_eis_223_archive import UID
    from test_eis_223_documents import docx_bytes

    company = "test223-" + uuid4().hex
    second = xml(deadline="2026-01-01T08:00:00+03:00", amount="900.37", code="USD", numeric="840")
    second = second.replace(b"32600000001", b"32600000002")
    old = xml().replace(b"<p:version>2</p:version>", b"<p:version>1</p:version>")
    ready = window(zip_bytes([("a.xml", xml()), ("b.xml", second), ("old.xml", old)]))
    ingest_notice223_window(storage, company, ready, actor_id="operator")
    with storage.transaction(company) as conn:
        saved = list(conn.execute(select(eis_223_notice_versions)).mappings())
    refs = {
        (r["purchase_number"], r["version_number"]): manifest223(
            documents.Eis223NoticeSnapshot.model_validate(r["snapshot"])
        ).notice
        for r in saved
    }
    first = refs[("32600000001", 2)]
    other = refs[("32600000002", 2)]
    monkeypatch.setattr(documents, "resource_gate", lambda *a, **k: None)
    documents.collect_document223(
        storage, company, first, UID, actor_id="operator", downloader=lambda *a: docx_bytes()
    )
    extra_tables = (eis_223_document_jobs, eis_223_document_receipts, eis_223_document_attempts)
    from procurement.storage.eis_223_quality import record_schema_check
    from test_eis_223_schema import check

    record_schema_check(storage, company, check(valid=False), actor_id="operator")

    def all_counts():
        with storage.transaction(company) as conn:
            return counts(storage, company) + tuple(
                conn.scalar(select(func.count()).select_from(t)) for t in extra_tables
            )

    before = all_counts()
    reads = []
    original = comparison.read_document223_status

    def observe(conn, *args, **kwargs):
        assert conn.scalar(text("SHOW transaction_read_only")) == "on"
        assert conn.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        reads.append(id(conn))
        return original(conn, *args, **kwargs)

    monkeypatch.setattr(comparison, "read_document223_status", observe)
    request = comparison.Comparison223Request(notices=(other, first))
    result = comparison.get_comparison223(storage, company, request, now=NOW)
    assert len(set(reads)) == 1 and len(reads) == 2
    assert result.checked_at == NOW and result.profit_order_status == result.coverage == "UNKNOWN"
    blocked, pending = result.rows
    assert blocked.notice.purchase_number == other.purchase_number
    assert blocked.readiness_status == "BLOCKED" and blocked.blocking_reasons == (
        "DEADLINE_EXPIRED",
    )
    assert str(blocked.notice.lots[0].initial_sum.value) == "900.37"
    assert blocked.notice.lots[0].initial_sum_rub is None
    assert blocked.notice.lots[0].currency.value == "USD"
    assert pending.readiness_status == "NEEDS_ANALYSIS" and pending.eligibility == "UNKNOWN"
    assert pending.documents[0].received and pending.documents[0].snippets
    assert pending.documents[0].review_status == "UNKNOWN"
    assert pending.source_schema_status == "FAIL"
    assert len(pending.source_schema_checks) == 1
    assert pending.blocking_reasons == () and pending.economics_status == "UNKNOWN"
    stale = comparison.get_comparison223(
        storage,
        company,
        comparison.Comparison223Request(notices=(refs[("32600000001", 1)], other)),
        now=NOW,
    )
    assert stale.rows[0].blocking_reasons == ("NOTICE_VERSION_STALE",)
    with pytest.raises(LookupError):
        comparison.get_comparison223(storage, "other-" + company, request, now=NOW)
    with pytest.raises(ValueError, match="NOTICE_DIGEST_CONFLICT"):
        comparison.get_comparison223(
            storage,
            company,
            comparison.Comparison223Request(
                notices=(other, first.model_copy(update={"notice_xml_sha256": "f" * 64}))
            ),
            now=NOW,
        )
    assert all_counts() == before


def test_223_refresh_families_are_fair_bounded_and_sql_scoped(storage):
    from datetime import timedelta

    from procurement.sources.eis_223_sync import window_key
    from procurement.storage.eis_223_sync import due_windows, record_attempt
    from procurement.storage.models import eis_223_sync_attempts

    company = "test223-" + uuid4().hex
    now = NOW + timedelta(hours=10)
    initial = due_windows(storage, company, now)
    assert len(initial) == 10
    assert {t.document_type for t in initial} == {
        "purchaseNoticeAESMBO",
        "purchaseNoticeZKESMBO",
        "purchaseNotice",
        "purchaseNoticeKESMBO",
        "purchaseNoticeZPESMBO",
    }
    for target in initial[:2]:
        record_attempt(
            storage,
            company,
            window_key(target.day, target.document_type),
            "NO_DATA",
            actor_id="operator",
            checked_at=now,
            response_sha256="a" * 64,
        )
    # Batch cap leaves the other eight targets first, even if the first batch becomes due again.
    assert due_windows(storage, company, now) == initial[2:]
    assert due_windows(storage, company, now + timedelta(hours=6))[:2] == initial[2:4]
    for target in initial[2:]:
        record_attempt(
            storage,
            company,
            window_key(target.day, target.document_type),
            "NO_DATA",
            actor_id="operator",
            checked_at=now + timedelta(minutes=1),
            response_sha256="b" * 64,
        )
    assert due_windows(storage, company, now + timedelta(hours=5)) == ()
    assert len(due_windows(storage, "other-" + company, now)) == 10
    tomorrow = due_windows(storage, company, now + timedelta(days=1))
    assert len(tomorrow) == 10 and all(
        t.day.isoformat() in {"2026-10-02", "2026-10-03"} for t in tomorrow
    )
    assert [t.day.isoformat() for t in tomorrow[:5]] == ["2026-10-03"] * 5
    for invalid in ("purchaseNoticeAE", "purchaseNoticeAESMBO/extra"):
        key = window_key(initial[0].day).replace("purchaseNoticeAESMBO", invalid)
        with pytest.raises(ValueError, match="ATTEMPT_SCOPE_INVALID"):
            record_attempt(
                storage,
                company,
                key,
                "NO_DATA",
                actor_id="operator",
                checked_at=now,
                response_sha256="a" * 64,
            )
    with storage.transaction(company) as conn:
        row = dict(conn.execute(select(eis_223_sync_attempts)).mappings().first())
    for key in (
        row["window_key"].replace("/50/", "/00/"),
        row["window_key"].rsplit("/", 1)[0] + "/purchaseNoticeAE",
    ):
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(
                insert(eis_223_sync_attempts).values(
                    **{**row, "attempt_id": str(uuid4()), "window_key": key}
                )
            )
    # Cross-tenant checkpoint cannot be forged for the new family either.
    for family in ("purchaseNoticeZKESMBO", "purchaseNoticeZPESMBO"):
        quotation = next(t for t in initial if t.document_type == family)
        with pytest.raises(ValueError, match="SYNCED_CHECKPOINT_MISSING"):
            record_attempt(
                storage,
                company,
                window_key(quotation.day, quotation.document_type),
                "SYNCED",
                actor_id="operator",
                checked_at=now,
                response_sha256="a" * 64,
            )
    guard_before = counts(storage, company)
    with storage.transaction(company, consistent_read=True) as conn:
        attempt_count = conn.scalar(select(func.count()).select_from(eis_223_sync_attempts))
    assert_direct_downgrade_guard(
        "20261003_01_eis_223_general_notice",
        expected_database="procurement_eis_test_20261005_s209",
        match="223 general history must be preserved",
    )
    assert counts(storage, company) == guard_before
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_223_sync_attempts)) == attempt_count
