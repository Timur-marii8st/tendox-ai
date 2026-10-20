"""Supplier observations preserve exact published price bases without inventing quotes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from procurement.domain.sourcing import LeadSourceKind, ServerLead
from procurement.sources.eis_supplier_catalog import (
    MAX_CARD_TEXT,
    MAX_CARDS,
    MAX_HTML_BYTES,
    MAX_HTML_DEPTH,
    MAX_HTML_NODES,
    PublishedSupplierPrice,
    SupplierCatalogCapture,
    SupplierCatalogObservation,
    SupplierCatalogSourceError,
    build_servermall_supplier_observation,
    observe_servermall_hpe_gen12,
)
from procurement.sources.servermall import SERVERMALL_HPE_GEN12_URL, ServerMallObservation

OBSERVED = datetime(2026, 10, 7, 10, tzinfo=UTC)
PRODUCT = "https://servermall.ru/catalog/servers/dl360/"


def html(card_text: str, *, duplicate_anchor: bool = False, extra_product: bool = False) -> bytes:
    offer = {"@type": "Offer", "name": "HPE DL360 Gen12 8SFF", "url": PRODUCT}
    graph = {"@graph": [{"@type": "OfferCatalog", "itemListElement": [offer]}]}
    anchors = f'<a href="{PRODUCT}">HPE DL360 Gen12 8SFF</a>'
    if duplicate_anchor:
        anchors += anchors
    if extra_product:
        anchors += '<a href="https://servermall.ru/catalog/servers/dl380/">DL380</a>'
    price_title = ""
    price_body = card_text
    match = re.match(r"(Цена(?:\s+базы)?\s*:\s*от)\s*(.*)", card_text, re.I)
    if match:
        price_title = f'<div class="list-price-title">{match.group(1)}</div>'
        price_body = match.group(2)
    return (
        '<html><script type="application/ld+json">'
        + json.dumps(graph)
        + f'</script><article class="product-card">{anchors}'
        + price_title
        + f'<div class="product-card__price-VAT">{price_body}</div></article></html>'
    ).encode()


def source(content: bytes, *, url: str = SERVERMALL_HPE_GEN12_URL) -> ServerMallObservation:
    digest = hashlib.sha256(content).hexdigest()
    lead = ServerLead(
        lead_id=PRODUCT,
        supplier="ServerMall",
        manufacturer="HPE",
        source_kind=LeadSourceKind.SUPPLIER_CATALOG,
        product_name="HPE DL360 Gen12 8SFF",
        source_url=url,
        product_url=PRODUCT,
        source_sha256=digest,
        observed_at=OBSERVED,
    )
    return ServerMallObservation(
        source_url=url,
        content=content,
        sha256=digest,
        observed_at=OBSERVED,
        leads=(lead,),
    )


def test_base_from_and_monthly_lease_remain_distinct_published_observations():
    content = html("Цена базы: от 1 234 500 ₽ Аренда: 45 000 ₽ / мес")
    result = build_servermall_supplier_observation(source(content), "HPE DL360 Gen12")
    lead = result.leads[0]
    assert lead.price_status == "PUBLISHED"
    assert [(price.kind, price.amount_rub) for price in lead.published_prices] == [
        ("BASE_PRICE_FROM", Decimal("1234500")),
        ("LEASE_MONTHLY", Decimal("45000")),
    ]
    assert all(
        price.quote_status == price.tax_status == "UNKNOWN" for price in lead.published_prices
    )
    assert all(
        price.provenance.document_id == result.source_sha256 for price in lead.published_prices
    )
    assert lead.stock == lead.delivery == lead.compliance == lead.participation == "UNKNOWN"
    assert result.coverage == result.tax == result.participation == "UNKNOWN"


def test_generic_price_from_is_not_base_or_configured_unit_cost():
    result = build_servermall_supplier_observation(
        source(html("Цена: от 900 000 ₽")), "HPE DL360"
    )
    price = result.leads[0].published_prices[0]
    assert price.kind == "PRICE_FROM" and price.amount_rub == Decimal("900000")
    assert price.configured_unit_cost == "UNKNOWN" and price.quote_status == "UNKNOWN"


@pytest.mark.parametrize(
    "content",
    [
        html("Цена по запросу"),
        html("Цена базы: от 100 ₽ Цена базы: от 200 ₽"),
        html("Аренда: договорная"),
    ],
)
def test_absent_or_ambiguous_visible_price_stays_unknown(content):
    lead = build_servermall_supplier_observation(source(content), "DL360 Gen12").leads[0]
    assert lead.price_status == "UNKNOWN" and lead.published_prices == ()


@pytest.mark.parametrize(
    "content",
    [
        html("Цена базы: от 100 ₽", extra_product=True),
        html("<script>Цена базы: от 100 ₽</script>"),
        html("<span hidden>Цена базы: от 100 ₽</span>"),
        html('<span style="display:none">Цена базы: от 100 ₽</span>'),
    ],
)
def test_broad_cross_product_or_hidden_price_stays_unknown(content):
    lead = build_servermall_supplier_observation(source(content), "DL360").leads[0]
    assert lead.price_status == "UNKNOWN" and lead.published_prices == ()


def test_void_element_does_not_leak_text_after_product_card():
    trailing = '<img src="x"></article><div>Цена базы: от 999 ₽</div></html>'.encode()
    content = html("").replace(
        b"</article></html>",
        trailing,
    )
    lead = build_servermall_supplier_observation(source(content), "DL360").leads[0]
    assert lead.price_status == "UNKNOWN"


def test_monthly_price_span_is_not_also_generic_price_from():
    lead = build_servermall_supplier_observation(
        source(html("Цена: от 500 ₽ / мес")), "DL360"
    ).leads[0]
    assert [(price.kind, price.amount_rub) for price in lead.published_prices] == [
        ("LEASE_MONTHLY", Decimal("500"))
    ]


def test_monthly_price_span_is_not_also_base_price_from():
    lead = build_servermall_supplier_observation(
        source(html("Цена базы: от 500 ₽ / мес в лизинг")), "DL360"
    ).leads[0]
    assert [(price.kind, price.amount_rub) for price in lead.published_prices] == [
        ("LEASE_MONTHLY", Decimal("500"))
    ]


def test_repeated_relative_product_links_and_live_lease_wording_are_one_card():
    relative = "/catalog/servers/dl360/"
    raw = html("19 563 ₽/мес в лизинг", duplicate_anchor=True).decode()
    head, tail = raw.split("</script>", 1)
    content = (head + "</script>" + tail.replace(PRODUCT, relative)).encode()
    lead = build_servermall_supplier_observation(source(content), "DL360").leads[0]
    assert [(price.kind, price.amount_rub) for price in lead.published_prices] == [
        ("LEASE_MONTHLY", Decimal("19563"))
    ]


def test_vat_price_branch_does_not_mix_neighbor_no_vat_amount():
    content = html("Цена базы: от 100 000 ₽").replace(
        b"</article>",
        '<div class="product-card__price-noVAT">Цена базы: от 80 000 ₽ без НДС</div>'
        '</article>'.encode(),
    )
    lead = build_servermall_supplier_observation(source(content), "DL360").leads[0]
    assert [(price.kind, price.amount_rub) for price in lead.published_prices] == [
        ("BASE_PRICE_FROM", Decimal("100000"))
    ]


@pytest.mark.parametrize("label", ["", "duplicate", "hidden"])
def test_base_price_requires_one_visible_scoped_sibling_label(label):
    content = html("Цена базы: от 100 000 ₽")
    title = '<div class="list-price-title">Цена базы: от</div>'.encode()
    if label == "":
        content = content.replace(title, b"")
    elif label == "duplicate":
        content = content.replace(title, title + title)
    else:
        content = content.replace(title, title.replace(b">", b" hidden>", 1))
    lead = build_servermall_supplier_observation(source(content), "DL360").leads[0]
    assert lead.price_status == "UNKNOWN" and lead.published_prices == ()


def test_filtered_lead_uses_original_jsonld_offer_index():
    offers = [
        {
            "@type": "Offer",
            "name": "HPE DL380 Gen12",
            "url": "https://servermall.ru/catalog/servers/dl380/",
        },
        {"@type": "Offer", "name": "HPE DL360 Gen12 8SFF", "url": PRODUCT},
    ]
    graph = {"@graph": [{"@type": "OfferCatalog", "itemListElement": offers}]}
    content = (
        '<html><script type="application/ld+json">'
        + json.dumps(graph)
        + f'</script><article class="product-card"><a href="{PRODUCT}">DL360</a></article></html>'
    ).encode()
    lead = build_servermall_supplier_observation(source(content), "DL360").leads[0]
    assert lead.name_provenance.locator.endswith("itemListElement[2]/name")


def test_capture_retains_exact_bytes_digest_time_and_fixed_source():
    content = html("Цена базы: от 100 ₽")
    observation = build_servermall_supplier_observation(source(content), "DL360")
    capture = SupplierCatalogCapture(observation=observation, content=content)
    assert capture.observation.source_url == SERVERMALL_HPE_GEN12_URL
    assert capture.observation.observed_at == OBSERVED
    assert capture.observation.source_sha256 == hashlib.sha256(content).hexdigest()
    assert capture.observation.byte_count == len(content)
    with pytest.raises(SupplierCatalogSourceError, match="CAPTURE_MISMATCH"):
        SupplierCatalogCapture(observation=observation, content=content + b"x")


def test_source_digest_url_and_lead_binding_fail_closed():
    content = html("Цена базы: от 100 ₽")
    original = source(content)
    with pytest.raises(SupplierCatalogSourceError, match="SOURCE_MISMATCH"):
        build_servermall_supplier_observation(replace(original, sha256="f" * 64), "DL360")
    with pytest.raises(SupplierCatalogSourceError, match="SOURCE_MISMATCH"):
        build_servermall_supplier_observation(
            replace(original, source_url="https://example.invalid/category"), "DL360"
        )
    bad_lead = original.leads[0].model_copy(update={"source_sha256": "f" * 64})
    with pytest.raises(SupplierCatalogSourceError, match="LEAD_SOURCE_MISMATCH"):
        build_servermall_supplier_observation(replace(original, leads=(bad_lead,)), "DL360")


def test_model_rejects_duplicate_urls_provenance_and_contradictory_prices():
    content = html("Цена базы: от 100 ₽")
    observation = build_servermall_supplier_observation(source(content), "DL360")
    payload = observation.model_dump(mode="python")
    payload["leads"] = [payload["leads"][0], payload["leads"][0]]
    payload["scanned_count"] = payload["matched_count"] = payload["returned_count"] = 2
    with pytest.raises(ValidationError, match="PRODUCT_URL_INVALID"):
        SupplierCatalogObservation.model_validate(payload)
    payload = observation.model_dump(mode="python")
    payload["leads"][0]["name_provenance"]["document_id"] = "f" * 64
    with pytest.raises(ValidationError, match="PROVENANCE_MISMATCH"):
        SupplierCatalogObservation.model_validate(payload)
    price = observation.leads[0].published_prices[0]
    lead_payload = observation.leads[0].model_dump(mode="python")
    lead_payload["published_prices"] = [price.model_dump(), price.model_dump()]
    with pytest.raises(ValidationError, match="PRICE_KIND_DUPLICATE"):
        type(observation.leads[0]).model_validate(lead_payload)
    with pytest.raises(ValidationError):
        PublishedSupplierPrice.model_validate(price.model_dump() | {"amount_rub": 1.2})


def test_huge_html_and_unsupported_query_never_fetch(monkeypatch):
    with pytest.raises(SupplierCatalogSourceError, match="SOURCE_MISMATCH"):
        build_servermall_supplier_observation(source(b"x" * (MAX_HTML_BYTES + 1)), "DL360")
    calls = []
    monkeypatch.setattr(
        "procurement.sources.eis_supplier_catalog.fetch_servermall_hpe_gen12",
        lambda query: calls.append(query),
    )
    for query in ("Dell сервер", "насос", "", "x " * 10):
        with pytest.raises(SupplierCatalogSourceError, match="QUERY_UNSUPPORTED"):
            observe_servermall_hpe_gen12(query)
    assert calls == []


def test_observer_makes_one_existing_fixed_fetch_and_returns_capture(monkeypatch):
    content = html("Цена базы: от 100 ₽")
    saved = source(content)
    calls = []

    def fetch(query):
        calls.append(query)
        return saved

    monkeypatch.setattr(
        "procurement.sources.eis_supplier_catalog.fetch_servermall_hpe_gen12", fetch
    )
    capture = observe_servermall_hpe_gen12("  HPE   DL360  ")
    assert calls == ["HPE DL360"]
    assert capture.content == content and capture.observation.source_requests == 1


@pytest.mark.parametrize(
    "addition",
    [
        "<div>" * (MAX_HTML_DEPTH + 1) + "</div>" * (MAX_HTML_DEPTH + 1),
        "<br>" * (MAX_HTML_NODES + 1),
        '<article class="product-card"></article>' * (MAX_CARDS + 1),
        f'<article class="product-card">{"x" * (MAX_CARD_TEXT + 1)}</article>',
    ],
    ids=("depth", "nodes", "cards", "card-text"),
)
def test_html_structure_resource_limits_fail_as_typed_source_error(addition):
    content = html("").replace(b"</html>", addition.encode() + b"</html>")
    with pytest.raises(SupplierCatalogSourceError, match="SOURCE_MISMATCH"):
        build_servermall_supplier_observation(source(content), "DL360")


def test_visible_html_is_parsed_once_for_all_matching_leads(monkeypatch):
    second_url = "https://servermall.ru/catalog/servers/dl360-second/"
    offers = [
        {"@type": "Offer", "name": "HPE DL360 Gen12 8SFF", "url": PRODUCT},
        {"@type": "Offer", "name": "HPE DL360 Gen12 16SFF", "url": second_url},
    ]
    graph = {"@graph": [{"@type": "OfferCatalog", "itemListElement": offers}]}
    content = (
        '<html><script type="application/ld+json">'
        + json.dumps(graph)
        + f'</script><article class="product-card"><a href="{PRODUCT}">one</a></article>'
        + f'<article class="product-card"><a href="{second_url}">two</a></article></html>'
    ).encode()
    first = source(content).leads[0]
    saved = ServerMallObservation(
        source_url=SERVERMALL_HPE_GEN12_URL,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        observed_at=OBSERVED,
        leads=(
            first,
            first.model_copy(
                update={
                    "lead_id": second_url,
                    "product_name": "HPE DL360 Gen12 16SFF",
                    "product_url": second_url,
                }
            ),
        ),
    )
    calls = 0
    from procurement.sources import eis_supplier_catalog as catalog

    original = catalog._VisibleCards.feed

    def counted_feed(parser, value):
        nonlocal calls
        calls += 1
        return original(parser, value)

    monkeypatch.setattr(catalog._VisibleCards, "feed", counted_feed)
    result = build_servermall_supplier_observation(saved, "DL360")
    assert calls == 1 and result.returned_count == result.matched_count == 2
    assert result.scanned_count == 2 and result.truncated is False


def test_parser_recursion_failure_is_normalized(monkeypatch):
    from procurement.sources import eis_supplier_catalog as catalog

    def fail(*args):
        raise RecursionError

    monkeypatch.setattr(catalog._VisibleCards, "feed", fail)
    with pytest.raises(SupplierCatalogSourceError, match="SOURCE_MISMATCH"):
        build_servermall_supplier_observation(source(html("")), "DL360")
