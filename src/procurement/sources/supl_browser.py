"""Строгий разбор одной публичной категории предложений Supl.biz из DOM."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

SUPL_PUMPS_URL = "https://supl.biz/promyishlennyie-nasosyi-category4240/"
_PRODUCT_ID = re.compile(r"proposal-preview-\d+")
_PRODUCT_PATH = re.compile(r"/[a-z0-9-]+-p\d+/")
_SELLER_PATH = re.compile(r"/profiles/\d+/")
_MAX_BYTES = 3 * 1024 * 1024


@dataclass(frozen=True)
class SuplListing:
    title: str
    url: str
    seller_name: str
    seller_url: str
    source_item_index: int


def supl_covers(query: str) -> bool:
    """Только насосы; поиск площадки и произвольные категории не вызываются."""
    return bool(re.search(r"\bнасос[а-яё]*\b", query, re.I))


class _Catalog(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.section_depth = 0
        self.product_count = 0
        self.title_link = False
        self.seller_link = False
        self.title_href: str | None = None
        self.seller_href: str | None = None
        self.title: list[str] = []
        self.seller_name: list[str] = []
        self.rows: list[SuplListing] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "section":
            if self.section_depth:
                self.section_depth += 1
            elif (
                values.get("itemtype") == "http://schema.org/Product"
                and _PRODUCT_ID.fullmatch(values.get("id") or "")
            ):
                self.section_depth = 1
                self.product_count += 1
                self.title_href = None
                self.seller_href = None
                self.title = []
                self.seller_name = []
        if tag != "a" or not self.section_depth:
            return
        href = values.get("href")
        if values.get("itemprop") == "url":
            if self.title_href is not None or not href:
                raise ValueError("CATALOG_SCHEMA_CHANGED")
            self.title_href = href
            self.title_link = True
        elif href and _SELLER_PATH.fullmatch(urlsplit(urljoin(SUPL_PUMPS_URL, href)).path):
            if self.seller_href is not None:
                raise ValueError("CATALOG_SCHEMA_CHANGED")
            self.seller_href = href
            self.seller_link = True

    def handle_data(self, data: str) -> None:
        if self.title_link:
            self.title.append(data)
        if self.seller_link:
            self.seller_name.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.title_link = False
            self.seller_link = False
        if tag == "section" and self.section_depth:
            self.section_depth -= 1
            if not self.section_depth:
                self._finish_product()

    def _finish_product(self) -> None:
        title = " ".join("".join(self.title).split())
        seller_name = " ".join("".join(self.seller_name).split())
        url = urljoin(SUPL_PUMPS_URL, self.title_href or "")
        seller_url = urljoin(SUPL_PUMPS_URL, self.seller_href or "")
        product = urlsplit(url)
        seller = urlsplit(seller_url)
        if (
            self.title_link or self.seller_link
            or ".." in urlsplit(self.title_href or "").path
            or "%" in (self.title_href or "")
            or ".." in urlsplit(self.seller_href or "").path
            or "%" in (self.seller_href or "")
            or not 1 <= len(title) <= 300
            or not 1 <= len(seller_name) <= 200
            or product.scheme != "https" or product.netloc != "supl.biz"
            or seller.scheme != "https" or seller.netloc != "supl.biz"
            or product.query or product.fragment or seller.query or seller.fragment
            or not _PRODUCT_PATH.fullmatch(product.path)
            or not _SELLER_PATH.fullmatch(seller.path)
            or len(self.rows) >= 100
            or any(row.url == url for row in self.rows)
        ):
            raise ValueError("CATALOG_SCHEMA_CHANGED")
        self.rows.append(SuplListing(title, url, seller_name, seller_url, len(self.rows) + 1))


def parse_supl_catalog(content: bytes) -> tuple[SuplListing, ...]:
    if not 0 < len(content) <= _MAX_BYTES:
        raise ValueError("CATALOG_SIZE_INVALID")
    parser = _Catalog()
    parser.feed(content.decode("utf-8"))
    parser.close()
    if parser.section_depth or not parser.product_count or not parser.rows:
        raise ValueError("CATALOG_SCHEMA_CHANGED")
    if parser.product_count != len(parser.rows):
        raise ValueError("CATALOG_SCHEMA_CHANGED")
    return tuple(parser.rows)
