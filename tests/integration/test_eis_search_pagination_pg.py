"""Exact multi-page parity, late imports, cancellation and tenant guards in real PG."""

from datetime import date, timedelta
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select
from test_eis_223_index_pg import storage as storage
from test_eis_notice_index_pg import _archive, _window, event_zip

from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.storage.eis_223_index import ingest_notice223_window, search_notice223_index
from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_notice_index import EisReadyWindow, ingest_ready_window
from procurement.storage.eis_search_pagination import SearchPageError
from procurement.storage.models import audit_events
from test_eis_223_archive import xml, zip_bytes
from test_eis_223_index import NOW, window


def audit_count(storage, company):
    with storage.transaction(company) as conn:
        return conn.scalar(select(func.count()).select_from(audit_events))


def archive44(size):
    out = BytesIO()
    with ZipFile(out, "w") as combined:
        for i in range(size):
            with ZipFile(
                BytesIO(
                    _archive(f"{i + 1:019d}", title="Поставка бумаги А4" if i % 3 else "Бумага")
                )
            ) as source:
                name = source.namelist()[0]
                combined.writestr(name, source.read(name))
    return out.getvalue()


def test_44_pages_have_exact_full_order_despite_later_imports_and_no_read_writes(storage):
    company = "paging44-" + uuid4().hex
    ingest_ready_window(
        storage, company, _window("17", archive44(205)), actor_id="test", received_at=NOW
    )
    oracle = search_eis_index(storage, company, "бумага а4", now=NOW).matched
    first = search_eis_index(storage, company, "бумага а4", now=NOW, paginate=True, limit=70)
    assert first.next_cursor and len(first.matched) == 70
    assert first.compared_candidate_notices == 205 and first.reused_candidate_notices == 0
    ingest_ready_window(
        storage,
        company,
        _window("18", _archive("9000000000000000000")),
        actor_id="test",
        received_at=NOW + timedelta(seconds=10),
    )
    before = audit_count(storage, company)
    pages = [first]
    while pages[-1].next_cursor:
        pages.append(
            search_eis_index(
                storage,
                company,
                "бумага а4",
                now=NOW + timedelta(minutes=1),
                paginate=True,
                cursor=pages[-1].next_cursor,
                limit=70,
            )
        )
    rows = tuple(row for page in pages for row in page.matched)
    assert len(rows) == len({row.purchase_number for row in rows}) == 205
    assert rows[:100] == oracle
    assert len(pages) == 3
    assert all(
        page.compared_candidate_notices == 0 and page.reused_candidate_notices == 205
        for page in pages[1:]
    )
    assert all(page.matched_count == 205 and page.snapshot_at == NOW for page in pages)
    assert len({page.page_snapshot_sha256 for page in pages}) == 1
    assert audit_count(storage, company) == before
    with pytest.raises(SearchPageError, match="SEARCH_PAGE_INVALID"):
        search_eis_index(
            storage,
            "other-" + company,
            "бумага а4",
            now=NOW,
            paginate=True,
            cursor=first.next_cursor,
        )


def event_for(number):
    out = BytesIO()
    with ZipFile(BytesIO(event_zip())) as source, ZipFile(out, "w") as target:
        target.writestr(
            "event.xml", source.read("event.xml").replace(b"0848300054826000154", number.encode())
        )
    return out.getvalue()


