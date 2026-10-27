"""Facts from retained official card HTML, never a claim of complete history.

No transport is performed here. Missing/stale response metadata remains diagnostic;
callers must qualify these receipts together with their trusted capture evidence.
Only the observed zk20 and ea20 notice routes are supported.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Generic, Literal, TypeVar
from urllib.parse import parse_qsl, urljoin, urlsplit

from procurement.sources.eis_public import _Node, _parse_html

MAX_CARD_BYTES = 4 * 1024**2
ORIGIN = "https://zakupki.gov.ru"
CONTRACT_PATH = "/epz/contract/contractCard/common-info.html"
NOTICE_PATH = "/epz/order/notice/view/common-info.html"
NOTICE_ZK_PATH = "/epz/order/notice/zk20/view/common-info.html"
NOTICE_EA_PATH = "/epz/order/notice/ea20/view/common-info.html"
DOCUMENTS_PATH = "/epz/order/notice/zk20/view/documents.html"
DOCUMENTS_EA_PATH = "/epz/order/notice/ea20/view/documents.html"
VERSION_PATH = "/epz/order/notice/printForm/viewByVersionNumber.html"
NOTICE_SECTION = "Извещение, изменение извещения о проведении запроса котировок в электронной форме"
NOTICE_KINDS = {
    "zk20": (
        NOTICE_SECTION,
        "Извещение о проведении запроса котировок в электронной форме",
        "Запрос котировок в электронной форме",
    ),
    "ea20": (
        "Извещение, изменение извещения о проведении электронного аукциона",
        "Извещение о проведении электронного аукциона",
        "Электронный аукцион",
    ),
}
T = TypeVar("T")


@dataclass(frozen=True)
class CardSnapshot:
    url: str
    final_url: str
    http_status: int
    requested_at: datetime
    checked_at: datetime
    content: bytes
    headers: tuple[tuple[str, str], ...] = ()
    # Ordered redirect targets; the requested URL is not included.
    redirect_chain: tuple[str, ...] = ()


@dataclass(frozen=True)
class CardReceipt:
    url: str
    final_url: str
    http_status: int
    requested_at: datetime
    checked_at: datetime
    content_sha256: str
    observation_sha256: str
    headers: tuple[tuple[str, str], ...]
    redirect_chain: tuple[str, ...]
    reasons: tuple[str, ...]
    scope: Literal["VISIBLE_CARD_ONLY"] = "VISIBLE_CARD_ONLY"
    history_completeness: Literal["UNKNOWN"] = "UNKNOWN"


@dataclass(frozen=True)
class CardFact(Generic[T]):
    value: T
    source_sha256: str
    locator: str


@dataclass(frozen=True)
class ContractCard:
    registry_number: CardFact[str]
    version: CardFact[int]
    version_date: CardFact[date]
    status: CardFact[str]
    purchase_number: CardFact[str]
    price: CardFact[Decimal]
    signed_on: CardFact[date]
    currency: CardFact[Literal["RUB"]]
    receipt: CardReceipt


@dataclass(frozen=True)
class NoticeCard:
    purchase_number: CardFact[str]
    status: CardFact[str]
    initial: CardFact[Decimal]
    currency: CardFact[Literal["RUB"]]
    receipt: CardReceipt
    version: None = None
    reasons: tuple[str, ...] = ("NOTICE_COMMON_INFO_VERSION_UNCONFIRMED",)


@dataclass(frozen=True)
class NoticeDocumentsCard:
    purchase_number: CardFact[str]
    version: CardFact[int]
    version_url: CardFact[str]
    status: CardFact[str]
    initial: CardFact[Decimal]
    currency: CardFact[Literal["RUB"]]
    receipt: CardReceipt


def _number(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{19,23}", value):
        raise ValueError("CARD_NUMBER_INVALID")


def _url(url: str, paths: set[str], key: str, number: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "zakupki.gov.ru"
        or parsed.path not in paths
        or parsed.fragment
        or parse_qsl(parsed.query, keep_blank_values=True) != [(key, number)]
    ):
        raise ValueError("CARD_URL_MISMATCH")


def _receipt(snapshot: CardSnapshot, number: str, kind: str) -> CardReceipt:
    _number(number)
    if (
        snapshot.requested_at.tzinfo is None
        or snapshot.requested_at.utcoffset() is None
        or snapshot.checked_at.tzinfo is None
        or snapshot.checked_at.utcoffset() is None
        or snapshot.checked_at < snapshot.requested_at
    ):
        raise ValueError("CARD_CAPTURE_TIME_INVALID")
    if snapshot.http_status != 200:
        raise ValueError("CARD_HTTP_STATUS_INVALID")
    if not isinstance(snapshot.content, bytes) or not 0 < len(snapshot.content) <= MAX_CARD_BYTES:
        raise ValueError("CARD_CONTENT_SIZE_INVALID")
    paths = {CONTRACT_PATH} if kind == "contract" else {DOCUMENTS_PATH, DOCUMENTS_EA_PATH}
    key = "reestrNumber" if kind == "contract" else "regNumber"
    if kind == "notice":
        paths = {NOTICE_PATH, NOTICE_ZK_PATH, NOTICE_EA_PATH}
    _url(snapshot.url, paths, key, number)
    _url(snapshot.final_url, paths, key, number)
    redirected = snapshot.url != snapshot.final_url
    if redirected and not (
        kind == "notice"
        and urlsplit(snapshot.url).path == NOTICE_PATH
        and urlsplit(snapshot.final_url).path == NOTICE_ZK_PATH
    ):
        raise ValueError("CARD_REDIRECT_UNSUPPORTED")
    if snapshot.redirect_chain != ((snapshot.final_url,) if redirected else ()):
        raise ValueError("CARD_REDIRECT_CHAIN_UNCONFIRMED")
    retained: dict[str, str] = {}
    for name, value in snapshot.headers:
        normalized = name.lower()
        if normalized not in {"content-type", "date", "age", "cache-control", "warning"}:
            continue
        if normalized in retained or len(value) > 4096 or "\n" in value or "\r" in value:
            raise ValueError("CARD_HEADERS_AMBIGUOUS")
        retained[normalized] = value.strip()
    reasons: list[str] = []
    content_type = retained.get("content-type")
    if content_type is None:
        reasons.append("CARD_CONTENT_TYPE_UNCONFIRMED")
    elif content_type.split(";", 1)[0].strip().lower() != "text/html":
        raise ValueError("CARD_CONTENT_TYPE_UNSUPPORTED")
    raw_date = retained.get("date")
    try:
        response_date = parsedate_to_datetime(raw_date) if raw_date else None
    except (ValueError, TypeError, OverflowError):
        response_date = None
    if response_date is None or response_date.utcoffset() is None:
        reasons.append("CARD_RESPONSE_DATE_UNCONFIRMED")
    elif not (
        snapshot.requested_at - timedelta(minutes=1)
        <= response_date
        <= snapshot.checked_at + timedelta(minutes=1)
    ):
        reasons.append("CARD_RESPONSE_DATE_OUTSIDE_CAPTURE")
    age = retained.get("age")
    if age is not None:
        if not re.fullmatch(r"[0-9]{1,12}", age):
            reasons.append("CARD_CACHE_AGE_UNCONFIRMED")
        elif int(age) > 0:
            reasons.append("CARD_CACHED_RESPONSE")
    if retained.get("warning"):
        reasons.append("CARD_CACHE_WARNING_PRESENT")
    content_sha = hashlib.sha256(snapshot.content).hexdigest()
    headers = tuple(sorted(retained.items()))
    metadata = {
        "url": snapshot.url,
        "final_url": snapshot.final_url,
        "http_status": snapshot.http_status,
        "requested_at": snapshot.requested_at.isoformat(),
        "checked_at": snapshot.checked_at.isoformat(),
        "content_sha256": content_sha,
        "headers": headers,
        "redirect_chain": snapshot.redirect_chain,
    }
    observation_sha = hashlib.sha256(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return CardReceipt(
        snapshot.url,
        snapshot.final_url,
        snapshot.http_status,
        snapshot.requested_at,
        snapshot.checked_at,
        content_sha,
        observation_sha,
        headers,
        snapshot.redirect_chain,
        tuple(reasons),
    )


def _tree(content: bytes) -> _Node:
    if b"\0" in content:
        raise ValueError("CARD_HTML_INVALID")
    try:
        root = _parse_html(content)
    except ValueError as error:
        raise ValueError("CARD_HTML_INVALID") from error
    pending = [(root, 0)]
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if depth > 100 or count > 100_000:
            raise ValueError("CARD_HTML_COMPLEXITY_LIMIT")
        clean: list[_Node | str] = []
        for child in node.children:
            if isinstance(child, _Node):
                style = re.sub(r"\s+", "", child.attrs.get("style", "")).lower()
                if (
                    child.tag in {"script", "style", "template", "noscript"}
                    or "hidden" in child.attrs
                    or child.attrs.get("aria-hidden", "").lower() == "true"
                    or "display:none" in style
                    or "visibility:hidden" in style
                ):
                    continue
                if (
                    "captcha"
                    in (child.attrs.get("id", "") + " " + child.attrs.get("class", "")).lower()
                ):
                    raise ValueError("CARD_CHALLENGE_PAGE")
                pending.append((child, depth + 1))
            clean.append(child)
        node.children = clean
    visible = root.text().lower()
    if any(
        term in visible
        for term in (
            "подтвердите, что вы не робот",
            "введите код с картинки",
            "access denied",
            "доступ ограничен",
            "доступ заблокирован",
        )
    ):
        raise ValueError("CARD_CHALLENGE_PAGE")
    return root


def _nodes(root: _Node, cls: str) -> list[_Node]:
    return [node for node in root.walk() if cls in node.classes()]


def _one(nodes: list[_Node]) -> _Node:
    if len(nodes) != 1:
        raise ValueError("CARD_FIELD_MISSING_OR_DUPLICATE")
    return nodes[0]


def _field(
    root: _Node, title: str, title_cls: str = "section__title", value_cls: str = "section__info"
) -> _Node:
    matches: list[_Node] = []
    for parent in root.walk():
        titles = [
            child
            for child in parent.children
            if isinstance(child, _Node) and title_cls in child.classes() and child.text() == title
        ]
        if titles:
            if len(titles) != 1:
                raise ValueError("CARD_FIELD_MISSING_OR_DUPLICATE")
            matches.append(
                _one(
                    [
                        child
                        for child in parent.children
                        if isinstance(child, _Node) and value_cls in child.classes()
                    ]
                )
            )
    return _one(matches)


def _summary(root: _Node, title: str) -> _Node:
    return _field(root, title, "cardMainInfo__title", "cardMainInfo__content")


def _fact(receipt: CardReceipt, value: T, locator: str) -> CardFact[T]:
    return CardFact(value, receipt.content_sha256, locator)


def _date(value: str) -> date:
    if not re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}", value):
        raise ValueError("CARD_DATE_INVALID")
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError as error:
        raise ValueError("CARD_DATE_INVALID") from error


def _money(value: str, *, rub: bool = False) -> Decimal:
    if rub:
        if not value.endswith(" ₽"):
            raise ValueError("CARD_CURRENCY_UNCONFIRMED")
        value = value[:-2]
    if not re.fullmatch(r"(?:[0-9]{1,3}(?: [0-9]{3})+|[0-9]{1,30}),[0-9]{2}", value):
        raise ValueError("CARD_PRICE_INVALID")
    amount = Decimal(value.replace(" ", "").replace(",", "."))
    if amount <= 0 or len(amount.as_tuple().digits) > 30:
        raise ValueError("CARD_PRICE_INVALID")
    return amount


def _equal(left: object, right: object) -> None:
    if left != right:
        raise ValueError("CARD_FIELDS_CONTRADICT")


def _purchase_header(root: _Node, number: str) -> None:
    text = _one(_nodes(root, "cardMainInfo__purchaseLink")).text()
    _equal(text, f"№ {number}")


def parse_contract_card(snapshot: CardSnapshot, expected_registry_number: str) -> ContractCard:
    receipt = _receipt(snapshot, expected_registry_number, "contract")
    root = _tree(snapshot.content)
    headers = [node for node in _nodes(root, "navBreadcrumb__text") if "№" in node.text()]
    header = _one(headers).text()
    match = re.fullmatch(
        r"№\s*([0-9]{19,23})\s*\(Версия №\s*([0-9]{1,6}) от "
        r"([0-9]{2}\.[0-9]{2}\.[0-9]{4}), действующая версия\)",
        header,
    )
    if match is None:
        raise ValueError("CONTRACT_CURRENT_VERSION_UNCONFIRMED")
    _equal(match[1], expected_registry_number)
    _purchase_header(root, expected_registry_number)
    _equal(
        _field(root, "Реестровый номер контракта").text().replace(" ", ""), expected_registry_number
    )
    status = _field(root, "Статус контракта").text()
    if status not in {"Исполнение", "Исполнение завершено"}:
        raise ValueError("CONTRACT_STATUS_UNSUPPORTED")
    _equal(status, _one(_nodes(root, "cardMainInfo__state")).text())
    notice_node = _field(root, "Номер извещения об осуществлении закупки")
    notice = notice_node.text()
    _number(notice)
    link = _one([node for node in notice_node.walk() if node.tag == "a"])
    _url(urljoin(ORIGIN, link.attrs.get("href", "")), {NOTICE_PATH}, "regNumber", notice)
    price = _money(_field(root, "Цена контракта").text())
    _equal(price, _money(_summary(root, "Цена контракта").text(), rub=True))
    signed = _date(_field(root, "Дата заключения контракта").text())
    _equal(signed, _date(_summary(root, "Заключение контракта").text()))
    _equal(_field(root, "Валюта контракта").text(), "РОССИЙСКИЙ РУБЛЬ (₽)")
    return ContractCard(
        _fact(receipt, match[1], ".navBreadcrumb__text / registry-number"),
        _fact(receipt, int(match[2]), ".navBreadcrumb__text / current-version"),
        _fact(receipt, _date(match[3]), ".navBreadcrumb__text / version-date"),
        _fact(receipt, status, ".section__title[Статус контракта] + .section__info"),
        _fact(receipt, notice, ".section__title[Номер извещения об осуществлении закупки]"),
        _fact(receipt, price, ".section__title[Цена контракта] + .section__info"),
        _fact(receipt, signed, ".section__title[Дата заключения контракта] + .section__info"),
        _fact(receipt, "RUB", ".section__title[Валюта контракта] + .section__info"),
        receipt,
    )


def _notice_identity(root: _Node, number: str) -> None:
    header = _one([node for node in _nodes(root, "navBreadcrumb__text") if "№" in node.text()])
    _equal(header.text(), f"№ {number}")
    _purchase_header(root, number)


def _notice_summary(root: _Node) -> tuple[str, Decimal]:
    status = _one(_nodes(root, "cardMainInfo__state")).text()
    # Completion of supplier selection does not imply contract execution.
    if status != "Определение поставщика завершено":
        raise ValueError("NOTICE_STATUS_UNSUPPORTED")
    price = _money(_summary(root, "Начальная цена").text(), rub=True)
    # The documents tab normally has no detail section. If supplied, it must
    # agree with the summary; duplicate/partial fields must not be ignored.
    details = {
        "Этап закупки": status,
        "Начальная (максимальная) цена контракта": price,
        "Валюта": "РОССИЙСКИЙ РУБЛЬ",
    }
    for title, expected in details.items():
        if any(node.text() == title for node in _nodes(root, "section__title")):
            text = _field(root, title).text()
            _equal(_money(text) if isinstance(expected, Decimal) else text, expected)
    return status, price


def parse_notice_card(snapshot: CardSnapshot, expected_purchase_number: str) -> NoticeCard:
    receipt = _receipt(snapshot, expected_purchase_number, "notice")
    root = _tree(snapshot.content)
    _notice_identity(root, expected_purchase_number)
    status, price = _notice_summary(root)
    method = _field(root, "Способ определения поставщика (подрядчика, исполнителя)").text()
    path = urlsplit(snapshot.final_url).path
    expected_method = {
        NOTICE_ZK_PATH: NOTICE_KINDS["zk20"][2],
        NOTICE_EA_PATH: NOTICE_KINDS["ea20"][2],
    }.get(path)
    if expected_method is not None:
        _equal(method, expected_method)
    elif method not in {kind[2] for kind in NOTICE_KINDS.values()}:
        raise ValueError("NOTICE_KIND_UNSUPPORTED")
    _equal(status, _field(root, "Этап закупки").text())
    _equal(price, _money(_field(root, "Начальная (максимальная) цена контракта").text()))
    _equal(_field(root, "Валюта").text(), "РОССИЙСКИЙ РУБЛЬ")
    return NoticeCard(
        _fact(receipt, expected_purchase_number, ".navBreadcrumb__text"),
        _fact(receipt, status, ".section__title[Этап закупки] + .section__info"),
        _fact(receipt, price, ".section__title[Начальная (максимальная) цена контракта]"),
        _fact(receipt, "RUB", ".section__title[Валюта] + .section__info"),
        receipt,
    )


def parse_notice_documents_card(
    snapshot: CardSnapshot,
    expected_purchase_number: str,
) -> NoticeDocumentsCard:
    receipt = _receipt(snapshot, expected_purchase_number, "documents")
    root = _tree(snapshot.content)
    _notice_identity(root, expected_purchase_number)
    status, price = _notice_summary(root)
    kind = {DOCUMENTS_PATH: "zk20", DOCUMENTS_EA_PATH: "ea20"}[urlsplit(snapshot.final_url).path]
    section_title, document_title, _ = NOTICE_KINDS[kind]
    sections = [
        node
        for node in _nodes(root, "blockInfo")
        if any(
            isinstance(child, _Node)
            and "blockInfo__title" in child.classes()
            and child.text() == section_title
            for child in node.children
        )
    ]
    section = _one(sections)
    current: list[_Node] = []
    for row in _nodes(section, "notice-documents"):
        revision = _field(row, "Редакция", "section__attrib", "section__value").text()
        if revision == "Действующая":
            current.append(row)
        elif revision != "Недействующая":
            raise ValueError("NOTICE_DOCUMENT_REVISION_UNSUPPORTED")
    row = _one(current)
    name = _one(_nodes(row, "docName")).text()
    if not re.fullmatch(
        re.escape(document_title)
        + r" от [0-9]{2}\.[0-9]{2}\.[0-9]{4} №\s*"
        + expected_purchase_number,
        name,
    ):
        raise ValueError("NOTICE_DOCUMENT_IDENTITY_UNCONFIRMED")
    links = [
        node
        for node in row.walk()
        if node.tag == "a" and VERSION_PATH in node.attrs.get("href", "")
    ]
    link = _one(links)
    url = urljoin(ORIGIN, link.attrs["href"])
    parsed = urlsplit(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "zakupki.gov.ru"
        or parsed.path != VERSION_PATH
        or parsed.fragment
        or len(query) != 3
        or dict(query).get("regNumber") != expected_purchase_number
        or dict(query).get("qualifier") != "regNumberAndVersion"
        or not re.fullmatch(r"[0-9]{1,6}", dict(query).get("versionNumber", ""))
    ):
        raise ValueError("NOTICE_DOCUMENT_VERSION_URL_INVALID")
    version = int(dict(query)["versionNumber"])
    return NoticeDocumentsCard(
        _fact(receipt, expected_purchase_number, ".navBreadcrumb__text"),
        _fact(receipt, version, ".notice-documents[Редакция=Действующая] a@versionNumber"),
        _fact(receipt, url, ".notice-documents[Редакция=Действующая] a@href"),
        _fact(receipt, status, ".cardMainInfo__state"),
        _fact(receipt, price, ".cardMainInfo__title[Начальная цена] + .cardMainInfo__content"),
        _fact(receipt, "RUB", ".cardMainInfo__title[Начальная цена] + .cardMainInfo__content / ₽"),
        receipt,
    )
