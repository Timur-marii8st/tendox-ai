"""Law, lot and source boundaries; source fixtures are synthetic."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from procurement.sources.eis_223_archive import parse_notice223_xml
from procurement.sources.eis_feed import EisArchiveReference, EisFeedResponse
from procurement.storage.eis_223_index import (
    Eis223IndexConflict,
    Eis223ReadyWindow,
    bind_notice223_window,
    compare_notice223,
    preflight_notice223_window,
)
from test_eis_223_archive import xml, zip_bytes

NOW = datetime(2026, 10, 2, tzinfo=UTC)


@pytest.mark.parametrize(
    "value,query,expected",
    [
        ("Услуги по оценке ценных бумаг", "бумага", False),
        ("Операции с ценными бумагами", "бумага", False),
        ("Услуги по оценке ценных бумаг", "ценные бумаги", True),
        ("Ценные бумаги и офисная бумага", "бумага", True),
        ("Бумага офисная и ценные бумаги", "бумага", True),
        ("Поставка бумаги офисной", "бумага", True),
        ("Определение цены бумаги для печати", "бумага", True),
        ("Мониторинг цен бумаги офисной", "бумага", True),
    ],
)
def test_paper_and_securities_sense_in_223_fields(value, query, expected):
    raw = xml().decode().replace("Поставка бумаги", value)
    raw = raw.replace("Бумага для печати", value).replace("Бумага А4 80", value)
    notice = parse_notice223_xml(raw.encode(), source_member="synthetic.xml")
    lead = compare_notice223(
        notice,
        query,
        now=NOW,
        source_window="getDocsIP/RI223/77/2026-10-01+03:00/purchaseNoticeAESMBO",
        source_response_sha256="b" * 64,
        archive_sha256="c" * 64,
    )
    assert (lead is not None) is expected
    if lead is not None:
        assert lead.match_quality == "STRONG"
        assert lead.application_status == "UNKNOWN"
        assert lead.term_evidence[0].source_value == value


@pytest.mark.parametrize("size", [0, 200, 451])
def test_search_visits_all_bounded_batches_and_matches_global_oracle(size):
    from contextlib import contextmanager

    from procurement.storage.eis_223_index import search_notice223_index

    query = "бумага а4"
    rows, oracle = [], []
    for index in range(size):
        raw = xml().replace(b"32600000001", f"326{index:08d}".encode())
        if index < size - 20:
            raw = raw.replace("Бумага А4 80".encode(), "Офисная бумага".encode())
        notice = parse_notice223_xml(raw, source_member="synthetic.xml")
        rows.append(
            {
                "snapshot": notice.model_dump(mode="json"),
                "purchase_number": notice.purchase_number,
                "version_number": notice.version_number,
                "xml_sha256": notice.xml_sha256,
                "window_key": KEY,
                "response_sha256": "b" * 64,
                "archive_sha256": "c" * 64,
            }
        )
        oracle.append(
            compare_notice223(
                notice,
                query,
                now=NOW,
                source_window=KEY,
                source_response_sha256="b" * 64,
                archive_sha256="c" * 64,
            )
        )
    oracle = sorted(
        (r for r in oracle if r),
        key=lambda r: (
            r.application_status == "FAIL",
            r.match_quality != "STRONG",
            -len(r.matched_terms),
            r.notice.purchase_number,
        ),
    )
    batches, transactions, quality_refs, projection_refs = [], [], [], []

    class Result:
        def __init__(self, values):
            self.values = values

        def scalar_one(self):
            return size

        def one(self):
            return (1, NOW)

        def mappings(self):
            return self

        def scalars(self):
            return self

        def all(self):
            return self.values

        def __iter__(self):
            return iter(self.values)

    class Connection:
        def execute(self, statement):
            sql = str(statement)
            params = statement.compile().params
            if "FROM eis_223_events" in sql or "FROM eis_223_lot_events" in sql:
                return Result([])
            if "FROM eis_223_schema_checks" in sql:
                quality_refs.extend(next(v for v in params.values() if isinstance(v, list)))
                return Result([])
            if "FROM eis_223_position_projections" in sql:
                projection_refs.extend(next(v for v in params.values() if isinstance(v, list)))
                return Result([])
            if "count(" in sql:
                return Result([])
            assert "LIMIT" in sql and "OFFSET" not in sql and "ORDER BY" in sql
            limit = next(v for k, v in params.items() if k.startswith("param_"))
            assert limit <= 200
            cursor = next((v for k, v in params.items() if k.startswith("purchase_number_")), "")
            selected = [r for r in rows if r["purchase_number"] > cursor][:limit]
            batches.append(len(selected))
            return Result(selected)

    class Storage:
        @contextmanager
        def transaction(self, company, *, consistent_read):
            transactions.append((company, consistent_read))
            yield Connection()

    result = search_notice223_index(Storage(), "tenant-a", query, now=NOW)
    assert transactions == [("tenant-a", True)]
    assert sum(batches) == result.evaluated_candidates == size
    assert result.matched_count == len(oracle)
    from procurement.sources.eis_223_events import resolve_purchase_rejection_state
    from procurement.sources.eis_223_lot_event_policy import resolve_lot_cancellation_state

    expected = [
        r.model_copy(
            update={
                "lot_cancellation_state": resolve_lot_cancellation_state(
                    r.notice.purchase_number, (), (), now=NOW
                ),
                "cancellation_state": resolve_purchase_rejection_state(
                    r.notice.purchase_number, (), (), now=NOW
                ),
            }
        )
        for r in oracle[:100]
    ]
    assert list(result.matched) == expected
    assert len(quality_refs) == min(100, len(oracle))
    assert len(projection_refs) == min(100, len(oracle))
    if size == 451:
        assert (
            batches == [200, 200, 51] and result.matched[0].notice.purchase_number == "32600000431"
        )


KEY = "getDocsIP/RI223/50/2026-10-01+03:00/purchaseNoticeAESMBO"
UID = "11111111-1111-4111-8111-111111111111"
ARCHIVE_UID = "a" * 32
URL = (
    "https://int44.zakupki.gov.ru/dstore/common/download/compound"
    f"?docRequestUid={UID}&compoundUid={ARCHIVE_UID.upper()}"
)


def window(raw=None, *, response="b" * 64):
    return Eis223ReadyWindow(
        window_key=KEY,
        response_sha256=response,
        prepared_sha256="c" * 64,
        archives=(raw or zip_bytes([("notice.xml", xml())]),),
        archive_urls=(URL,),
    )


def compare(raw, query):
    return compare_notice223(
        parse_notice223_xml(raw, source_member="notice.xml"),
        query,
        now=NOW,
        source_window=KEY,
        source_response_sha256="b" * 64,
        archive_sha256="c" * 64,
    )


def responses():
    initial = EisFeedResponse(
        service="IP",
        kind="BY_REGION",
        state="LINKS_PENDING",
        source_mode="PROD",
        response_id=UID,
        request_id=UID,
        created_at=NOW,
        source_time_raw=NOW.isoformat(),
        source_time_status="AWARE",
        source_sha256="b" * 64,
        archive_urls=(URL,),
    )
    prepared = replace(
        initial,
        kind="PREPARED",
        state="READY",
        source_sha256="c" * 64,
        archive_urls=(),
        prepared_archives=(EisArchiveReference(URL, ARCHIVE_UID),),
        doc_request_uid=UID,
    )
    return initial, prepared


def source_set(count: int):
    initial, prepared = responses()
    urls = tuple(URL.replace(ARCHIVE_UID.upper(), f"{index:032x}") for index in range(1, count + 1))
    initial = replace(initial, archive_urls=urls)
    prepared = replace(
        prepared,
        prepared_archives=tuple(
            EisArchiveReference(source_url, f"{index:032x}")
            for index, source_url in enumerate(urls, 1)
        ),
    )
    raws = tuple(
        zip_bytes(
            [
                (
                    f"notice-{index}.xml",
                    xml().replace(b"32600000001", f"326{index:08d}".encode()),
                )
            ]
        )
        for index in range(1, count + 1)
    )
    return initial, prepared, dict(zip(urls, raws, strict=True))


def test_complete_window_binds_request_archive_set_and_exact_bytes():
    initial, prepared = responses()
    raw = window().archives[0]
    ready = bind_notice223_window(KEY, initial, prepared, {URL: raw})
    inspections, manifest = preflight_notice223_window("tenant-a", ready)
    assert len(inspections) == 1 and len(manifest) == 64
    assert inspections[0].records[0].law == "223"


def test_four_archive_source_set_binds_and_preflights_completely():
    initial, prepared, downloaded = source_set(4)
    ready = bind_notice223_window(KEY, initial, prepared, downloaded)
    inspections, manifest = preflight_notice223_window("tenant-a", ready)
    assert len(ready.archives) == len(inspections) == 4
    assert len(manifest) == 64
    assert {item.records[0].purchase_number for item in inspections} == {
        "32600000001",
        "32600000002",
        "32600000003",
        "32600000004",
    }


def test_nine_complete_archives_report_count_limit_after_exact_set_binding():
    initial, prepared, downloaded = source_set(9)
    with pytest.raises(Eis223IndexConflict, match="ARCHIVE_COUNT_LIMIT"):
        bind_notice223_window(KEY, initial, prepared, downloaded)
    downloaded.pop(next(iter(downloaded)))
    with pytest.raises(Eis223IndexConflict, match="ARCHIVE_SET_MISMATCH"):
        bind_notice223_window(KEY, initial, prepared, downloaded)


def test_five_archives_with_433_members_form_one_complete_window():
    initial, prepared, downloaded = source_set(5)
    offset = 0
    for source_url, count in zip(downloaded, (100, 100, 100, 100, 33), strict=True):
        downloaded[source_url] = zip_bytes(
            [
                (
                    f"notice-{offset + i}.xml",
                    xml().replace(b"32600000001", f"326{offset + i:08d}".encode()),
                )
                for i in range(1, count + 1)
            ]
        )
        offset += count
    ready = bind_notice223_window(KEY, initial, prepared, downloaded)
    inspections, manifest = preflight_notice223_window("tenant-a", ready)
    assert len(inspections) == 5
    assert sum(len(item.records) for item in inspections) == 433
    assert len(manifest) == 64


def test_801_members_refused_before_any_xml_parse(monkeypatch):
    import procurement.storage.eis_223_index as subject

    initial, prepared, downloaded = source_set(5)
    for source_url, count in zip(downloaded, (200, 200, 200, 200, 1), strict=True):
        downloaded[source_url] = zip_bytes([(f"notice-{i}.xml", xml()) for i in range(count)])
    ready = bind_notice223_window(KEY, initial, prepared, downloaded)

    def no_parse(*args, **kwargs):
        pytest.fail("aggregate member refusal must precede XML parsing")

    monkeypatch.setattr(subject, "inspect_notice223_archive", no_parse)
    with pytest.raises(Eis223IndexConflict, match="WINDOW_MEMBER_LIMIT"):
        preflight_notice223_window("tenant-a", ready)


def test_duplicate_source_uid_is_set_mismatch_not_count_success():
    initial, prepared, downloaded = source_set(4)
    duplicate = prepared.prepared_archives[0]
    prepared = replace(
        prepared,
        prepared_archives=(*prepared.prepared_archives[:-1], duplicate),
    )
    with pytest.raises(Eis223IndexConflict, match="ARCHIVE_SET_MISMATCH"):
        bind_notice223_window(KEY, initial, prepared, downloaded)


def test_all_zip_headers_are_bounded_before_any_xml_parse(monkeypatch):
    import procurement.storage.eis_223_index as subject

    initial, prepared, downloaded = source_set(2)
    ready = bind_notice223_window(KEY, initial, prepared, downloaded)
    monkeypatch.setattr(subject, "MAX_NOTICE_MEMBERS", 1)

    def no_parse(*args, **kwargs):
        pytest.fail("XML parsing must follow full-window header checks")

    monkeypatch.setattr(subject, "inspect_notice223_archive", no_parse)
    with pytest.raises(Eis223IndexConflict, match="WINDOW_MEMBER_LIMIT"):
        preflight_notice223_window("tenant-a", ready)


def test_per_archive_expansion_limit_is_checked_before_xml_parse(monkeypatch):
    import procurement.storage.eis_223_index as subject

    ready = window()
    monkeypatch.setattr(subject, "MAX_ARCHIVE_EXPANDED_BYTES", 1)

    def no_parse(*args, **kwargs):
        pytest.fail("per-ZIP headers must be bounded before XML parsing")

    monkeypatch.setattr(subject, "inspect_notice223_archive", no_parse)
    with pytest.raises(Eis223IndexConflict, match="ARCHIVE_RESOURCE_LIMIT"):
        preflight_notice223_window("tenant-a", ready)


def test_final_bad_zip_never_partially_preflights(monkeypatch):
    import procurement.storage.eis_223_index as subject

    initial, prepared, downloaded = source_set(2)
    downloaded[prepared.prepared_archives[-1].url] = b"not-a-zip"
    ready = bind_notice223_window(KEY, initial, prepared, downloaded)

    def no_parse(*args, **kwargs):
        pytest.fail("earlier ZIP XML must not parse before final ZIP header validation")

    monkeypatch.setattr(subject, "inspect_notice223_archive", no_parse)
    with pytest.raises(Eis223IndexConflict, match="ARCHIVE_INVALID"):
        preflight_notice223_window("tenant-a", ready)


@pytest.mark.parametrize("change", ["test", "uid", "empty", "forged", "extra", "pending"])
def test_incomplete_or_rebound_window_is_rejected(change):
    initial, prepared = responses()
    downloaded = {URL: window().archives[0]}
    if change == "test":
        initial = replace(initial, source_mode="TEST")
    elif change == "uid":
        prepared = replace(prepared, doc_request_uid="22222222-2222-4222-8222-222222222222")
    elif change == "empty":
        downloaded = {}
    elif change == "forged":
        fake = URL.replace(ARCHIVE_UID.upper(), "D" * 32)
        prepared = replace(prepared, prepared_archives=(EisArchiveReference(fake, ARCHIVE_UID),))
        downloaded = {fake: window().archives[0]}
    elif change == "extra":
        downloaded[URL + "x"] = b"extra"
    else:
        prepared = replace(prepared, state="PREPARING")
    with pytest.raises(ValueError):
        bind_notice223_window(KEY, initial, prepared, downloaded)


def test_duplicates_across_archives_are_rejected_before_storage():
    a = zip_bytes([("one.xml", xml())])
    b = zip_bytes([("two.xml", xml())])
    ready = window().model_copy(
        update={
            "archives": (a, b),
            "archive_urls": (URL, URL.replace(ARCHIVE_UID.upper(), "D" * 32)),
        }
    )
    with pytest.raises(Eis223IndexConflict, match="NOTICE_VERSION_DUPLICATE"):
        preflight_notice223_window("tenant-a", ready)


def test_window_family_is_selected_before_parsing_and_cannot_be_relabelled():
    family = "purchaseNoticeZKESMBO"
    raw = xml().replace(b"purchaseNoticeAESMBO", family.encode())
    selected = window(zip_bytes([("quotation.xml", raw)])).model_copy(
        update={
            "window_key": KEY.replace("purchaseNoticeAESMBO", family),
        }
    )
    inspections, _ = preflight_notice223_window("tenant-a", selected)
    assert inspections[0].records[0].document_type == family
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_UNSUPPORTED"):
        preflight_notice223_window("tenant-a", selected.model_copy(update={"window_key": KEY}))


def test_morphology_one_item_keeps_currency_and_unknown_deadline():
    lead = compare(xml(code="USD", numeric="840"), "бумаги А4 80")
    assert lead.match_quality == "STRONG" and lead.matched_lot_ordinal == "1"
    assert lead.application_status == "UNKNOWN" and lead.notice.lots[0].initial_sum_rub is None
    assert all(e.locator.endswith("additionalInfo") for e in lead.term_evidence)
    assert lead.notice.economics_status == "UNKNOWN"


def test_terms_from_separate_lots_never_form_strong_match():
    second = (
        "<t:lot><t:ordinalNumber>2</t:ordinalNumber><t:lotData>"
        "<t:subject>Сервер</t:subject></t:lotData></t:lot>"
    )
    lead = compare(xml(second_lot=second), "бумага сервер")
    assert lead.match_quality == "PARTIAL" and len(lead.matched_terms) == 1


def test_terms_from_separate_items_never_form_strong_match():
    raw = xml().decode().replace("Бумага А4 80", "Бумага А4")
    raw = raw.replace(
        "</t:lotItems>",
        "<t:lotItem><t:additionalInfo>Картон 80</t:additionalInfo></t:lotItem></t:lotItems>",
    )
    assert compare(raw.encode(), "бумага 80").match_quality == "PARTIAL"


def test_expired_aware_deadline_blocks_even_strong_match():
    lead = compare(xml(deadline="2026-10-01T08:00:00+03:00"), "бумага")
    assert lead.match_quality == "STRONG" and lead.application_status == "FAIL"
    assert "Срок подачи истёк" in lead.reasons[-1]


@pytest.mark.parametrize("query", ["", "а", "!!!", "x" * 121])
def test_invalid_query_fails_before_storage(query):
    with pytest.raises(ValueError):
        compare(xml(), query)


def test_prefix_collision_is_not_a_match():
    assert (
        compare(
            xml().replace("Поставка бумаги".encode(), "Поставка экспонатов".encode()), "экспозиции"
        )
        is None
    )


def test_complete_notice_window_above32mib_is_atomic_preflight():
    from io import BytesIO
    from zipfile import ZIP_STORED, ZipFile

    from procurement.sources.eis_223_window_limits import MAX_NOTICE_COMPRESSED_BYTES

    initial, prepared, downloaded = source_set(4)
    for i, ref in enumerate(prepared.prepared_archives, 1):
        raw = (
            xml().replace(b"32600000001", f"3260000000{i}".encode())
            + b"<!--"
            + b"x" * (8_500_000 - 7)
            + b"-->"
        )
        stream = BytesIO()
        with ZipFile(stream, "w", compression=ZIP_STORED) as z:
            z.writestr(f"large-{i}.xml", raw)
        downloaded[ref.url] = stream.getvalue()
    ready = bind_notice223_window(KEY, initial, prepared, downloaded)
    assert 32 * 1024**2 < sum(map(len, ready.archives)) < MAX_NOTICE_COMPRESSED_BYTES
    inspected, _ = preflight_notice223_window("tenant-a", ready)
    assert sum(len(a.records) for a in inspected) == 4


def test_notice_window_above40mib_rejected_before_any_xml(monkeypatch):
    import procurement.storage.eis_223_index as subject

    ready = window()
    oversized = ready.model_copy(update={"archives": (b"x" * (40 * 1024**2 + 1),)})
    monkeypatch.setattr(
        subject,
        "inspect_notice223_archive",
        lambda *a, **k: pytest.fail("must reject headers before parse"),
    )
    with pytest.raises(Eis223IndexConflict, match="WINDOW_BYTES_LIMIT"):
        preflight_notice223_window("tenant-a", oversized)
