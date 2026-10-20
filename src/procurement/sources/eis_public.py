"""Bounded parser and browser reader for the public EIS notice search page."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict

from procurement.sources.eis_browser import EisBrowserConfigError, eis_browser_proxy_server
from procurement.sources.eis_discovery import (
    MAX_ATTACHMENT_BYTES,
    _official_attachment_url,
    _search_key,
)

if TYPE_CHECKING:
    from playwright.async_api import ProxySettings

EIS_SEARCH_URL = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html"
_MAX_HTML_BYTES = 8 * 1024 * 1024
_CRAWL_DELAY = timedelta(seconds=60)
_SEARCH_PAGE_SIZE = 100
_NUMBER = re.compile(r"^(?:\d{11}|\d{19,23})$")
_WORDS = re.compile(r"[\w]+", re.UNICODE)
_INTENT_WORDS = {
    "закупка",
    "закупки",
    "найди",
    "найти",
    "перепродавать",
    "поставить",
    "поставлять",
    "продавать",
    "хочу",
}
_GENERIC_CATEGORY_WORDS = {"оборудование", "оборудования"}
_VOID_TAGS = {
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
    "wbr",
}


class EisPublicError(ValueError):
    """Safe error code for changed/blocked public EIS pages."""


def _public_browser_proxy() -> ProxySettings | None:
    try:
        server = eis_browser_proxy_server()
    except EisBrowserConfigError as error:
        raise EisPublicError("PROXY_CONFIG_INVALID") from error
    return {"server": server} if server is not None else None


class EisPublicLead(BaseModel):
    model_config = ConfigDict(frozen=True)

    purchase_number: str
    subject: str
    customer: str | None = None
    law: Literal["44-fz", "223-fz"]
    method: str
    stage: str
    nmck_rub: Decimal | None = None
    deadline_date: date | None = None
    detail_url: str
    documents_url: str | None = None
    matched_terms: tuple[str, ...]
    application_status: Literal["UNKNOWN", "FAIL"] = "UNKNOWN"
    economic_status: Literal["UNKNOWN"] = "UNKNOWN"
    source_locator: str
    source_sha256: str


class EisPublicSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    search_url: str
    status: Literal[
        "COMPLETED", "SOURCE_CHANGED", "BLOCKED", "RATE_LIMITED", "SOURCE_ERROR", "COOLDOWN"
    ]
    observed_at: AwareDatetime
    source_sha256: str | None = None
    scanned_count: int | None = None
    # One entry per identifiable raw row, before title matching. None means legacy/unknown.
    purchase_numbers: tuple[str, ...] | None = None
    unidentified_count: int | None = None
    unique_scanned_count: int | None = None
    unparsed_count: int = 0
    source_result_count_floor: int | None = None
    source_result_count_exact: bool = False
    query_exceeds_page_limit: bool = False
    has_more_pages: bool = False
    page_number: int = 1
    page_size: Literal[50, 100] = 100
    coverage: Literal["FIRST_PAGE_ONLY", "SINGLE_PAGE"] = "FIRST_PAGE_ONLY"
    reason: str | None = None
    retry_at: AwareDatetime | None = None
    leads: tuple[EisPublicLead, ...] = ()


class EisPublicDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    filename: str
    url: str
    source_locator: str
    supported: bool = True


class EisPublicDocumentsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents_url: str
    status: Literal[
        "COMPLETED", "SOURCE_CHANGED", "BLOCKED", "RATE_LIMITED", "SOURCE_ERROR", "COOLDOWN"
    ]
    observed_at: AwareDatetime
    source_sha256: str | None = None
    reason: str | None = None
    retry_at: AwareDatetime | None = None
    documents: tuple[EisPublicDocument, ...] = ()
    missing_formats: tuple[str, ...] = ()


class EisPublicDetailField(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: Literal["deadline", "delivery_location", "quantity", "condition", "stage", "other"]
    label: str
    value: str
    source_locator: str
    evidence_snippet: str


class EisPublicCustomer(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    organization_code: str
    profile_url: str
    source_locator: str
    source_sha256: str


class EisPublicDetailResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    detail_url: str
    status: Literal[
        "COMPLETED", "SOURCE_CHANGED", "BLOCKED", "RATE_LIMITED", "SOURCE_ERROR", "COOLDOWN"
    ]
    observed_at: AwareDatetime
    source_sha256: str | None = None
    source_purchase_number: str | None = None
    exact_deadline: AwareDatetime | None = None
    customer: EisPublicCustomer | None = None
    fields: tuple[EisPublicDetailField, ...] = ()
    reason: str | None = None
    retry_at: AwareDatetime | None = None


class EisCustomerProfileResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_url: str
    organization_code: str
    status: Literal[
        "COMPLETED", "SOURCE_CHANGED", "BLOCKED", "RATE_LIMITED", "SOURCE_ERROR", "COOLDOWN"
    ]
    observed_at: AwareDatetime
    source_sha256: str | None = None
    inn: str | None = None
    inn_locator: str | None = None
    contracts_url: str | None = None
    contracts_locator: str | None = None
    reason: str | None = None
    retry_at: AwareDatetime | None = None


class EisCustomerContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    registry_number: str
    subject: str | None = None
    price_rub: Decimal | None = None
    signed_on: date | None = None
    contract_url: str
    notice_number: str | None = None
    notice_url: str | None = None
    notice_locator: str | None = None
    relevance_status: Literal["MATCHED_VISIBLE", "UNKNOWN"] = "UNKNOWN"
    matched_terms: tuple[str, ...] = ()
    source_locator: str
    source_sha256: str


class EisCustomerContractsResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    search_url: str
    status: Literal[
        "COMPLETED", "SOURCE_CHANGED", "BLOCKED", "RATE_LIMITED", "SOURCE_ERROR", "COOLDOWN"
    ]
    observed_at: AwareDatetime
    source_sha256: str | None = None
    product_query: str | None = None
    coverage: Literal["FIRST_PAGE_ONLY"] = "FIRST_PAGE_ONLY"
    scanned_count: int = 0
    skipped_count: int = 0
    contracts: tuple[EisCustomerContract, ...] = ()
    reason: str | None = None
    retry_at: AwareDatetime | None = None


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def walk(self) -> Iterator[_Node]:
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()

    def first(self, class_name: str) -> _Node | None:
        return next((node for node in self.walk() if class_name in node.classes()), None)

    def text(self) -> str:
        parts = (child.text() if isinstance(child, _Node) else child for child in self.children)
        return " ".join(" ".join(parts).split())


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(_Node(tag, {key: value or "" for key, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _parse_html(content: bytes) -> _Node:
    if not content or len(content) > _MAX_HTML_BYTES:
        raise EisPublicError("HTML_SIZE_INVALID")
    try:
        parser = _Tree()
        parser.feed(content.decode("utf-8"))
        parser.close()
    except (UnicodeError, RecursionError) as error:
        raise EisPublicError("HTML_INVALID") from error
    return parser.root


def _official_url(href: str, allowed: tuple[str, ...]) -> str | None:
    try:
        url = urljoin("https://zakupki.gov.ru", href)
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in {
            "zakupki.gov.ru",
            "www.zakupki.gov.ru",
        }:
            return None
        if parts.port not in {None, 443} or parts.username or parts.password or parts.fragment:
            return None
        return url if any(parts.path.startswith(prefix) for prefix in allowed) else None
    except ValueError:
        return None


def _price(text: str) -> Decimal | None:
    if "₽" not in text:
        return None
    match = re.search(r"([\d\s\u00a0\u202f]+,\d{2})\s*₽", text)
    if not match:
        return None
    try:
        amount = Decimal(
            match.group(1)
            .replace(" ", "")
            .replace("\u00a0", "")
            .replace("\u202f", "")
            .replace(",", ".")
        )
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _deadline_date(card: _Node) -> date | None:
    for node in card.walk():
        if "data-block__title" not in node.classes() or node.text() != "Окончание подачи заявок":
            continue
        # The observed page places the value immediately after the title.
        parent = next((candidate for candidate in card.walk() if node in candidate.children), None)
        if parent is None:
            continue
        values = [
            child
            for child in parent.children
            if isinstance(child, _Node) and "data-block__value" in child.classes()
        ]
        for value in values:
            try:
                return datetime.strptime(value.text(), "%d.%m.%Y").date()
            except ValueError:
                continue
    return None


def public_search_url(
    query: str, page_number: int = 1, *, page_size: int = _SEARCH_PAGE_SIZE
) -> str:
    """Build one bounded application-stage search page observed on EIS."""
    normalized = " ".join(query.split())
    words = _WORDS.findall(normalized)
    if not 1 <= len(words) <= 8 or not 1 <= len(normalized) <= 120:
        raise EisPublicError("QUERY_INVALID")
    if not 1 <= page_number <= 20:
        raise EisPublicError("PAGE_NUMBER_INVALID")
    if page_size not in {50, 100}:
        raise EisPublicError("PAGE_SIZE_INVALID")
    params = {
        "searchString": normalized,
        "morphology": "on",
        "pageNumber": str(page_number),
        "recordsPerPage": f"_{page_size}",
        "sortBy": "UPDATE_DATE",
        "fz44": "on",
        "fz223": "on",
        "af": "on",
    }
    return f"{EIS_SEARCH_URL}?{urlencode(params)}"


def parse_public_search(
    content: bytes, query: str, search_url: str, observed_at: datetime
) -> EisPublicSearchResult:
    """Parse one official result page; a title match is a lead, not profit."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be aware")
    parts = urlsplit(search_url)
    if (
        parts.scheme != "https"
        or parts.hostname != "zakupki.gov.ru"
        or parts.path != "/epz/order/extendedsearch/results.html"
    ):
        raise EisPublicError("SEARCH_URL_INVALID")
    if parse_qs(parts.query).get("searchString", [None])[0] != query:
        raise EisPublicError("SEARCH_QUERY_MISMATCH")
    page_size_value = parse_qs(parts.query).get("recordsPerPage", [None])[0]
    if page_size_value not in {"_50", "_100"}:
        raise EisPublicError("SEARCH_PAGE_SIZE_MISMATCH")
    page_size: Literal[50, 100] = 50 if page_size_value == "_50" else 100
    try:
        page_number = int(parse_qs(parts.query).get("pageNumber", ["1"])[0])
    except ValueError as error:
        raise EisPublicError("SEARCH_PAGE_MISMATCH") from error
    if not 1 <= page_number <= 20:
        raise EisPublicError("SEARCH_PAGE_MISMATCH")
    root = _parse_html(content)
    visible = root.text().casefold()
    if any(
        marker in visible
        for marker in (
            "подтвердите, что вы не робот",
            "verify you are human",
            "доступ временно ограничен",
        )
    ):
        raise EisPublicError("BLOCKED_PAGE")
    cards = [node for node in root.walk() if "search-registry-entry-block" in node.classes()]
    if len(cards) > page_size:
        raise EisPublicError("SEARCH_PAGE_SIZE_CHANGED")
    if not cards and "ничего не найдено" not in visible:
        raise EisPublicError("SEARCH_MARKUP_CHANGED")
    digest = hashlib.sha256(content).hexdigest()
    words = tuple(
        dict.fromkeys(
            word.casefold()
            for word in _WORDS.findall(query)
            if len(word) >= 3 and word.casefold() not in _INTENT_WORDS
        )
    )
    leads: list[EisPublicLead] = []
    purchase_numbers: list[str] = []
    valid_cards = 0
    for index, card in enumerate(cards, 1):
        number_box = card.first("registry-entry__header-mid__number")
        subject_box = card.first("registry-entry__body-value")
        if number_box is None:
            continue
        link = next((node for node in number_box.walk() if node.tag == "a"), None)
        if link is None:
            continue
        number = re.sub(r"\D", "", link.text())
        detail = _official_url(
            link.attrs.get("href", ""),
            ("/epz/order/notice/", "/223/purchase/public/purchase/info/"),
        )
        if (
            not _NUMBER.fullmatch(number)
            or detail is None
            or parse_qs(urlsplit(detail).query).get("regNumber", [number])[0] != number
        ):
            continue
        purchase_numbers.append(number)
        if subject_box is None:
            continue
        subject = subject_box.text()
        title = card.first("registry-entry__header-top__title")
        law_method = title.text() if title else ""
        law = "44-fz" if "44-ФЗ" in law_method else "223-fz" if "223-ФЗ" in law_method else None
        if law is None:
            continue
        valid_cards += 1
        stage_box = card.first("registry-entry__header-mid__title")
        stage = stage_box.text() if stage_box else ""
        customer_box = card.first("registry-entry__body-href")
        customer = customer_box.text() if customer_box else None
        price_box = card.first("price-block__value")
        docs = next(
            (
                node
                for node in card.walk()
                if node.tag == "a" and "documents.html" in node.attrs.get("href", "")
            ),
            None,
        )
        docs_url = (
            _official_url(
                docs.attrs["href"], ("/epz/order/notice/", "/223/purchase/public/purchase/info/")
            )
            if docs
            else None
        )
        title_keys = {_search_key(word) for word in _WORDS.findall(subject)}
        matched = tuple(word for word in words if _search_key(word) in title_keys)
        specific_words = tuple(word for word in words if word not in _GENERIC_CATEGORY_WORDS)
        required_words = specific_words or words
        if not required_words or any(
            _search_key(word) not in title_keys for word in required_words
        ):
            continue
        deadline = _deadline_date(card)
        leads.append(
            EisPublicLead(
                purchase_number=number,
                subject=subject[:4000],
                customer=customer,
                law=law,
                method=law_method,
                stage=stage,
                nmck_rub=_price(price_box.text()) if price_box else None,
                deadline_date=deadline,
                detail_url=detail,
                documents_url=docs_url,
                matched_terms=matched,
                application_status="FAIL"
                if stage != "Подача заявок"
                or (deadline is not None and deadline < observed_at.date())
                else "UNKNOWN",
                source_locator=f"search-result-card[{index}]",
                source_sha256=digest,
            )
        )
    if cards and not valid_cards:
        raise EisPublicError("SEARCH_MARKUP_CHANGED")
    if cards and not leads:
        # The site can match inflections/attachments that are absent in the title.
        # This is a valid empty *title* shortlist, not a claim of no procurements.
        pass
    leads.sort(
        key=lambda row: (
            -len(row.matched_terms),
            row.deadline_date or date.max,
            row.purchase_number,
        )
    )
    decoded = content.decode("utf-8", errors="ignore")
    total_label = re.search(
        r"результаты поиска\s+(?P<more>более\s+)?"
        r"(?P<count>\d[\d\s\u00a0\u202f]{0,20})\s+записей",
        visible,
    )
    source_result_count_floor = (
        int(re.sub(r"\s", "", total_label.group("count"))) if total_label else None
    )
    source_result_count_exact = total_label is not None and total_label.group("more") is None
    query_exceeds_page_limit = source_result_count_floor is not None and (
        source_result_count_floor > 20 * page_size
        if source_result_count_exact
        else source_result_count_floor >= 20 * page_size
    )
    page_targets = {
        int(value)
        for value in re.findall(r"(?:goToPage\(|pageNumber=)(\d{1,3})", decoded)
        if 1 <= int(value) <= 20
    }
    return EisPublicSearchResult(
        query=query,
        search_url=search_url,
        status="COMPLETED",
        observed_at=observed_at,
        source_sha256=digest,
        scanned_count=len(cards),
        purchase_numbers=tuple(purchase_numbers),
        unidentified_count=len(cards) - len(purchase_numbers),
        unique_scanned_count=len(set(purchase_numbers))
        if len(purchase_numbers) == len(cards)
        else None,
        unparsed_count=len(cards) - valid_cards,
        source_result_count_floor=source_result_count_floor,
        source_result_count_exact=source_result_count_exact,
        query_exceeds_page_limit=query_exceeds_page_limit,
        has_more_pages=any(target > page_number for target in page_targets)
        or (
            len(cards) == page_size
            and source_result_count_floor is not None
            and source_result_count_floor > page_number * page_size
        ),
        page_number=page_number,
        page_size=page_size,
        coverage="FIRST_PAGE_ONLY" if page_number == 1 else "SINGLE_PAGE",
        leads=tuple(leads),
    )


