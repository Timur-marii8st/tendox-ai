"""Fixed-category supplier price observations; never configured quotes or compliance facts."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.catalog_routes import servermall_covers, title_matches_query
from procurement.sources.servermall import (
    SERVERMALL_HPE_GEN12_URL,
    ServerMallObservation,
    ServerMallSourceError,
    _catalog_offers,
    fetch_servermall_hpe_gen12,
)

SUPPLIER_CATALOG_POLICY: Literal["eis-supplier-catalog-v1"] = "eis-supplier-catalog-v1"
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_LEADS = 10
MAX_HTML_DEPTH = 64
MAX_HTML_NODES = 20_000
MAX_CARDS = 100
MAX_CARD_TEXT = 32_000
Unknown = Literal["UNKNOWN"]
PriceKind = Literal["BASE_PRICE_FROM", "PRICE_FROM", "LEASE_MONTHLY"]


class SupplierCatalogModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SupplierCatalogSourceError(ValueError):
    """The fixed public source cannot produce a bounded trustworthy observation."""


class PublishedSupplierPrice(SupplierCatalogModel):
    kind: PriceKind
    amount_rub: Decimal
    raw_label: str = Field(min_length=1, max_length=300)
    provenance: Provenance
    configured_unit_cost: Unknown = "UNKNOWN"
    quote_status: Unknown = "UNKNOWN"
    tax_status: Unknown = "UNKNOWN"

    @field_validator("amount_rub", mode="before")
    @classmethod
    def exact_decimal(cls, value: object) -> object:
        if isinstance(value, (float, bool)):
            raise ValueError("SUPPLIER_PRICE_INEXACT")
        return value

    @field_validator("amount_rub")
    @classmethod
    def bounded_decimal(cls, value: Decimal) -> Decimal:
        exponent = value.as_tuple().exponent
        if (
            not value.is_finite()
            or value <= 0
            or len(value.as_tuple().digits) > 18
            or not isinstance(exponent, int)
        ):
            raise ValueError("SUPPLIER_PRICE_INVALID")
        if abs(exponent) > 2:
            raise ValueError("SUPPLIER_PRICE_INVALID")
        return value


class SupplierCatalogLead(SupplierCatalogModel):
    supplier: Literal["ServerMall"] = "ServerMall"
    manufacturer: Literal["HPE"] = "HPE"
    product_name: str = Field(min_length=1, max_length=500)
    product_url: str = Field(min_length=1, max_length=2_000)
    name_provenance: Provenance
    price_status: Literal["PUBLISHED", "UNKNOWN"]
    published_prices: tuple[PublishedSupplierPrice, ...] = Field(max_length=3)
    stock: Unknown = "UNKNOWN"
    delivery: Unknown = "UNKNOWN"
    compliance: Unknown = "UNKNOWN"
    participation: Unknown = "UNKNOWN"

    @model_validator(mode="after")
    def consistent_prices(self) -> SupplierCatalogLead:
        kinds = [price.kind for price in self.published_prices]
        if len(set(kinds)) != len(kinds):
            raise ValueError("SUPPLIER_PRICE_KIND_DUPLICATE")
        if (self.price_status == "PUBLISHED") != bool(self.published_prices):
            raise ValueError("SUPPLIER_PRICE_STATUS_INVALID")
        return self


class SupplierCatalogObservation(SupplierCatalogModel):
    policy_version: Literal["eis-supplier-catalog-v1"] = SUPPLIER_CATALOG_POLICY
    source_url: Literal["https://servermall.ru/sets/servery-hp-proliant-gen12/"] = (
        "https://servermall.ru/sets/servery-hp-proliant-gen12/"
    )
    observed_at: AwareDatetime
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(ge=1, le=MAX_HTML_BYTES, strict=True)
    query: str = Field(min_length=1, max_length=80)
    leads: tuple[SupplierCatalogLead, ...] = Field(max_length=MAX_LEADS)
    scanned_count: int = Field(ge=1, le=50, strict=True)
    matched_count: int = Field(ge=0, le=50, strict=True)
    returned_count: int = Field(ge=0, le=MAX_LEADS, strict=True)
    truncated: bool = Field(strict=True)
    scope: Literal["ONE_CATEGORY_PAGE_ONLY"] = "ONE_CATEGORY_PAGE_ONLY"
    source_requests: Literal[1] = 1
    coverage: Unknown = "UNKNOWN"
    tax: Unknown = "UNKNOWN"
    stock: Unknown = "UNKNOWN"
    delivery: Unknown = "UNKNOWN"
    compliance: Unknown = "UNKNOWN"
    participation: Unknown = "UNKNOWN"

    @model_validator(mode="after")
    def exact_source_binding(self) -> SupplierCatalogObservation:
        if (
            self.matched_count > self.scanned_count
            or self.returned_count != len(self.leads)
            or self.returned_count != min(self.matched_count, MAX_LEADS)
            or self.truncated != (self.matched_count > self.returned_count)
        ):
            raise ValueError("SUPPLIER_COUNTS_INVALID")
        seen: set[str] = set()
        for lead in self.leads:
            if lead.product_url in seen or not _valid_product_url(lead.product_url):
                raise ValueError("SUPPLIER_PRODUCT_URL_INVALID")
            seen.add(lead.product_url)
            facts = (
                lead.name_provenance,
                *(price.provenance for price in lead.published_prices),
            )
            if any(fact.document_id != self.source_sha256 for fact in facts):
                raise ValueError("SUPPLIER_PROVENANCE_MISMATCH")
        return self


@dataclass(frozen=True)
class SupplierCatalogCapture:
    observation: SupplierCatalogObservation
    content: bytes

    def __post_init__(self) -> None:
        if (
            type(self.content) is not bytes
            or len(self.content) != self.observation.byte_count
            or hashlib.sha256(self.content).hexdigest() != self.observation.source_sha256
        ):
            raise SupplierCatalogSourceError("SUPPLIER_CAPTURE_MISMATCH")


class _Card:
    def __init__(self, locator: str) -> None:
        self.locator = locator
        self.depth = 0
        self.text: list[str] = []
        self.text_characters = 0
        self.urls: list[str] = []
        self.price_depth = 0
        self.price_branch_seen = False
        self.price_label_depth = 0
        self.price_label_branches = 0
        self.price_label_text: list[str] = []


class _VisibleCards(HTMLParser):
    _VOID = frozenset(
        {
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
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self.cards: list[_Card] = []
        self.active: list[_Card] = []
        self.suppressed_depth = 0
        self.element_depth = 0
        self.nodes = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.nodes += 1
        if self.nodes > MAX_HTML_NODES:
            raise ValueError("SUPPLIER_HTML_NODES_LIMIT")
        if tag not in self._VOID:
            self.element_depth += 1
            if self.element_depth > MAX_HTML_DEPTH:
                raise ValueError("SUPPLIER_HTML_DEPTH_LIMIT")
        attributes = dict(attrs)
        hidden = (
            tag in {"script", "style", "template"}
            or "hidden" in attributes
            or (attributes.get("aria-hidden") or "").casefold() == "true"
            or "display:none" in (attributes.get("style") or "").replace(" ", "").casefold()
        )
        if self.suppressed_depth and tag not in self._VOID:
            self.suppressed_depth += 1
        elif hidden and tag not in self._VOID:
            self.suppressed_depth = 1
        class_tokens = (attributes.get("class") or "").casefold().split()
        if not self.suppressed_depth and tag in {"article", "li", "div"} and any(
            token in {"product-card", "catalog-item", "product-item"}
            for token in class_tokens
        ):
            if len(self.cards) >= MAX_CARDS:
                raise ValueError("SUPPLIER_HTML_CARDS_LIMIT")
            card = _Card(f"html/{tag}.product-card[{len(self.cards) + 1}]")
            self.cards.append(card)
            self.active.append(card)
        if tag not in self._VOID:
            for card in self.active:
                card.depth += 1
            if self.active and self.active[-1].price_depth:
                self.active[-1].price_depth += 1
            if self.active and self.active[-1].price_label_depth:
                self.active[-1].price_label_depth += 1
        if (
            self.active
            and not self.suppressed_depth
            and "product-card__price-vat" in class_tokens
        ):
            card = self.active[-1]
            if card.price_branch_seen:
                raise ValueError("SUPPLIER_PRICE_BRANCH_AMBIGUOUS")
            card.price_branch_seen = True
            card.price_depth = 1
        if (
            self.active
            and not self.suppressed_depth
            and "list-price-title" in class_tokens
        ):
            card = self.active[-1]
            card.price_label_branches += 1
            card.price_label_depth = 1
        href = attributes.get("href")
        if (
            self.active
            and not self.suppressed_depth
            and tag == "a"
            and isinstance(href, str)
        ):
            canonical = _canonical_product_url(href)
            if canonical is not None:
                self.active[-1].urls.append(canonical)

    def handle_data(self, data: str) -> None:
        if not self.suppressed_depth and self.active:
            card = self.active[-1]
            if card.text_characters + len(data) > MAX_CARD_TEXT:
                raise ValueError("SUPPLIER_CARD_TEXT_LIMIT")
            card.text_characters += len(data)
            if card.price_depth:
                card.text.append(data)
            if card.price_label_depth:
                card.price_label_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._VOID:
            return
        for card in self.active:
            card.depth -= 1
        if self.active and self.active[-1].price_depth:
            self.active[-1].price_depth -= 1
        if self.active and self.active[-1].price_label_depth:
            self.active[-1].price_label_depth -= 1
        self.active = [card for card in self.active if card.depth > 0]
        if self.suppressed_depth:
            self.suppressed_depth -= 1
        if self.element_depth:
            self.element_depth -= 1


_PRICE_PATTERNS: tuple[tuple[PriceKind, re.Pattern[str]], ...] = (
    (
        "BASE_PRICE_FROM",
        re.compile(
            r"Цена\s+базы\s*:\s*от\s*([0-9][0-9\s\u00a0]*)\s*₽"
            r"(?!\s*(?:/\s*мес|в\s+месяц))",
            re.I,
        ),
    ),
    (
        "PRICE_FROM",
        re.compile(
            r"(?<!базы\s)Цена\s*:\s*от\s*([0-9][0-9\s\u00a0]*)\s*₽(?!\s*(?:/\s*мес|в\s+месяц))",
            re.I,
        ),
    ),
    (
        "LEASE_MONTHLY",
        re.compile(
            r"(?:аренд\w*\s*:?\s*|от\s*)?([0-9][0-9\s\u00a0]*)\s*₽\s*"
            r"(?:/\s*мес(?:\s+в\s+лизинг)?|в\s+месяц)",
            re.I,
        ),
    ),
)


def _valid_product_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "servermall.ru"
        and parsed.path.startswith("/catalog/servers/")
        and parsed.path.endswith("/")
        and not parsed.query
        and not parsed.fragment
    )


def _canonical_product_url(url: str) -> str | None:
    if url.startswith("/catalog/servers/"):
        url = "https://servermall.ru" + url
    return url if _valid_product_url(url) else None


def _visible_cards(html: bytes) -> tuple[_Card, ...]:
    parser = _VisibleCards()
    try:
        parser.feed(html.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise SupplierCatalogSourceError("SUPPLIER_SOURCE_MISMATCH") from error
    return tuple(parser.cards)


def _card_prices(
    cards: tuple[_Card, ...], product_url: str, digest: str
) -> tuple[PublishedSupplierPrice, ...]:
    matching = [card for card in cards if set(card.urls) == {product_url}]
    if len(matching) != 1:
        return ()
    card = matching[0]
    amount_text = " ".join(" ".join(card.text).split())
    label_text = " ".join(" ".join(card.price_label_text).split())
    text = f"{label_text} {amount_text}" if card.price_label_branches == 1 else amount_text
    observed: list[PublishedSupplierPrice] = []
    for kind, pattern in _PRICE_PATTERNS:
        matches = list(pattern.finditer(text))
        if len(matches) > 1:
            return ()
        if not matches:
            continue
        if kind != "LEASE_MONTHLY" and card.price_label_branches != 1:
            continue
        match = matches[0]
        digits = re.sub(r"[\s\u00a0]", "", match.group(1))
        if not digits.isdecimal():
            return ()
        try:
            observed.append(
                PublishedSupplierPrice(
                    kind=kind,
                    amount_rub=Decimal(digits),
                    raw_label=match.group(0),
                    provenance=Provenance(
                        document_id=digest,
                        locator=(
                            f"{card.locator}/price-title+price-VAT[{kind}]"
                            if kind != "LEASE_MONTHLY"
                            else f"{card.locator}/price-VAT[{kind}]"
                        ),
                        extractor=Extractor.API,
                    ),
                )
            )
        except (ValidationError, RecursionError) as error:
            raise SupplierCatalogSourceError("SUPPLIER_SOURCE_MISMATCH") from error
    return tuple(observed)


def build_servermall_supplier_observation(
    source: ServerMallObservation, query: str
) -> SupplierCatalogObservation:
    """Project one retained fixed-category response without any product-page navigation."""
    if not _supported_query(query):
        raise SupplierCatalogSourceError("SUPPLIER_QUERY_UNSUPPORTED")
    if (
        source.source_url != SERVERMALL_HPE_GEN12_URL
        or not 0 < len(source.content) <= MAX_HTML_BYTES
        or hashlib.sha256(source.content).hexdigest() != source.sha256
        or source.observed_at.tzinfo is None
        or source.observed_at.utcoffset() is None
    ):
        raise SupplierCatalogSourceError("SUPPLIER_SOURCE_MISMATCH")
    leads = []
    try:
        offers = _catalog_offers(source.content)
        cards = _visible_cards(source.content)
    except (ServerMallSourceError, ValidationError, RecursionError) as error:
        raise SupplierCatalogSourceError("SUPPLIER_SOURCE_MISMATCH") from error
    offer_indexes: dict[str, tuple[int, str]] = {}
    matching_offers: list[tuple[int, str, str]] = []
    for index, offer in enumerate(offers, 1):
        url, name = offer.get("url"), offer.get("name")
        if (
            offer.get("@type") != "Offer"
            or not isinstance(url, str)
            or not isinstance(name, str)
            or not name.strip()
            or not _valid_product_url(url)
            or url in offer_indexes
        ):
            raise SupplierCatalogSourceError("SUPPLIER_SOURCE_MISMATCH")
        offer_indexes[url] = (index, name.strip())
        if title_matches_query(name, query):
            matching_offers.append((index, name.strip(), url))
    expected = matching_offers[:MAX_LEADS]
    if len(source.leads) != len(expected):
        raise SupplierCatalogSourceError("SUPPLIER_LEAD_SOURCE_MISMATCH")
    for lead, expected_offer in zip(source.leads, expected, strict=True):
        if (
            lead.product_url is None
            or not _valid_product_url(lead.product_url)
            or lead.source_url != source.source_url
            or lead.source_sha256 != source.sha256
            or lead.observed_at != source.observed_at
        ):
            raise SupplierCatalogSourceError("SUPPLIER_LEAD_SOURCE_MISMATCH")
        source_offer = offer_indexes.get(lead.product_url)
        if (
            source_offer is None
            or source_offer[1] != lead.product_name
            or expected_offer != (source_offer[0], lead.product_name, lead.product_url)
        ):
            raise SupplierCatalogSourceError("SUPPLIER_LEAD_SOURCE_MISMATCH")
        source_index = source_offer[0]
        prices = _card_prices(cards, lead.product_url, source.sha256)
        try:
            leads.append(
                SupplierCatalogLead(
                    product_name=lead.product_name,
                    product_url=lead.product_url,
                    name_provenance=Provenance(
                        document_id=source.sha256,
                        locator=f"jsonld/OfferCatalog/itemListElement[{source_index}]/name",
                        extractor=Extractor.API,
                    ),
                    price_status="PUBLISHED" if prices else "UNKNOWN",
                    published_prices=prices,
                )
            )
        except (ValidationError, RecursionError) as error:
            raise SupplierCatalogSourceError("SUPPLIER_SOURCE_MISMATCH") from error
    try:
        return SupplierCatalogObservation(
            observed_at=source.observed_at,
            source_sha256=source.sha256,
            byte_count=len(source.content),
            query=" ".join(query.split()),
            leads=tuple(leads),
            scanned_count=len(offers),
            matched_count=len(matching_offers),
            returned_count=len(leads),
            truncated=len(matching_offers) > len(leads),
        )
    except (ValidationError, RecursionError) as error:
        raise SupplierCatalogSourceError("SUPPLIER_SOURCE_MISMATCH") from error


def _supported_query(query: object) -> bool:
    if not isinstance(query, str):
        return False
    normalized = " ".join(query.split())
    return (
        1 <= len(normalized.split()) <= 5
        and len(normalized) <= 80
        and servermall_covers(normalized)
    )


def observe_servermall_hpe_gen12(query: str) -> SupplierCatalogCapture:
    """Make exactly the existing fixed-category GET after rejecting unsupported queries."""
    if not _supported_query(query):
        raise SupplierCatalogSourceError("SUPPLIER_QUERY_UNSUPPORTED")
    try:
        source = fetch_servermall_hpe_gen12(" ".join(query.split()))
    except ServerMallSourceError as error:
        raise SupplierCatalogSourceError("SUPPLIER_SOURCE_UNAVAILABLE") from error
    return SupplierCatalogCapture(
        observation=build_servermall_supplier_observation(source, query),
        content=source.content,
    )
