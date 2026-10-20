import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from procurement.sources import supplier_catalog as c

ROOT = "https://bumaga-s.ru/"
FORM = b'<form action="/categories/search"><input type="text" id="global_search" name="q"></form>'


def anchor(path: str, title: str = "Бумага офисная") -> str:
    return f'<a href="{path}">{title}</a>'


def test_form_builds_exact_public_query_and_provenance() -> None:
    spec = c.build_catalog_search(ROOT, FORM, "Бумага для офисной техники")
    assert spec is not None
    assert parse_qs(urlsplit(spec.search_url).query) == {"q": ["Бумага для офисной техники"]}
    assert spec.raw_action == "/categories/search" and spec.field == "q"
    assert spec.html_sha256 == hashlib.sha256(FORM).hexdigest()
    assert spec.locator == 'locator("form").nth(0)'


@pytest.mark.parametrize(
    "content",
    [
        FORM.replace(b"<form ", b'<form method="post" '),
        FORM.replace(b'name="q"', b'name="private"'),
        FORM.replace(b"/categories/search", b"https://evil.ru/categories/search"),
        FORM + FORM,
        b'<base href="https://evil.ru/">' + FORM,
        b"<div hidden>" + FORM + b"</div>",
    ],
)
def test_unsupported_forms_not_invented(content: bytes) -> None:
    assert c.build_catalog_search(ROOT, content, "Бумага") is None


def test_unknown_or_private_query_controls_rejected() -> None:
    with pytest.raises(ValueError):
        c.build_catalog_search(ROOT, FORM, "Бумага\nsecret")


def test_labeled_links_dedup_stable_dom_ordinals() -> None:
    content = (
        anchor("/товар/a", "")
        + anchor("/товар/a")
        + anchor("/товар/a")
        + anchor("/товар/b", "Товар B")
    ).encode()
    result = c.parse_catalog_links(ROOT, content)
    assert result.status == "FOUND" and result.returned_count == 2 and result.scanned_count == 4
    assert [link.dom_ordinal for link in result.links] == [2, 4]
    assert [link.index for link in result.links] == [1, 2]
    assert result.links[0].raw_href == "/товар/a"
    assert result.links[0].locator == 'locator("a").nth(1)'
    assert result.links[0].technical_status == result.links[0].price_status == "UNKNOWN"
    assert result.coverage == "UNKNOWN"


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.ru/товар/a",
        "http://bumaga-s.ru/товар/a",
        "/categories/a",
        "javascript:alert(1)",
        "/товар/../secret",
        "https://user:pass@bumaga-s.ru/товар/a",
        "https://127.0.0.1/товар/a",
    ],
)
def test_unsafe_or_nonproduct_links_ignored(href: str) -> None:
    assert c.parse_catalog_links(ROOT, anchor(href).encode()).status == "EMPTY"


def test_hidden_script_and_base_links_not_candidates() -> None:
    content = (
        "<div hidden>" + anchor("/товар/a") + "</div><script>" + anchor("/товар/b") + "</script>"
    )
    assert c.parse_catalog_links(ROOT, content.encode()).status == "EMPTY"
    assert (
        c.parse_catalog_links(ROOT, b'<base href="/">' + anchor("/товар/a").encode()).status
        == "UNSUPPORTED"
    )


def test_bounded_links_depth_encoding_and_body() -> None:
    content = "".join(anchor(f"/товар/{i}") for i in range(11)).encode()
    result = c.parse_catalog_links(ROOT, content)
    assert result.status == "FOUND" and len(result.links) == 10 and result.truncated
    assert [link.index for link in result.links] == list(range(1, 11))
    assert c.parse_catalog_links(ROOT, b"<div>" * 129).status == "LIMIT_EXCEEDED"
    assert c.parse_catalog_links(ROOT, b"\xff").status == "UNSUPPORTED"
    assert c.parse_catalog_links(ROOT, b"x" * (c.MAX_BODY_BYTES + 1)).status == "LIMIT_EXCEEDED"