def _documents_url_valid(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (
            parts.scheme == "https"
            and parts.hostname == "zakupki.gov.ru"
            and parts.port in {None, 443}
            and parts.username is None
            and parts.password is None
            and parts.fragment == ""
            and re.fullmatch(r"/epz/order/notice/[a-zA-Z0-9]+/view/documents\.html", parts.path)
            is not None
            and _NUMBER.fullmatch(parse_qs(parts.query).get("regNumber", [""])[0]) is not None
        )
    except ValueError:
        return False


def _detail_url_number(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.hostname != "zakupki.gov.ru"
            or parts.port not in {None, 443}
            or parts.username
            or parts.password
            or parts.fragment
            or not (
                re.fullmatch(r"/epz/order/notice/[a-zA-Z0-9]+/view/common-info\.html", parts.path)
                or parts.path.startswith("/223/purchase/public/purchase/info/")
            )
        ):
            return None
        query = parse_qs(parts.query)
        number = next(
            (
                query[key][0]
                for key in ("regNumber", "purchaseInfoId", "purchaseId")
                if query.get(key)
            ),
            None,
        )
        return number if number and _NUMBER.fullmatch(number) else None
    except ValueError:
        return None


def _customer_profile_code(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        codes = parse_qs(parts.query).get("organizationCode", [])
        if (
            parts.scheme != "https"
            or parts.hostname != "zakupki.gov.ru"
            or parts.port not in {None, 443}
            or parts.username
            or parts.password
            or parts.fragment
            or parts.path != "/epz/organization/view/info.html"
            or len(codes) != 1
            or re.fullmatch(r"\d{11}", codes[0]) is None
        ):
            return None
        return codes[0]
    except ValueError:
        return None


def parse_customer_profile(
    content: bytes, profile_url: str, observed_at: datetime
) -> EisCustomerProfileResult:
    """Extract only an explicit, unambiguous INN from the official organization card."""
    code = _customer_profile_code(profile_url)
    if code is None:
        raise EisPublicError("CUSTOMER_URL_INVALID")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be aware")
    root = _parse_html(content)
    if any(
        marker in root.text().casefold()
        for marker in ("подтвердите, что вы не робот", "verify you are human")
    ):
        raise EisPublicError("BLOCKED_PAGE")
    found: list[tuple[str, str]] = []
    for index, parent in enumerate(root.walk(), 1):
        children = [child for child in parent.children if isinstance(child, _Node)]
        for position, label in enumerate(children[:-1]):
            if label.text().strip() != "ИНН":
                continue
            for value in children[position + 1 :]:
                digits = re.sub(r"\D", "", value.text())
                if re.fullmatch(r"\d{10}|\d{12}", digits):
                    found.append((digits, f"inn-field[{index}]"))
                    break
    unique = {item[0] for item in found}
    if len(unique) != 1:
        raise EisPublicError("CUSTOMER_INN_UNVERIFIED")
    inn, locator = found[0]
    contract_links: list[tuple[str, str]] = []
    for index, link in enumerate(root.walk(), 1):
        if link.tag != "a":
            continue
        target = _official_url(link.attrs.get("href", ""), ("/epz/contract/search/",))
        if target is None or urlsplit(target).path != "/epz/contract/search/results.html":
            continue
        customer_filters = parse_qs(urlsplit(target).query).get("customerIdOrg", [])
        if len(customer_filters) != 1 or not re.search(
            rf"(?<!\d){re.escape(inn)}(?!\d)", customer_filters[0]
        ):
            continue
        contract_links.append((target, f"customer-contracts-link[{index}]"))
    contracts_url, contracts_locator = (
        contract_links[0] if len({target for target, _ in contract_links}) == 1 else (None, None)
    )
    return EisCustomerProfileResult(
        profile_url=profile_url,
        organization_code=code,
        status="COMPLETED",
        observed_at=observed_at,
        source_sha256=hashlib.sha256(content).hexdigest(),
        inn=inn,
        inn_locator=locator,
        contracts_url=contracts_url,
        contracts_locator=contracts_locator,
    )


def contract_product_query(value: str) -> str:
    """Keep only meaningful supplier terms for a bounded customer-contract search."""
    words = [
        word
        for word in _WORDS.findall(" ".join(value.split()))
        if len(word) >= 3 and word.casefold() not in _INTENT_WORDS
    ]
    query = " ".join(words)
    if not 1 <= len(words) <= 8 or not 1 <= len(query) <= 120:
        raise EisPublicError("HISTORY_QUERY_INVALID")
    return query


def completed_contracts_url(profile_link: str, inn: str, product_query: str | None = None) -> str:
    """Use the official organization link with the observed completed-stage filter."""
    try:
        parts = urlsplit(profile_link)
        query = parse_qs(parts.query)
        customer_filters = query.get("customerIdOrg", [])
        stages = query.get("contractStageList", [])
        search_terms = query.get("searchString", [])
        normalized_query = (
            contract_product_query(product_query) if product_query is not None else None
        )
        if (
            parts.scheme != "https"
            or parts.hostname != "zakupki.gov.ru"
            or parts.port not in {None, 443}
            or parts.username
            or parts.password
            or parts.fragment
            or parts.path != "/epz/contract/search/results.html"
            or re.fullmatch(r"\d{10}|\d{12}", inn) is None
            or len(customer_filters) != 1
            or re.search(rf"(?<!\d){re.escape(inn)}(?!\d)", customer_filters[0]) is None
            or len(stages) != 1
            or stages[0] not in {"0", "1"}
            or len(search_terms) > 1
            or (normalized_query is None and bool(search_terms))
        ):
            raise EisPublicError("CONTRACT_SEARCH_URL_INVALID")
        params = [
            (key, "1" if key == "contractStageList" else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key != "searchString"
        ]
        if normalized_query is not None:
            params.append(("searchString", normalized_query))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))
    except ValueError as error:
        raise EisPublicError("CONTRACT_SEARCH_URL_INVALID") from error


def parse_completed_contracts(
    content: bytes,
    search_url: str,
    inn: str,
    customer_name: str,
    observed_at: datetime,
    product_query: str | None = None,
) -> EisCustomerContractsResult:
    """Read one filtered result page; never infer an entire customer history."""
    normalized_query = contract_product_query(product_query) if product_query is not None else None
    if completed_contracts_url(search_url, inn, normalized_query) != search_url:
        raise EisPublicError("CONTRACT_SEARCH_URL_INVALID")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be aware")
    root = _parse_html(content)
    if any(
        marker in root.text().casefold()
        for marker in ("подтвердите, что вы не робот", "verify you are human")
    ):
        raise EisPublicError("BLOCKED_PAGE")
    if normalized_query is not None:
        observed_filters = [
            node.attrs.get("value", "")
            for node in root.walk()
            if node.tag == "input" and node.attrs.get("name") == "searchString"
        ]
        observed_stages = [
            node.attrs.get("value", "")
            for node in root.walk()
            if node.tag == "input" and node.attrs.get("name") == "contractStageList"
        ]
        observed_customers = [
            node.attrs.get("value", "")
            for node in root.walk()
            if node.tag == "input" and node.attrs.get("name") == "customerIdOrg"
        ]
        if (
            observed_filters != [normalized_query]
            or observed_stages != ["1"]
            or len(observed_customers) != 1
            or re.search(rf"(?<!\d){re.escape(inn)}(?!\d)", observed_customers[0]) is None
        ):
            raise EisPublicError("CONTRACT_FILTER_UNVERIFIED")
    cards = [node for node in root.walk() if "search-registry-entry-block" in node.classes()]
    if not cards:
        empty_markers = [
            node
            for node in root.walk()
            if node.tag == "p"
            and "noRecords" in node.classes()
            and node.text().strip() == "Поиск не дал результатов"
        ]
        if len(empty_markers) == 1:
            return EisCustomerContractsResult(
                search_url=search_url,
                status="COMPLETED",
                observed_at=observed_at,
                source_sha256=hashlib.sha256(content).hexdigest(),
                product_query=normalized_query,
                reason="NO_RESULTS_FIRST_PAGE",
            )
        raise EisPublicError("CONTRACT_MARKUP_CHANGED")
    digest = hashlib.sha256(content).hexdigest()
    contracts: list[EisCustomerContract] = []
    skipped = 0
    verified = 0
    for index, card in enumerate(cards[:10], 1):
        number_box = card.first("registry-entry__header-mid__number")
        stage_box = card.first("registry-entry__header-mid__title")
        customer_box = card.first("registry-entry__body-href")
        if number_box is None or stage_box is None or customer_box is None:
            raise EisPublicError("CONTRACT_MARKUP_CHANGED")
        link = next((node for node in number_box.walk() if node.tag == "a"), None)
        if link is None:
            raise EisPublicError("CONTRACT_MARKUP_CHANGED")
        number = re.sub(r"\D", "", link.text())
        contract_url = _official_url(link.attrs.get("href", ""), ("/epz/contract/contractCard/",))
        if (
            _NUMBER.fullmatch(number) is None
            or contract_url is None
            or urlsplit(contract_url).path != "/epz/contract/contractCard/common-info.html"
            or parse_qs(urlsplit(contract_url).query).get("reestrNumber", []) != [number]
        ):
            skipped += 1
            continue
        verified += 1
        if (
            stage_box.text().strip() != "Исполнение завершено"
            or customer_box.text().casefold().strip() != customer_name.casefold().strip()
        ):
            skipped += 1
            continue
        subject = None
        for item in card.walk():
            if "lots-wrap-content__body--item" not in item.classes():
                continue
            title = item.first("lots-wrap-content__body__title")
            value = item.first("lots-wrap-content__body__val")
            if title and value and title.text().strip() == "Объекты закупки":
                subject = value.text()[:400] or None
                break
        query_words = tuple(_WORDS.findall(normalized_query)) if normalized_query else ()
        subject_keys = {_search_key(word) for word in _WORDS.findall(subject or "")}
        matched_terms = tuple(word for word in query_words if _search_key(word) in subject_keys)
        specific_words = tuple(
            word for word in query_words if word.casefold() not in _GENERIC_CATEGORY_WORDS
        )
        required_words = specific_words or query_words
        relevance_status: Literal["MATCHED_VISIBLE", "UNKNOWN"] = (
            "MATCHED_VISIBLE"
            if required_words and all(_search_key(word) in subject_keys for word in required_words)
            else "UNKNOWN"
        )
        notice_links: list[tuple[str, str]] = []
        for link_index, notice_link in enumerate(card.walk(), 1):
            if notice_link.tag != "a":
                continue
            target = _official_url(notice_link.attrs.get("href", ""), ("/epz/order/notice/",))
            if target is None or urlsplit(target).path != "/epz/order/notice/view/common-info.html":
                continue
            numbers = parse_qs(urlsplit(target).query).get("regNumber", [])
            if len(numbers) == 1 and _NUMBER.fullmatch(numbers[0]):
                notice_links.append((target, f"contract-card[{index}]/notice-link[{link_index}]"))
        notice_url, notice_locator = (
            notice_links[0] if len({target for target, _ in notice_links}) == 1 else (None, None)
        )
        notice_number = parse_qs(urlsplit(notice_url).query)["regNumber"][0] if notice_url else None
        price = None
        for block in card.walk():
            if "price-block" not in block.classes():
                continue
            title = block.first("price-block__title")
            value = block.first("price-block__value")
            if title and value and title.text().strip() == "Цена контракта":
                price = _price(value.text())
                break
        signed_on = None
        for block in card.walk():
            if "data-block" not in block.classes():
                continue
            children = [child for child in block.children if isinstance(child, _Node)]
            for position, title in enumerate(children[:-1]):
                if (
                    "data-block__title" in title.classes()
                    and title.text().strip() == "Заключение контракта"
                    and "data-block__value" in children[position + 1].classes()
                ):
                    with suppress(ValueError):
                        signed_on = datetime.strptime(
                            children[position + 1].text().strip(), "%d.%m.%Y"
                        ).date()
                    break
        contracts.append(
            EisCustomerContract(
                registry_number=number,
                subject=subject,
                price_rub=price,
                signed_on=signed_on,
                contract_url=contract_url,
                notice_number=notice_number,
                notice_url=notice_url,
                notice_locator=notice_locator,
                relevance_status=relevance_status,
                matched_terms=matched_terms,
                source_locator=f"contract-card[{index}]",
                source_sha256=digest,
            )
        )
    if verified == 0:
        raise EisPublicError("CONTRACT_MARKUP_CHANGED")
    return EisCustomerContractsResult(
        search_url=search_url,
        status="COMPLETED",
        observed_at=observed_at,
        source_sha256=digest,
        product_query=normalized_query,
        scanned_count=len(cards),
        skipped_count=skipped,
        contracts=tuple(contracts),
    )


def _detail_field_name(
    label: str,
) -> Literal["deadline", "delivery_location", "quantity", "condition", "stage", "other"]:
    key = label.casefold()
    if "окончан" in key and ("заяв" in key or "предлож" in key):
        return "deadline"
    if "место" in key and ("постав" in key or "достав" in key or "выполн" in key):
        return "delivery_location"
    if "количеств" in key or "объем" in key or "объём" in key:
        return "quantity"
    if "услов" in key or "порядок постав" in key or "срок постав" in key:
        return "condition"
    if any(marker in key for marker in ("этап закуп", "статус закуп", "статус извещ")):
        return "stage"
    return "other"


def _explicit_deadline(value: str) -> datetime | None:
    matches = tuple(
        re.finditer(
            r"(\d{2}\.\d{2}\.\d{4})\s+(\d{1,2}:\d{2})\s*"
            r"(?:\((UTC(?:[+-]\d{1,2}(?::?\d{2})?)?|МСК|MSK|[+-]\d{2}:?\d{2})\)"
            r"|(UTC(?:[+-]\d{1,2}(?::?\d{2})?)?|МСК|MSK|[+-]\d{2}:?\d{2}))"
            r"(?![\w:+-])",
            value,
            re.IGNORECASE,
        )
    )
    parsed: set[datetime] = set()
    for match in matches:
        zone = (match.group(3) or match.group(4)).upper()
        if zone == "UTC":
            offset = "+00:00"
        elif zone in {"МСК", "MSK"}:
            offset = "+03:00"
        elif zone.startswith("UTC"):
            offset = zone.removeprefix("UTC")
        else:
            offset = zone
        if re.fullmatch(r"[+-]\d{1,2}", offset):
            sign, hours = offset[0], int(offset[1:])
            offset = f"{sign}{hours:02d}:00"
        elif re.fullmatch(r"[+-]\d{4}", offset):
            offset = f"{offset[:3]}:{offset[3:]}"
        try:
            parsed.add(
                datetime.fromisoformat(
                    f"{datetime.strptime(match.group(1), '%d.%m.%Y').date().isoformat()}T"
                    f"{match.group(2)}:00{offset}"
                )
            )
        except ValueError:
            continue
    return next(iter(parsed)) if len(parsed) == 1 else None


def _deadline_calendar_date(value: str) -> date | None:
    matches = set(re.findall(r"(?<!\d)(\d{2}\.\d{2}\.\d{4})(?!\d)", value))
    if len(matches) != 1:
        return None
    try:
        return datetime.strptime(next(iter(matches)), "%d.%m.%Y").date()
    except ValueError:
        return None


def parse_public_detail(
    content: bytes, detail_url: str, observed_at: datetime
) -> EisPublicDetailResult:
    """Parse labeled common-info facts without inferring absent timezone or facts."""
    source_number = _detail_url_number(detail_url)
    if source_number is None:
        raise EisPublicError("DETAIL_URL_INVALID")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be aware")
    root = _parse_html(content)
    visible = root.text()
    folded = visible.casefold()
    if any(marker in folded for marker in ("подтвердите, что вы не робот", "verify you are human")):
        raise EisPublicError("BLOCKED_PAGE")

    digest = hashlib.sha256(content).hexdigest()
    customers: list[EisPublicCustomer] = []
    for index, section in enumerate(root.walk(), 1):
        if "cardMainInfo__section" not in section.classes():
            continue
        children = [child for child in section.children if isinstance(child, _Node)]
        if not any(
            "cardMainInfo__title" in child.classes() and child.text().strip() == "Заказчик"
            for child in children
        ):
            continue
        for child in children:
            if "cardMainInfo__content" not in child.classes():
                continue
            for link in child.walk():
                if link.tag != "a":
                    continue
                url = _official_url(link.attrs.get("href", ""), ("/epz/organization/view/",))
                if url is None or urlsplit(url).path != "/epz/organization/view/info.html":
                    continue
                codes = parse_qs(urlsplit(url).query).get("organizationCode", [])
                if len(codes) != 1 or re.fullmatch(r"\d{11}", codes[0]) is None:
                    continue
                name = link.text()[:500]
                if name:
                    customers.append(
                        EisPublicCustomer(
                            name=name,
                            organization_code=codes[0],
                            profile_url=url,
                            source_locator=f"customer-header[{index}]",
                            source_sha256=digest,
                        )
                    )
    customer = customers[0] if len({row.organization_code for row in customers}) == 1 else None

    fields: list[EisPublicDetailField] = []
    deadline_evidence: list[tuple[date | None, datetime | None]] = []
    seen: set[tuple[str, str]] = set()
    labels = ("title", "label", "caption")
    values = ("value", "info", "text")
    for index, parent in enumerate(root.walk(), 1):
        children = [child for child in parent.children if isinstance(child, _Node)]
        for position, label_node in enumerate(children[:-1]):
            if not any(marker in " ".join(label_node.classes()).casefold() for marker in labels):
                continue
            value_node = next(
                (
                    node
                    for node in children[position + 1 :]
                    if any(marker in " ".join(node.classes()).casefold() for marker in values)
                ),
                None,
            )
            label = label_node.text()[:500]
            value = value_node.text()[:4000] if value_node else ""
            if not label or not value or (label, value) in seen:
                continue
            name = _detail_field_name(label)
            if name == "other" and label.casefold().strip() not in {
                "номер извещения",
                "реестровый номер",
            }:
                continue
            seen.add((label, value))
            snippet = f"{label}: {value}"[:4500]
            fields.append(
                EisPublicDetailField(
                    name=name,
                    label=label,
                    value=value,
                    source_locator=f"labeled-field[{index}]",
                    evidence_snippet=snippet,
                )
            )
            if name == "deadline":
                deadline_evidence.append(
                    (_deadline_calendar_date(value), _explicit_deadline(value))
                )

    page_numbers = {
        match
        for match in re.findall(r"(?<!\d)(?:\d{11}|\d{19,23})(?!\d)", visible)
        if match == source_number
    }
    labeled_numbers = {
        re.sub(r"\D", "", field.value)
        for field in fields
        if field.label.casefold().strip() in {"номер извещения", "реестровый номер"}
    }
    if labeled_numbers and source_number not in labeled_numbers:
        raise EisPublicError("DETAIL_NUMBER_MISMATCH")
    if not fields or (not page_numbers and not labeled_numbers):
        raise EisPublicError("DETAIL_MARKUP_CHANGED")
    unique_deadlines = {deadline for _, deadline in deadline_evidence if deadline is not None}
    exact_deadline = (
        next(iter(unique_deadlines))
        if len(unique_deadlines) == 1
        and all(calendar_date is not None for calendar_date, _ in deadline_evidence)
        and all(
            calendar_date == next(iter(unique_deadlines)).date()
            for calendar_date, _ in deadline_evidence
        )
        else None
    )
    return EisPublicDetailResult(
        detail_url=detail_url,
        status="COMPLETED",
        observed_at=observed_at,
        source_sha256=digest,
        source_purchase_number=source_number,
        exact_deadline=exact_deadline,
        customer=customer,
        fields=tuple(fields),
    )


def parse_public_documents(
    content: bytes, documents_url: str, observed_at: datetime
) -> EisPublicDocumentsResult:
    """List all visible official files and flag formats supported by extraction."""
    if not _documents_url_valid(documents_url):
        raise EisPublicError("DOCUMENTS_URL_INVALID")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be aware")
    root = _parse_html(content)
    visible = root.text().casefold()
    if "подтвердите, что вы не робот" in visible or "verify you are human" in visible:
        raise EisPublicError("BLOCKED_PAGE")
    section = root.first("blockFilesTabDocs")
    if section is None:
        raise EisPublicError("DOCUMENTS_MARKUP_CHANGED")
    digest = hashlib.sha256(content).hexdigest()
    documents: list[EisPublicDocument] = []
    missing_formats: set[str] = set()
    seen: set[str] = set()
    for index, attachment in enumerate(
        (node for node in section.walk() if "attachment" in node.classes()), 1
    ):
        for link in (node for node in attachment.walk() if node.tag == "a"):
            url = _official_url(
                link.attrs.get("href", ""),
                ("/44fz/filestore/public/1.0/download/", "/epz/order/notice/"),
            )
            if url is None or not _official_attachment_url(url) or url in seen:
                continue
            filename = link.attrs.get("title", "").strip() or link.text()
            if not filename or len(filename) > 255 or re.search(r"[/\\\x00]", filename):
                continue
            suffix = Path(filename).suffix.casefold()
            supported = suffix in {".pdf", ".docx", ".xlsx", ".zip"}
            if not supported:
                missing_formats.add(suffix.removeprefix(".") or "unknown")
            documents.append(
                EisPublicDocument(
                    filename=filename,
                    url=url,
                    source_locator=f"attachment[{index}]",
                    supported=supported,
                )
            )
            seen.add(url)
    return EisPublicDocumentsResult(
        documents_url=documents_url,
        status="COMPLETED",
        observed_at=observed_at,
        source_sha256=digest,
        documents=tuple(documents),
        missing_formats=tuple(sorted(missing_formats)),
    )


@contextmanager
def _host_lease() -> Iterator[datetime | None]:
    """One shared host cooldown across tenants and local server workers."""
    default_directory = Path(__file__).resolve().parents[3] / "data" / "eis-public-browser"
    directory = Path(os.environ.get("EIS_BROWSER_STATE_DIR", str(default_directory))).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "request.lock"
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise EisPublicError("SOURCE_BUSY") from None
    try:
        with stream:
            stream.write(datetime.now(UTC).isoformat())
        cooldown = directory / "cooldown.json"
        if cooldown.exists():
            try:
                until = datetime.fromisoformat(
                    json.loads(cooldown.read_text(encoding="utf-8"))["retry_at"]
                )
                if until.tzinfo is None:
                    raise ValueError
            except (ValueError, KeyError, json.JSONDecodeError) as error:
                raise EisPublicError("COOLDOWN_STATE_INVALID") from error
            if until > datetime.now(UTC):
                yield until
                return
        now = datetime.now(UTC)
        cooldown.write_text(
            json.dumps({"retry_at": (now + _CRAWL_DELAY).isoformat()}), encoding="utf-8"
        )
        yield None
    finally:
        lock.unlink(missing_ok=True)


async def _browser_search(
    url: str, query: str, raw_observer: Callable[[bytes], None] | None = None
) -> EisPublicSearchResult:
    try:
        from playwright.async_api import Error, TimeoutError, async_playwright
    except ImportError as error:
        raise EisPublicError("BROWSER_UNAVAILABLE") from error
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, timeout=15_000, proxy=_public_browser_proxy()
            )
            try:
                page = await browser.new_page(accept_downloads=False)
                response = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                if response is None:
                    raise EisPublicError("SOURCE_ERROR")
                if response.status in {403, 451}:
                    raise EisPublicError("BLOCKED")
                if response.status == 429:
                    raise EisPublicError("RATE_LIMITED")
                if response.status != 200 or page.url != url:
                    raise EisPublicError("SOURCE_ERROR")
                content = (await page.content()).encode("utf-8")
                if raw_observer is not None:
                    raw_observer(content)
                return parse_public_search(content, query, url, datetime.now(UTC))
            finally:
                await browser.close()
    except (Error, TimeoutError) as error:
        raise EisPublicError("BROWSER_REQUEST_FAILED") from error


