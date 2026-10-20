"""Official manufacturer discovery remains an exact, non-quote observation."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from pypdf import PdfWriter

from procurement.domain.sourcing import LeadSourceKind
from procurement.sources.manufacturer_catalog import (
    OFFICIAL_SERVER_CATALOGS,
    ManufacturerCatalogSourceError,
    match_official_server_catalog,
    parse_official_manufacturer_catalog,
)

OBSERVED = datetime(2026, 9, 20, tzinfo=UTC)


def _html(title: str) -> bytes:
    return f"<html><head><title>{title}</title></head><body>official</body></html>".encode()


@pytest.mark.parametrize(
    ("query", "manufacturer"),
    (
        ("DL360 Gen12", "HPE"),
        ("ThinkSystem SR630 V3", "Lenovo"),
        ("PowerEdge R660", "Dell"),
    ),
)
def test_distinctive_model_query_routes_to_official_catalog(query: str, manufacturer: str) -> None:
    definition = match_official_server_catalog(query)
    assert definition is not None
    assert definition.manufacturer == manufacturer


@pytest.mark.parametrize("definition", OFFICIAL_SERVER_CATALOGS[:2])
def test_official_html_becomes_non_quote_lead(definition) -> None:

    observation = parse_official_manufacturer_catalog(
        definition,
        _html(definition.expected_title),
        observed_at=OBSERVED,
    )
    lead = observation.leads[0]
    assert lead.manufacturer == definition.manufacturer
    assert lead.source_kind is LeadSourceKind.MANUFACTURER_CATALOG
    assert lead.price_rub is None
    assert lead.bom is None
    assert lead.source_sha256 == observation.sha256


def test_dell_technical_guide_pdf_becomes_non_quote_lead() -> None:
    definition = OFFICIAL_SERVER_CATALOGS[2]
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": "Dell PowerEdge R660 Technical Guide"})
    output = BytesIO()
    writer.write(output)

    observation = parse_official_manufacturer_catalog(
        definition,
        output.getvalue(),
        observed_at=OBSERVED,
    )

    assert observation.media_type == "application/pdf"
    assert observation.leads[0].manufacturer == "Dell"
    assert observation.leads[0].price_rub is None
    assert observation.leads[0].bom is None


def test_generic_or_unknown_query_is_not_misrouted() -> None:
    assert match_official_server_catalog("server") is None
    assert match_official_server_catalog("PowerEdge R760") is None


def test_changed_or_oversized_official_page_fails_closed() -> None:
    definition = OFFICIAL_SERVER_CATALOGS[0]
    with pytest.raises(ManufacturerCatalogSourceError, match="identity"):
        parse_official_manufacturer_catalog(
            definition,
            _html("unexpected product"),
            observed_at=OBSERVED,
        )
    with pytest.raises(ManufacturerCatalogSourceError, match="limit"):
        parse_official_manufacturer_catalog(
            definition,
            b"x" * (2 * 1024 * 1024 + 1),
            observed_at=OBSERVED,
        )
