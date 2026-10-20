"""Synthetic public-page fixtures: browser access is covered by a live smoke check."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from procurement.sources.eis_public import (
    EisPublicError,
    EisPublicSearchResult,
    _public_browser_proxy,
    completed_contracts_url,
    parse_completed_contracts,
    parse_customer_profile,
    parse_public_detail,
    parse_public_documents,
    parse_public_search,
    public_search_url,
    read_public_html,
    search_public_eis,
)


def test_public_proxy_rejects_credentials_without_exposing_them(monkeypatch) -> None:
    monkeypatch.setenv("EIS_BROWSER_PROXY", "socks5://user:secret@proxy:1080")
    with pytest.raises(EisPublicError) as caught:
        _public_browser_proxy()
    assert str(caught.value) == "PROXY_CONFIG_INVALID"
    monkeypatch.setenv("EIS_BROWSER_PROXY", "socks5://eis-proxy:1080")
    assert _public_browser_proxy() == {"server": "socks5://eis-proxy:1080"}


def test_customer_profile_requires_explicit_unique_inn_and_official_url() -> None:
    url = "https://zakupki.gov.ru/epz/organization/view/info.html?organizationCode=01234567890"
    content = """<div><span class="section__title">ИНН</span>
      <span class="section__info">7708410783</span></div>""".encode()
    result = parse_customer_profile(content, url, datetime(2026, 9, 25, tzinfo=UTC))
    assert result.inn == "7708410783"
    assert result.source_sha256 and result.inn_locator
    with pytest.raises(EisPublicError, match="CUSTOMER_INN_UNVERIFIED"):
        parse_customer_profile(content.replace(b"7708410783", b"unknown"), url, datetime.now(UTC))
    with pytest.raises(EisPublicError, match="CUSTOMER_URL_INVALID"):
        parse_customer_profile(
            content, url.replace("zakupki.gov.ru", "evil.test"), datetime.now(UTC)
        )


def test_completed_customer_contracts_require_matching_customer_and_price_label() -> None:
    profile_url = (
        "https://zakupki.gov.ru/epz/organization/view/info.html?organizationCode=01234567890"
    )
    profile_html = (
        '<div><span class="section__title">ИНН</span>'
        '<span class="section__info">7708410783</span></div>'
        '<a href="/epz/contract/search/results.html?fz44=on&amp;contractStageList=0'
        '&amp;customerIdOrg=-1:ГБУzZz7708410783">Контракты</a>'
    ).encode()
    profile = parse_customer_profile(profile_html, profile_url, datetime(2026, 9, 25, tzinfo=UTC))
    assert profile.contracts_url and profile.contracts_locator
    search_url = completed_contracts_url(profile.contracts_url, "7708410783")
    assert "contractStageList=1" in search_url
    with pytest.raises(EisPublicError, match="CONTRACT_SEARCH_URL_INVALID"):
        completed_contracts_url(profile.contracts_url, "1111111111")

    contract_html = """<div class="search-registry-entry-block">
      <div class="registry-entry__header-mid__number">
        <a href="/epz/contract/contractCard/common-info.html?reestrNumber=0123456789012345678">
          № 0123456789012345678</a></div>
      <div class="registry-entry__header-mid__title">Исполнение завершено</div>
      <div class="registry-entry__body-href">ГБУ</div>
      <div class="lots-wrap-content__body--item">
        <div class="lots-wrap-content__body__title">Объекты закупки</div>
        <div class="lots-wrap-content__body__val">Бумага А4</div>
      </div>
      <div class="price-block"><div class="price-block__title">Цена контракта</div>
        <div class="price-block__value">120 000,00 ₽</div></div>
      <div class="data-block"><div class="data-block__title">Заключение контракта</div>
        <div class="data-block__value">01.08.2026</div></div>
    </div>""".encode()
    result = parse_completed_contracts(
        contract_html, search_url, "7708410783", "ГБУ", datetime(2026, 9, 25, tzinfo=UTC)
    )
    assert result.scanned_count == 1 and result.skipped_count == 0
    assert result.coverage == "FIRST_PAGE_ONLY" and result.source_sha256
    contract = result.contracts[0]
    assert contract.price_rub == Decimal("120000.00")
    assert contract.signed_on.isoformat() == "2026-08-01"
    assert contract.subject == "Бумага А4"
    assert contract.source_sha256 == result.source_sha256

    wrong_customer = parse_completed_contracts(
        contract_html, search_url, "7708410783", "Другое ГБУ", datetime.now(UTC)
    )
    assert wrong_customer.contracts == () and wrong_customer.skipped_count == 1
    active = parse_completed_contracts(
        contract_html.replace("Исполнение завершено".encode(), "Исполнение".encode()),
        search_url,
        "7708410783",
        "ГБУ",
        datetime.now(UTC),
    )
    assert active.contracts == () and active.skipped_count == 1
    other_price = parse_completed_contracts(
        contract_html.replace("Цена контракта".encode(), "Максимальное значение".encode()),
        search_url,
        "7708410783",
        "ГБУ",
        datetime.now(UTC),
    )
    assert other_price.contracts[0].price_rub is None


def test_product_filtered_contracts_verify_visible_match_and_notice_link() -> None:
    base = (
        "https://zakupki.gov.ru/epz/contract/search/results.html"
        "?fz44=on&contractStageList=0&customerIdOrg=-1:ГБУzZz7708410783"
    )
    url = completed_contracts_url(base, "7708410783", "хочу бумагу перепродавать")
    assert "searchString=" in url
    html = """<input name="searchString" value="бумагу">
      <input name="contractStageList" value="1">
      <input name="customerIdOrg" value="-1:ГБУzZz7708410783">
      <div class="search-registry-entry-block">
        <div class="registry-entry__header-mid__number">
          <a href="/epz/contract/contractCard/common-info.html?reestrNumber=0123456789012345678">
            № 0123456789012345678</a></div>
        <div class="registry-entry__header-mid__title">Исполнение завершено</div>
        <div class="registry-entry__body-href">ГБУ</div>
        <div class="lots-wrap-content__body--item">
          <div class="lots-wrap-content__body__title">Объекты закупки</div>
          <div class="lots-wrap-content__body__val">Поставка бумаги А4</div>
        </div>
        <a href="/epz/order/notice/view/common-info.html?regNumber=1111111111111111111">
          Сведения закупки</a>
      </div>""".encode()
    result = parse_completed_contracts(
        html, url, "7708410783", "ГБУ", datetime.now(UTC), "хочу бумагу перепродавать"
    )
    assert result.product_query == "бумагу"
    contract = result.contracts[0]
    assert contract.relevance_status == "MATCHED_VISIBLE"
    assert contract.matched_terms == ("бумагу",)
    assert contract.notice_number == "1111111111111111111"
    assert contract.notice_url and contract.notice_locator

    hidden_match = parse_completed_contracts(
        html.replace("Поставка бумаги А4".encode(), "Перчатки хирургические".encode()),
        url,
        "7708410783",
        "ГБУ",
        datetime.now(UTC),
        "бумагу",
    )
    assert hidden_match.contracts[0].relevance_status == "UNKNOWN"
    assert hidden_match.contracts[0].matched_terms == ()
    with pytest.raises(EisPublicError, match="CONTRACT_FILTER_UNVERIFIED"):
        parse_completed_contracts(
            html.replace('value="бумагу"'.encode(), b'value="other"'),
            url,
            "7708410783",
            "ГБУ",
            datetime.now(UTC),
            "бумагу",
        )

    empty = parse_completed_contracts(
        html.split(b'<div class="search-registry-entry-block">')[0]
        + '<p class="noRecords">Поиск не дал результатов</p>'.encode(),
        url,
        "7708410783",
        "ГБУ",
        datetime.now(UTC),
        "бумагу",
    )
    assert empty.status == "COMPLETED"
    assert empty.reason == "NO_RESULTS_FIRST_PAGE"
    assert empty.contracts == ()


def _html(*, stage: str = "Подача заявок", link: str | None = None) -> bytes:
    detail = link or "/epz/order/notice/ea20/view/common-info.html?regNumber=0123456789012345678"
    return f"""<html><body><div class="search-registry-entry-block">
      <div class="registry-entry__header-top__title">Электронный аукцион 44-ФЗ</div>
      <div class="registry-entry__header-mid__title">{stage}</div>
      <div class="registry-entry__header-mid__number"><a href="{detail}">
      № 0123456789012345678</a></div>
      <div class="registry-entry__body-value">Поставка бумаги А4</div>
      <div class="registry-entry__body-href">Заказчик</div>
      <div class="price-block__value">182 420,00 ₽</div>
      <div><div class="data-block__title">Окончание подачи заявок</div>
      <div class="data-block__value">05.10.2026</div></div>
      <div class="href-block"><a
        href="/epz/order/notice/ea20/view/documents.html?regNumber=0123456789012345678"
      >Документы</a></div>
    </div></body></html>""".encode()


def test_public_search_parses_card_without_profit_or_open_status_claim() -> None:
    query = "бумагу"
    result = parse_public_search(
        _html(), query, public_search_url(query), datetime(2026, 9, 25, tzinfo=UTC)
    )
    assert result.status == "COMPLETED"
    assert result.coverage == "FIRST_PAGE_ONLY"
    assert result.scanned_count == 1
    lead = result.leads[0]
    assert lead.nmck_rub == Decimal("182420.00")
    assert lead.deadline_date.isoformat() == "2026-10-05"
    assert lead.application_status == "UNKNOWN"
    assert lead.economic_status == "UNKNOWN"
    assert lead.matched_terms == ("бумагу",)
    assert lead.documents_url and lead.documents_url.startswith("https://zakupki.gov.ru/")
    assert lead.source_sha256 == result.source_sha256


def test_public_search_bounds_pages_and_reports_single_page_coverage() -> None:
    query = "бумагу"
    url = public_search_url(query, page_number=2)
    result = parse_public_search(
        _html() + b'<a href="?pageNumber=3">3</a>',
        query,
        url,
        datetime(2026, 9, 25, tzinfo=UTC),
    )
    assert result.page_number == 2
    assert result.coverage == "SINGLE_PAGE"
    assert result.has_more_pages is True
    with pytest.raises(EisPublicError, match="PAGE_NUMBER_INVALID"):
        public_search_url(query, page_number=21)


@pytest.mark.parametrize("page_size", [50, 100])
def test_public_search_reads_supported_size_and_rejects_page_size_drift(page_size) -> None:
    query = "бумага"
    template = _html().decode().removeprefix("<html><body>").removesuffix("</body></html>")
    cards = [
        template.replace("0123456789012345678", f"{index:019d}")
        for index in range(1, page_size + 2)
    ]
    content = ("<html><body>" + "".join(cards[:page_size]) + "</body></html>").encode()
    url = public_search_url(query, page_size=page_size)
    assert f"recordsPerPage=_{page_size}" in url
    result = parse_public_search(content, query, url, datetime.now(UTC))
    assert result.scanned_count == len(result.leads) == page_size
    assert result.unique_scanned_count == page_size
    assert result.leads[-1].source_locator == f"search-result-card[{page_size}]"
    page_twenty = parse_public_search(
        content.replace(b"<body>", "<body>Результаты поиска более 15 000 записей".encode(), 1),
        query,
        public_search_url(query, page_number=20, page_size=page_size),
        datetime.now(UTC),
    )
    assert page_twenty.has_more_pages is True
    with pytest.raises(EisPublicError, match="SEARCH_PAGE_SIZE_CHANGED"):
        parse_public_search(
            ("<html><body>" + "".join(cards) + "</body></html>").encode(),
            query,
            url,
            datetime.now(UTC),
        )
    with pytest.raises(EisPublicError, match="SEARCH_PAGE_SIZE_MISMATCH"):
        parse_public_search(content, query, url.replace(f"_{page_size}", "_200"), datetime.now(UTC))
    with pytest.raises(EisPublicError, match="PAGE_SIZE_INVALID"):
        public_search_url(query, page_size=200)


def test_missing_title_on_one_card_keeps_other_results_and_exposes_source_cap() -> None:
    query = "бумага"
    template = _html().decode().removeprefix("<html><body>").removesuffix("</body></html>")
    without_title = template.replace(
        '<div class="registry-entry__body-value">Поставка бумаги А4</div>', ""
    ).replace("0123456789012345678", "0000000000000000002")
    assert without_title != template
    content = (
        "<html><body>Результаты поиска более 15 000 записей"
        + template
        + without_title
        + '<a href="?pageNumber=20">20</a></body></html>'
    ).encode()
    result = parse_public_search(content, query, public_search_url(query), datetime.now(UTC))
    assert result.status == "COMPLETED"
    assert result.scanned_count == 2 and result.unparsed_count == 1
    assert len(result.leads) == 1
    assert result.source_result_count_floor == 15000
    assert result.source_result_count_exact is False
    assert result.query_exceeds_page_limit is True
    assert result.purchase_numbers == ("0123456789012345678", "0000000000000000002")
    assert result.unique_scanned_count == 2
    assert result.unidentified_count == 0


def test_raw_identifiers_include_nonmatching_titles_and_duplicates() -> None:
    card = _html().decode().removeprefix("<html><body>").removesuffix("</body></html>")
    content = ("<html><body>" + card * 2 + "</body></html>").encode()
    result = parse_public_search(
        content, "серверы", public_search_url("серверы"), datetime.now(UTC)
    )
    assert result.leads == ()
    assert result.purchase_numbers == ("0123456789012345678",) * 2
    assert result.scanned_count == 2
    assert result.unique_scanned_count == 1


def test_invalid_raw_identifier_leaves_unique_unknown() -> None:
    card = _html().decode().removeprefix("<html><body>").removesuffix("</body></html>")
    content = (
        "<html><body>" + card + card.replace("0123456789012345678", "123") + "</body></html>"
    ).encode()
    result = parse_public_search(content, "бумага", public_search_url("бумага"), datetime.now(UTC))
    assert result.scanned_count == 2 and result.unidentified_count == 1
    assert result.unique_scanned_count is None
    assert result.purchase_numbers == ("0123456789012345678",)


def test_public_search_requires_all_meaningful_category_terms() -> None:
    content = _html().replace("Поставка бумаги А4".encode(), "Медицинское оборудование".encode())
    result = parse_public_search(
        content,
        "хочу серверное оборудование перепродавать",
        public_search_url("хочу серверное оборудование перепродавать"),
        datetime(2026, 9, 25, tzinfo=UTC),
    )
    assert result.leads == ()

    server_content = _html().replace("Поставка бумаги А4".encode(), "Поставка серверов".encode())
    server_result = parse_public_search(
        server_content,
        "серверное оборудование",
        public_search_url("серверное оборудование"),
        datetime(2026, 9, 25, tzinfo=UTC),
    )
    assert len(server_result.leads) == 1
    assert server_result.leads[0].matched_terms == ("серверное",)


def test_public_search_does_not_treat_malformed_cards_as_completed_empty() -> None:
    content = b'<div class="search-registry-entry-block"><div>broken</div></div>'
    with pytest.raises(EisPublicError, match="SEARCH_MARKUP_CHANGED"):
        parse_public_search(
            content,
            "сервер",
            public_search_url("сервер"),
            datetime(2026, 9, 25, tzinfo=UTC),
        )


def test_public_search_accepts_11_digit_223_number() -> None:
    content = (
        _html()
        .replace(b"0123456789012345678", b"12345678901")
        .replace("Электронный аукцион 44-ФЗ".encode(), "Закупка 223-ФЗ".encode())
    )
    result = parse_public_search(
        content,
        "бумагу",
        public_search_url("бумагу"),
        datetime(2026, 9, 25, tzinfo=UTC),
    )
    assert result.leads[0].purchase_number == "12345678901"
    assert result.leads[0].law == "223-fz"


def test_public_search_expired_card_is_fail() -> None:
    result = parse_public_search(
        _html(stage="Работа комиссии"),
        "бумагу",
        public_search_url("бумагу"),
        datetime(2026, 10, 6, tzinfo=UTC),
    )
    assert result.leads[0].application_status == "FAIL"


def test_public_search_rejects_external_detail_and_block_page() -> None:
    with pytest.raises(EisPublicError, match="SEARCH_MARKUP_CHANGED"):
        parse_public_search(
            _html(link="https://evil.test/procurement"),
            "бумагу",
            public_search_url("бумагу"),
            datetime(2026, 9, 25, tzinfo=UTC),
        )
    with pytest.raises(EisPublicError, match="BLOCKED_PAGE"):
        parse_public_search(
            "Подтвердите, что вы не робот".encode(),
            "бумагу",
            public_search_url("бумагу"),
            datetime(2026, 9, 25, tzinfo=UTC),
        )
    with pytest.raises(EisPublicError, match="SEARCH_MARKUP_CHANGED"):
        parse_public_search(
            b"<html><body>Unexpected layout</body></html>",
            "бумагу",
            public_search_url("бумагу"),
            datetime(2026, 9, 25, tzinfo=UTC),
        )


def test_public_documents_keeps_unsupported_official_files_visible() -> None:
    url = (
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/documents.html"
        "?regNumber=0123456789012345678"
    )
    content = b"""<html><div class="blockFilesTabDocs">
      <div class="attachment"><a title="spec.docx"
        href="/44fz/filestore/public/1.0/download/priz/file.html?uid=abc">file</a></div>
      <div class="attachment"><a title="private.pdf"
        href="https://evil.test/private.pdf">file</a></div>
      <div class="attachment"><a title="macro.xlsm"
        href="/44fz/filestore/public/1.0/download/priz/file.html?uid=def">file</a></div>
    </div></html>"""
    result = parse_public_documents(content, url, datetime(2026, 9, 25, tzinfo=UTC))
    assert result.status == "COMPLETED"
    assert len(result.documents) == 2
    assert result.documents[0].filename == "spec.docx"
    assert result.documents[0].supported is True
    assert result.documents[0].source_locator == "attachment[1]"
    assert result.documents[1].filename == "macro.xlsm"
    assert result.documents[1].supported is False
    assert result.missing_formats == ("xlsm",)
    assert result.source_sha256


def test_public_detail_keeps_labeled_evidence_and_only_explicit_timezone() -> None:
    url = (
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
        "?regNumber=0123456789012345678"
    )
    content = """<html><body>
      <div><div class="section__title">Номер извещения</div>
      <div class="section__info">0123456789012345678</div></div>
      <div><div class="section__title">Окончание подачи заявок</div>
      <div class="section__info">05.10.2026 09:30 МСК</div></div>
      <div><div class="section__title">Место поставки товара</div>
      <div class="section__info">г. Москва</div></div>
      <div><div class="section__title">Количество товара</div>
      <div class="section__info">12 штук</div></div>
    </body></html>""".encode()
    result = parse_public_detail(content, url, datetime(2026, 9, 25, tzinfo=UTC))
    assert result.status == "COMPLETED"
    assert result.source_purchase_number == "0123456789012345678"
    assert result.exact_deadline is not None
    assert result.exact_deadline.isoformat() == "2026-10-05T09:30:00+03:00"
    assert {field.name for field in result.fields} >= {"deadline", "delivery_location", "quantity"}
    assert all(field.evidence_snippet for field in result.fields)

    no_zone = content.replace(" 09:30 МСК".encode(), b"")
    assert (
        parse_public_detail(no_zone, url, datetime(2026, 9, 25, tzinfo=UTC)).exact_deadline is None
    )


def test_public_detail_customer_is_exact_official_header_link() -> None:
    url = (
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
        "?regNumber=0123456789012345678"
    )
    content = """<html><body>
      <div class="cardMainInfo__section"><span class="cardMainInfo__title">Заказчик</span>
      <span class="cardMainInfo__content">
        <a href="/epz/organization/view/info.html?organizationCode=01234567890">ГБУ Пример</a>
      </span></div>
      <div class="section__title">Номер извещения</div>
      <div class="section__info">0123456789012345678</div>
    </body></html>""".encode()
    detail = parse_public_detail(content, url, datetime(2026, 9, 25, tzinfo=UTC))
    assert detail.customer is not None
    assert detail.customer.organization_code == "01234567890"
    assert detail.customer.name == "ГБУ Пример"
    assert detail.customer.source_sha256 == detail.source_sha256
    assert detail.customer.source_locator.startswith("customer-header[")

    forged = content.replace(
        b"/epz/organization/view/info.html", b"https://evil.test/epz/organization/view/info.html"
    )
    assert parse_public_detail(forged, url, datetime(2026, 9, 25, tzinfo=UTC)).customer is None
    ambiguous = content.replace(
        b"</body>",
        (
            '<div class="cardMainInfo__section">'
            '<span class="cardMainInfo__title">Заказчик</span>'
            '<span class="cardMainInfo__content">'
            '<a href="/epz/organization/view/info.html?organizationCode=99999999999">'
            "Другое ГБУ</a></span></div></body>"
        ).encode(),
    )
    assert parse_public_detail(ambiguous, url, datetime(2026, 9, 25, tzinfo=UTC)).customer is None


@pytest.mark.parametrize(
    ("zone", "expected"),
    [
        ("(МСК)", "2026-10-05T09:30:00+03:00"),
        ("(UTC+3)", "2026-10-05T09:30:00+03:00"),
        ("UTC+03:00", "2026-10-05T09:30:00+03:00"),
        ("+0400", "2026-10-05T09:30:00+04:00"),
    ],
)
def test_public_detail_parses_complete_explicit_timezone(zone: str, expected: str) -> None:
    url = (
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
        "?regNumber=0123456789012345678"
    )
    content = f"""<div><div class="label">Номер извещения</div>
      <div class="value">0123456789012345678</div></div>
      <div><div class="label">Окончание подачи заявок</div>
      <div class="value">05.10.2026 09:30 {zone}</div></div>""".encode()
    result = parse_public_detail(content, url, datetime(2026, 9, 25, tzinfo=UTC))
    assert result.exact_deadline is not None
    assert result.exact_deadline.isoformat() == expected


def test_public_detail_conflicting_deadlines_are_unknown_and_stage_is_evidence() -> None:
    url = (
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
        "?regNumber=0123456789012345678"
    )
    content = """<div><div class="label">Номер извещения</div>
      <div class="value">0123456789012345678</div></div>
      <div><div class="label">Окончание подачи заявок</div>
      <div class="value">05.10.2026 09:30 (МСК)</div></div>
      <div><div class="label">Окончание подачи предложений</div>
      <div class="value">06.10.2026 09:30 (МСК)</div></div>
      <div><div class="label">Этап закупки</div>
      <div class="value">Закупка отменена</div></div>
      <div><div class="label">Номер обеспечения исполнения</div>
      <div class="value">99999999999</div></div>""".encode()
    result = parse_public_detail(content, url, datetime(2026, 9, 25, tzinfo=UTC))
    assert result.exact_deadline is None
    assert any(field.name == "stage" and "отменена" in field.value for field in result.fields)
    assert all(field.label != "Номер обеспечения исполнения" for field in result.fields)


def test_public_detail_accepts_matching_date_summary_and_exact_deadline() -> None:
    url = (
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
        "?regNumber=0123456789012345678"
    )
    template = """<div><div class="label">Номер извещения</div>
      <div class="value">0123456789012345678</div></div>
      <div><div class="label">Окончание подачи заявок</div>
      <div class="value">{summary}</div></div>
      <div><div class="label">Дата и время окончания срока подачи заявок</div>
      <div class="value">02.10.2026 07:00 (МСК)</div></div>"""
    result = parse_public_detail(
        template.format(summary="02.10.2026").encode(),
        url,
        datetime(2026, 9, 25, tzinfo=UTC),
    )
    assert result.exact_deadline is not None
    assert result.exact_deadline.isoformat() == "2026-10-02T07:00:00+03:00"

    conflict = parse_public_detail(
        template.format(summary="03.10.2026").encode(),
        url,
        datetime(2026, 9, 25, tzinfo=UTC),
    )
    assert conflict.exact_deadline is None


def test_public_documents_rejects_unofficial_page() -> None:
    with pytest.raises(EisPublicError, match="DOCUMENTS_URL_INVALID"):
        parse_public_documents(
            b"<html></html>",
            "https://evil.test/epz/order/notice/ea20/view/documents.html"
            "?regNumber=0123456789012345678",
            datetime(2026, 9, 25, tzinfo=UTC),
        )


def test_public_reader_enforces_shared_cooldown(monkeypatch, tmp_path) -> None:
    from procurement.sources import eis_public

    monkeypatch.setenv("EIS_BROWSER_STATE_DIR", str(tmp_path))
    calls = []

    async def fake_browser(url: str, query: str, raw_observer=None) -> EisPublicSearchResult:
        calls.append(url)
        return EisPublicSearchResult(
            query=query,
            search_url=url,
            status="COMPLETED",
            observed_at=datetime(2026, 9, 25, tzinfo=UTC),
            scanned_count=0,
        )

    monkeypatch.setattr(eis_public, "_browser_search", fake_browser)
    assert search_public_eis("бумага").status == "COMPLETED"
    second = search_public_eis("сервер")
    assert second.status == "COOLDOWN"
    assert second.retry_at is not None
    assert len(calls) == 1


def test_public_html_returns_exact_bytes_to_observer(monkeypatch, tmp_path) -> None:
    from procurement.sources import eis_public

    url = (
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html"
        "?regNumber=0123456789012345678"
    )
    content = b"<html><body>bounded source</body></html>"
    observed: list[bytes] = []
    monkeypatch.setenv("EIS_BROWSER_STATE_DIR", str(tmp_path))

    async def fake_browser_html(requested: str) -> bytes:
        assert requested == url
        return content

    monkeypatch.setattr(eis_public, "_browser_html", fake_browser_html)
    assert read_public_html(url, observed.append) == content
    assert observed == [content]
