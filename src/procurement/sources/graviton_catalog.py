"""Ограниченный набор публичных категорий производителя; карточки не являются КП."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from procurement.sources.catalog_routes import title_matches_query
from procurement.sources.eaeu_registry import _validated_query
from procurement.sources.http_transport import public_source_client

GRAVITON_SERVERS_URL = "https://graviton.ru/catalog/servery-i-khranenie-dannykh/servery/"
_MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class GravitonRoute:
    key: str
    name: str
    url: str
    pattern: str


GRAVITON_ROUTES = (
    GravitonRoute("servers", "серверы", GRAVITON_SERVERS_URL, r"\bсервер[а-яё]*\b"),
    GravitonRoute(
        "laptops", "ноутбуки",
        "https://graviton.ru/catalog/klientskie-ustroystva/noutbuki/",
        r"\bноутбук[а-яё]*\b",
    ),
    GravitonRoute(
        "printers", "принтеры и МФУ",
        "https://graviton.ru/catalog/klientskie-ustroystva/printery/",
        r"\b(?:принтер[а-яё]*|мфу)\b",
    ),
    GravitonRoute(
        "pcs", "ПК",
        "https://graviton.ru/catalog/klientskie-ustroystva/pk/",
        r"\b(?:пк|компьютер[а-яё]*)\b",
    ),
)


class GravitonCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2048)
    source_item_index: int = Field(ge=1, le=100)
    manufacturer_claim: Literal["Гравитон"] = "Гравитон"
    suitability: Literal["UNKNOWN"] = "UNKNOWN"


class GravitonAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: Literal["graviton_catalog"] = "graviton_catalog"
    site_name: str = "Гравитон · каталог"
    category_key: Literal["servers", "laptops", "printers", "pcs"] | None = None
    query: str
    source_url: str = GRAVITON_SERVERS_URL
    fetch_status: Literal["COMPLETED", "SOURCE_ERROR", "QUERY_NOT_COVERED"]
    observed_at: AwareDatetime
    parser_version: Literal["graviton-catalog-v2"] = "graviton-catalog-v2"
    coverage: Literal["ONE_CATEGORY_PAGE_ONLY"] = "ONE_CATEGORY_PAGE_ONLY"
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    response_byte_size: int | None = None
    scanned_count: int | None = None
    error_code: str | None = None
    candidates: tuple[GravitonCandidate, ...] = ()


def graviton_route(query: str) -> GravitonRoute | None:
    if re.search(r"\b(?:hpe|hp|dell|lenovo|supermicro|proliant|depo)\b", query, re.I):
        return None
    found = [route for route in GRAVITON_ROUTES if re.search(route.pattern, query, re.I)]
    return found[0] if len(found) == 1 else None


def graviton_covers(query: str) -> bool:
    return graviton_route(query) is not None


class _Catalog(HTMLParser):
    def __init__(self, route: GravitonRoute) -> None:
        super().__init__()
        self.route = route
        self.list_depth = 0
        self.lists = 0
        self.href: str | None = None
        self.in_title = False
        self.title_count = 0
        self.title: list[str] = []
        self.rows: list[GravitonCandidate] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "ul":
            if "catalog__list" in classes:
                self.lists += 1
                if self.lists != 1:
                    raise ValueError("CATALOG_SCHEMA_CHANGED")
                self.list_depth = 1
            elif self.list_depth:
                self.list_depth += 1
        if not self.list_depth:
            return
        if tag == "a" and "catalog-item" in classes:
            if self.href is not None or not values.get("href"):
                raise ValueError("CATALOG_SCHEMA_CHANGED")
            self.href = values["href"]
            self.title = []
            self.title_count = 0
        if self.href is not None and "catalog-item__title" in classes:
            if tag != "p" or self.in_title:
                raise ValueError("CATALOG_SCHEMA_CHANGED")
            self.in_title = True
            self.title_count += 1

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            self.in_title = False
        if tag == "a" and self.href is not None:
            title = " ".join("".join(self.title).split())
            url = urljoin(self.route.url, self.href)
            parsed = urlsplit(url)
            prefix = urlsplit(self.route.url).path
            if (
                self.in_title
                or self.title_count != 1
                or not 1 <= len(title) <= 300
                or parsed.scheme != "https"
                or parsed.netloc != "graviton.ru"
                or parsed.query
                or parsed.fragment
                or not parsed.path.startswith(prefix)
                or not re.fullmatch(r"[a-z0-9_-]+/", parsed.path[len(prefix) :])
                or len(self.rows) >= 100
                or any(row.url == url for row in self.rows)
            ):
                raise ValueError("CATALOG_SCHEMA_CHANGED")
            self.rows.append(
                GravitonCandidate(
                    title=title,
                    url=url,
                    source_item_index=len(self.rows) + 1,
                )
            )
            self.href = None
        if tag == "ul" and self.list_depth:
            self.list_depth -= 1
            if not self.list_depth and self.href is not None:
                raise ValueError("CATALOG_SCHEMA_CHANGED")


def parse_graviton_catalog(
    content: bytes, route: GravitonRoute = GRAVITON_ROUTES[0]
) -> tuple[GravitonCandidate, ...]:
    """Только основная категория; меню, рекомендации и характеристики не читаются."""
    if not 0 < len(content) <= _MAX_BYTES:
        raise ValueError("CATALOG_SIZE_INVALID")
    parser = _Catalog(route)
    parser.feed(content.decode("utf-8"))
    parser.close()
    if parser.lists != 1 or parser.list_depth or parser.href is not None or not parser.rows:
        raise ValueError("CATALOG_SCHEMA_CHANGED")
    return tuple(parser.rows)


def search_graviton_catalog(query: str) -> GravitonAttempt:
    normalized = " ".join(_validated_query(query))
    route = graviton_route(normalized)
    base = GravitonAttempt(
        query=normalized, fetch_status="QUERY_NOT_COVERED", observed_at=datetime.now(UTC),
        site_name=f"Гравитон · {route.name}" if route else "Гравитон · каталог",
        category_key=route.key if route else None,
        source_url=route.url if route else GRAVITON_SERVERS_URL,
    )
    if route is None:
        return base
    try:
        with (
            public_source_client() as client,
            client.stream("GET", route.url) as response,
        ):
            if response.status_code != 200 or "text/html" not in response.headers.get(
                "content-type", ""
            ):
                raise ValueError("CATALOG_UNAVAILABLE")
            parts: list[bytes] = []
            size = 0
            for part in response.iter_bytes():
                size += len(part)
                if size > _MAX_BYTES:
                    raise ValueError("CATALOG_SIZE_INVALID")
                parts.append(part)
        content = b"".join(parts)
        rows = parse_graviton_catalog(content, route)
        return base.model_copy(
            update={
                "fetch_status": "COMPLETED",
                "observed_at": datetime.now(UTC),
                "response_sha256": hashlib.sha256(content).hexdigest(),
                "response_byte_size": len(content),
                "scanned_count": len(rows),
                "candidates": tuple(
                    row for row in rows if title_matches_query(row.title, normalized)
                ),
            }
        )
    except (httpx.HTTPError, ValueError):
        return base.model_copy(
            update={
                "fetch_status": "SOURCE_ERROR",
                "observed_at": datetime.now(UTC),
                "error_code": "CATALOG_UNAVAILABLE_OR_CHANGED",
            }
        )