def search_public_eis(
    query: str,
    page_number: int = 1,
    raw_observer: Callable[[bytes], None] | None = None,
    *,
    page_size: Literal[50, 100] = 100,
) -> EisPublicSearchResult:
    """Read one live public search page with a host-wide 60-second cooldown."""
    normalized_query = " ".join(query.split())
    url = public_search_url(normalized_query, page_number, page_size=page_size)
    now = datetime.now(UTC)
    try:
        with _host_lease() as retry_at:
            if retry_at:
                return EisPublicSearchResult(
                    query=query,
                    search_url=url,
                    status="COOLDOWN",
                    observed_at=now,
                    page_number=page_number,
                    page_size=page_size,
                    coverage="FIRST_PAGE_ONLY" if page_number == 1 else "SINGLE_PAGE",
                    reason="ROBOTS_CRAWL_DELAY",
                    retry_at=retry_at,
                )
            loop_factory = (
                asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
            )
            with asyncio.Runner(loop_factory=loop_factory) as runner:
                return runner.run(_browser_search(url, normalized_query, raw_observer))
    except EisPublicError as error:
        code = str(error)
        status = (
            "BLOCKED"
            if code in {"BLOCKED", "BLOCKED_PAGE"}
            else "RATE_LIMITED"
            if code == "RATE_LIMITED"
            else "SOURCE_CHANGED"
            if code == "SEARCH_MARKUP_CHANGED"
            else "SOURCE_ERROR"
        )
        return EisPublicSearchResult(
            query=query,
            search_url=url,
            status=status,
            observed_at=now,
            page_number=page_number,
            page_size=page_size,
            coverage="FIRST_PAGE_ONLY" if page_number == 1 else "SINGLE_PAGE",
            reason=code,
        )


