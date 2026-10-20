"""Retained-HTML-only bumaga-s-v1 form and product-link adapter."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.sources.supplier_page import (
    MAX_BODY_BYTES,
    DeclaredFact,
    DisplayedPrice,
    PageCapture,
    PageObservation,
    PageReadError,
    ProductObservation,
    validate_page_url,
)
from procurement.sources.supplier_serp import build_supplier_query

HOST = "bumaga-s.ru"
REVISION: Literal["bumaga-s-v1"] = "bumaga-s-v1"
MAX_NODES = 50000
MAX_DEPTH = 128


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CatalogSearchSpec(FrozenModel):
    source_url: str
    query: str = Field(min_length=1, max_length=150)
    raw_action: str = Field(min_length=1, max_length=2048)
    field: Literal["q"] = "q"
    search_url: str = Field(max_length=2048)
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(max_length=200)


class CatalogLink(FrozenModel):
    index: int = Field(ge=1, le=10, strict=True)
    dom_ordinal: int = Field(ge=1, le=MAX_NODES, strict=True)
    title: str = Field(min_length=1, max_length=300)
    raw_href: str = Field(min_length=1, max_length=2048)
    url: str = Field(max_length=2048)
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1, max_length=200)
    technical_status: Literal["UNKNOWN"] = "UNKNOWN"
    price_status: Literal["UNKNOWN"] = "UNKNOWN"


class CatalogLinks(FrozenModel):
    revision: Literal["bumaga-s-v1"] = REVISION
    source_url: str
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["FOUND", "EMPTY", "UNSUPPORTED", "LIMIT_EXCEEDED"]
    links: tuple[CatalogLink, ...] = Field(default=(), max_length=10)
    scanned_count: int = Field(default=0, ge=0, le=MAX_NODES, strict=True)
    returned_count: int = Field(default=0, ge=0, le=10, strict=True)
    truncated: bool = Field(default=False, strict=True)
    coverage: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def consistent(self) -> CatalogLinks:
        if self.returned_count != len(self.links) or self.scanned_count < len(self.links):
            raise ValueError("LINK_COUNT_INVALID")
        if (self.status == "FOUND") != bool(self.links):
            raise ValueError("LINK_STATUS_INVALID")
        if [link.index for link in self.links] != list(range(1, len(self.links) + 1)):
            raise ValueError("LINK_ORDER_INVALID")
        if len({link.url for link in self.links}) != len(self.links):
            raise ValueError("LINK_DUPLICATE")
        if any(
            link.html_sha256 != self.html_sha256
            or _product_url(self.source_url, link.raw_href) != link.url
            for link in self.links
        ):
            raise ValueError("LINK_BINDING_INVALID")
        return self


def _supported_url(url: str) -> bool:
    try:
        return validate_page_url(url) == url and urlsplit(url).hostname == HOST
    except PageReadError:
        return False


def _product_url(source: str, href: str) -> str | None:
    if len(href) > 2048 or not _supported_url(source):
        return None
    try:
        target = validate_page_url(urljoin(source, href))
        parts = urlsplit(target)
        path = unquote(parts.path, errors="strict")
        if parts.hostname != HOST or not path.startswith("/товар/") or len(path) <= len("/товар/"):
            return None
        if any(piece in {".", ".."} for piece in path.split("/")) or "\\" in path:
            return None
        return target
    except (PageReadError, UnicodeError):
        return None


class _Limit(Exception):
    pass


class _CatalogParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.nodes = 0
        self.anchor_ordinal = 0
        self.anchor: tuple[int, str, list[str]] | None = None
        self.links: list[tuple[int, str, str]] = []
        self.forms: list[tuple[int, str, bool]] = []
        self.form: tuple[int, str, bool] | None = None
        self.form_ordinal = 0
        self.has_base = False
        self.malformed = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES or len(self.stack) >= MAX_DEPTH:
            raise _Limit
        values = dict(attrs)
        hidden = (
            any(flag for _, flag in self.stack)
            or tag in {"script", "style", "template", "noscript"}
            or "hidden" in values
            or values.get("aria-hidden") == "true"
            or "display:none" in (values.get("style") or "").replace(" ", "").lower()
            or "visibility:hidden" in (values.get("style") or "").replace(" ", "").lower()
        )
        if tag == "base":
            self.has_base = True
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append((tag, hidden))
        if tag == "a":
            self.anchor_ordinal += 1
            if self.anchor is not None:
                self.malformed = True
            if not hidden:
                self.anchor = (self.anchor_ordinal, values.get("href") or "", [])
        if tag == "form":
            self.form_ordinal += 1
            if self.form is not None:
                self.malformed = True
            if not hidden and (values.get("method") or "get").lower() == "get":
                self.form = (self.form_ordinal, values.get("action") or "", False)
        if (
            tag == "input"
            and not hidden
            and self.form
            and values.get("id") == "global_search"
            and values.get("name") == "q"
            and (values.get("type") or "text").lower() == "text"
            and "disabled" not in values
        ):
            self.form = (self.form[0], self.form[1], True)

    def handle_data(self, data: str) -> None:
        if self.anchor and not any(hidden for _, hidden in self.stack):
            self.anchor[2].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.anchor:
            ordinal, href, text = self.anchor
            self.links.append((ordinal, href, " ".join("".join(text).split())))
            self.anchor = None
        if tag == "form" and self.form:
            self.forms.append(self.form)
            self.form = None
        tags = [item[0] for item in self.stack]
        if tag in tags:
            offset = len(tags) - tags[::-1].index(tag) - 1
            del self.stack[offset:]


def _parse(content: bytes) -> _CatalogParser:
    if type(content) is not bytes or not content or len(content) > MAX_BODY_BYTES:
        raise _Limit
    text = content.decode("utf-8", errors="strict")
    parser = _CatalogParser()
    parser.feed(text)
    parser.close()
    return parser


def build_catalog_search(url: str, content: bytes, public_name: str) -> CatalogSearchSpec | None:
    # Reuse the public-name validation; do not add supplier keywords to internal search.
    build_supplier_query(public_name)
    query = " ".join(public_name.split())
    if not _supported_url(url):
        return None
    try:
        parser = _parse(content)
    except (_Limit, UnicodeError):
        return None
    if parser.has_base or parser.malformed:
        return None
    candidates = []
    for ordinal, action, has_input in parser.forms:
        if not has_input or len(action) > 2048:
            continue
        try:
            resolved = validate_page_url(urljoin(url, action))
        except PageReadError:
            continue
        if resolved != "https://bumaga-s.ru/categories/search":
            continue
        candidates.append(
            CatalogSearchSpec(
                source_url=url,
                query=query,
                raw_action=action,
                search_url=resolved + "?" + urlencode({"q": query}, quote_via=quote),
                html_sha256=hashlib.sha256(content).hexdigest(),
                locator=f'locator("form").nth({ordinal - 1})',
            )
        )
    return candidates[0] if len(candidates) == 1 else None


def parse_catalog_links(url: str, content: bytes) -> CatalogLinks:
    digest = hashlib.sha256(content).hexdigest()

    def result(
        status: Literal["FOUND", "EMPTY", "UNSUPPORTED", "LIMIT_EXCEEDED"],
        links: tuple[CatalogLink, ...] = (),
        scanned: int = 0,
        truncated: bool = False,
    ) -> CatalogLinks:
        return CatalogLinks(
            source_url=url,
            html_sha256=digest,
            status=status,
            links=links,
            scanned_count=scanned,
            returned_count=len(links),
            truncated=truncated or status == "LIMIT_EXCEEDED",
        )

    if not _supported_url(url):
        return result("UNSUPPORTED")
    try:
        parser = _parse(content)
    except _Limit:
        return result("LIMIT_EXCEEDED")
    except UnicodeError:
        return result("UNSUPPORTED")
    if parser.has_base or parser.malformed or parser.anchor is not None:
        return result("UNSUPPORTED")
    links: list[CatalogLink] = []
    seen: set[str] = set()
    truncated = False
    for ordinal, href, title in parser.links:
        target = _product_url(url, href)
        if target is None or not title or target in seen:
            continue
        if len(links) == 10:
            truncated = True
            continue
        if len(title) > 300:
            return result("LIMIT_EXCEEDED", scanned=parser.anchor_ordinal)
        seen.add(target)
        links.append(
            CatalogLink(
                index=len(links) + 1,
                dom_ordinal=ordinal,
                title=title,
                raw_href=href,
                url=target,
                html_sha256=digest,
                locator=f'locator("a").nth({ordinal - 1})',
            )
        )
    return result("FOUND" if links else "EMPTY", tuple(links), parser.anchor_ordinal, truncated)


class _ProductMicrodata(HTMLParser):
    """Closed adapter for one Product span and its directly nested Offer scope."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None, bool]] = []
        self.nodes = 0
        self.products = 0
        self.offers = 0
        self.meta_ordinal = 0
        self.ambiguous = False
        self.facts: dict[str, list[tuple[str, str]]] = {
            "name": [],
            "price": [],
            "priceCurrency": [],
        }

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES or len(self.stack) >= MAX_DEPTH:
            raise _Limit
        values = dict(attrs)
        scope = None
        enclosing = [value for _, value, _ in self.stack if value is not None]
        style = re.sub(r"\s+", "", values.get("style") or "").casefold()
        hidden = (
            any(inert for _, _, inert in self.stack)
            or tag in {"template", "noscript", "script", "style"}
            or "hidden" in values
            or "inert" in values
            or (values.get("aria-hidden") or "").casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        if "itemscope" in values:
            if len(attrs) != len(values):
                self.ambiguous = True
            itemtype = values.get("itemtype") or ""
            scope = "OTHER"
            if itemtype in {"http://schema.org/Product", "https://schema.org/Product"}:
                self.products += 1
                scope = "PRODUCT"
                if tag != "span" or enclosing or hidden:
                    self.ambiguous = True
            elif itemtype in {"http://schema.org/Offer", "https://schema.org/Offer"}:
                scope = "OFFER"
                if hidden or enclosing != ["PRODUCT"] or values.get("itemprop") != "offers":
                    self.ambiguous = True
                else:
                    self.offers += 1
        if tag == "meta":
            self.meta_ordinal += 1
            field = values.get("itemprop") or ""
            expected = ["PRODUCT"] if field == "name" else ["PRODUCT", "OFFER"]
            if field in self.facts and "PRODUCT" in enclosing:
                if (
                    hidden
                    or enclosing != expected
                    or scope is not None
                    or len(attrs) != len(values)
                ):
                    self.ambiguous = True
                else:
                    self.facts[field].append(
                        (
                            values.get("content") or "",
                            f'locator("meta").nth({self.meta_ordinal - 1})@content',
                        )
                    )
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append((tag, scope, hidden))

    def handle_endtag(self, tag: str) -> None:
        tags = [item[0] for item in self.stack]
        if tag not in tags:
            return
        offset = len(tags) - tags[::-1].index(tag) - 1
        if offset != len(tags) - 1 and any(scope for _, scope, _ in self.stack[offset:]):
            self.ambiguous = True
        del self.stack[offset:]


def enrich_catalog_product(capture: PageCapture) -> PageCapture:
    """Read exact retained microdata only; never overwrite JSON-LD observations."""
    observation = capture.observation
    if (
        observation.status != "COMPLETED"
        or observation.extraction_status != "EMPTY"
        or capture.content is None
        or _product_url(observation.final_url, observation.final_url) is None
    ):
        return capture
    parser = _ProductMicrodata()
    extraction: Literal["EXTRACTED", "AMBIGUOUS", "LIMIT_EXCEEDED"] = "AMBIGUOUS"
    products: tuple[ProductObservation, ...] = ()
    try:
        parser.feed(capture.content.decode("utf-8", errors="strict"))
        parser.close()
        if parser.products == 0:
            return capture
        if (
            parser.products == 1
            and parser.offers == 1
            and not parser.ambiguous
            and not any(scope for _, scope, _ in parser.stack)
            and all(len(values) == 1 for values in parser.facts.values())
        ):
            name, name_locator = parser.facts["name"][0]
            raw_price, price_locator = parser.facts["price"][0]
            currency, _ = parser.facts["priceCurrency"][0]
            if (
                name.strip()
                and len(name) <= 500
                and len(raw_price) <= 80
                and re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", raw_price)
                and re.fullmatch(r"[A-Z]{3}", currency)
            ):
                digest = observation.html_sha256
                assert digest is not None
                price = DisplayedPrice(
                    amount=Decimal(raw_price),
                    raw_amount=raw_price,
                    currency=currency,
                    price_kind="EXACT",
                    html_sha256=digest,
                    locator=price_locator,
                )
                declared = DeclaredFact(value=name, html_sha256=digest, locator=name_locator)
                products = (
                    ProductObservation(
                        locator="locator(\"span[itemscope][itemtype$='/Product']\").nth(0)",
                        name=declared,
                        prices=(price,),
                    ),
                )
                extraction = "EXTRACTED"
    except _Limit:
        extraction = "LIMIT_EXCEEDED"
    except (UnicodeError, ValueError, InvalidOperation):
        extraction = "AMBIGUOUS"
    data = observation.model_dump()
    data.update(
        extraction_status=extraction,
        page_kind="PRODUCT" if products else "UNKNOWN",
        products=products,
    )
    return PageCapture(PageObservation.model_validate(data), capture.content)
