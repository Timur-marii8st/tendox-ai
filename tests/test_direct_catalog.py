"""Direct catalog search preserves scope and source provenance."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from procurement.sources.direct_catalog import DirectCatalogStatus, search_direct_catalog
from procurement.sources.servermall import (
    SERVERMALL_HPE_GEN12_URL,
    ServerMallObservation,
    ServerMallSourceError,
)


def test_direct_catalog_returns_source_backed_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    from procurement.domain.sourcing import LeadSourceKind, ServerLead

    observed = datetime(2026, 9, 21, tzinfo=UTC)
    product_url = "https://servermall.ru/catalog/servers/example/"

    def fetch(query: str) -> ServerMallObservation:
        assert query == "HPE ProLiant Gen12"
        return ServerMallObservation(
            source_url=SERVERMALL_HPE_GEN12_URL,
            content=b"source",
            sha256="a" * 64,
            observed_at=observed,
            leads=(ServerLead(
                lead_id=product_url,
                supplier="ServerMall",
                manufacturer="HPE",
                source_kind=LeadSourceKind.SUPPLIER_CATALOG,
                product_name="HPE ProLiant Gen12",
                source_url=SERVERMALL_HPE_GEN12_URL,
                product_url=product_url,
                source_sha256="a" * 64,
                observed_at=observed,
            ),),
        )

    monkeypatch.setattr("procurement.sources.direct_catalog.fetch_servermall_hpe_gen12", fetch)
    result = search_direct_catalog("HPE ProLiant Gen12")
    assert result.fetch_status is DirectCatalogStatus.COMPLETED
    assert result.coverage == "ONE_CATEGORY_PAGE_ONLY"
    assert result.response_sha256 == "a" * 64
    assert result.candidates[0].url == product_url
    assert result.candidates[0].suitability == "UNKNOWN"


def test_unavailable_direct_catalog_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def fetch(_query: str) -> None:
        raise ServerMallSourceError("offline")

    monkeypatch.setattr("procurement.sources.direct_catalog.fetch_servermall_hpe_gen12", fetch)
    result = search_direct_catalog("HPE DL360")
    assert result.fetch_status is DirectCatalogStatus.SOURCE_ERROR
    assert result.candidates == ()
    assert result.response_sha256 is None
