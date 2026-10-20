"""Ограниченный разбор публичного JSON-LD, без извлечения обещаний о BOM."""

import hashlib
import json
from datetime import UTC, datetime

import pytest

from procurement.sources.servermall import (
    SERVERMALL_HPE_GEN12_URL,
    ServerMallSourceError,
    parse_servermall_hpe_gen12,
)

OBSERVED = datetime(2026, 9, 20, tzinfo=UTC)


def page(*offers: dict[str, str]) -> bytes:
    graph = {"@graph": [{"@type": "OfferCatalog", "itemListElement": list(offers)}]}
    return (
        '<html><script type="application/ld+json">' + json.dumps(graph) + "</script></html>"
    ).encode()


def offer(name: str, url: str) -> dict[str, str]:
    return {"@type": "Offer", "name": name, "url": url, "price": "100000"}


def test_discovery_uses_catalog_digest_but_not_base_price_as_quote() -> None:
    html = page(
        offer("HPE DL360 Gen12 8SFF", "https://servermall.ru/catalog/servers/dl360/"),
        offer("HPE DL380 Gen12", "https://servermall.ru/catalog/servers/dl380/"),
    )
    leads = parse_servermall_hpe_gen12(html, query="DL360 Gen12", observed_at=OBSERVED)
    assert len(leads) == 1
    assert leads[0].source_url == SERVERMALL_HPE_GEN12_URL
    assert leads[0].source_sha256 == hashlib.sha256(html).hexdigest()
    assert leads[0].product_url == "https://servermall.ru/catalog/servers/dl360/"
    assert leads[0].price_rub is None
    assert leads[0].bom is None


def test_no_match_is_not_fabricated() -> None:
    html = page(offer("HPE DL380 Gen12", "https://servermall.ru/catalog/servers/dl380/"))
    assert parse_servermall_hpe_gen12(html, query="DL360 Gen12", observed_at=OBSERVED) == ()


def test_model_prefix_is_not_an_exact_title_term() -> None:
    html = page(offer("HPE DL360 Gen12", "https://servermall.ru/catalog/servers/dl360/"))
    assert parse_servermall_hpe_gen12(html, query="HPE DL36", observed_at=OBSERVED) == ()


@pytest.mark.parametrize(
    "url",
    [
        "http://servermall.ru/catalog/servers/dl360/",
        "https://other.example/catalog/servers/dl360/",
        "https://servermall.ru/catalog/servers/dl360/?secret=1",
        "https://servermall.ru/sets/servery-hp-proliant-gen12/",
    ],
)
def test_external_or_unexpected_product_link_fails_closed(url: str) -> None:
    html = page(offer("HPE DL360 Gen12", url))
    with pytest.raises(ServerMallSourceError):
        parse_servermall_hpe_gen12(html, query="DL360", observed_at=OBSERVED)


def test_changed_or_oversized_source_fails_closed() -> None:
    with pytest.raises(ServerMallSourceError):
        parse_servermall_hpe_gen12(b"<html></html>", query="DL360", observed_at=OBSERVED)
    with pytest.raises(ServerMallSourceError):
        parse_servermall_hpe_gen12(
            b"x" * (2 * 1024 * 1024 + 1), query="DL360", observed_at=OBSERVED
        )


def test_duplicate_product_link_fails_closed() -> None:
    item = offer("HPE DL360 Gen12", "https://servermall.ru/catalog/servers/dl360/")
    with pytest.raises(ServerMallSourceError):
        parse_servermall_hpe_gen12(page(item, item), query="DL360", observed_at=OBSERVED)
