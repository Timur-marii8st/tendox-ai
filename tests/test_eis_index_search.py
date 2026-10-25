"""The comparison never turns relevance or NMCK into participation approval."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from procurement.domain.discovery_economics import DiscoveryCostInput
from procurement.sources.eis_feed_archive import (
    EisCharacteristic,
    EisCharacteristicValue,
    EisLotItem,
    EisNoticeSnapshot,
)
from procurement.sources.eis_index_search import compare_indexed_notices, search_keys_v1
from procurement.sources.eis_procedure_state import EisProcedureState

NOW = datetime(2026, 9, 27, tzinfo=UTC)
DEADLINE = datetime(2026, 10, 5, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    "query,title",
    [
        ("маски", "Медицинских масок"),
        ("Бумага", "поставка бумаги"),
        ("серверное оборудование", "Серверного оборудования"),
        ("ёжики", "Ежики"),
        ("SSD 512", "SSD 512"),
    ],
)
def test_lexical_prefilter_does_not_lose_real_comparison_match(query: str, title: str) -> None:
    result = compare_indexed_notices((_notice("0848300054826000154", title),), query, now=NOW)
    assert result.matched_notices
    assert set(search_keys_v1(query)) & set(search_keys_v1(title))


def _notice(number: str, title: str, version: int = 1) -> EisNoticeSnapshot:
    return EisNoticeSnapshot(
        purchase_number=number,
        document_type="epNotificationEF2020",
        version_number=version,
        title=title,
        published_at=NOW,
        deadline=DEADLINE,
        nmck_rub=Decimal("182420.00"),
        xml_sha256=str(version) * 64,
        source_member=f"{number}.xml",
    )


@pytest.mark.parametrize(
    "query,title",
    [
        ("экспозиции", "Награждение экспортера года"),
        ("экспозиции", "Перевозка военных экспонатов"),
        ("серверы", "Сервировка стола"),
        ("контракт", "Контрацептивы"),
        ("кабель", "Кабельное оборудование"),
        ("SSD 512", "SSD 5120"),
    ],
)
def test_coarse_prefix_alone_cannot_produce_strong_evidence(query, title):
    notice = _notice("9000000000000000001", title)
    result = compare_indexed_notices((notice,), query, now=NOW)
    assert not result.matched_notices or result.matched_notices[0].match_quality == "PARTIAL"
    assert all(query.split()[-1] not in n.matched_terms for n in result.matched_notices)


@pytest.mark.parametrize(
    "query,title",
    [
        ("экспозиции", "Проектирование экспозиции"),
        ("бумага", "Поставка бумаги"),
        ("серверное оборудование", "Серверным оборудованием"),
        ("маски", "Поставка масок"),
    ],
)
def test_morphology_retains_exact_source_value_and_locator(query, title):
    notice = _notice("9000000000000000001", title)
    match = compare_indexed_notices((notice,), query, now=NOW).matched_notices[0]
    assert match.match_quality == "STRONG"
    assert all(e.source_value == title and e.value_kind == "TITLE" for e in match.term_evidence)
    assert all(e.locator.endswith("/commonInfo/purchaseObjectInfo") for e in match.term_evidence)


def test_coarse_persisted_keys_remain_identical_despite_refinement():
    assert search_keys_v1("экспозиции экспонатов экспортер") == ("экспо",)
    assert search_keys_v1("Серверного оборудования") == ("обору", "серве")


@pytest.mark.parametrize(
    "value",
    [
        "Услуги по оценке Векселя, облигации, акции и др. ценные бумаги",
        "Депозитарный учет ценных бумаг",
        "Операции с ценными бумагами",
        "ЦЕННЫЕ БУМАГИ, ценные бумаги",
    ],
)
def test_paper_query_excludes_securities_in_title_and_item(value):
    notice = _notice("9000000000000000001", value)
    assert not compare_indexed_notices((notice,), "бумага", now=NOW).matched_notices
    item = replace(
        _paper_item("А4"), name=value, characteristics=(), locator="synthetic/purchaseObject[42]"
    )
    notice = replace(notice, title="Услуги по оценке имущества", lot_items=(item,))
    assert not compare_indexed_notices((notice,), "бумага", now=NOW).matched_notices
    assert "бумаг" in search_keys_v1(value)  # No derived-index migration.


@pytest.mark.parametrize(
    "value",
    [
        "Поставка бумаги офисной",
        "Бумага для печати",
        "Ценные бумаги и офисная бумага",
        "Бумага офисная и ценные бумаги",
        "Бланки на самокопирующейся бумаге для приема вещей и ценностей",
        "Определение цены бумаги для печати",
        "Мониторинг цен бумаги офисной",
    ],
)
def test_paper_occurrence_is_preserved_even_next_to_financial_occurrences(value):
    notice = _notice("9000000000000000001", value)
    lead = compare_indexed_notices((notice,), "бумага", now=NOW).matched_notices[0]
    assert lead.match_quality == "STRONG"
    assert lead.term_evidence[0].source_value == value


def test_paper_item_remains_visible_under_securities_title():
    notice = replace(
        _notice("9000000000000000001", "Учет ценных бумаг"),
        lot_items=(
            replace(
                _paper_item("А4"),
                name="Бумага офисная",
                characteristics=(),
                locator="synthetic/item",
            ),
        ),
    )
    lead = compare_indexed_notices((notice,), "бумага", now=NOW).matched_notices[0]
    assert lead.match_quality == "STRONG"
    assert lead.term_evidence[0].value_kind == "ITEM_NAME"


def test_explicit_securities_query_still_matches_morphology():
    notice = _notice("9000000000000000001", "Депозитарный учет ценных бумаг")
    lead = compare_indexed_notices((notice,), "ценные бумаги", now=NOW).matched_notices[0]
    assert lead.match_quality == "STRONG"


def test_price_query_does_not_enable_the_financial_paper_sense():
    notice = _notice("9000000000000000001", "Оценка ценных бумаг")
    leads = compare_indexed_notices((notice,), "бумага цена", now=NOW).matched_notices
    assert all(
        lead.match_quality == "PARTIAL" and "бумага" not in lead.matched_terms for lead in leads
    )


def test_open_competition_never_approves_unreviewed_criteria_or_economics():
    notice = replace(
        _notice("0848300054826000154", "Поставка бумаги"), document_type="epNotificationEOK2020"
    )
    lead = compare_indexed_notices((notice,), "бумага", now=NOW).matched_notices[0]
    assert lead.application_status == lead.economics_status == "UNKNOWN"
    assert any("критерии оценки и квалификация UNKNOWN" in r for r in lead.reasons)
    expired = replace(notice, deadline=NOW)
    assert (
        compare_indexed_notices((expired,), "бумага", now=NOW).matched_notices[0].application_status
        == "FAIL"
    )


def test_paper_query_matches_one_of_multiple_archived_notices() -> None:
    paper = _notice("0848300054826000154", "Поставка бумаги для офисной техники")
    masks = _notice("0348200077726000176", "Поставка медицинских масок")
    result = compare_indexed_notices((paper, masks), "хочу перепродавать бумагу", now=NOW)
    assert result.inspected_current_notices == 2
    assert [item.snapshot.purchase_number for item in result.matched_notices] == [
        paper.purchase_number
    ]
    assert result.matched_notices[0].application_status == "UNKNOWN"
    assert result.matched_notices[0].match_quality == "STRONG"
    assert result.matched_notices[0].economics_status == "UNKNOWN"
    assert result.matched_notices[0].conservative_profit_rub is None
    assert result.corpus_coverage == "UNKNOWN"


def test_function_words_never_match_unrelated_items_or_widen_query_prefilter() -> None:
    paper = _notice("9000000000000000001", "Поставка бумаги для принтеров")
    unrelated = _notice("9000000000000000002", "Кресло для кабинета")
    result = compare_indexed_notices((paper, unrelated), "бумага для принтеров", now=NOW)
    assert [item.snapshot.purchase_number for item in result.matched_notices] == [
        paper.purchase_number
    ]
    assert result.matched_notices[0].match_quality == "STRONG"
    from procurement.sources.eis_index_search import search_query_keys_v1

    assert "для" not in search_query_keys_v1("бумага для принтеров")
    assert "для" in search_keys_v1("бумага для принтеров")  # Persisted v1 semantics stay stable.
    assert result.matched_notices[0].matched_terms == ("бумага", "принтеров")


def test_query_with_only_function_words_is_invalid():
    with pytest.raises(ValueError, match="QUERY_INVALID"):
        compare_indexed_notices((), "для или при", now=NOW)


def test_exact_costs_enable_only_preliminary_economic_order() -> None:
    first = _notice("0848300054826000154", "Поставка бумаги")
    second = _notice("0848300064126000341", "Бумага для печати")
    costs = DiscoveryCostInput(
        goods="80000",
        expenses="10000",
        vat_rate="0.20",
        basis="КП поставщика для всего лота",
        costs_complete_ack=True,
    )
    result = compare_indexed_notices(
        (first, second),
        "бумага",
        now=NOW,
        costs_by_exact_notice={(second.purchase_number, second.xml_sha256): costs},
    )
    assert result.matched_notices[0].snapshot.purchase_number == second.purchase_number
    assert result.matched_notices[0].economics_status == "ESTIMATE"
    assert result.matched_notices[0].application_status == "UNKNOWN"
    assert result.matched_notices[1].economics_status == "UNKNOWN"


def test_latest_version_replaces_old_title_and_stale_costs() -> None:
    old = _notice("0848300054826000154", "Поставка бумаги")
    current = _notice(old.purchase_number, "Поставка серверов", 2)
    result = compare_indexed_notices((old, current), "бумага", now=NOW)
    assert result.inspected_current_notices == 1
    assert result.matched_notices == ()


def test_expired_deadline_blocks_even_with_costs() -> None:
    notice = _notice("0848300054826000154", "Поставка бумаги")
    result = compare_indexed_notices(
        (notice,),
        "бумага",
        now=datetime(2026, 10, 6, tzinfo=UTC),
        costs_by_exact_notice={
            (notice.purchase_number, notice.xml_sha256): DiscoveryCostInput(
                goods="80000",
                expenses="10000",
                vat_rate="0.20",
                basis="КП",
                costs_complete_ack=True,
            )
        },
    )
    assert result.matched_notices[0].application_status == "FAIL"
    assert result.matched_notices[0].economics_status == "BLOCKED"
    assert result.matched_notices[0].conservative_profit_rub is None


def test_conflicting_same_version_is_rejected() -> None:
    first = _notice("0848300054826000154", "Поставка бумаги")
    with pytest.raises(ValueError, match="NOTICE_VERSION_CONFLICT"):
        compare_indexed_notices((first, replace(first, xml_sha256="b" * 64)), "бумага", now=NOW)


def test_cancellation_blocks_profit_even_before_future_deadline() -> None:
    notice = _notice("0848300054826000154", "Поставка бумаги")
    result = compare_indexed_notices(
        (notice,),
        "бумага",
        now=NOW,
        procedure_states={notice.purchase_number: EisProcedureState("FAIL", ("XML отмены: abc",))},
        costs_by_exact_notice={
            (notice.purchase_number, notice.xml_sha256): DiscoveryCostInput(
                goods="80000",
                expenses="10000",
                vat_rate="0.20",
                basis="КП",
                costs_complete_ack=True,
            )
        },
    )
    lead = result.matched_notices[0]
    assert lead.application_status == "FAIL"
    assert lead.economics_status == "BLOCKED" and lead.conservative_profit_rub is None
    assert "XML отмены: abc" in lead.reasons


def test_partial_match_does_not_receive_profit_estimate() -> None:
    masks = _notice("0348200077726000176", "Поставка медицинских масок")
    chatbot = _notice("0348200081026005942", "Медицинский чат-бот")
    costs = DiscoveryCostInput(
        goods="80000",
        expenses="10000",
        vat_rate="0.20",
        basis="КП",
        costs_complete_ack=True,
    )
    result = compare_indexed_notices(
        (chatbot, masks),
        "медицинские маски",
        now=NOW,
        costs_by_exact_notice={(chatbot.purchase_number, chatbot.xml_sha256): costs},
    )
    assert [item.match_quality for item in result.matched_notices] == ["STRONG", "PARTIAL"]
    assert result.matched_notices[1].economics_status == "UNKNOWN"
    assert result.matched_notices[1].conservative_profit_rub is None


def test_item_name_can_match_when_notice_title_is_generic() -> None:
    generic = _notice("0348300232026000312", "Закупка расходных материалов")
    item = EisLotItem(
        name="Перчатки смотровые из латекса",
        ktru_code=None,
        okpd2_code=None,
        quantity=None,
        unit="Пара",
        unit_price_rub=None,
        line_sum_rub=None,
        foreign_goods_prohibited=None,
        locator="epNotificationEF2020/notificationInfo/purchaseObjectsInfo/notDrugPurchaseObjectsInfo/purchaseObject[1]",
    )
    result = compare_indexed_notices(
        (replace(generic, lot_items=(item,)),), "латексные перчатки", now=NOW
    )
    assert len(result.matched_notices) == 1
    assert result.matched_notices[0].match_quality == "STRONG"
    assert result.matched_notices[0].match_locator.endswith("purchaseObject[1]/name")


def test_short_modifiers_are_not_silently_dropped_from_strong_match():
    notice = _notice("9000000000000000001", "Бумага А3 70")
    result = compare_indexed_notices((notice,), "бумага А4 80", now=NOW)
    assert result.matched_notices[0].match_quality == "PARTIAL"
    assert result.matched_notices[0].matched_terms == ("бумага",)
    from procurement.sources.eis_index_search import search_query_keys_v1

    assert search_query_keys_v1("бумага А4 80") == search_query_keys_v1("бумага")
    assert search_keys_v1("бумага А4 80") == search_keys_v1("бумага")
    with pytest.raises(ValueError, match="QUERY_INVALID"):
        compare_indexed_notices((), "А4 80", now=NOW)


def test_short_format_in_title_is_found_with_explicit_evidence():
    notice = _notice("9000000000000000001", "Бумага A4 80")
    result = compare_indexed_notices((notice,), "бумага А4 80", now=NOW)
    lead = result.matched_notices[0]
    assert lead.match_quality == "STRONG" and lead.matched_terms == ("бумага", "а4", "80")
    assert {item.term for item in lead.term_evidence} == set(lead.matched_terms)
    assert all(item.locator.endswith("purchaseObjectInfo") for item in lead.term_evidence)
    assert lead.application_status == lead.economics_status == "UNKNOWN"


def _paper_item(format_value: str, *, minimum: Decimal | None = None) -> EisLotItem:
    value = EisCharacteristicValue(
        format_value,
        minimum,
        "greaterOrEqual" if minimum else None,
        Decimal("100") if minimum else None,
        None,
        None,
        "item[1]/characteristic[1]/value[1]",
    )
    return EisLotItem(
        "Бумага",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "item[1]",
        (EisCharacteristic("Формат", "KTRU", None, (value,), "item[1]/characteristic[1]"),),
    )


def test_characteristics_are_scoped_to_one_item_and_ranges_remain_unknown():
    notice = replace(
        _notice("9000000000000000001", "Канцтовары"),
        lot_items=(_paper_item("A4", minimum=Decimal("80")),),
    )
    lead = compare_indexed_notices((notice,), "бумага А4 80", now=NOW).matched_notices[0]
    assert lead.match_quality == "STRONG"
    assert [part.value_kind for part in lead.term_evidence] == ["ITEM_NAME", "TEXT", "MINIMUM"]
    assert lead.term_evidence[-1].locator.endswith("value[1]")
    assert any("границе характеристики" in reason for reason in lead.reasons)
    assert lead.application_status == lead.economics_status == "UNKNOWN"
    # Matching words in characteristics alone cannot escape the v1 indexed anchors.
    assert compare_indexed_notices((notice,), "формат А4", now=NOW).matched_notices == ()


def test_words_from_different_items_never_form_a_complete_match():
    first = _paper_item("A3", minimum=Decimal("80"))
    second = replace(_paper_item("A4"), locator="item[2]")
    notice = replace(_notice("9000000000000000001", "Канцтовары"), lot_items=(first, second))
    lead = compare_indexed_notices((notice,), "бумага А4 80", now=NOW).matched_notices[0]
    assert lead.match_quality == "PARTIAL"
    assert lead.matched_terms == ("бумага", "80")
