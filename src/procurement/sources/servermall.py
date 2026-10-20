"""Read-only поиск названий серверов в одном публичном каталоге ServerMall.

Из структурированного каталога не выводятся exact BOM, наличие или цена
комплекта. HTML сохраняется только в памяти; digest относится к нему, а не
к странице товара. Поддерживается одна фиксированная страница без пагинации.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import cast
from urllib.parse import urlsplit

import httpx

from procurement.domain.sourcing import LeadSourceKind, ServerLead
from procurement.sources.catalog_routes import title_matches_query
from procurement.sources.http_transport import public_source_client

SERVERMALL_HPE_GEN12_URL = "https://servermall.ru/sets/servery-hp-proliant-gen12/"
_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_ITEMS = 50
_MAX_RESULTS = 10


class ServerMallSourceError(ValueError):
    """Недоступный или изменившийся источник остаётся UNKNOWN."""


@dataclass(frozen=True)
class ServerMallObservation:
    """Exact public response bytes and the leads derived only from those bytes."""

    source_url: str
    content: bytes
    sha256: str
    observed_at: datetime
    leads: tuple[ServerLead, ...]


class _JsonLdScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._inside = False
        self._current: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._inside = True
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._inside:
            self._current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside:
            self.scripts.append("".join(self._current))
            self._inside = False


def _catalog_offers(html: bytes) -> list[dict[str, object]]:
    if not html or len(html) > _MAX_HTML_BYTES:
        raise ServerMallSourceError("HTML каталога пуст или превышает лимит")
    parser = _JsonLdScripts()
    try:
        parser.feed(html.decode("utf-8"))
        documents = [json.loads(script) for script in parser.scripts]
    except (UnicodeDecodeError, ValueError) as error:
        raise ServerMallSourceError("структурированные данные каталога повреждены") from error
    catalogs = [
        node
        for document in documents
        if isinstance(document, dict) and isinstance(document.get("@graph"), list)
        for node in document["@graph"]
        if isinstance(node, dict) and node.get("@type") == "OfferCatalog"
    ]
    if len(catalogs) != 1 or not isinstance(catalogs[0].get("itemListElement"), list):
        raise ServerMallSourceError("ожидался один OfferCatalog")
    offers = catalogs[0]["itemListElement"]
    if not 0 < len(offers) <= _MAX_ITEMS or not all(isinstance(item, dict) for item in offers):
        raise ServerMallSourceError("число или форма карточек не поддерживается")
    return cast(list[dict[str, object]], offers)


def parse_servermall_hpe_gen12(
    html: bytes, *, query: str, observed_at: datetime
) -> tuple[ServerLead, ...]:
    """Найти совпадения по названию; не интерпретировать комплектацию."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ServerMallSourceError("observed_at должен содержать часовой пояс")
    terms = query.casefold().split()
    if not 1 <= len(terms) <= 5 or len(query) > 80:
        raise ServerMallSourceError("поисковая строка должна содержать 1–5 слов")
    digest = hashlib.sha256(html).hexdigest()
    leads: list[ServerLead] = []
    seen_urls: set[str] = set()
    for offer in _catalog_offers(html):
        if offer.get("@type") != "Offer":
            raise ServerMallSourceError("неожиданный тип карточки")
        name, url = offer.get("name"), offer.get("url")
        if not isinstance(name, str) or not name.strip() or not isinstance(url, str):
            raise ServerMallSourceError("у карточки нет названия или ссылки")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "servermall.ru"
            or not parsed.path.startswith("/catalog/servers/")
            or not parsed.path.endswith("/")
            or parsed.query
            or parsed.fragment
            or url in seen_urls
        ):
            raise ServerMallSourceError("недопустимая или повторная ссылка карточки")
        seen_urls.add(url)
        if title_matches_query(name, query):
            leads.append(
                ServerLead(
                    lead_id=url,
                    supplier="ServerMall",
                    manufacturer="HPE",
                    source_kind=LeadSourceKind.SUPPLIER_CATALOG,
                    product_name=name.strip(),
                    source_url=SERVERMALL_HPE_GEN12_URL,
                    product_url=url,
                    source_sha256=digest,
                    observed_at=observed_at,
                )
            )
    return tuple(leads[:_MAX_RESULTS])


def fetch_servermall_hpe_gen12(query: str) -> ServerMallObservation:
    """Получить один exact snapshot и вывести из него только названия и URL."""
    terms = query.casefold().split()
    if not 1 <= len(terms) <= 5 or len(query) > 80:
        raise ServerMallSourceError("поисковая строка должна содержать 1–5 слов")
    try:
        with (
            public_source_client() as client,
            client.stream("GET", SERVERMALL_HPE_GEN12_URL) as response,
        ):
            if response.status_code != 200 or "text/html" not in response.headers.get(
                "content-type", ""
            ):
                raise ServerMallSourceError("каталог не вернул HTML 200")
            parts: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > _MAX_HTML_BYTES:
                    raise ServerMallSourceError("ответ каталога превышает лимит")
                parts.append(chunk)
    except httpx.HTTPError as error:
        raise ServerMallSourceError("каталог недоступен") from error
    content = b"".join(parts)
    observed_at = datetime.now(UTC)
    return ServerMallObservation(
        source_url=SERVERMALL_HPE_GEN12_URL,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        observed_at=observed_at,
        leads=parse_servermall_hpe_gen12(content, query=query, observed_at=observed_at),
    )


def search_servermall_hpe_gen12(query: str) -> tuple[ServerLead, ...]:
    """Совместимый read-only вход для потребителей, которым не нужен snapshot."""
    return fetch_servermall_hpe_gen12(query).leads
