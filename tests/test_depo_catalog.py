"""Найденная модель DEPO не подтверждает комплектацию или допуск."""

import hashlib

import httpx
import pytest

from procurement.sources import depo_catalog as source

URL = source.DEPO_SERVERS_URL + "depo-storm-1000/server-depo-storm-1430b1r/"


def card(title="Сервер DEPO Storm 1430B1R", url=URL):
    return (
        '<div class="block-servers__item">'
        '<a href="https://other.invalid/ad/">Реклама</a>'
        f'<div class="block-servers__name"><a href="{url}"><span>{title}</span></a></div>'
        '<div class="block-servers__description">Описание</div>'
        "</div>"
    )


def html(contents=None):
    return ('<div class="block-servers__list">' + (contents or card()) + "</div>").encode()


def test_only_named_cards_inside_main_list_are_parsed():
    content = card(url="https://other.invalid/advert/").encode() + html() + card(
        url="https://other.invalid/footer/"
    ).encode()
    rows = source.parse_depo_catalog(content)
    assert len(rows) == 1
    assert rows[0].url == URL and rows[0].source_item_index == 1
    assert rows[0].suitability == "UNKNOWN"


@pytest.mark.parametrize(
    "url",
    [
        "https://other.invalid/catalog/servery/depo-storm-1000/server-depo-storm-1430b1r/",
        URL.replace("https:", "http:"),
        URL + "?foo=1",
        URL + "#tab",
        source.DEPO_SERVERS_URL + "../foreign/product/",
        source.DEPO_SERVERS_URL + "depo-storm-1000/%2e%2e/",
        URL.replace("www.depo.ru", "user:password@www.depo.ru"),
        URL.replace("www.depo.ru", "www.depo.ru:443"),
    ],
)
def test_unexpected_product_url_rejected(url):
    with pytest.raises(ValueError):
        source.parse_depo_catalog(html(card(url=url)))


@pytest.mark.parametrize(
    "content",
    [
        b"<html>captcha</html>",
        b'<div class="block-servers__list"></div>',
        html(card() + card()),
        html(card().replace("block-servers__name", "changed-name")),
        html()[:-6],
        b"x" * (2 * 1024 * 1024 + 1),
    ],
    ids=["challenge", "empty", "duplicate", "missing-name", "unclosed", "oversized"],
)
def test_changed_or_ambiguous_catalog_is_source_error(content):
    with pytest.raises(ValueError):
        source.parse_depo_catalog(content)


@pytest.mark.parametrize("query", ["Ноутбук DEPO", "Сервер HPE", "Сервер Гравитон"])
def test_uncovered_query_does_not_open_connection(monkeypatch, query):
    monkeypatch.setattr(source, "public_source_client", lambda: pytest.fail("unplanned request"))
    assert source.search_depo_catalog(query).fetch_status == "QUERY_NOT_COVERED"


def test_search_preserves_hash_and_zero_matches(monkeypatch):
    content = html()
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=content, headers={"content-type": "text/html"})

    monkeypatch.setattr(
        source,
        "public_source_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), trust_env=False),
    )
    found = source.search_depo_catalog("Сервер DEPO Storm 1430B1R")
    assert found.fetch_status == "COMPLETED" and len(found.candidates) == 1
    assert found.response_sha256 == hashlib.sha256(content).hexdigest()
    assert found.scanned_count == 1
    missing = source.search_depo_catalog("Сервер DEPO Storm 9999")
    assert missing.fetch_status == "COMPLETED" and missing.candidates == ()
    assert calls == [source.DEPO_SERVERS_URL] * 2


@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_source_refusal_is_unknown_not_no_products(monkeypatch, status):
    monkeypatch.setattr(
        source,
        "public_source_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, content=html())),
            trust_env=False,
        ),
    )
    result = source.search_depo_catalog("Сервер DEPO")
    assert result.fetch_status == "SOURCE_ERROR"
    assert result.scanned_count is None and not result.candidates
