"""Недоверенное состояние страницы не расширяет утверждённый маршрут."""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from procurement.sources import browser_catalog as browser
from procurement.sources import yandex_business as source
from procurement.sources.catalog_routes import category_page_url, yandex_route
from procurement.sources.yandex_pagination import PaginationError, category_continuation


def state(page=1, more=True):
    return {
        "id": "synthetic",
        "entity": "visibleSearchResult",
        "hids": [138608],
        "page": page,
        "pageCount": 30 if more else page,
        "itemsPerPage": 8,
        "hasNextPage": more,
        "currentPageIds": [str(page)],
        "searchResultIds": {str(page): "synthetic-result"},
    }


def patch(value):
    return (
        '<noframes data-apiary="patch">'
        + json.dumps({"collections": {"visibleSearchResult": {"synthetic": value}}})
        + "</noframes>"
    ).encode()


def catalog(page=1, more=True):
    product = {
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "item": {
                    "@type": "Product",
                    "name": f"МФУ HP {page}",
                    "url": f"https://market.yandex.ru/card/synthetic/{page}",
                },
            }
        ],
    }
    return (
        '<script type="application/ld+json">' + json.dumps(product) + "</script>"
    ).encode() + patch(state(page, more))


def test_state_continuation_without_anchor_reads_second_page(monkeypatch):
    calls = []
    route = yandex_route("МФУ HP")
    assert route

    def fetch(url):
        calls.append(url)
        return catalog(len(calls))

    monkeypatch.setattr(source, "_fetch_category_page", fetch)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    result = source.search_yandex_business_category("МФУ HP")
    assert calls == [category_page_url(route, 1), category_page_url(route, 2)]
    assert len(result.candidates) == 2
    assert result.stop_reason == "PAGE_LIMIT"
    assert result.pages[0].continuation_evidence == "PAGE_STATE"


def test_state_continuation_is_bound_to_the_page():
    route = yandex_route("МФУ")
    assert route
    found = category_continuation(patch(state()), route, 1)
    assert found.status == "NEXT_PAGE"
    assert found.evidence == "PAGE_STATE"
    assert "visibleSearchResult" in found.locator
    assert category_continuation(patch(state(more=False)), route, 1).status == "END_REPORTED"


def test_empty_initial_collection_then_populated_patch():
    route = yandex_route("МФУ")
    assert route
    empty = b'<noframes data-apiary="patch">{"collections":{"visibleSearchResult":{}}}</noframes>'
    assert category_continuation(empty + patch(state()), route, 1).status == "NEXT_PAGE"
    assert category_continuation(empty, route, 1).status == "UNKNOWN"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("hids", [91013]),
        ("hids", [138608, 91013]),
        ("hids", ["138608"]),
        ("page", 2),
        ("page", True),
        ("page", "1"),
        ("pageCount", 0),
        ("pageCount", True),
        ("pageCount", 100001),
        ("hasNextPage", "true"),
        ("hasNextPage", False),
        ("hasNextPage", 1),
        ("itemsPerPage", 0),
        ("itemsPerPage", 101),
        ("itemsPerPage", True),
        ("currentPageIds", ["1", "2"]),
        ("searchResultIds", {"2": "wrong"}),
        ("entity", "other"),
        ("id", "other"),
    ],
)
def test_wrong_or_ambiguous_state_is_not_a_next_page(key, value):
    route = yandex_route("МФУ")
    assert route
    with pytest.raises(PaginationError, match=r"^PAGINATION_STATE_INVALID$"):
        category_continuation(patch({**state(), key: value}), route, 1)


@pytest.mark.parametrize(
    "content",
    [
        patch(state()) + patch(state()),
        patch(state()).replace(b'"page": 1', b'"page": 1, "page": 2'),
        b'<noframes data-apiary="patch">{"visibleSearchResult": invalid}</noframes>',
        patch(state()).replace(b"</noframes>", b""),
        patch(state(more=False)) + b'<a href="?page=2">next</a>',
    ],
)
def test_conflicts_duplicates_and_broken_json_fail_closed(content):
    route = yandex_route("МФУ")
    assert route
    with pytest.raises(PaginationError):
        category_continuation(content, route, 1)


def test_unrelated_text_and_javascript_are_not_instructions():
    route = yandex_route("МФУ")
    assert route
    for content in [
        b"hasNextPage:true",
        b"<script>" + patch(state()) + b"</script>",
        b'<noframes data-apiary="patch">{"collections": {}}</noframes>',
    ]:
        assert category_continuation(content, route, 1).status == "UNKNOWN"


def test_page_two_wrong_number_does_not_accept_stale_cards(monkeypatch):
    calls = []

    def fetch(url):
        calls.append(url)
        return catalog() if len(calls) == 1 else catalog(2).replace(b'"page": 2', b'"page": 1')

    monkeypatch.setattr(source, "_fetch_category_page", fetch)
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    result = source.search_yandex_business_category("МФУ HP")
    assert result.fetch_status == "PARTIAL"
    assert len(result.candidates) == 1
    assert result.pages[1].error_code == "PAGINATION_STATE_INVALID"


@pytest.mark.parametrize("stale", [False, True])
def test_chromium_state_pagination_and_stale_second_page(stale):
    playwright = pytest.importorskip("playwright.async_api")
    route = yandex_route("МФУ HP")
    assert route

    async def run():
        async with playwright.async_playwright() as runtime:
            try:
                engine = await runtime.chromium.launch()
            except playwright.Error:
                pytest.skip("Chromium is not installed")
            try:
                context = await engine.new_context()
                calls = []

                async def respond(interception):
                    calls.append(interception.request.url)
                    content = catalog(1) if len(calls) == 1 else catalog(2, more=False)
                    if stale and len(calls) == 2:
                        content = content.replace(b'"page": 2', b'"page": 1')
                    await interception.fulfill(status=200, content_type="text/html", body=content)

                await context.route("**/*", respond)
                page = await context.new_page()
                base = browser.BrowserAttempt(
                    company_id="synthetic",
                    site=browser.BrowserSite.YANDEX_BUSINESS,
                    query="МФУ HP",
                    source_url=category_page_url(route, 1),
                    status=browser.BrowserStatus.SOURCE_ERROR,
                    observed_at=datetime.now(UTC),
                    query_mode="TITLE_TERMS",
                )
                result = await browser._run_pages(
                    page, base, browser.BrowserOptions(natural_motion=False)
                )
                assert calls == [category_page_url(route, 1), category_page_url(route, 2)]
                assert result.status == ("PARTIAL" if stale else "COMPLETED")
                assert result.pages[0].continuation_evidence == "PAGE_STATE"
                if stale:
                    assert len(result.candidates) == 1
                    assert result.pages[1].error_code == "PAGINATION_STATE_INVALID"
                else:
                    assert len(result.candidates) == 2
                    assert result.stop_reason == "END_REPORTED"
                    assert result.candidates[1].source_page_number == 2
                    assert result.candidates[1].source_sha256 == result.pages[1].sha256
            finally:
                await engine.close()

    asyncio.run(run())