async def _browser_html(url: str) -> bytes:
    try:
        from playwright.async_api import Error, TimeoutError, async_playwright
    except ImportError as error:
        raise EisPublicError("BROWSER_UNAVAILABLE") from error
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, timeout=15_000, proxy=_public_browser_proxy()
            )
            try:
                page = await browser.new_page(accept_downloads=False)
                response = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                if response is None:
                    raise EisPublicError("SOURCE_ERROR")
                if response.status in {403, 451}:
                    raise EisPublicError("BLOCKED")
                if response.status == 429:
                    raise EisPublicError("RATE_LIMITED")
                if response.status != 200 or page.url != url:
                    raise EisPublicError("SOURCE_ERROR")
                content = (await page.content()).encode("utf-8")
                _parse_html(content)
                return content
            finally:
                await browser.close()
    except (Error, TimeoutError) as error:
        raise EisPublicError("BROWSER_REQUEST_FAILED") from error


def read_public_html(url: str, raw_observer: Callable[[bytes], None] | None = None) -> bytes:
    """Fetch bounded official common-info HTML under the shared host cooldown."""
    if _detail_url_number(url) is None:
        raise EisPublicError("DETAIL_URL_INVALID")
    with _host_lease() as retry_at:
        if retry_at:
            raise EisPublicError("ROBOTS_CRAWL_DELAY")
        loop_factory = (
            asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
        )
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            content = runner.run(_browser_html(url))
    if raw_observer is not None:
        raw_observer(content)
    return content


