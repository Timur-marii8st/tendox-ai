"""Маршрут запроса, конкретные страницы и частичная выдача, без живой сети."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest

from procurement.sources import browser_catalog as browser
from procurement.sources import yandex_business as source
from procurement.sources.catalog_routes import (
    category_page_url,
    has_next_category_page,
    servermall_covers,
    title_matches_query,
    yandex_route,
)


def html(rows, next_url=None):
    graph = {
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "item": {
                    "@type": "Product",
                    "name": name,
                    "url": f"https://market.yandex.ru/card/test/{key}",
                },
            }
            for name, key in rows
        ],
    }
    return (
        '<html><body><script type="application/ld+json">'
        + json.dumps(graph)
        + "</script>"
        + (f'<a href="{next_url}">Далее</a>' if next_url else "")
        + "</body></html>"
    ).encode()


@pytest.mark.parametrize(
    ("query", "category"),
    [
        ("Насос центробежный", "pumps"),
        ("Ноутбуки Lenovo", "laptops"),
        ("Принтер лазерный", "printers"),
        ("МФУ Canon", "printers"),
        ("Ноутбук и насос", None),
        ("Бумага A4", None),
        ("HPE DL360", None),
    ],
)
def test_unambiguous_routing(query, category):
    route = yandex_route(query)
    assert (route.key if route else None) == category
    assert not servermall_covers("Насос центробежный")
    assert not servermall_covers("Сервер Dell")
    assert not servermall_covers("Сервер DEPO")
    assert servermall_covers("HPE DL360 Gen12")


def test_title_matching_is_all_terms_not_substring_or_suitability():
    assert title_matches_query("Ноутбук Lenovo V15", "Ноутбуки Lenovo")
    assert not title_matches_query("Ноутбук Lenovo", "Ноутбук HP")
    assert not title_matches_query("Насос дренажный", "Насос центробежный")
    assert not title_matches_query("Принтер X1234", "Принтер X123")


def test_first_page_includes_category_id_required_by_live_catalog():
    route = yandex_route("Ноутбук Lenovo")
    assert route
    assert category_page_url(route, 1) == f"{route.url}?hid=91013"
    assert source.yandex_business_category_for_query("Ноутбук Lenovo") == category_page_url(
        route, 1
    )


def test_http_pages_filter_after_scanning_all_rows_and_deduplicate(monkeypatch):
    route = yandex_route("Ноутбук Lenovo")
    assert route
    first = html(
        [*(("Ноутбук HP", i) for i in range(11)), ("Ноутбук Lenovo", 50)],
        category_page_url(route, 2),
    )
    second = html([("Ноутбук Lenovo", 50), ("Ноутбук Lenovo V15", 51)])
    calls = []

    def fetch(url):
        calls.append(url)
        return first if len(calls) == 1 else second

    monkeypatch.setattr(source, "_fetch_category_page", fetch)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    result = source.search_yandex_business_category("Ноутбук Lenovo")
    assert result.fetch_status == source.YandexBusinessStatus.COMPLETED
    assert calls == [category_page_url(route, 1), category_page_url(route, 2)]
    assert result.scanned_count == 14
    assert len(result.candidates) == 2
    assert [r.source_page_number for r in result.candidates] == [1, 2]
    assert result.candidates[1].source_sha256 == hashlib.sha256(second).hexdigest()
    assert result.stop_reason == "NO_NEXT_EVIDENCE"
    assert all(r.suitability == "UNKNOWN" for r in result.candidates)


@pytest.mark.parametrize("failure", ["timeout", "repeat", "invalid"])
def test_second_page_failure_keeps_first_page(monkeypatch, failure):
    route = yandex_route("Насос")
    assert route
    first = html([("Насос тестовый", 1)], category_page_url(route, 2))

    def fetch(url):
        if url == category_page_url(route, 1) or failure == "repeat":
            return first
        if failure == "timeout":
            raise httpx.ReadTimeout("private request details")
        return b"<html>challenge</html>"

    monkeypatch.setattr(source, "_fetch_category_page", fetch)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    result = source.search_yandex_business_category("Насос")
    assert result.fetch_status == source.YandexBusinessStatus.PARTIAL
    assert len(result.candidates) == 1
    assert [p.status for p in result.pages] == ["COMPLETED", "SOURCE_ERROR"]
    assert "private request details" not in result.model_dump_json()


def test_no_next_link_does_not_guess_or_follow_foreign_page(monkeypatch):
    content = html([("Принтер HP", 1)], "https://evil.example/?page=2")
    calls = []
    monkeypatch.setattr(source, "_fetch_category_page", lambda url: calls.append(url) or content)
    result = source.search_yandex_business_category("Принтер Canon")
    assert result.fetch_status == source.YandexBusinessStatus.COMPLETED
    assert result.candidates == ()
    assert len(calls) == 1
    assert result.stop_reason == "NO_NEXT_EVIDENCE"


def test_budget_never_fetches_third_page(monkeypatch):
    route = yandex_route("Насос")
    assert route
    calls = []

    def fetch(url):
        calls.append(url)
        number = len(calls)
        return html([("Насос", number)], f"{route.url}?hid={route.hid}&page={number + 1}")

    monkeypatch.setattr(source, "_fetch_category_page", fetch)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    result = source.search_yandex_business_category("Насос")
    assert len(calls) == 2
    assert result.stop_reason == "PAGE_LIMIT"


def test_next_link_requires_same_category_and_consistent_parameters():
    route = yandex_route("Насос")
    assert route
    assert has_next_category_page(html([], "?page=2"), route, 1)
    assert not has_next_category_page(html([], "?hid=999&page=2"), route, 1)
    assert not has_next_category_page(html([], "?page=2&page=3"), route, 1)
    assert not has_next_category_page(html([], "?page=2&text=other"), route, 1)


@pytest.mark.parametrize("failure", ["timeout", "blocked", "repeat"])
def test_browser_partial_keeps_page_evidence(monkeypatch, failure):
    route = yandex_route("Ноутбук Lenovo")
    assert route
    base = browser.BrowserAttempt(
        company_id="a",
        site=browser.BrowserSite.YANDEX_BUSINESS,
        query="Ноутбук Lenovo",
        source_url=category_page_url(route, 1),
        status=browser.BrowserStatus.SOURCE_ERROR,
        observed_at=datetime.now(UTC),
        query_mode="TITLE_TERMS",
    )
    calls = []

    async def run_page(page, attempt, options):
        calls.append(attempt.source_url)
        if len(calls) == 2 and failure == "timeout":
            raise TimeoutError
        if len(calls) == 2 and failure == "blocked":
            return attempt.model_copy(update={"status": browser.BrowserStatus.BLOCKED})
        return attempt.model_copy(
            update={
                "status": browser.BrowserStatus.COMPLETED,
                "catalog_fingerprint": "a" * 64,
                "dom_sha256": "b" * 64,
                "has_next_page": True,
                "candidates": (
                    browser.BrowserCandidate(
                        title="Ноутбук Lenovo",
                        url="https://market.yandex.ru/card/test/1",
                        locator="row 1",
                        source_page_url=category_page_url(route, 1),
                        source_page_number=1,
                        source_sha256="b" * 64,
                    ),
                ),
            }
        )

    monkeypatch.setattr(browser, "_run_page", run_page)
    result = asyncio.run(
        browser._run_pages(None, base, browser.BrowserOptions(natural_motion=False))
    )
    assert result.status == browser.BrowserStatus.PARTIAL
    assert len(result.candidates) == 1
    assert [p.status for p in result.pages] == ["COMPLETED", "SOURCE_ERROR"]
    assert result.candidates[0].source_page_url == category_page_url(route, 1)


def test_irrelevant_servermall_request_does_not_fetch(monkeypatch):
    from procurement.sources import direct_catalog

    monkeypatch.setattr(
        direct_catalog,
        "fetch_servermall_hpe_gen12",
        lambda _: pytest.fail("must not fetch server catalog for pump"),
    )
    result = direct_catalog.search_direct_catalog("Насос")
    assert result.fetch_status == direct_catalog.DirectCatalogStatus.QUERY_NOT_COVERED


def test_real_browser_follows_approved_next_page_when_first_has_no_matches():
    playwright = pytest.importorskip("playwright.async_api")
    route = yandex_route("Ноутбук Lenovo")
    assert route
    first = html([("Ноутбук HP", 1)], category_page_url(route, 2))
    second = html([("Ноутбук Lenovo V15", 2)])

    async def run():
        async with playwright.async_playwright() as runtime:
            try:
                engine = await runtime.chromium.launch()
            except playwright.Error:
                pytest.skip("Chromium is not installed")
            try:
                context = await engine.new_context()
                requested = []

                async def respond(interception):
                    requested.append(interception.request.url)
                    await interception.fulfill(
                        status=200,
                        content_type="text/html",
                        body=(
                            first
                            if interception.request.url == category_page_url(route, 1)
                            else second
                        ),
                    )

                await context.route("**/*", respond)
                page = await context.new_page()
                base = browser.BrowserAttempt(
                    company_id="a",
                    site=browser.BrowserSite.YANDEX_BUSINESS,
                    query="Ноутбук Lenovo",
                    source_url=category_page_url(route, 1),
                    status=browser.BrowserStatus.SOURCE_ERROR,
                    observed_at=datetime.now(UTC),
                    query_mode="TITLE_TERMS",
                )
                result = await browser._run_pages(
                    page, base, browser.BrowserOptions(natural_motion=False)
                )
                assert result.status == browser.BrowserStatus.COMPLETED
                assert requested == [category_page_url(route, 1), category_page_url(route, 2)]
                assert [p.matched_count for p in result.pages] == [0, 1]
                assert result.candidates[0].source_page_number == 2
                assert result.candidates[0].source_sha256 == result.pages[1].sha256
            finally:
                await engine.close()

    asyncio.run(run())
