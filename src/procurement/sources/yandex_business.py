"""Bounded read-only title search in a routed Yandex Market for Business category.

This is a category page, not site-wide search or a confirmed supplier offer.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from enum import StrEnum
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from procurement.sources.catalog_routes import (
    MAX_CATEGORY_PAGES,
    CatalogPageEvidence,
    category_page_url,
    title_matches_query,
    yandex_route,
)
from procurement.sources.eaeu_registry import _validated_query
from procurement.sources.http_transport import public_source_client
from procurement.sources.yandex_pagination import PaginationError, category_continuation

YANDEX_BUSINESS_PUMPS_URL = (
    "https://business.market.yandex.ru/catalog--nasosy-i-komplektuiushchie/18060427/list"
)
_MAX_HTML_BYTES = 3 * 1024 * 1024
_MAX_ITEMS = 100


class YandexBusinessStatus(StrEnum):
    COMPLETED = "COMPLETED"
    SOURCE_ERROR = "SOURCE_ERROR"
    QUERY_NOT_COVERED = "QUERY_NOT_COVERED"
    PARTIAL = "PARTIAL"


class YandexBusinessCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2048)
    source_item_index: int = Field(ge=1, le=_MAX_ITEMS)
    suitability: Literal["UNKNOWN"] = "UNKNOWN"
    source_page_url: str | None = None
    source_page_number: int | None = None
    source_sha256: str | None = None


class YandexBusinessAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: Literal["yandex_market_business"] = "yandex_market_business"
    site_name: str = "Яндекс Маркет для Бизнеса"
    query: str
    category_url: str | None = None
    fetch_status: YandexBusinessStatus
    observed_at: datetime
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    response_byte_size: int | None = None
    scanned_count: int | None = None
    error_code: str | None = None
    coverage: Literal["BOUNDED_CATEGORY_PAGES"] = "BOUNDED_CATEGORY_PAGES"
    query_mode: Literal["TITLE_TERMS"] = "TITLE_TERMS"
    category_key: str | None = None
    pages: tuple[CatalogPageEvidence, ...] = ()
    stop_reason: str | None = None
    candidates: tuple[YandexBusinessCandidate, ...] = ()


class _SourceError(ValueError):
    pass


class _JsonLdScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._inside = False
        self._content: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._inside = True
            self._content = []

    def handle_data(self, data: str) -> None:
        if self._inside:
            self._content.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside:
            self.scripts.append("".join(self._content))
            self._inside = False


def yandex_business_category_for_query(query: str) -> str | None:
    """Only a confirmed category is routed; unmatched products remain uncovered."""
    route = yandex_route(query)
    return category_page_url(route, 1) if route else None


def parse_yandex_business_category(
    content: bytes,
) -> tuple[int, tuple[YandexBusinessCandidate, ...]]:
    if not content or len(content) > _MAX_HTML_BYTES:
        raise _SourceError("invalid category response size")
    parser = _JsonLdScripts()
    try:
        parser.feed(content.decode("utf-8"))
        documents = [json.loads(script) for script in parser.scripts]
    except (UnicodeDecodeError, ValueError) as error:
        raise _SourceError("invalid category structured data") from error
    lists = [
        item for item in documents if isinstance(item, dict) and item.get("@type") == "ItemList"
    ]
    if len(lists) != 1 or not isinstance(lists[0].get("itemListElement"), list):
        raise _SourceError("one product ItemList is required")
    rows = lists[0]["itemListElement"]
    if not 0 < len(rows) <= _MAX_ITEMS:
        raise _SourceError("unexpected number of category products")
    candidates: list[YandexBusinessCandidate] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or row.get("@type") != "ListItem":
            raise _SourceError("invalid category list item")
        product = row.get("item")
        if not isinstance(product, dict) or product.get("@type") != "Product":
            raise _SourceError("invalid category product")
        name, url = product.get("name"), product.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            raise _SourceError("product title or URL missing")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "market.yandex.ru"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or not parsed.path.startswith("/card/")
            or parsed.query
            or parsed.fragment
        ):
            raise _SourceError("product URL is outside the published catalog")
        title = " ".join(name.split())
        if not title or len(title) > 300 or len(url) > 2048 or url in seen:
            raise _SourceError("duplicate or invalid product")
        seen.add(url)
        candidates.append(YandexBusinessCandidate(title=title, url=url, source_item_index=index))
    return len(rows), tuple(candidates)


def _fetch_category_page(url: str) -> bytes:
    with (
        public_source_client() as client,
        client.stream("GET", url) as response,
    ):
        if response.status_code != 200 or "text/html" not in response.headers.get(
            "content-type", ""
        ):
            raise _SourceError(f"HTTP_{response.status_code}_OR_NOT_HTML")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > _MAX_HTML_BYTES:
                raise _SourceError("PAGE_SIZE_LIMIT")
            chunks.append(chunk)
    return b"".join(chunks)


def search_yandex_business_category(query: str) -> YandexBusinessAttempt:
    """Не более двух страниц выбранной категории, с фильтром по словам названия."""
    normalized = " ".join(_validated_query(query))
    if not any(character.isalnum() for character in normalized):
        raise ValueError("query must contain a letter or digit")
    route = yandex_route(normalized)
    if route is None:
        return YandexBusinessAttempt(
            query=normalized,
            fetch_status=YandexBusinessStatus.QUERY_NOT_COVERED,
            observed_at=datetime.now(UTC),
            error_code="NO_UNAMBIGUOUS_CATEGORY_FOR_QUERY",
        )
    pages: list[CatalogPageEvidence] = []
    candidates: dict[str, YandexBusinessCandidate] = {}
    signatures: set[tuple[str, ...]] = set()
    stop_reason = "PAGE_LIMIT"
    for number in range(1, MAX_CATEGORY_PAGES + 1):
        url = category_page_url(route, number)
        try:
            if number > 1:
                time.sleep(1)
            content = _fetch_category_page(url)
            scanned, rows = parse_yandex_business_category(content)
            continuation = category_continuation(content, route, number)
            signature = tuple(sorted(row.url for row in rows))
            if signature in signatures:
                raise _SourceError("REPEATED_PAGE")
            signatures.add(signature)
            digest = hashlib.sha256(content).hexdigest()
            matches = [row for row in rows if title_matches_query(row.title, normalized)]
            for row in matches:
                candidates.setdefault(
                    row.url,
                    row.model_copy(
                        update={
                            "source_page_url": url,
                            "source_page_number": number,
                            "source_sha256": digest,
                        }
                    ),
                )
            pages.append(
                CatalogPageEvidence(
                    page_number=number,
                    source_url=url,
                    observed_at=datetime.now(UTC),
                    status="COMPLETED",
                    sha256=digest,
                    byte_size=len(content),
                    scanned_count=scanned,
                    matched_count=len(matches),
                    continuation=continuation.status,
                    continuation_evidence=continuation.evidence,
                    continuation_locator=continuation.locator,
                )
            )
            if continuation.status != "NEXT_PAGE":
                stop_reason = (
                    "END_REPORTED" if continuation.status == "END_REPORTED" else "NO_NEXT_EVIDENCE"
                )
                break
        except (httpx.HTTPError, ValueError) as error:
            reason = (
                str(error)
                if isinstance(error, (_SourceError, PaginationError))
                else "PAGE_UNAVAILABLE_OR_CHANGED"
            )
            pages.append(
                CatalogPageEvidence(
                    page_number=number,
                    source_url=url,
                    observed_at=datetime.now(UTC),
                    status="SOURCE_ERROR",
                    error_code=reason,
                )
            )
            stop_reason = reason
            break
    failed = pages[-1].status == "SOURCE_ERROR"
    successful = [page for page in pages if page.status == "COMPLETED"]
    return YandexBusinessAttempt(
        query=normalized,
        category_url=category_page_url(route, 1),
        category_key=route.key,
        site_name=f"Яндекс Маркет для Бизнеса · {route.name}",
        fetch_status=(
            YandexBusinessStatus.PARTIAL if successful else YandexBusinessStatus.SOURCE_ERROR
        )
        if failed
        else YandexBusinessStatus.COMPLETED,
        observed_at=datetime.now(UTC),
        response_sha256=pages[0].sha256,
        response_byte_size=pages[0].byte_size,
        scanned_count=sum(page.scanned_count for page in successful),
        candidates=tuple(candidates.values()),
        pages=tuple(pages),
        stop_reason=stop_reason,
        error_code=pages[-1].error_code,
    )