def microdata(price: str = "299.6", currency: str = "RUB") -> bytes:
    return (
        f'<span itemscope itemtype="http://schema.org/Product">'
        f'<meta itemprop="name" content="Бумага SvetoCopy Eco">'
        f'<span itemprop="offers" itemscope itemtype="http://schema.org/Offer">'
        f'<meta itemprop="price" content="{price}">'
        f'<meta itemprop="priceCurrency" content="{currency}">'
        f"</span></span>"
    ).encode()


def enrich(content: bytes) -> c.PageCapture:
    from datetime import UTC, datetime

    from procurement.sources.supplier_page import PageCapture, parse_supplier_page

    observation = parse_supplier_page(
        ROOT + "товар/paper", content, observed_at=datetime(2026, 10, 6, tzinfo=UTC)
    )
    return c.enrich_catalog_product(PageCapture(observation, content))


def test_microdata_exact_price_retains_html_and_unknown_commercial_facts() -> None:
    from decimal import Decimal

    content = microdata()
    capture = enrich(content)
    product = capture.observation.products[0]
    assert product.name.value == "Бумага SvetoCopy Eco"
    assert product.prices[0].amount == Decimal("299.6") and product.prices[0].currency == "RUB"
    assert product.prices[0].raw_amount == "299.6" and product.prices[0].price_kind == "EXACT"
    assert product.prices[0].html_sha256 == hashlib.sha256(content).hexdigest()
    assert product.brand is product.manufacturer is product.sku is product.seller is None
    assert (
        capture.observation.quote_status == capture.observation.configured_cost_status == "UNKNOWN"
    )
    assert capture.content == content


@pytest.mark.parametrize(
    "content",
    [
        microdata() + microdata(),
        microdata().replace(b'itemprop="offers"', b'itemprop="unrelated"'),
        microdata("NaN"),
        microdata("0"),
        microdata(currency=""),
        microdata().replace(
            b'<meta itemprop="price"', b'<meta itemprop="price" content="1"><meta itemprop="price"'
        ),
        microdata().replace(b'itemprop="priceCurrency"', b'itemprop="unrelated"'),
    ],
)
def test_microdata_ambiguous_missing_and_forged_scopes_do_not_yield_price(content: bytes) -> None:
    result = enrich(content).observation
    assert result.extraction_status == "AMBIGUOUS" and not result.products


def test_microdata_never_overwrites_jsonld_conflict() -> None:
    content = (
        microdata() + b'<script type="application/ld+json">{"@type":"Product","name":"Other",'
        b'"offers":{"@type":"Offer","price":"900","priceCurrency":"USD"}}</script>'
    )
    from decimal import Decimal

    result = enrich(content).observation
    assert result.products[0].name.value == "Other"
    assert result.products[0].prices[0].amount == Decimal("900")


@pytest.mark.parametrize(
    "wrapper",
    [
        "<template>",
        "<noscript>",
        "<div hidden>",
        "<div inert>",
        '<div aria-hidden="true">',
        '<div style="display: none">',
        '<div style="DISPLAY:\n none !important">',
        '<div style="visibility:hidden">',
    ],
)
def test_microdata_hidden_or_inert_ancestors_never_extract(wrapper: str) -> None:
    tag = wrapper.split()[0].lstrip("<").rstrip(">")
    content = wrapper.encode() + microdata() + f"</{tag}>".encode()
    result = enrich(content).observation
    assert result.extraction_status == "AMBIGUOUS" and not result.products


def test_hidden_competing_product_does_not_silently_admit_active_product() -> None:
    result = enrich(microdata() + b"<template>" + microdata("1") + b"</template>").observation
    assert result.extraction_status == "AMBIGUOUS" and not result.products


def test_hidden_offer_metadata_is_not_eligible_but_normal_meta_stays_supported() -> None:
    hidden = microdata().replace(b'<span itemprop="offers"', b'<span hidden itemprop="offers"')
    assert enrich(hidden).observation.extraction_status == "AMBIGUOUS"
    assert enrich(microdata()).observation.extraction_status == "EXTRACTED"
