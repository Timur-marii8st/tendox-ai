"""Карточки производителя не являются допуском, КП или реестровой записью."""

import hashlib

import httpx
import pytest

from procurement.sources import graviton_catalog as source

URL = source.GRAVITON_SERVERS_URL + "synthetic-server/"


def card(title="Сервер Гравитон Тест", url=URL):
    return f'<a class="catalog-item" href="{url}"><p class="catalog-item__title">{title}</p></a>'


def html(contents=None):
    return ('<ul class="catalog__list"><li>' + (contents or card()) + "</li></ul>").encode()


def test_only_main_category_is_parsed():
    content = (
        card("Рекомендация", "https://other.invalid/").encode()
        + html()
        + card("Реклама", "https://other.invalid/").encode()
    )
    rows = source.parse_graviton_catalog(content)
    assert len(rows) == 1
    assert rows[0].url == URL
    assert rows[0].source_item_index == 1
    assert rows[0].suitability == "UNKNOWN"


@pytest.mark.parametrize(
    "url",
    [
        "https://other.invalid/server/",
        "http://graviton.ru/catalog/server/",
        source.GRAVITON_SERVERS_URL,
        URL + "?private=1",
        URL + "#fragment",
        source.GRAVITON_SERVERS_URL + "../foreign/",
        source.GRAVITON_SERVERS_URL + "%2e%2e/",
        URL.replace("graviton.ru", "user:password@graviton.ru"),
        URL.replace("graviton.ru", "graviton.ru:443"),
    ],
)
def test_unexpected_product_url_rejected(url):
    with pytest.raises(ValueError):
        source.parse_graviton_catalog(html(card(url=url)))


@pytest.mark.parametrize(
    "content",
    [
        b"<html>captcha</html>",
        b'<ul class="catalog__list"></ul>',
        html(card() + card()),
        html() + html(),
        html().replace(b"</ul>", b""),
        html().replace(b"catalog-item__title", b"unknown-title"),
        b"x" * (2 * 1024 * 1024 + 1),
    ],
    ids=[
        "challenge",
        "empty",
        "duplicate-card",
        "two-lists",
        "unclosed",
        "title-change",
        "oversized",
    ],
)
def test_changed_or_ambiguous_catalog_is_not_empty_success(content):
    with pytest.raises(ValueError):
        source.parse_graviton_catalog(content)


@pytest.mark.parametrize(
    "query",
    ["Насос", "Сервер HPE", "Сервер Dell", "Сервер DEPO", "Ноутбук Lenovo", "Сервер и ноутбук"],
)
def test_uncovered_query_does_not_open_connection(monkeypatch, query):
    monkeypatch.setattr(source, "public_source_client", lambda: pytest.fail("unplanned request"))
    assert source.search_graviton_catalog(query).fetch_status == "QUERY_NOT_COVERED"


@pytest.mark.parametrize(
    ("query", "route_key", "title", "slug"),
    [
        ("Ноутбук Гравитон Н15А-Б", "laptops", "Ноутбук «Гравитон» Н15А-Б", "graviton-n15a-b"),
        ("МФУ Гравитон ГМ2501", "printers", "МФУ «Гравитон» ГМ2501", "mfu-graviton-gm2501"),
        ("Компьютер Гравитон Д52И", "pcs", "ПК «Гравитон» Д52И", "pk-graviton-d52i"),
    ],
)
def test_each_public_category_has_exact_url_and_unknown_suitability(
    monkeypatch, query, route_key, title, slug
):
    route = next(r for r in source.GRAVITON_ROUTES if r.key == route_key)
    content = html(card(title=title, url=route.url + slug + "/"))
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=content, headers={"content-type": "text/html"})

    monkeypatch.setattr(
        source,
        "public_source_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), trust_env=False),
    )
    result = source.search_graviton_catalog(query)
    assert calls == [route.url]
    assert result.fetch_status == "COMPLETED"
    assert result.category_key == route_key and result.source_url == route.url
    assert result.candidates[0].title == title
    assert result.candidates[0].suitability == "UNKNOWN"
    with pytest.raises(ValueError):
        source.parse_graviton_catalog(html(card(title, URL)), route)


def test_live_contract_with_synthetic_http_preserves_hash_and_zero_matches(monkeypatch):
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
    found = source.search_graviton_catalog("Сервер Гравитон")
    assert found.fetch_status == "COMPLETED" and len(found.candidates) == 1
    assert found.response_sha256 == hashlib.sha256(content).hexdigest()
    assert found.scanned_count == 1
    missing = source.search_graviton_catalog("Сервер Гравитон Другой")
    assert missing.fetch_status == "COMPLETED" and missing.candidates == ()
    assert calls == [source.GRAVITON_SERVERS_URL] * 2


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
    result = source.search_graviton_catalog("Сервер Гравитон")
    assert result.fetch_status == "SOURCE_ERROR"
    assert result.scanned_count is None
    assert not result.candidates