def read_public_detail(
    url: str, raw_observer: Callable[[bytes], None] | None = None
) -> EisPublicDetailResult:
    """Read and parse one official common-info page without guessing missing facts."""
    if _detail_url_number(url) is None:
        raise EisPublicError("DETAIL_URL_INVALID")
    now = datetime.now(UTC)
    try:
        content = read_public_html(url, raw_observer)
        return parse_public_detail(content, url, datetime.now(UTC))
    except EisPublicError as error:
        code = str(error)
        if code == "ROBOTS_CRAWL_DELAY":
            cooldown = (
                Path(
                    os.environ.get(
                        "EIS_BROWSER_STATE_DIR",
                        str(Path(__file__).resolve().parents[3] / "data" / "eis-public-browser"),
                    )
                )
                / "cooldown.json"
            )
            try:
                retry_at = datetime.fromisoformat(
                    json.loads(cooldown.read_text(encoding="utf-8"))["retry_at"]
                )
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                retry_at = None
            return EisPublicDetailResult(
                detail_url=url,
                status="COOLDOWN",
                observed_at=now,
                reason=code,
                retry_at=retry_at,
            )
        status = (
            "BLOCKED"
            if code in {"BLOCKED", "BLOCKED_PAGE"}
            else "RATE_LIMITED"
            if code == "RATE_LIMITED"
            else "SOURCE_CHANGED"
            if code in {"DETAIL_MARKUP_CHANGED", "DETAIL_NUMBER_MISMATCH"}
            else "SOURCE_ERROR"
        )
        return EisPublicDetailResult(
            detail_url=url,
            status=status,
            observed_at=now,
            source_purchase_number=_detail_url_number(url),
            reason=code,
        )


