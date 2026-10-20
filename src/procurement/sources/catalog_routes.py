"""Проверенные категории, ограниченные URL страниц и лексический поиск названий."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qsl, urljoin, urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

MAX_CATEGORY_PAGES = 2


@dataclass(frozen=True)
class CategoryRoute:
    key: str
    name: str
    url: str
    hid: str
    pattern: str


YANDEX_CATEGORIES = (
    CategoryRoute(
        "pumps",
        "Насосы и комплектующие",
        "https://business.market.yandex.ru/catalog--nasosy-i-komplektuiushchie/18060427/list",
        "15774673",
        r"\bнасос[а-яё]*\b",
    ),
    CategoryRoute(
        "laptops",
        "Ноутбуки",
        "https://business.market.yandex.ru/catalog--noutbuki/40998496/list",
        "91013",
        r"\bноутбук[а-яё]*\b",
    ),
    CategoryRoute(
        "printers",
        "Принтеры и МФУ",
        "https://business.market.yandex.ru/catalog--printery-i-mfu/41000270/list",
        "138608",
        r"\b(?:принтер[а-яё]*|мфу)\b",
    ),
)


class CatalogPageEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: int = Field(ge=1, le=MAX_CATEGORY_PAGES)
    source_url: str
    observed_at: AwareDatetime
    status: Literal["COMPLETED", "SOURCE_ERROR"]
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    byte_size: int | None = None
    scanned_count: int = 0
    matched_count: int = 0
    error_code: str | None = None
    continuation: Literal["NEXT_PAGE", "END_REPORTED", "UNKNOWN"] = "UNKNOWN"
    continuation_evidence: Literal["LINK", "PAGE_STATE", "LINK_AND_PAGE_STATE"] | None = None
    continuation_locator: str | None = None


def yandex_route(query: str) -> CategoryRoute | None:
    found = [route for route in YANDEX_CATEGORIES if re.search(route.pattern, query, re.I)]
    return found[0] if len(found) == 1 else None


def servermall_covers(query: str) -> bool:
    if re.search(
        r"\b(?:dell|lenovo|supermicro|graviton|гравитон|depo)\b|\bgen\s*(?:10|11)\b", query, re.I
    ):
        return False
    return bool(re.search(r"\b(?:сервер[а-яё]*|hpe|proliant|dl360|dl380)\b", query, re.I))


def category_page_url(route: CategoryRoute, number: int) -> str:
    if not 1 <= number <= MAX_CATEGORY_PAGES:
        raise ValueError("category page outside approved budget")
    first = f"{route.url}?hid={route.hid}"
    return first if number == 1 else f"{first}&page={number}"


def category_navigation_allowed(route: CategoryRoute, url: str, number: int = 1) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.fragment or parsed._replace(query="").geturl() != route.url:
            return False
        pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=3)
    except ValueError:
        return False
    values = dict(pairs)
    return (
        len(values) == len(pairs)
        and set(values) <= {"hid", "rs", "page"}
        and values.get("hid", route.hid) == route.hid
        and values.get("page", "1") == str(number)
        and (not values or "hid" in values or set(values) == {"page"})
        and len(values.get("rs", "")) <= 2048
        and all(ord(c) >= 32 for c in values.get("rs", ""))
    )


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href")
        if tag in {"a", "link"} and href:
            self.hrefs.append(href)


def has_next_category_page(content: bytes, route: CategoryRoute, number: int) -> bool:
    """Наличие ссылки на следующую страницу; её URL не становится командой."""
    parser = _Links()
    parser.feed(content.decode("utf-8"))
    for href in parser.hrefs:
        if category_navigation_allowed(route, urljoin(route.url, href), number + 1):
            return True
    return False


def title_matches_query(title: str, query: str) -> bool:
    """Все слова запроса должны встречаться в названии; это не hard gate ТЗ.

    Нормализуются только известные товарные существительные, не характеристики.
    """

    def tokens(value: str) -> set[str]:
        words = re.findall(r"[\w]+", value.casefold().replace("ё", "е"))
        return {
            "насос"
            if re.fullmatch(r"насос(?:ы|а|ов|ом|у|е)?", word)
            else "ноутбук"
            if re.fullmatch(r"ноутбук(?:и|а|ов|ом|у|е)?", word)
            else "принтер"
            if re.fullmatch(r"принтер(?:ы|а|ов|ом|у|е)?", word)
            else "пк"
            if re.fullmatch(r"компьютер(?:ы|а|ов|ом|у|е)?", word)
            else word
            for word in words
        }

    requested = tokens(query)
    return bool(requested) and requested <= tokens(title)
