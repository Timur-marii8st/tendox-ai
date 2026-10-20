"""Read-only search in a supported marketplace catalog, with explicit scope."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from procurement.sources.catalog_routes import servermall_covers
from procurement.sources.eaeu_registry import _validated_query
from procurement.sources.servermall import (
    SERVERMALL_HPE_GEN12_URL,
    ServerMallSourceError,
    fetch_servermall_hpe_gen12,
)


class DirectCatalogStatus(StrEnum):
    COMPLETED = "COMPLETED"
    SOURCE_ERROR = "SOURCE_ERROR"
    QUERY_NOT_COVERED = "QUERY_NOT_COVERED"


class DirectCatalogCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    url: str
    supplier: str
    manufacturer_claim: str | None = None
    suitability: Literal["UNKNOWN"] = "UNKNOWN"


class DirectCatalogAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: str = "servermall_hpe_gen12"
    site_name: str = "ServerMall · HPE ProLiant Gen12"
    catalog_url: str = SERVERMALL_HPE_GEN12_URL
    query: str
    fetch_status: DirectCatalogStatus
    observed_at: datetime
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    response_byte_size: int | None = None
    error_code: str | None = None
    coverage: Literal["ONE_CATEGORY_PAGE_ONLY"] = "ONE_CATEGORY_PAGE_ONLY"
    candidates: tuple[DirectCatalogCandidate, ...] = ()


def search_direct_catalog(query: str) -> DirectCatalogAttempt:
    """Search one published category page; zero matches says nothing about the rest of the site."""
    normalized = " ".join(_validated_query(query))
    if not any(character.isalnum() for character in normalized):
        raise ValueError("query must contain a letter or digit")
    if not servermall_covers(normalized):
        return DirectCatalogAttempt(
            query=normalized,
            fetch_status=DirectCatalogStatus.QUERY_NOT_COVERED,
            observed_at=datetime.now(UTC),
            error_code="CATEGORY_NOT_RELEVANT",
        )
    try:
        observation = fetch_servermall_hpe_gen12(normalized)
    except ServerMallSourceError:
        return DirectCatalogAttempt(
            query=normalized,
            fetch_status=DirectCatalogStatus.SOURCE_ERROR,
            observed_at=datetime.now(UTC),
            error_code="CATALOG_UNAVAILABLE_OR_CHANGED",
        )
    return DirectCatalogAttempt(
        query=normalized,
        fetch_status=DirectCatalogStatus.COMPLETED,
        observed_at=observation.observed_at,
        response_sha256=observation.sha256,
        response_byte_size=len(observation.content),
        candidates=tuple(
            DirectCatalogCandidate(
                title=lead.product_name,
                url=lead.product_url,
                supplier=lead.supplier,
                manufacturer_claim=lead.manufacturer,
            )
            for lead in observation.leads
        ),
    )
