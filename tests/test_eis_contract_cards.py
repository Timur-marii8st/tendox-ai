"""Synthetic retained cards: no live fixtures and no network."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from procurement.sources.eis_contract_cards import (
    CONTRACT_PATH,
    DOCUMENTS_EA_PATH,
    DOCUMENTS_PATH,
    MAX_CARD_BYTES,
    NOTICE_EA_PATH,
    NOTICE_KINDS,
    NOTICE_PATH,
    NOTICE_SECTION,
    NOTICE_ZK_PATH,
    ORIGIN,
    VERSION_PATH,
    CardSnapshot,
    parse_contract_card,
    parse_notice_card,
    parse_notice_documents_card,
)

REGISTRY = "1000000000026000001"
NOTICE = "0100000000026000001"
NOW = datetime(2026, 10, 25, 10, tzinfo=UTC)
HEADERS = (("Content-Type", "text/html; charset=utf-8"), ("Date", "Sun, 25 Oct 2026 10:00:00 GMT"))


def field(title, value, title_class="section__title", value_class="section__info"):
    return (
        f'<section><span class="{title_class}">{title}</span>'
        f'<span class="{value_class}">{value}</span></section>'
    )


def summary(title, value):
    return field(title, value, "cardMainInfo__title", "cardMainInfo__content")


def identity(number, suffix=""):
    return (
        f'<span class="navBreadcrumb__text">№ {number}{suffix}</span>'
        f'<span class="cardMainInfo__purchaseLink">№ {number}</span>'
    )


def contract_html():
    return (
        identity(REGISTRY, " (Версия № 0 от 23.10.2026, действующая версия)")
        + '<span class="cardMainInfo__state">Исполнение</span>'
        + summary("Цена контракта", "9 007 199 254 740 993,01 ₽")
        + summary("Заключение контракта", "23.10.2026")
        + field("Реестровый номер контракта", REGISTRY)
        + field("Статус контракта", "Исполнение")
        + field(
            "Номер извещения об осуществлении закупки",
            f'<a href="{NOTICE_PATH}?regNumber={NOTICE}">{NOTICE}</a>',
        )
        + field("Цена контракта", "9 007 199 254 740 993,01")
        + field("Дата заключения контракта", "23.10.2026")
        + field("Валюта контракта", "РОССИЙСКИЙ РУБЛЬ (₽)")
    )


def notice_html():
    return (
        identity(NOTICE)
        + '<span class="cardMainInfo__state">Определение поставщика завершено</span>'
        + field("Этап закупки", "Определение поставщика завершено")
        + summary("Начальная цена", "270 000,00 ₽")
        + field("Начальная (максимальная) цена контракта", "270 000,00")
        + field("Валюта", "РОССИЙСКИЙ РУБЛЬ")
        + field(
            "Способ определения поставщика (подрядчика, исполнителя)",
            "Запрос котировок в электронной форме",
        )
    )


def document_row(version="1", revision="Действующая"):
    return (
        '<div class="notice-documents">'
        '<div class="section__value docName">Извещение о проведении запроса котировок '
        f"в электронной форме от 13.10.2026 №{NOTICE}</div>"
        + field("Редакция", revision, "section__attrib", "section__value")
        + f'<a href="{VERSION_PATH}?regNumber={NOTICE}&amp;versionNumber={version}'
        '&amp;qualifier=regNumberAndVersion">Печатная форма</a></div>'
    )


def documents_html(rows=None):
    return (
        identity(NOTICE)
        + '<span class="cardMainInfo__state">Определение поставщика завершено</span>'
        + summary("Начальная цена", "270 000,00 ₽")
        + '<div class="blockInfo">'
        + f'<h2 class="blockInfo__title">{NOTICE_SECTION}</h2>'
        + (document_row() if rows is None else rows)
        + "</div>"
    )


def snapshot(html=None, *, kind="contract"):
    path = {"contract": CONTRACT_PATH, "notice": NOTICE_ZK_PATH, "documents": DOCUMENTS_PATH}[kind]
    number = REGISTRY if kind == "contract" else NOTICE
    key = "reestrNumber" if kind == "contract" else "regNumber"
    url = f"{ORIGIN}{path}?{key}={number}"
    return CardSnapshot(
        url,
        url,
        200,
        NOW,
        NOW + timedelta(seconds=2),
        (contract_html() if html is None else html).encode(),
        HEADERS,
    )


def contract(html):
    return parse_contract_card(snapshot(html), REGISTRY)


def test_contract_facts_are_decimal_and_zero_version_not_incremented():
    result = parse_contract_card(snapshot(), REGISTRY)
    assert result.version.value == 0
    assert result.version_date.value == date(2026, 10, 23)
    assert result.price.value == Decimal("9007199254740993.01")
    assert result.signed_on.value == date(2026, 10, 23)
    assert result.status.value == "Исполнение"
    assert result.purchase_number.value == NOTICE
    assert result.currency.value == "RUB"
    assert result.receipt.history_completeness == "UNKNOWN"
    assert result.receipt.reasons == ()  # Absent Age alone is not stale evidence.
    assert result.price.source_sha256 == sha256(snapshot().content).hexdigest()
    assert "Цена контракта" in result.price.locator


def test_completed_status_is_retained_not_inferred_execution():
    assert contract(contract_html().replace("Исполнение", "Исполнение завершено")).status.value == (
        "Исполнение завершено"
    )


@pytest.mark.parametrize(
    "old,new",
    [
        ("действующая версия", "недействующая версия"),
        ("действующая версия", "архивная версия"),
        ("Версия № 0", "Версия № -1"),
        ("Версия № 0", "Версия № 1.0"),
        ("от 23.10.2026", "от 31.02.2026"),
        ("Исполнение", "Исполнение прекращено"),
        ("РОССИЙСКИЙ РУБЛЬ (₽)", "ДОЛЛАР США"),
    ],
)
def test_contract_rejects_unconfirmed_version_status_currency(old, new):
    with pytest.raises(ValueError):
        contract(contract_html().replace(old, new))


@pytest.mark.parametrize(
    "title,value",
    [
        ("Цена контракта", "9 007 199 254 740 993,01"),
        ("Статус контракта", "Исполнение"),
        ("Дата заключения контракта", "23.10.2026"),
        ("Реестровый номер контракта", REGISTRY),
        ("Валюта контракта", "РОССИЙСКИЙ РУБЛЬ (₽)"),
    ],
)
def test_duplicate_fields_even_equal_are_rejected(title, value):
    with pytest.raises(ValueError, match="DUPLICATE"):
        contract(contract_html() + field(title, value))


@pytest.mark.parametrize(
    "title,old,new",
    [
        ("Цена контракта", "9 007 199 254 740 993,01", "1,00"),
        ("Статус контракта", "Исполнение", "Исполнение завершено"),
        ("Дата заключения контракта", "23.10.2026", "24.10.2026"),
        ("Реестровый номер контракта", REGISTRY, "1000000000026000002"),
    ],
)
def test_summary_detail_contradictions_rejected(title, old, new):
    with pytest.raises(ValueError, match="CONTRADICT"):
        contract(contract_html().replace(field(title, old), field(title, new)))


@pytest.mark.parametrize(
    "amount",
    ["NaN", "Infinity", "1e3", "1.00", "-1,00", "0,00", "1 00,00", "1,001", "1,0", "1,00 ₽"],
)
def test_no_float_or_ambiguous_money(amount):
    with pytest.raises(ValueError):
        contract(contract_html().replace("9 007 199 254 740 993,01", amount))


@pytest.mark.parametrize("tag", ["script", "style", "template", "noscript"])
def test_nonvisible_fields_cannot_supply_missing_evidence(tag):
    price_field = field("Цена контракта", "9 007 199 254 740 993,01")
    html = contract_html().replace(price_field, f"<{tag}>{price_field}</{tag}>")
    with pytest.raises(ValueError):
        contract(html)
    assert contract(contract_html() + f"<{tag}>{contract_html()}</{tag}>").version.value == 0


@pytest.mark.parametrize(
    "attribute",
    ["hidden", 'aria-hidden="true"', 'style="display: none"', 'style="visibility:hidden"'],
)
def test_hidden_facts_are_not_current_evidence(attribute):
    html = contract_html().replace(
        'class="navBreadcrumb__text"', f'class="navBreadcrumb__text" {attribute}'
    )
    with pytest.raises(ValueError):
        contract(html)


def test_footer_or_tooltip_does_not_supply_current_version():
    header = identity(REGISTRY, " (Версия № 0 от 23.10.2026, действующая версия)")
    html = contract_html().replace(header, identity(REGISTRY))
    html += f"<footer>{header}</footer>"
    with pytest.raises(ValueError):
        contract(html)
    html = contract_html().replace("действующая версия)", "архивная версия)")
    html += '<div data-tooltip="действующая версия">footer version 99</div>'
    with pytest.raises(ValueError):
        contract(html)


@pytest.mark.parametrize(
    "challenge", ['<div id="captcha">123</div>', "<p>Подтвердите, что вы не робот</p>"]
)
def test_challenge_is_not_a_card_even_with_card_markup(challenge):
    with pytest.raises(ValueError, match="CHALLENGE"):
        contract(contract_html() + challenge)


@pytest.mark.parametrize(
    "change",
    [
        {"http_status": 302},
        {"http_status": 503},
        {"url": f"http://zakupki.gov.ru{CONTRACT_PATH}?reestrNumber={REGISTRY}"},
        {"url": f"https://evil.test{CONTRACT_PATH}?reestrNumber={REGISTRY}"},
        {"url": f"https://user@zakupki.gov.ru{CONTRACT_PATH}?reestrNumber={REGISTRY}"},
        {"url": f"https://zakupki.gov.ru:443{CONTRACT_PATH}?reestrNumber={REGISTRY}"},
        {"url": f"{ORIGIN}{CONTRACT_PATH}?reestrNumber={REGISTRY}&x=1"},
        {"url": f"{ORIGIN}{CONTRACT_PATH}?reestrNumber={REGISTRY}#fragment"},
        {"final_url": f"{ORIGIN}{CONTRACT_PATH}?reestrNumber=1000000000026000002"},
        {"redirect_chain": ("https://evil.test",)},
        {"requested_at": NOW.replace(tzinfo=None)},
        {"checked_at": NOW - timedelta(seconds=1)},
        {"content": b""},
        {"content": b"x" * (MAX_CARD_BYTES + 1)},
        {"content": b"\xff"},
        {"content": b"\0"},
    ],
)
def test_transport_identity_time_bounds_fail_closed(change):
    with pytest.raises(ValueError):
        parse_contract_card(replace(snapshot(), **change), REGISTRY)


def test_body_identity_and_notice_link_must_match():
    with pytest.raises(ValueError):
        parse_contract_card(snapshot(), "1000000000026000002")
    with pytest.raises(ValueError):
        contract(contract_html().replace(f"regNumber={NOTICE}", "regNumber=0100000000026000002"))


@pytest.mark.parametrize(
    "headers,reason",
    [
        ((), "CARD_CONTENT_TYPE_UNCONFIRMED"),
        ((HEADERS[0],), "CARD_RESPONSE_DATE_UNCONFIRMED"),
        ((HEADERS[0], ("Date", "nonsense")), "CARD_RESPONSE_DATE_UNCONFIRMED"),
        (
            (HEADERS[0], ("Date", "Sun, 25 Oct 2026 08:00:00 GMT")),
            "CARD_RESPONSE_DATE_OUTSIDE_CAPTURE",
        ),
        ((*HEADERS, ("Age", "1")), "CARD_CACHED_RESPONSE"),
        ((*HEADERS, ("Age", "-1")), "CARD_CACHE_AGE_UNCONFIRMED"),
        ((*HEADERS, ("Warning", '110 - "Response is stale"')), "CARD_CACHE_WARNING_PRESENT"),
    ],
)
def test_missing_or_stale_transport_remains_diagnostic(headers, reason):
    result = parse_contract_card(replace(snapshot(), headers=headers), REGISTRY)
    assert reason in result.receipt.reasons
    assert result.receipt.history_completeness == "UNKNOWN"


@pytest.mark.parametrize(
    "headers",
    [
        (*HEADERS, ("DATE", HEADERS[1][1])),
        (("Content-Type", "application/json"),),
        (*HEADERS, ("Age", "0\nAge: 1")),
    ],
)
def test_ambiguous_headers_are_rejected(headers):
    with pytest.raises(ValueError):
        parse_contract_card(replace(snapshot(), headers=headers), REGISTRY)


def test_receipt_binds_body_and_transport_but_does_not_retain_secrets():
    original = parse_contract_card(snapshot(), REGISTRY).receipt
    later = parse_contract_card(
        replace(snapshot(), checked_at=NOW + timedelta(seconds=3)), REGISTRY
    ).receipt
    altered = contract(contract_html() + " ").receipt
    assert original.content_sha256 == later.content_sha256
    assert original.observation_sha256 != later.observation_sha256
    assert original.content_sha256 != altered.content_sha256
    assert original.observation_sha256 != altered.observation_sha256
    receipt = parse_contract_card(
        replace(snapshot(), headers=(*HEADERS, ("Set-Cookie", "private"))), REGISTRY
    ).receipt
    assert "private" not in repr(receipt)


def test_depth_bound_prevents_recursive_failure():
    with pytest.raises(ValueError, match="COMPLEXITY"):
        contract("<div>" * 120 + contract_html() + "</div>" * 120)


def test_notice_common_info_never_invents_version_from_footer():
    result = parse_notice_card(
        snapshot(notice_html() + "<footer>Версия 99</footer>", kind="notice"), NOTICE
    )
    assert result.version is None
    assert result.reasons == ("NOTICE_COMMON_INFO_VERSION_UNCONFIRMED",)
    assert result.initial.value == Decimal("270000.00")


def test_only_observed_notice_redirect_with_complete_chain_accepted():
    final = snapshot(notice_html(), kind="notice")
    redirected = replace(
        final, url=final.url.replace(NOTICE_ZK_PATH, NOTICE_PATH), redirect_chain=(final.url,)
    )
    assert parse_notice_card(redirected, NOTICE).purchase_number.value == NOTICE
    with pytest.raises(ValueError, match="REDIRECT_CHAIN"):
        parse_notice_card(replace(redirected, redirect_chain=()), NOTICE)
    with pytest.raises(ValueError):
        parse_notice_card(replace(redirected, final_url=final.url.replace("zk20", "ef")), NOTICE)


def test_notice_documents_current_version_is_bound_to_notice_row_not_protocol():
    protocol = (
        '<div class="blockInfo"><h2 class="blockInfo__title">Протоколы работы комиссии</h2>'
        + document_row("99")
        + "</div>"
    )
    result = parse_notice_documents_card(
        snapshot(
            documents_html(document_row("0", "Недействующая") + document_row()) + protocol,
            kind="documents",
        ),
        NOTICE,
    )
    assert result.version.value == 1
    assert result.status.value == "Определение поставщика завершено"
    assert result.initial.value == Decimal("270000.00")
    assert result.currency.value == "RUB"
    assert result.initial.source_sha256 == result.version.source_sha256
    assert "versionNumber=1&" in result.version_url.value
    assert result.receipt.history_completeness == "UNKNOWN"


@pytest.mark.parametrize(
    "html",
    [
        documents_html(document_row("1") + document_row("2")),
        documents_html(document_row("1", "Недействующая")),
        documents_html().replace(NOTICE_SECTION, "Протоколы работы комиссии"),
        documents_html().replace("Извещение о проведении", "Протокол проведения"),
        documents_html().replace("versionNumber=1", "versionNumber=-1"),
        documents_html().replace("versionNumber=1", "versionNumber=1.0"),
        documents_html().replace("versionNumber=1", "versionNumber=1&versionNumber=2"),
        documents_html().replace(f"regNumber={NOTICE}", "regNumber=0100000000026000002"),
        documents_html().replace(VERSION_PATH, "https://evil.test" + VERSION_PATH),
        documents_html().replace("Действующая", "Неизвестная"),
        documents_html()
        .replace('class="docName"', 'class="elsewhere"')
        .replace('class="section__value docName"', 'class="elsewhere"'),
    ],
)
def test_notice_document_ambiguous_wrong_archived_versions_rejected(html):
    with pytest.raises(ValueError):
        parse_notice_documents_card(snapshot(html, kind="documents"), NOTICE)


@pytest.mark.parametrize("status", ["Определение поставщика отменено", "Закупка отменена", "", "?"])
def test_current_notice_version_does_not_override_cancelled_or_unknown_stage(status):
    html = documents_html().replace("Определение поставщика завершено", status)
    with pytest.raises(ValueError, match="NOTICE_STATUS_UNSUPPORTED"):
        parse_notice_documents_card(snapshot(html, kind="documents"), NOTICE)


@pytest.mark.parametrize(
    "old,new",
    [
        ('class="cardMainInfo__state"', 'class="unrelated"'),
        ("Начальная цена", "Неизвестная цена"),
        ("270 000,00 ₽", "270 000,00 USD"),
        ("270 000,00 ₽", "270000.00 ₽"),
    ],
)
def test_notice_documents_require_stage_and_rub_price_from_same_card(old, new):
    with pytest.raises(ValueError):
        parse_notice_documents_card(
            snapshot(documents_html().replace(old, new), kind="documents"), NOTICE
        )


@pytest.mark.parametrize(
    "extra",
    [
        '<span class="cardMainInfo__state">Определение поставщика завершено</span>',
        summary("Начальная цена", "270 000,00 ₽"),
        summary("Начальная цена", "1,00 ₽"),
        field("Этап закупки", "Закупка отменена"),
        field("Начальная (максимальная) цена контракта", "1,00"),
        field("Валюта", "ДОЛЛАР США"),
        field("Этап закупки", "Определение поставщика завершено") * 2,
    ],
)
def test_notice_documents_reject_duplicate_or_contradictory_stage_price_currency(extra):
    with pytest.raises(ValueError):
        parse_notice_documents_card(snapshot(documents_html() + extra, kind="documents"), NOTICE)


def test_notice_documents_can_confirm_same_values_in_optional_detail_fields():
    details = (
        field("Этап закупки", "Определение поставщика завершено")
        + field("Начальная (максимальная) цена контракта", "270 000,00")
        + field("Валюта", "РОССИЙСКИЙ РУБЛЬ")
    )
    result = parse_notice_documents_card(
        snapshot(documents_html() + details, kind="documents"), NOTICE
    )
    assert result.version.value == 1
    assert result.initial.value == Decimal("270000.00")


def ea_documents_html():
    return (
        documents_html()
        .replace(NOTICE_KINDS["zk20"][0], NOTICE_KINDS["ea20"][0])
        .replace(NOTICE_KINDS["zk20"][1], NOTICE_KINDS["ea20"][1])
    )


def ea_snapshot(html, *, documents=True):
    original = snapshot(html, kind="documents" if documents else "notice")
    url = original.url.replace(
        DOCUMENTS_PATH if documents else NOTICE_ZK_PATH,
        DOCUMENTS_EA_PATH if documents else NOTICE_EA_PATH,
    )
    return replace(original, url=url, final_url=url)


def test_observed_ea_documents_route_binds_current_auction_row():
    result = parse_notice_documents_card(ea_snapshot(ea_documents_html()), NOTICE)
    assert result.version.value == 1
    assert result.initial.value == Decimal("270000.00")
    assert result.currency.value == "RUB"
    assert result.status.value == "Определение поставщика завершено"


def test_ea_common_info_requires_same_auction_method():
    html = notice_html().replace(NOTICE_KINDS["zk20"][2], NOTICE_KINDS["ea20"][2])
    result = parse_notice_card(ea_snapshot(html, documents=False), NOTICE)
    assert result.initial.value == Decimal("270000.00")
    assert result.version is None
    with pytest.raises(ValueError, match="CONTRADICT"):
        parse_notice_card(ea_snapshot(notice_html(), documents=False), NOTICE)
    with pytest.raises(ValueError, match="CONTRADICT"):
        parse_notice_card(snapshot(html, kind="notice"), NOTICE)


@pytest.mark.parametrize(
    "html",
    [
        documents_html(),
        ea_documents_html().replace(NOTICE_KINDS["ea20"][1], NOTICE_KINDS["zk20"][1]),
        ea_documents_html().replace(NOTICE_KINDS["ea20"][0], NOTICE_KINDS["zk20"][0]),
    ],
)
def test_ea_route_rejects_wrong_procedure_section_or_current_row(html):
    with pytest.raises(ValueError):
        parse_notice_documents_card(ea_snapshot(html), NOTICE)


def test_zk_route_rejects_auction_and_unobserved_ok20_route():
    with pytest.raises(ValueError):
        parse_notice_documents_card(snapshot(ea_documents_html(), kind="documents"), NOTICE)
    original = ea_snapshot(ea_documents_html())
    wrong = original.url.replace("ea20", "ok20")
    with pytest.raises(ValueError, match="URL_MISMATCH"):
        parse_notice_documents_card(replace(original, url=wrong, final_url=wrong), NOTICE)


def test_no_unobserved_generic_to_ea_redirect_or_cross_kind_redirect():
    original = ea_snapshot(notice_html(), documents=False)
    for source_path in (NOTICE_PATH, NOTICE_ZK_PATH):
        with pytest.raises(ValueError, match="REDIRECT_UNSUPPORTED"):
            parse_notice_card(
                replace(
                    original,
                    url=original.url.replace(NOTICE_EA_PATH, source_path),
                    redirect_chain=(original.url,),
                ),
                NOTICE,
            )