def read_customer_profile(
    url: str, raw_observer: Callable[[bytes], None] | None = None
) -> EisCustomerProfileResult:
    """Read one official customer page under the shared EIS host cooldown."""
    code = _customer_profile_code(url)
    if code is None:
        raise EisPublicError("CUSTOMER_URL_INVALID")
    now = datetime.now(UTC)
    try:
        with _host_lease() as retry_at:
            if retry_at:
                return EisCustomerProfileResult(
                    profile_url=url,
                    organization_code=code,
                    status="COOLDOWN",
                    observed_at=now,
                    reason="ROBOTS_CRAWL_DELAY",
                    retry_at=retry_at,
                )
            loop_factory = (
                asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
            )
            with asyncio.Runner(loop_factory=loop_factory) as runner:
                content = runner.run(_browser_html(url))
        if raw_observer is not None:
            raw_observer(content)
        return parse_customer_profile(content, url, datetime.now(UTC))
    except EisPublicError as error:
        reason = str(error)
        status = (
            "BLOCKED"
            if reason in {"BLOCKED", "BLOCKED_PAGE"}
            else "RATE_LIMITED"
            if reason == "RATE_LIMITED"
            else "SOURCE_CHANGED"
            if reason == "CUSTOMER_INN_UNVERIFIED"
            else "SOURCE_ERROR"
        )
        return EisCustomerProfileResult(
            profile_url=url,
            organization_code=code,
            status=status,
            observed_at=now,
            reason=reason,
        )


