import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from procurement.sources.public_unit_price import extract_public_unit_price
from procurement.sources.supplier_page import parse_supplier_page

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
URL = "https://supplier.example.com/product/one"
XML = "a" * 64


def offer():
    return {
        "@type": "Product",
        "name": "Synthetic bolt",
        "offers": {
            "@type": "Offer",
            "price": "120.00",
            "priceCurrency": "RUB",
            "priceSpecification": {
                "@type": "UnitPriceSpecification",
                "price": "120.00",
                "priceCurrency": "RUB",
                "valueAddedTaxIncluded": False,
                "referenceQuantity": {
                    "@type": "QuantitativeValue",
                    "value": "10",
                    "unitText": "шт",
                },
            },
        },
    }


def parse(value):
    content = (
        '<h1>Synthetic bolt</h1><script type="application/ld+json">'
        + json.dumps(value)
        + "</script>"
    ).encode()
    observation = parse_supplier_page(URL, content, observed_at=NOW)
    return extract_public_unit_price(
        content, observation, company_id="alpha", notice_xml_sha256=XML, line_id="1", now=NOW
    )


def test_reference_quantity_and_tax_basis_are_extracted_with_source_locators():
    result = parse(offer())
    assert result is not None
    assert result.price.value == 120
    assert result.quantity_per_price.value == 10
    assert result.unit.code == "piece" and result.amount_basis == "EX_VAT"
    assert result.company_id == "alpha" and result.notice_xml_sha256 == XML
    assert result.price.provenance.locator.endswith(".priceSpecification.price")
    assert result.unit.provenance.locator.endswith(".referenceQuantity.unitText")
    assert result.technical_status == result.availability == "UNKNOWN"


@pytest.mark.parametrize(
    "field", ["referenceQuantity", "valueAddedTaxIncluded", "priceCurrency", "price"]
)
def test_missing_price_basis_field_is_not_guessed(field):
    value = offer()
    del value["offers"]["priceSpecification"][field]
    assert parse(value) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"price": "1.00"},
        {"priceCurrency": "USD"},
        {"valueAddedTaxIncluded": "false"},
        {"eligibleQuantity": {"minValue": 1000}},
        {"priceType": "SalePrice"},
        {"billingIncrement": 12},
        {"validForMemberTier": "VIP"},
        {"validThrough": "2020-01-01T00:00:00+00:00"},
        {"validThrough": "2099-01-01"},
        {"unitText": "kg"},
    ],
)
def test_conflicting_conditional_or_ambiguous_price_is_rejected(changes):
    value = offer()
    value["offers"]["priceSpecification"].update(changes)
    assert parse(value) is None


def test_product_and_offer_ambiguity_are_not_merged():
    assert parse([offer(), copy.deepcopy(offer())]) is None
    value = offer()
    value["offers"] = [value["offers"], copy.deepcopy(value["offers"])]
    assert parse(value) is None


def test_packaging_is_not_guessed_from_product_title_or_number_in_name():
    value = offer()
    value["name"] = "Paper 500 sheets 5/100"
    value["offers"]["priceSpecification"]["referenceQuantity"]["unitText"] = "упаковка"
    assert parse(value) is None


def test_gross_price_is_labelled_gross_and_not_silently_converted_to_net():
    value = offer()
    value["offers"]["priceSpecification"]["valueAddedTaxIncluded"] = True
    result = parse(value)
    assert result is not None and result.amount_basis == "GROSS"


def test_validity_from_future_or_expired_offer_is_rejected():
    value = offer()
    value["offers"]["validFrom"] = (NOW + timedelta(days=1)).isoformat()
    assert parse(value) is None


def test_exact_saved_body_hash_is_required():
    content = b'<script type="application/ld+json">{}</script>'
    observation = parse_supplier_page(URL, content, observed_at=NOW)
    with pytest.raises(ValueError, match="BODY_MISMATCH"):
        extract_public_unit_price(
            content + b"changed",
            observation,
            company_id="alpha",
            notice_xml_sha256=XML,
            line_id="1",
            now=NOW,
        )


@pytest.mark.parametrize(
    "availability",
    ["http://schema.org/OutOfStock", "https://schema.org/OutOfStock", "OutOfStock", "Discontinued"],
)
def test_explicit_unavailable_product_is_not_downgraded_to_unknown(availability):
    value = offer()
    value["offers"]["availability"] = availability
    result = parse(value)
    assert result is not None and result.availability == "UNAVAILABLE"


def test_nonboolean_offer_tax_declaration_is_not_equal_to_false():
    value = offer()
    value["offers"]["valueAddedTaxIncluded"] = 0
    assert parse(value) is None
