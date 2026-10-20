"""Одна публичная серверная категория DEPO: только названия и ссылки моделей."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from procurement.sources.catalog_routes import title_matches_query
from procurement.sources.eaeu_registry import _validated_query
from procurement.sources.http_transport import public_source_client

DEPO_SERVERS_URL = "https://www.depo.ru/catalog/servery/"
_MAX_BYTES = 2 * 1024 * 1024
_PRODUCT_PATH = re.compile(r"/catalog/servery/[a-z0-9-]+/[a-z0-9-]+/")


class DepoCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=2048)
    source_item_index: int = Field(ge=1, le=100)
    manufacturer_claim: Literal["DEPO"] = "DEPO"
    suitability: Literal["UNKNOWN"] = "UNKNOWN"


class DepoAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: Literal["depo_servers"] = "depo_servers"
    site_name: str = "DEPO · серверы (одна публичная категория)"
    query: str
    source_url: str = DEPO_SERVERS_URL
    fetch_status: Literal["COMPLETED", "SOURCE_ERROR", "QUERY_NOT_COVERED"]
    observed_at: AwareDatetime
    parser_version: Literal["depo-servers-v1"] = "depo-servers-v1"
    coverage: Literal["ONE_CATEGORY_PAGE_ONLY"] = "ONE_CATEGORY_PAGE_ONLY"
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    response_byte_size: int | None = None
    scanned_count: int | None = None
    error_code: str | None = None
    candidates: tuple[DepoCandidate, ...] = ()


def depo_covers(query: str) -> bool:
    if re.search(r"\b(?:hpe|hp|dell|lenovo|supermicro|proliant|гравитон|graviton)\b", query, re.I):
        return False
    return bool(re.search(r"\bсервер[а-яё]*\b", query, re.I))


class _Catalog(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.list_depth = 0
        self.list_count = 0
        self.item_depth = 0
        self.name_depth = 0
        self.name_anchor = False
        self.name_count = 0
        self.name_href: str | None = None
        self.title: list[str] = []
        self.rows: list[DepoCandidate] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "div":
            if self.list_depth:
                self.list_depth += 1
            elif "block-servers__list" in classes:
                self.list_depth = 1
                self.list_count += 1
            if self.item_depth:
                self.item_depth += 1
            elif self.list_depth and "block-servers__item" in classes:
                self.item_depth = 1
                self.name_count = 0
                self.name_href = None
                self.title = []
            if self.item_depth and "block-servers__name" in classes:
                if self.name_depth:
                    raise ValueError("CATALOG_SCHEMA_CHANGED")
                self.name_depth = self.item_depth
                self.name_count += 1
        elif tag == "a" and self.name_depth:
            if self.name_anchor or self.name_href is not None or not values.get("href"):
                raise ValueError("CATALOG_SCHEMA_CHANGED")
            self.name_anchor = True
            self.name_href = values["href"]

    def handle_data(self, data: str) -> None:
        if self.name_anchor:
            self.title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.name_anchor:
            self.name_anchor = False
        if tag != "div":
            return
        if self.name_depth and self.name_depth == self.item_depth:
            self.name_depth = 0
        if self.item_depth:
            self.item_depth -= 1
            if not self.item_depth:
                self._finish_item()
        if self.list_depth:
            self.list_depth -= 1

    def _finish_item(self) -> None:
        title = " ".join("".join(self.title).split())
        url = urljoin(DEPO_SERVERS_URL, self.name_href or "")
        parsed = urlsplit(url)
        if (
            self.name_anchor
            or self.name_depth
            or self.name_count != 1
            or not 1 <= len(title) <= 300
            or parsed.scheme != "https"
            or parsed.netloc != "www.depo.ru"
            or parsed.query
            or parsed.fragment
            or not _PRODUCT_PATH.fullmatch(parsed.path)
            or len(self.rows) >= 100
            or any(row.url == url for row in self.rows)
        ):
            raise ValueError("CATALOG_SCHEMA_CHANGED")
        self.rows.append(DepoCandidate(title=title, url=url, source_item_index=len(self.rows) + 1))


def parse_depo_catalog(content: bytes) -> tuple[DepoCandidate, ...]:
    """Читает только блоки карточек внутри основного списка серверной категории."""
    if not 0 < len(content) <= _MAX_BYTES:
        raise ValueError("CATALOG_SIZE_INVALID")
    parser = _Catalog()
    parser.feed(content.decode("utf-8"))
    parser.close()
    if parser.list_count < 1 or parser.list_depth or parser.item_depth or not parser.rows:
        raise ValueError("CATALOG_SCHEMA_CHANGED")
    return tuple(parser.rows)


def search_depo_catalog(query: str) -> DepoAttempt:
    normalized = " ".join(_validated_query(query))
    base = DepoAttempt(
        query=normalized, fetch_status="QUERY_NOT_COVERED", observed_at=datetime.now(UTC)
    )
    if not depo_covers(normalized):
        return base
    try:
        with public_source_client() as client, client.stream("GET", DEPO_SERVERS_URL) as response:
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
        rows = parse_depo_catalog(content)
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
    except (httpx.HTTPError, ValueError, UnicodeError):
        return base.model_copy(
            update={
                "fetch_status": "SOURCE_ERROR",
                "observed_at": datetime.now(UTC),
                "error_code": "CATALOG_UNAVAILABLE_OR_CHANGED",
            }
        )