def read_completed_contracts(
    profile_link: str,
    inn: str,
    customer_name: str,
    raw_observer: Callable[[bytes], None] | None = None,
    product_query: str | None = None,
) -> EisCustomerContractsResult:
    """Read the first completed-contract page linked by an official customer card."""
    url = completed_contracts_url(profile_link, inn, product_query)
    now = datetime.now(UTC)
    try:
        with _host_lease() as retry_at:
            if retry_at:
                return EisCustomerContractsResult(
                    search_url=url,
                    status="COOLDOWN",
                    observed_at=now,
                    product_query=contract_product_query(product_query) if product_query else None,
                    reason="ROBOTS_CRAWL_DELAY",
                    retry_at=retry_at,
                )
            loop_factory = (
                asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
            )
            with asyncio.Runner(loop_factory=loop_factory) as runner:
                content = runner.run(_browser_html(url))
        if raw_observer is not None:
            raw_observer(content)
        return parse_completed_contracts(
            content, url, inn, customer_name, datetime.now(UTC), product_query
        )
    except EisPublicError as error:
        reason = str(error)
        status = (
            "BLOCKED"
            if reason in {"BLOCKED", "BLOCKED_PAGE"}
            else "RATE_LIMITED"
            if reason == "RATE_LIMITED"
            else "SOURCE_CHANGED"
            if reason in {"CONTRACT_MARKUP_CHANGED", "CONTRACT_FILTER_UNVERIFIED"}
            else "SOURCE_ERROR"
        )
        return EisCustomerContractsResult(
            search_url=url,
            status=status,
            observed_at=now,
            product_query=contract_product_query(product_query) if product_query else None,
            reason=reason,
        )


