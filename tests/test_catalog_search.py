"""Multi-source catalog discovery preserves success and failure independently."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from procurement.domain.sourcing import LeadSourceKind, ServerLead, SourcingSourceStatus
from procurement.sources.catalog_search import fetch_server_catalog_sources
from procurement.sources.manufacturer_catalog import (
    ManufacturerCatalogObservation,
    ManufacturerCatalogSourceError,
)
from procurement.sources.servermall import ServerMallObservation, ServerMallSourceError

NOW = datetime(2026, 9, 20, tzinfo=UTC)


def _lead(*, official: bool) -> ServerLead:
    content = b"official" if official else b"supplier"
    return ServerLead(
        lead_id="official" if official else "supplier",
        supplier="HPE" if official else "ServerMall",
        manufacturer="HPE",
        source_kind=(
            LeadSourceKind.MANUFACTURER_CATALOG if official else LeadSourceKind.SUPPLIER_CATALOG
        ),
        product_name="HPE DL360 Gen12",
        source_url="https://www.hpe.com/psnow/doc/a50006984enw"
        if official
        else "https://servermall.ru/sets/servery-hp-proliant-gen12/",
        source_sha256=hashlib.sha256(content).hexdigest(),
        observed_at=NOW,
    )


def _official_observation() -> ManufacturerCatalogObservation:
    content = b"official"
    lead = _lead(official=True)
    return ManufacturerCatalogObservation(
        source_name="HPE official catalog",
        source_url=lead.source_url,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        observed_at=NOW,
        media_type="text/html",
        leads=(lead,),
    )


def _supplier_observation() -> ServerMallObservation:
    content = b"supplier"
    lead = _lead(official=False)
    return ServerMallObservation(
        source_url=lead.source_url,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        observed_at=NOW,
        leads=(lead,),
    )


def test_hpe_query_preserves_official_and_supplier_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "procurement.sources.catalog_search.fetch_official_manufacturer_catalog",
        lambda query: _official_observation(),
    )
    monkeypatch.setattr(
        "procurement.sources.catalog_search.fetch_servermall_hpe_gen12",
        lambda query: _supplier_observation(),
    )

    attempts = fetch_server_catalog_sources("DL360 Gen12")
    assert [item.source_kind for item in attempts] == [
        LeadSourceKind.MANUFACTURER_CATALOG,
        LeadSourceKind.SUPPLIER_CATALOG,
    ]
    assert all(item.status is SourcingSourceStatus.COMPLETED for item in attempts)
    assert [item.content for item in attempts] == [b"official", b"supplier"]


def test_partial_success_keeps_supplier_and_official_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(query: str):
        raise ManufacturerCatalogSourceError("unavailable")

    monkeypatch.setattr(
        "procurement.sources.catalog_search.fetch_official_manufacturer_catalog",
        unavailable,
    )
    monkeypatch.setattr(
        "procurement.sources.catalog_search.fetch_servermall_hpe_gen12",
        lambda query: _supplier_observation(),
    )

    attempts = fetch_server_catalog_sources("DL360 Gen12")
    assert attempts[0].status is SourcingSourceStatus.SOURCE_ERROR
    assert attempts[0].content is None
    assert attempts[1].status is SourcingSourceStatus.COMPLETED
    assert attempts[1].leads[0].source_kind is LeadSourceKind.SUPPLIER_CATALOG


def test_lenovo_does_not_call_unrelated_hpe_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(query: str):
        raise ManufacturerCatalogSourceError("unavailable")

    monkeypatch.setattr(
        "procurement.sources.catalog_search.fetch_official_manufacturer_catalog",
        unavailable,
    )
    monkeypatch.setattr(
        "procurement.sources.catalog_search.fetch_servermall_hpe_gen12",
        lambda query: pytest.fail("HPE supplier catalog is unrelated to Lenovo"),
    )

    attempts = fetch_server_catalog_sources("SR630 V3")
    assert len(attempts) == 1
    assert attempts[0].source_name == "Lenovo official catalog"
    assert attempts[0].status is SourcingSourceStatus.SOURCE_ERROR


def test_all_hpe_failures_are_returned_not_collapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def official_unavailable(query: str):
        raise ManufacturerCatalogSourceError("unavailable")

    def supplier_unavailable(query: str):
        raise ServerMallSourceError("unavailable")

    monkeypatch.setattr(
        "procurement.sources.catalog_search.fetch_official_manufacturer_catalog",
        official_unavailable,
    )
    monkeypatch.setattr(
        "procurement.sources.catalog_search.fetch_servermall_hpe_gen12",
        supplier_unavailable,
    )

    attempts = fetch_server_catalog_sources("DL360 Gen12")
    assert len(attempts) == 2
    assert all(item.status is SourcingSourceStatus.SOURCE_ERROR for item in attempts)
    assert all(item.error_code == "SOURCE_UNAVAILABLE_OR_CHANGED" for item in attempts)


def test_ambiguous_official_family_query_fails_closed() -> None:
    attempts = fetch_server_catalog_sources("DL360 Gen12 SR630 V3")
    assert len(attempts) == 1
    assert attempts[0].status is SourcingSourceStatus.SOURCE_ERROR
    assert attempts[0].error_code == "AMBIGUOUS_SOURCE_ROUTING"