def test_new_cancellation_invalidates_44_continuation_and_blocks_fresh_search(storage):
    company = "paging44-event-" + uuid4().hex
    ingest_ready_window(
        storage, company, _window("17", archive44(3)), actor_id="test", received_at=NOW
    )
    first = search_eis_index(storage, company, "бумага", now=NOW, paginate=True, limit=1)
    number = first.matched[0].purchase_number
    ingest_ready_window(
        storage,
        company,
        EisReadyWindow(
            EisDateSelection("50", date(2026, 9, 25), 3, "epNotificationCancel").window_key,
            "c" * 64,
            1,
            (event_for(number),),
        ),
        actor_id="test",
        received_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(SearchPageError, match="SEARCH_PAGE_CHANGED"):
        search_eis_index(
            storage,
            company,
            "бумага",
            now=NOW + timedelta(seconds=2),
            paginate=True,
            cursor=first.next_cursor,
            limit=1,
        )
    fresh = search_eis_index(
        storage, company, "бумага", now=NOW + timedelta(seconds=2), paginate=True
    )
    assert (
        next(row for row in fresh.matched if row.purchase_number == number).application_status
        == "FAIL"
    )


def test_223_pages_cover_more_than_100_with_frozen_notice_scope(storage):
    company = "paging223-" + uuid4().hex
    entries = [
        (f"{i}.xml", xml().replace(b"32600000001", f"326{i:08d}".encode())) for i in range(205)
    ]
    for index, batch in enumerate((entries[:150], entries[150:])):
        ingest_notice223_window(
            storage,
            company,
            window(zip_bytes(batch), response=str(index + 1) * 64),
            actor_id="test",
            now=NOW,
        )
    oracle = search_notice223_index(storage, company, "бумага", now=NOW).matched
    first = search_notice223_index(storage, company, "бумага", now=NOW, paginate=True, limit=70)
    extra = xml().replace(b"32600000001", b"32699999999")
    ingest_notice223_window(
        storage,
        company,
        window(zip_bytes([("extra.xml", extra)]), response="d" * 64),
        actor_id="test",
        now=NOW + timedelta(seconds=10),
    )
    before = audit_count(storage, company)
    second = search_notice223_index(
        storage,
        company,
        "бумага",
        now=NOW + timedelta(minutes=1),
        paginate=True,
        cursor=first.next_cursor,
        limit=70,
    )
    third = search_notice223_index(
        storage,
        company,
        "бумага",
        now=NOW + timedelta(minutes=2),
        paginate=True,
        cursor=second.next_cursor,
        limit=70,
    )
    rows = first.matched + second.matched + third.matched
    assert len(rows) == len({row.notice.purchase_number for row in rows}) == 205
    assert rows[:100] == oracle and third.next_cursor is None
    assert first.compared_candidates == 205 and first.reused_candidates == 0
    assert second.compared_candidates == third.compared_candidates == 0
    assert second.reused_candidates == third.reused_candidates == 205
    assert first.page_snapshot_sha256 == second.page_snapshot_sha256 == third.page_snapshot_sha256
    assert all(row.application_status in {"UNKNOWN", "FAIL"} for row in rows)
    assert audit_count(storage, company) == before


@pytest.mark.parametrize("change", ["event", "schema"])
def test_223_cached_base_never_hides_new_live_evidence(storage, change):
    company = "paging223-live-" + uuid4().hex
    entries = [
        (f"{i}.xml", xml().replace(b"32600000001", f"326{i:08d}".encode())) for i in range(3)
    ]
    ingest_notice223_window(storage, company, window(zip_bytes(entries)), actor_id="test", now=NOW)
    first = search_notice223_index(storage, company, "бумага", now=NOW, paginate=True, limit=1)
    warm = search_notice223_index(
        storage, company, "бумага", now=NOW, paginate=True, cursor=first.next_cursor, limit=1
    )
    assert warm.compared_candidates == 0 and warm.reused_candidates == 3
    notice = first.matched[0].notice
    if change == "event":
        from test_eis_223_events_pg import quality, store

        from test_eis_223_events import event_xml

        raw = event_xml(number=notice.purchase_number)
        store(storage, company, raw)
        quality(storage, company, raw)
    else:
        from procurement.sources.eis_223_schema import (
            SCHEMAS,
            VALIDATOR,
            Eis223SchemaCheck,
            SchemaDiagnostic,
        )
        from procurement.storage.eis_223_quality import record_schema_check

        hashes = SCHEMAS["16.2"]
        record_schema_check(
            storage,
            company,
            Eis223SchemaCheck(
                purchase_number=notice.purchase_number,
                version_number=notice.version_number,
                xml_sha256=notice.xml_sha256,
                schema_release="16.2",
                package_sha256=hashes[0],
                root_sha256=hashes[1],
                tree_sha256=hashes[2],
                validator_version=VALIDATOR,
                status="FAIL",
                diagnostics=(
                    SchemaDiagnostic(
                        line=1, path="/synthetic", type_name="TEST", message="synthetic"
                    ),
                ),
                checked_at=NOW,
            ),
            actor_id="test",
        )
    before = audit_count(storage, company)
    with pytest.raises(SearchPageError, match="SEARCH_PAGE_CHANGED"):
        search_notice223_index(
            storage,
            company,
            "бумага",
            now=NOW + timedelta(seconds=2),
            paginate=True,
            cursor=first.next_cursor,
            limit=1,
        )
    assert audit_count(storage, company) == before