async def _browser_documents(
    url: str, raw_observer: Callable[[bytes], None] | None = None
) -> EisPublicDocumentsResult:
    try:
        from playwright.async_api import Error, TimeoutError, async_playwright
    except ImportError as error:
        raise EisPublicError("BROWSER_UNAVAILABLE") from error
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, timeout=15_000, proxy=_public_browser_proxy()
            )
            try:
                page = await browser.new_page(accept_downloads=False)
                response = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                if response is None:
                    raise EisPublicError("SOURCE_ERROR")
                if response.status in {403, 451}:
                    raise EisPublicError("BLOCKED")
                if response.status == 429:
                    raise EisPublicError("RATE_LIMITED")
                if response.status != 200 or page.url != url:
                    raise EisPublicError("SOURCE_ERROR")
                content = (await page.content()).encode("utf-8")
                if raw_observer is not None:
                    raw_observer(content)
                return parse_public_documents(content, url, datetime.now(UTC))
            finally:
                await browser.close()
    except (Error, TimeoutError) as error:
        raise EisPublicError("BROWSER_REQUEST_FAILED") from error


def read_public_documents(
    url: str, raw_observer: Callable[[bytes], None] | None = None
) -> EisPublicDocumentsResult:
    """Read one verified public 44-FZ documents page under the shared delay."""
    if not _documents_url_valid(url):
        raise EisPublicError("DOCUMENTS_URL_INVALID")
    now = datetime.now(UTC)
    try:
        with _host_lease() as retry_at:
            if retry_at:
                return EisPublicDocumentsResult(
                    documents_url=url,
                    status="COOLDOWN",
                    observed_at=now,
                    reason="ROBOTS_CRAWL_DELAY",
                    retry_at=retry_at,
                )
            loop_factory = (
                asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
            )
            with asyncio.Runner(loop_factory=loop_factory) as runner:
                return runner.run(_browser_documents(url, raw_observer))
    except EisPublicError as error:
        code = str(error)
        status = (
            "BLOCKED"
            if code in {"BLOCKED", "BLOCKED_PAGE"}
            else "RATE_LIMITED"
            if code == "RATE_LIMITED"
            else "SOURCE_CHANGED"
            if code == "DOCUMENTS_MARKUP_CHANGED"
            else "SOURCE_ERROR"
        )
        return EisPublicDocumentsResult(
            documents_url=url,
            status=status,
            observed_at=now,
            reason=code,
        )


async def _browser_download(url: str) -> bytes:
    """Read a browser download; Chromium validates the site's TLS certificate."""
    try:
        from playwright.async_api import Error, TimeoutError, async_playwright
    except ImportError as error:
        raise EisPublicError("BROWSER_UNAVAILABLE") from error
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, timeout=15_000, proxy=_public_browser_proxy()
            )
            try:
                context = await browser.new_context(accept_downloads=True)
                page = await context.new_page()
                async with page.expect_download(timeout=25_000) as pending:
                    # A successful file download aborts the page navigation.
                    with suppress(Error):
                        await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                download = await pending.value
                failure = await asyncio.wait_for(download.failure(), timeout=10)
                if download.url != url or failure:
                    raise EisPublicError("ATTACHMENT_UNAVAILABLE")
                path_value = await asyncio.wait_for(download.path(), timeout=10)
                if path_value is None:
                    raise EisPublicError("ATTACHMENT_UNAVAILABLE")
                path = Path(path_value)
                if path.stat().st_size > MAX_ATTACHMENT_BYTES:
                    raise EisPublicError("ATTACHMENT_TOO_LARGE")
                return path.read_bytes()
            finally:
                await browser.close()
    except (Error, TimeoutError, OSError) as error:
        raise EisPublicError("ATTACHMENT_UNAVAILABLE") from error


def download_public_attachment(url: str) -> bytes:
    """Download one official public EIS attachment under the shared host delay."""
    if not _official_attachment_url(url):
        raise EisPublicError("ATTACHMENT_URL_INVALID")
    with _host_lease() as retry_at:
        if retry_at:
            raise EisPublicError("ROBOTS_CRAWL_DELAY")
        loop_factory = (
            asyncio.ProactorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
        )
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            return runner.run(_browser_download(url))
