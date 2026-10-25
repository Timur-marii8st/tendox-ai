"""Full saved corpus selection, cross-law continuation and exact delivery provenance."""

from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from test_eis_223_index_pg import storage as storage
from test_eis_notice_index_pg import _window

from procurement.storage.eis_223_index import ingest_notice223_window
from procurement.storage.eis_global_price import GlobalPriceOptions, search_global_price
from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_notice_index import ingest_ready_window
from procurement.storage.eis_search_pagination import SearchPageError
from procurement.storage.models import audit_events
from test_eis_223_archive import xml, zip_bytes
from test_eis_223_index import NOW, window
from test_eis_feed_archive import _archive, _notice


def count_audit(storage, company):
    with storage.transaction(company) as conn:
        return conn.scalar(select(func.count()).select_from(audit_events))


@pytest.fixture(scope="module")
def corpus(storage):
    company = "global-price-" + uuid4().hex
    entries44 = []
    entries223 = []
    for i in range(205):
        number = f"{i + 1:019d}"
        amount = "9999999.00000001" if i == 204 else str(i + 1000)
        region = "Республика Татарстан" if i == 204 else "Москва"
        raw = (
            _notice(number)
            .decode()
            .replace("182420.00", amount)
            .replace(
                "</contractConditionsInfo>",
                f"<deliveryPlaceInfo><deliveryPlace><region><name>{region}</name></region></deliveryPlace></deliveryPlaceInfo></contractConditionsInfo>",
            )
        )
        entries44.append((number + ".xml", raw.encode()))
        n223 = f"{32600000001 + i:011d}"
        raw223 = (
            xml(amount=str(2000 + i), deadline="2026-10-09T08:00:00Z")
            .decode()
            .replace("32600000001", n223)
        )
        # Structured delivery place; customer location intentionally disagrees.
        raw223 = raw223.replace(
            "<t:lotData>",
            "<t:lotData><t:deliveryPlace><t:region>Москва</t:region></t:deliveryPlace>",
        )
        entries223.append((n223 + ".xml", raw223.encode()))
    ingest_ready_window(
        storage, company, _window("17", _archive(*entries44)), actor_id="test", received_at=NOW
    )
    raws = tuple(zip_bytes(entries223[i : i + 100]) for i in range(0, len(entries223), 100))
    base = window(raws[0])
    multi = base.model_copy(
        update={
            "archives": raws,
            "archive_urls": tuple(
                base.archive_urls[0].replace("A" * 32, f"{i + 1:032X}") for i in range(len(raws))
            ),
        }
    )
    ingest_notice223_window(storage, company, multi, actor_id="test", now=NOW)
    return company


def test_best_notice_outside_first100_is_selected_and_all410_continue_without_loss(storage, corpus):
    company = corpus
    legacy = search_eis_index(storage, company, "бумага", now=NOW)
    assert "0000000000000000205" not in [x.purchase_number for x in legacy.matched]
    before = count_audit(storage, company)
    opts = GlobalPriceOptions(query="бумага")
    page = search_global_price(storage, company, opts, now=NOW, limit=73)
    seen = []
    values = []
    assert page.result44.matched[0].purchase_number == "0000000000000000205"
    while True:
        from procurement.storage.eis_global_price import source_price223

        rows = [("44", x.purchase_number, x.nmck_rub) for x in page.result44.matched] + [
            ("223", x.notice.purchase_number, source_price223(x)) for x in page.result223.matched
        ]
        rows.sort(
            key=lambda r: (
                r[2] is None,
                r[2].copy_negate() if r[2] is not None else Decimal(0),
                r[0],
                r[1],
            )
        )
        values.extend(r[2] for r in rows)
        seen.extend((r[0], r[1]) for r in rows)
        assert len(rows) <= 73 and page.matched_count == 410
        if not page.next_cursor:
            break
        page = search_global_price(
            storage,
            company,
            opts,
            now=NOW + timedelta(minutes=1),
            cursor=page.next_cursor,
            limit=73,
        )
    assert len(seen) == len(set(seen)) == 410
    assert values == sorted(values, reverse=True)
    assert count_audit(storage, company) == before


def test_region_is_applied_before_limit_to_exact_xml_and_aliases(storage, corpus):
    tat = search_global_price(
        storage,
        corpus,
        GlobalPriceOptions(query="бумага", delivery_region="Татарстан респ."),
        now=NOW,
        limit=1,
    )
    assert (
        tat.matched_count == 1 and tat.result44.matched[0].purchase_number == "0000000000000000205"
    )
    assert tat.navigation and all(x.delivery_regions for x in tat.navigation.values())
    moscow = search_global_price(
        storage,
        corpus,
        GlobalPriceOptions(query="бумага", delivery_region="г. Москва"),
        now=NOW,
        limit=100,
    )
    assert moscow.matched_count == 409 and not moscow.result44.matched
    assert len(moscow.result223.matched) == 100
    assert not search_global_price(
        storage, "other-" + uuid4().hex, GlobalPriceOptions(query="бумага"), now=NOW
    ).matched_count


