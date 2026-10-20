"""Multi-source, fail-closed server catalog discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from procurement.domain.sourcing import LeadSourceKind, ServerLead, SourcingSourceStatus
from procurement.sources.manufacturer_catalog import (
    OFFICIAL_SERVER_CATALOGS,
    ManufacturerCatalogDefinition,
    ManufacturerCatalogSourceError,
    fetch_official_manufacturer_catalog,
    match_official_server_catalog,
)
from procurement.sources.servermall import (
    SERVERMALL_HPE_GEN12_URL,
    ServerMallSourceError,
    fetch_servermall_hpe_gen12,
)


@dataclass(frozen=True)
class CatalogSourceAttempt:
    source_name: str
    source_kind: LeadSourceKind
    source_url: str
    media_type: str
    status: SourcingSourceStatus
    observed_at: datetime
    content: bytes | None = None
    sha256: str | None = None
    leads: tuple[ServerLead, ...] = ()
    error_code: str | None = None


def _official_attempt(
    query: str, definition: ManufacturerCatalogDefinition
) -> CatalogSourceAttempt:
    source_name = f"{definition.manufacturer} official catalog"
    try:
        observation = fetch_official_manufacturer_catalog(query)
        if observation is None:  # pragma: no cover - same code-owned matcher
            raise RuntimeError("official catalog routing changed during one call")
        return CatalogSourceAttempt(
            source_name=observation.source_name,
            source_kind=LeadSourceKind.MANUFACTURER_CATALOG,
            source_url=observation.source_url,
            media_type=observation.media_type,
            status=SourcingSourceStatus.COMPLETED,
            observed_at=observation.observed_at,
            content=observation.content,
            sha256=observation.sha256,
            leads=observation.leads,
        )
    except ManufacturerCatalogSourceError:
        return CatalogSourceAttempt(
            source_name=source_name,
            source_kind=LeadSourceKind.MANUFACTURER_CATALOG,
            source_url=definition.source_url,
            media_type=definition.media_type,
            status=SourcingSourceStatus.SOURCE_ERROR,
            observed_at=datetime.now(UTC),
            error_code="SOURCE_UNAVAILABLE_OR_CHANGED",
        )


def _supplier_attempt(query: str) -> CatalogSourceAttempt:
    try:
        observation = fetch_servermall_hpe_gen12(query)
        return CatalogSourceAttempt(
            source_name="ServerMall",
            source_kind=LeadSourceKind.SUPPLIER_CATALOG,
            source_url=observation.source_url,
            media_type="text/html",
            status=SourcingSourceStatus.COMPLETED,
            observed_at=observation.observed_at,
            content=observation.content,
            sha256=observation.sha256,
            leads=observation.leads,
        )
    except ServerMallSourceError:
        return CatalogSourceAttempt(
            source_name="ServerMall",
            source_kind=LeadSourceKind.SUPPLIER_CATALOG,
            source_url=SERVERMALL_HPE_GEN12_URL,
            media_type="text/html",
            status=SourcingSourceStatus.SOURCE_ERROR,
            observed_at=datetime.now(UTC),
            error_code="SOURCE_UNAVAILABLE_OR_CHANGED",
        )


def fetch_server_catalog_sources(query: str) -> tuple[CatalogSourceAttempt, ...]:
    """Fetch every applicable source without hiding partial failures."""
    try:
        official = match_official_server_catalog(query)
    except ManufacturerCatalogSourceError:
        definition = OFFICIAL_SERVER_CATALOGS[0]
        return (
            CatalogSourceAttempt(
                source_name="Official manufacturer catalog routing",
                source_kind=LeadSourceKind.MANUFACTURER_CATALOG,
                source_url=definition.source_url,
                media_type=definition.media_type,
                status=SourcingSourceStatus.SOURCE_ERROR,
                observed_at=datetime.now(UTC),
                error_code="AMBIGUOUS_SOURCE_ROUTING",
            ),
        )
    if official is None:
        return (_supplier_attempt(query),)
    attempts = [_official_attempt(query, official)]
    if official.manufacturer == "HPE":
        attempts.append(_supplier_attempt(query))
    return tuple(attempts)
