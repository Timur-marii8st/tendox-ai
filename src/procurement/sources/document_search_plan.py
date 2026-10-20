"""Exact, reviewable search payload derived from an uploaded tender document."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.documents.extraction import ExtractionStatus
from procurement.documents.facts import DocumentRole
from procurement.domain.provenance import Provenance
from procurement.sources.catalog_routes import (
    MAX_CATEGORY_PAGES,
    category_page_url,
    servermall_covers,
    yandex_route,
)
from procurement.sources.depo_catalog import DEPO_SERVERS_URL, depo_covers
from procurement.sources.eaeu_registry import EAEU_REGISTRY_URL, _validated_query
from procurement.sources.graviton_catalog import graviton_route
from procurement.sources.servermall import SERVERMALL_HPE_GEN12_URL
from procurement.sources.supl_browser import SUPL_PUMPS_URL, supl_covers
from procurement.sources.yandex_business import yandex_business_category_for_query
from procurement.sources.yandex_pagination import PAGINATION_POLICY

if TYPE_CHECKING:
    from procurement.api.contracts import DocumentRecord

_PRODUCT_ANCHOR = re.compile(
    r"^(?:наименование\s+(?:товара|продукции|оборудования)|"
    r"предмет\s+(?:закупки|поставки)|товар)\s*[:—–-]\s*(.+)$",
    re.IGNORECASE,
)

SearchMode = Literal["AUTO", "HTTP", "BROWSER"]


class SearchPlanStatus(StrEnum):
    READY = "READY"
    NO_PRODUCT_ANCHOR = "NO_PRODUCT_ANCHOR"
    AMBIGUOUS = "AMBIGUOUS"
    EXTRACTION_UNAVAILABLE = "EXTRACTION_UNAVAILABLE"


class SearchDestination(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: str
    site_name: str
    api_url: str
    exact_query: str
    transport: Literal["HTTP", "HTTP_THEN_BROWSER", "BROWSER"] = "HTTP"
    browser_loads_page_resources: bool = False
    browser_policy_version: Literal["browser-catalog-v5"] | None = None
    page_urls: tuple[str, ...] = ()
    match_policy: Literal["SOURCE_QUERY", "TITLE_TERMS_V1"] = "SOURCE_QUERY"
    pagination_policy: Literal["CATEGORY_LINK_OR_STATE_V1"] | None = None


class SearchQueryEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    provenance: Provenance


class DocumentSupplierSearchPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    schema_version: Literal["supplier-search-plan-v8"] = "supplier-search-plan-v8"
    mode: SearchMode = "AUTO"
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: SearchPlanStatus
    query: str | None = None
    query_evidence: SearchQueryEvidence | None = None
    alternative_evidence: tuple[SearchQueryEvidence, ...] = ()
    destinations: tuple[SearchDestination, ...] = ()
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _exact_plan(self) -> Self:
        if self.status is SearchPlanStatus.READY:
            if self.query is None or self.query_evidence is None or not self.destinations:
                raise ValueError("ready plan needs a query, evidence and destinations")
            if self.query != self.query_evidence.query:
                raise ValueError("query differs from source evidence")
            if self.query_evidence.provenance.document_id != self.document_id:
                raise ValueError("query evidence belongs to another document")
        elif self.query is not None or self.query_evidence is not None or self.destinations:
            raise ValueError("unready plan cannot expose executable payload")
        if any(
            item.provenance.document_id != self.document_id for item in self.alternative_evidence
        ):
            raise ValueError("alternative evidence belongs to another document")
        payload = self.model_dump(mode="json", exclude={"plan_sha256"})
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.plan_sha256 != digest:
            raise ValueError("search plan digest mismatch")
        return self


def _build_plan(
    document: DocumentRecord,
    status: SearchPlanStatus,
    *,
    query_evidence: SearchQueryEvidence | None = None,
    alternatives: tuple[SearchQueryEvidence, ...] = (),
    mode: SearchMode = "AUTO",
) -> DocumentSupplierSearchPlan:
    query = query_evidence.query if query_evidence else None
    destinations: tuple[SearchDestination, ...] = ()
    if query is not None:
        destinations = (
            SearchDestination(
                site_id="eaeu_products",
                site_name="Реестр промышленных товаров ЕАЭС",
                api_url=EAEU_REGISTRY_URL,
                exact_query=query,
            ),
        )
        if servermall_covers(query):
            destinations += (
                SearchDestination(
                    site_id="servermall_hpe_gen12",
                    site_name="ServerMall · HPE ProLiant Gen12 (одна категория)",
                    api_url=SERVERMALL_HPE_GEN12_URL,
                    exact_query=query,
                    transport="HTTP_THEN_BROWSER" if mode == "AUTO" else mode,
                    browser_loads_page_resources=mode != "HTTP",
                    browser_policy_version="browser-catalog-v5" if mode != "HTTP" else None,
                    page_urls=(SERVERMALL_HPE_GEN12_URL,),
                    match_policy="TITLE_TERMS_V1",
                ),
            )
        category_url = yandex_business_category_for_query(query)
        route = yandex_route(query)
        if category_url is not None and route is not None:
            destinations += (
                SearchDestination(
                    site_id="yandex_market_business",
                    site_name=(
                        f"Яндекс Маркет для Бизнеса · {route.name} "
                        f"(до {MAX_CATEGORY_PAGES} страниц)"
                    ),
                    api_url=category_url,
                    pagination_policy=PAGINATION_POLICY,
                    exact_query=query,
                    transport="HTTP_THEN_BROWSER" if mode == "AUTO" else mode,
                    browser_loads_page_resources=mode != "HTTP",
                    browser_policy_version="browser-catalog-v5" if mode != "HTTP" else None,
                    page_urls=tuple(
                        category_page_url(route, i) for i in range(1, MAX_CATEGORY_PAGES + 1)
                    ),
                    match_policy="TITLE_TERMS_V1",
                ),
            )
        graviton = graviton_route(query)
        if graviton is not None:
            destinations += (
                SearchDestination(
                    site_id="graviton_catalog",
                    site_name=f"Гравитон · {graviton.name} (одна публичная категория)",
                    api_url=graviton.url,
                    exact_query=query,
                    page_urls=(graviton.url,),
                    match_policy="TITLE_TERMS_V1",
                ),
            )
        if depo_covers(query):
            destinations += (
                SearchDestination(
                    site_id="depo_servers",
                    site_name="DEPO · серверы (одна публичная категория)",
                    api_url=DEPO_SERVERS_URL,
                    exact_query=query,
                    page_urls=(DEPO_SERVERS_URL,),
                    match_policy="TITLE_TERMS_V1",
                ),
            )
        if mode != "HTTP" and supl_covers(query):
            destinations += (
                SearchDestination(
                    site_id="supl_biz_pumps",
                    site_name="Supl.biz · промышленные насосы (одна публичная категория)",
                    api_url=SUPL_PUMPS_URL,
                    exact_query=query,
                    transport="BROWSER",
                    browser_loads_page_resources=True,
                    browser_policy_version="browser-catalog-v5",
                    page_urls=(SUPL_PUMPS_URL,),
                    match_policy="TITLE_TERMS_V1",
                ),
            )
    serializable = DocumentSupplierSearchPlan.model_construct(
        mode=mode,
        document_id=document.document_id,
        source_document_sha256=document.sha256,
        status=status,
        query=query,
        query_evidence=query_evidence,
        alternative_evidence=alternatives,
        destinations=destinations,
        plan_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"plan_sha256"})
    digest = hashlib.sha256(
        json.dumps(serializable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DocumentSupplierSearchPlan(
        mode=mode,
        document_id=document.document_id,
        source_document_sha256=document.sha256,
        status=status,
        query=query,
        query_evidence=query_evidence,
        alternative_evidence=alternatives,
        destinations=destinations,
        plan_sha256=digest,
    )


def build_document_supplier_search_plan(
    document: DocumentRecord, *, mode: SearchMode = "AUTO"
) -> DocumentSupplierSearchPlan:
    """Use only explicit product-name anchors; never infer an item from specs."""
    if (
        document.document_role is not DocumentRole.TENDER_REQUIREMENTS
        or document.extraction.status is not ExtractionStatus.PASS
    ):
        return _build_plan(document, SearchPlanStatus.EXTRACTION_UNAVAILABLE, mode=mode)
    found: dict[str, SearchQueryEvidence] = {}
    for block in document.extraction.blocks:
        if block.provenance.document_id != document.document_id:
            continue
        for line in block.text.splitlines():
            match = _PRODUCT_ANCHOR.fullmatch(line.strip())
            if match is None:
                continue
            candidate = " ".join(match.group(1).strip(" .;:").split())
            try:
                words = _validated_query(candidate)
            except ValueError:
                continue
            query = " ".join(words)
            if not any(character.isalnum() for character in query):
                continue
            found.setdefault(
                query.casefold(),
                SearchQueryEvidence(query=query, provenance=block.provenance),
            )
    if not found:
        return _build_plan(document, SearchPlanStatus.NO_PRODUCT_ANCHOR, mode=mode)
    if len(found) > 1:
        return _build_plan(
            document,
            SearchPlanStatus.AMBIGUOUS,
            alternatives=tuple(found.values())[:10],
            mode=mode,
        )
    return _build_plan(
        document, SearchPlanStatus.READY, query_evidence=next(iter(found.values())), mode=mode
    )
