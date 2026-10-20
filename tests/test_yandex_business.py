"""Category preview cannot be mistaken for site-wide product search."""

from __future__ import annotations

import json

from procurement.sources.yandex_business import (
    YANDEX_BUSINESS_PUMPS_URL,
    YandexBusinessStatus,
    parse_yandex_business_category,
    search_yandex_business_category,
    yandex_business_category_for_query,
)


def _html(url: str = "https://market.yandex.ru/card/test-product/123") -> bytes:
    item = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "item": {"@type": "Product", "name": "Насос тестовый", "url": url},
            }
        ],
    }
    return (
        '<html><script type="application/ld+json">'
        + json.dumps(item, ensure_ascii=False)
        + "</script></html>"
    ).encode()


def test_category_parser_keeps_exact_source_url_and_unknown_suitability() -> None:
    count, candidates = parse_yandex_business_category(_html())
    assert count == 1
    assert candidates[0].url == "https://market.yandex.ru/card/test-product/123"
    assert candidates[0].suitability == "UNKNOWN"


def test_category_parser_rejects_foreign_product_url() -> None:
    from pytest import raises

    with raises(ValueError):
        parse_yandex_business_category(_html("https://example.com/card/product/123"))


def test_unmapped_query_does_not_fetch_category() -> None:
    assert yandex_business_category_for_query("Насос центробежный") == (
        YANDEX_BUSINESS_PUMPS_URL + "?hid=15774673"
    )
    result = search_yandex_business_category("Сервер HPE")
    assert result.fetch_status is YandexBusinessStatus.QUERY_NOT_COVERED
    assert result.category_url is None
    assert result.candidates == ()