@pytest.mark.parametrize("law", ["44", "223"])
def test_many_archive_origins_use_bounded_sql_without_losing_navigation(storage, law):
    company = "global-batch-" + uuid4().hex
    expected = {}
    for index in range(20):
        if law == "44":
            number = f"{index + 1:019d}"
            raw = (
                _notice(number)
                .decode()
                .replace(
                    "</contractConditionsInfo>",
                    "<deliveryPlaceInfo><deliveryPlace><region><name>Москва</name></region>"
                    "</deliveryPlace></deliveryPlaceInfo></contractConditionsInfo>",
                )
                .encode()
            )
            ingest_ready_window(
                storage,
                company,
                _window(f"{index:02d}", _archive(("notice.xml", raw))),
                actor_id="test",
                received_at=NOW,
            )
        else:
            number = f"{32600000001 + index:011d}"
            raw = (
                xml(deadline="2026-10-09T08:00:00Z")
                .decode()
                .replace("32600000001", number)
                .replace(
                    "<t:lotData>",
                    "<t:lotData><t:deliveryPlace><t:region>Москва</t:region></t:deliveryPlace>",
                )
                .encode()
            )
            item = window(zip_bytes([("notice.xml", raw)]))
            item = item.model_copy(
                update={
                    "window_key": item.window_key.replace("2026-10-01", f"2026-09-{index + 1:02d}"),
                }
            )
            ingest_notice223_window(storage, company, item, actor_id="test", now=NOW)
        expected[number] = sha256(raw).hexdigest()

    queries = []
    table = "eis_feed_archives" if law == "44" else "eis_223_blobs"

    def record_sql(connection, cursor, statement, parameters, context, executemany):
        if f"{table}.content" in statement and statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    before = count_audit(storage, company)
    event.listen(storage._engine, "before_cursor_execute", record_sql)
    try:
        result = search_global_price(
            storage,
            company,
            GlobalPriceOptions(query="бумага", law=law, delivery_region="Москва"),
            now=NOW,
            limit=100,
        )
    finally:
        event.remove(storage._engine, "before_cursor_execute", record_sql)
    assert result.matched_count == 20 and result.unknown_region_count == 0
    assert {nav.purchase_number: nav.xml_sha256 for nav in result.navigation.values()} == expected
    assert len(queries) == 2  # One bounded metadata query, then exact-origin content join.
    assert count_audit(storage, company) == before


def test_region_and_law_change_reject_existing_cursor(storage, corpus):
    first = search_global_price(
        storage, corpus, GlobalPriceOptions(query="бумага"), now=NOW, limit=1
    )
    with pytest.raises(SearchPageError, match="INVALID"):
        search_global_price(
            storage,
            corpus,
            GlobalPriceOptions(query="бумага", law="44"),
            now=NOW,
            cursor=first.next_cursor,
        )
    with pytest.raises(SearchPageError, match="INVALID"):
        search_global_price(
            storage,
            corpus,
            GlobalPriceOptions(query="бумага", delivery_region="Москва"),
            now=NOW,
            cursor=first.next_cursor,
        )


def test_unknown_region_is_explicit_and_late_import_does_not_change_old_snapshot(storage):
    company = "global-unknown-" + uuid4().hex
    ingest_ready_window(
        storage,
        company,
        _window(
            "17",
            _archive(
                ("one.xml", _notice("0000000000000000001")),
                ("two.xml", _notice("0000000000000000002")),
            ),
        ),
        actor_id="test",
        received_at=NOW,
    )
    opts = GlobalPriceOptions(query="бумага", law="44", delivery_region="Москва")
    hidden = search_global_price(storage, company, opts, now=NOW, limit=1)
    assert hidden.matched_count == 0 and hidden.unknown_region_count == 2
    opts = opts.model_copy(update={"include_unknown_region": True})
    first = search_global_price(storage, company, opts, now=NOW, limit=1)
    assert first.matched_count == 2 and first.next_cursor
    ingest_ready_window(
        storage,
        company,
        _window(
            "18",
            _archive(
                ("late.xml", _notice("0000000000000000003").replace(b"182420.00", b"999999999.00"))
            ),
        ),
        actor_id="test",
        received_at=NOW + timedelta(seconds=10),
    )
    second = search_global_price(
        storage, company, opts, now=NOW + timedelta(minutes=1), limit=1, cursor=first.next_cursor
    )
    assert second.matched_count == 2 and not second.next_cursor
    assert second.page_snapshot_sha256 == first.page_snapshot_sha256
    fresh = search_global_price(storage, company, opts, now=NOW + timedelta(minutes=1), limit=1)
    assert (
        fresh.matched_count == 3
        and fresh.result44.matched[0].purchase_number == "0000000000000000003"
    )


def test_global_cancellation_invalidates_cursor_and_cannot_win_by_price(storage):
    from datetime import date

    from test_eis_search_pagination_pg import event_for

    from procurement.sources.eis_feed_sync import EisDateSelection
    from procurement.storage.eis_notice_index import EisReadyWindow

    company = "global-cancel-" + uuid4().hex
    entries = [
        (f"{i}.xml", _notice(f"{i + 1:019d}").replace(b"182420.00", str(1000 - i).encode()))
        for i in range(3)
    ]
    ingest_ready_window(
        storage, company, _window("17", _archive(*entries)), actor_id="test", received_at=NOW
    )
    opts = GlobalPriceOptions(query="бумага", law="44")
    first = search_global_price(storage, company, opts, now=NOW, limit=1)
    number = first.result44.matched[0].purchase_number
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
    with pytest.raises(SearchPageError, match="CHANGED"):
        search_global_price(
            storage,
            company,
            opts,
            now=NOW + timedelta(seconds=2),
            cursor=first.next_cursor,
            limit=1,
        )
    fresh = search_global_price(storage, company, opts, now=NOW + timedelta(seconds=2))
    assert fresh.result44.matched[-1].purchase_number == number
    assert fresh.result44.matched[-1].application_status == "FAIL"
