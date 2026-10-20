"""Bounded public SERP observations; links are unverified, never supplier facts."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from playwright.async_api import Page

MAX_DOM_BYTES = 8 * 1024 * 1024
SUFFIX = "производитель поставщик купить оптом"


class SearchEngine(StrEnum):
    BING = "BING"
    BRAVE = "BRAVE"
    DUCKDUCKGO = "DUCKDUCKGO"
    MOJEEK = "MOJEEK"
    YANDEX = "YANDEX"
    GOOGLE = "GOOGLE"


ENGINES = (SearchEngine.BING, SearchEngine.YANDEX, SearchEngine.GOOGLE)
LEGACY_ENGINES = ENGINES
HISTORICAL_EXPANDED_ENGINES = tuple(SearchEngine)
BASE_URLS = {
    SearchEngine.BING: "https://www.bing.com/search",
    SearchEngine.BRAVE: "https://search.brave.com/search",
    SearchEngine.DUCKDUCKGO: "https://html.duckduckgo.com/html/",
    SearchEngine.MOJEEK: "https://www.mojeek.com/search",
    SearchEngine.YANDEX: "https://yandex.ru/search/",
    SearchEngine.GOOGLE: "https://www.google.com/search",
}
ASSET_HOSTS = {
    SearchEngine.BING: ("bing.com", "bing.net"),
    SearchEngine.YANDEX: ("yandex.ru", "yastatic.net"),
    SearchEngine.GOOGLE: ("google.com", "gstatic.com"),
}
Status = Literal[
    "COMPLETED",
    "EMPTY",
    "BLOCKED",
    "RATE_LIMITED",
    "TIMEOUT",
    "SOURCE_CHANGED",
    "SOURCE_ERROR",
    "BROWSER_UNAVAILABLE",
    "COOLDOWN",
]
Reason = Literal[
    "ORGANIC_LINKS_FOUND",
    "EXPLICIT_EMPTY",
    "ACCESS_BLOCKED",
    "RATE_LIMITED",
    "TIMEOUT",
    "DOM_LIMIT",
    "QUERY_BINDING_INVALID",
    "ORGANIC_STRUCTURE_UNVERIFIED",
    "SOURCE_ERROR",
    "BROWSER_UNAVAILABLE",
    "BATCH_TIMEOUT",
    "ENGINE_COOLDOWN",
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SerpLink(FrozenModel):
    rank: int = Field(ge=1, le=50, strict=True)
    title: str = Field(min_length=1, max_length=300)
    snippet: str = Field(max_length=1200)
    url: str = Field(max_length=2048)
    dom_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1, max_length=256)
    role_status: Literal["UNKNOWN"] = "UNKNOWN"
    price_status: Literal["UNKNOWN"] = "UNKNOWN"
    technical_status: Literal["UNKNOWN"] = "UNKNOWN"

    @field_validator("url")
    @classmethod
    def public_url(cls, value: str) -> str:
        if safe_public_url(value) != value:
            raise ValueError("LINK_URL_INVALID")
        return value


class EngineAttempt(FrozenModel):
    engine: SearchEngine
    query: str = Field(min_length=1, max_length=240)
    source_url: str = Field(max_length=2048)
    observed_at: AwareDatetime
    status: Status
    reason_code: Reason
    dom_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    byte_count: int | None = Field(default=None, ge=1, le=MAX_DOM_BYTES, strict=True)
    links: tuple[SerpLink, ...] = Field(default=(), max_length=10)
    scanned_count: int = Field(default=0, ge=0, le=50, strict=True)
    returned_count: int = Field(default=0, ge=0, le=10, strict=True)
    truncated: bool = Field(default=False, strict=True)
    elapsed_ms: int = Field(default=0, ge=0, le=90000, strict=True)
    browser_navigation_count: Literal[0, 1] = 0

    @field_validator("browser_navigation_count", mode="before")
    @classmethod
    def strict_navigation(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("NAVIGATION_INVALID")
        return value

    @model_validator(mode="after")
    def consistent(self) -> EngineAttempt:
        if self.source_url != source_url(self.engine, self.query):
            raise ValueError("SOURCE_URL_INVALID")
        if self.returned_count != len(self.links):
            raise ValueError("LINK_COUNT_INVALID")
        if (self.dom_sha256 is None) != (self.byte_count is None):
            raise ValueError("DOM_BINDING_INVALID")
        if self.links and (self.status != "COMPLETED" or self.scanned_count < len(self.links)):
            raise ValueError("LINK_STATUS_INVALID")
        if self.status == "COMPLETED" and not self.links:
            raise ValueError("EMPTY_COMPLETED_INVALID")
        if any(link.dom_sha256 != self.dom_sha256 for link in self.links):
            raise ValueError("LINK_DOM_INVALID")
        ranks = [link.rank for link in self.links]
        if ranks != sorted(set(ranks)) or len({link.url for link in self.links}) != len(self.links):
            raise ValueError("LINK_ORDER_INVALID")
        prefixes = {
            SearchEngine.BING: 'locator("li.b_algo").nth(',
            SearchEngine.BRAVE: 'locator("#results .snippet[data-type=web]").nth(',
            SearchEngine.DUCKDUCKGO: (
                'locator(".result.results_links.web-result:not(.result--ad)").nth('
            ),
            SearchEngine.MOJEEK: (
                'locator("ul.results-standard > li:not(.ad):not(.sponsored)").nth('
            ),
            SearchEngine.YANDEX: (
                'locator("li.serp-item").nth(',
                "locator(\"ul[aria-label='Результаты поиска'] > li\").nth(",
            ),
            SearchEngine.GOOGLE: 'locator("#search a:has(h3)").nth(',
        }
        prefix = prefixes.get(self.engine)
        allowed_prefixes = prefix if isinstance(prefix, tuple) else (prefix,)
        if self.links and (
            prefix is None
            or any(
                not any(link.locator.startswith(value) for value in allowed_prefixes)
                for link in self.links
            )
        ):
            raise ValueError("LOCATOR_INVALID")
        reasons = {
            "COMPLETED": {"ORGANIC_LINKS_FOUND"},
            "EMPTY": {"EXPLICIT_EMPTY"},
            "BLOCKED": {"ACCESS_BLOCKED"},
            "RATE_LIMITED": {"RATE_LIMITED"},
            "TIMEOUT": {"TIMEOUT", "BATCH_TIMEOUT"},
            "SOURCE_CHANGED": {
                "DOM_LIMIT",
                "QUERY_BINDING_INVALID",
                "ORGANIC_STRUCTURE_UNVERIFIED",
            },
            "SOURCE_ERROR": {"SOURCE_ERROR"},
            "BROWSER_UNAVAILABLE": {"BROWSER_UNAVAILABLE"},
            "COOLDOWN": {"ENGINE_COOLDOWN"},
        }
        if self.reason_code not in reasons[self.status]:
            raise ValueError("STATUS_REASON_INVALID")
        if self.status in {"COMPLETED", "EMPTY"} and self.dom_sha256 is None:
            raise ValueError("DOM_REQUIRED")
        if self.status in {"COMPLETED", "EMPTY"} and self.browser_navigation_count != 1:
            raise ValueError("NAVIGATION_REQUIRED")
        if self.status not in {"COMPLETED", "EMPTY"} and (
            self.links or self.scanned_count or self.truncated
        ):
            raise ValueError("FAILED_RESULT_INVALID")
        if self.status in {"COOLDOWN", "BROWSER_UNAVAILABLE"} and (
            self.browser_navigation_count or self.dom_sha256
        ):
            raise ValueError("UNAVAILABLE_EVIDENCE_INVALID")
        return self


class SearchBatch(FrozenModel):
    query: str = Field(max_length=240)
    attempts: tuple[EngineAttempt, ...] = Field(min_length=3, max_length=6)
    status: Literal["COMPLETED", "PARTIAL", "UNAVAILABLE"]
    coverage: Literal["UNKNOWN"] = "UNKNOWN"
    supplierpage_requests: Literal[0] = 0

    @model_validator(mode="after")
    def consistent(self) -> SearchBatch:
        _query(self.query)
        order = tuple(a.engine for a in self.attempts)
        if order not in {ENGINES, HISTORICAL_EXPANDED_ENGINES}:
            raise ValueError("ENGINE_ORDER_INVALID")
        if any(a.query != self.query for a in self.attempts):
            raise ValueError("QUERY_BINDING_INVALID")
        done = sum(a.status in {"COMPLETED", "EMPTY"} for a in self.attempts)
        expected = (
            "COMPLETED" if done == len(self.attempts) else "PARTIAL" if done else "UNAVAILABLE"
        )
        if self.status != expected:
            raise ValueError("BATCH_STATUS_INVALID")
        return self


@dataclass(frozen=True)
class SerpCapture:
    batch: SearchBatch
    contents: tuple[bytes | None, ...]

    def __post_init__(self) -> None:
        if len(self.contents) != len(self.batch.attempts):
            raise ValueError("CONTENT_COUNT_INVALID")
        for attempt, content in zip(self.batch.attempts, self.contents, strict=True):
            if content is None:
                if attempt.dom_sha256 is not None:
                    raise ValueError("CONTENT_MISSING")
            elif type(content) is not bytes or not 1 <= len(content) <= MAX_DOM_BYTES:
                raise ValueError("CONTENT_INVALID")
            elif (
                len(content) != attempt.byte_count
                or hashlib.sha256(content).hexdigest() != attempt.dom_sha256
            ):
                raise ValueError("CONTENT_BINDING_INVALID")


def build_supplier_query(public_position_name: str) -> str:
    if not isinstance(public_position_name, str) or any(
        unicodedata.category(c).startswith("C") for c in public_position_name
    ):
        raise ValueError("PUBLIC_POSITION_INVALID")
    name = " ".join(public_position_name.split())
    if not name or len(name) > 150 or name.casefold() in {"unknown", "неизвестно", "n/a"}:
        raise ValueError("PUBLIC_POSITION_INVALID")
    return f"{name} {SUFFIX}"


def _query(query: str) -> str:
    suffix = f" {SUFFIX}"
    if not query.endswith(suffix) or build_supplier_query(query[: -len(suffix)]) != query:
        raise ValueError("PUBLIC_QUERY_INVALID")
    return query


def source_url(engine: SearchEngine, query: str) -> str:
    return (
        BASE_URLS[engine]
        + "?"
        + urlencode({"text" if engine == SearchEngine.YANDEX else "q": _query(query)})
    )


def _host_under(host: str, roots: tuple[str, ...]) -> bool:
    return any(host == root or host.endswith("." + root) for root in roots)


def safe_public_url(value: str) -> str | None:
    try:
        if len(value) > 2048 or any(ord(c) < 33 for c in value) or "\\" in value:
            return None
        parts = urlsplit(value)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower()
        if parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.port:
            return None
        if (
            not host
            or "." not in host
            or host.endswith(
                (
                    ".local",
                    ".localhost",
                    ".lan",
                    ".internal",
                    ".test",
                    ".invalid",
                    ".example",
                    ".onion",
                )
            )
        ):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
            return None
        if not any(c.isalpha() for c in host.rsplit(".", 1)[-1]):
            return None
        if _host_under(
            host,
            (
                "bing.com",
                "bing.net",
                "brave.com",
                "duckduckgo.com",
                "mojeek.com",
                "google.com",
                "yandex.ru",
                "yandex.com",
                "gstatic.com",
                "yastatic.net",
            ),
        ):
            return None
        return urlunsplit((parts.scheme, host, parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError):
        return None


def _link_url(value: str, engine: SearchEngine = SearchEngine.BING) -> str | None:
    try:
        parts = urlsplit(value)
        if (
            engine == SearchEngine.BING
            and parts.scheme == "https"
            and parts.hostname in {"www.bing.com", "bing.com"}
            and parts.path == "/ck/a"
        ):
            values = parse_qs(parts.query).get("u", [])
            if len(values) != 1 or not values[0].startswith("a1"):
                return None
            encoded = values[0][2:]
            value = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            ).decode("utf-8")
        elif engine == SearchEngine.GOOGLE and (
            (not parts.scheme and value.startswith("/url?"))
            or (
                parts.scheme == "https"
                and _host_under((parts.hostname or "").lower(), ("google.com",))
                and parts.path == "/url"
            )
        ):
            query_values = parse_qs(parts.query).get("q", [])
            url_values = parse_qs(parts.query).get("url", [])
            if query_values and url_values:
                return None
            values = query_values or url_values
            if len(values) != 1:
                return None
            value = values[0]
        elif engine == SearchEngine.YANDEX and (
            (not parts.scheme and value.startswith("/clck/"))
            or (
                parts.scheme == "https"
                and _host_under((parts.hostname or "").lower(), ("yandex.ru", "yandex.com"))
                and parts.path.startswith("/clck/")
            )
        ):
            values = parse_qs(parts.query).get("url", [])
            if len(values) != 1:
                return None
            value = values[0]
        return safe_public_url(value)
    except (ValueError, UnicodeError):
        return None


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
    "track",
    "wbr",
}
_NON_VISIBLE_TAGS = {"script", "style", "template", "noscript"}


@dataclass
class _HtmlNode:
    tag: str
    attrs: dict[str, str]
    parent: _HtmlNode | None
    children: list[_HtmlNode]
    content: list[str | _HtmlNode]


class _TreeParser(HTMLParser):
    """Small inert HTML tree used only for conservative selector matching."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("document", {}, None, [], [])
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HtmlNode(
            tag.casefold(),
            {key.casefold(): value or "" for key, value in attrs},
            self.stack[-1],
            [],
            [],
        )
        self.stack[-1].children.append(node)
        self.stack[-1].content.append(node)
        if node.tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag.casefold():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        folded = tag.casefold()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == folded:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].content.append(data)


def _walk(node: _HtmlNode):
    for child in node.children:
        yield child
        yield from _walk(child)


def _classes(node: _HtmlNode) -> set[str]:
    return {value.casefold() for value in node.attrs.get("class", "").split()}


def _hidden(node: _HtmlNode) -> bool:
    current: _HtmlNode | None = node
    while current is not None:
        style = current.attrs.get("style", "").casefold().replace(" ", "")
        if (
            current.tag in _NON_VISIBLE_TAGS
            or "hidden" in current.attrs
            or current.attrs.get("aria-hidden", "").casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            return True
        current = current.parent
    return False


def _text(node: _HtmlNode) -> str:
    if _hidden(node):
        return ""
    values = [
        value if isinstance(value, str) else "" if value.tag in _NON_VISIBLE_TAGS else _text(value)
        for value in node.content
    ]
    return " ".join(" ".join(values).split())


def _ancestor(node: _HtmlNode, tag: str, stop: _HtmlNode | None = None) -> _HtmlNode | None:
    current = node.parent
    while current is not None and current is not stop:
        if current.tag == tag:
            return current
        current = current.parent
    return None


def _descendant(node: _HtmlNode, *, tag: str | None = None, classes: set[str] | None = None):
    for child in _walk(node):
        if (tag is None or child.tag == tag) and (
            classes is None or bool(_classes(child) & classes)
        ):
            yield child


def _excluded(node: _HtmlNode, *, stop: _HtmlNode | None = None) -> bool:
    ids = {"tads", "tadsb", "bottomads", "rhs", "botstuff", "bres"}
    exact_classes = {
        "ad",
        "ads-ad",
        "advlabel",
        "directlabel",
        "commercial-unit-desktop-top",
        "cu-container",
        "g-scrolling-carousel",
        "knowledge-panel",
        "kp-wholepage",
        "pla-unit",
        "related-question-pair",
        "ueierd",
    }
    current: _HtmlNode | None = node
    while current is not None and current is not stop:
        classes = _classes(current)
        fast_name = current.attrs.get("data-fast-name", "").casefold()
        if (
            current.attrs.get("id", "").casefold() in ids
            or bool(classes & exact_classes)
            or any(
                "sponsored" in value or "advert" in value or value.startswith("ad-")
                for value in classes
            )
            or fast_name in {"ad", "adv", "direct"}
            or "data-ad" in current.attrs
            or "data-text-ad" in current.attrs
        ):
            return True
        current = current.parent
    return False


def _input_values(root: _HtmlNode, engine: SearchEngine) -> list[str]:
    values: list[str] = []
    for node in _walk(root):
        if node.tag not in {"input", "textarea"}:
            continue
        name = node.attrs.get("name", "")
        node_id = node.attrs.get("id", "")
        matched = (engine == SearchEngine.GOOGLE and (name == "q" or node_id == "APjFqb")) or (
            engine == SearchEngine.YANDEX and (name == "text" or node_id == "text")
        )
        if matched:
            values.append(node.attrs.get("value", "") if node.tag == "input" else _text(node))
    return values


def _snippet(container: _HtmlNode, class_names: set[str]) -> str:
    folded = {value.casefold() for value in class_names}
    for node in _descendant(container, classes=folded):
        value = _text(node)
        if value:
            return value
    return ""


def _google_rows(root: _HtmlNode) -> tuple[list[tuple[str, str, str, bool]], bool]:
    searches = [node for node in _walk(root) if node.attrs.get("id") == "search"]
    rows: list[tuple[str, str, str, bool]] = []
    if len(searches) == 1:
        search = searches[0]
        for anchor in _descendant(search, tag="a"):
            headings = [node for node in _descendant(anchor, tag="h3")]
            if not headings:
                continue
            heading = headings[0]
            container = anchor.parent or search
            current = anchor.parent
            while current is not None and current is not search:
                if _classes(current) & {"g", "tf2cxc", "mjjyud"}:
                    container = current
                    break
                current = current.parent
            rows.append(
                (
                    anchor.attrs.get("href", ""),
                    _text(heading),
                    _snippet(container, {"VwiC3b", "IsZvec"}),
                    not _hidden(anchor) and not _excluded(anchor, stop=search),
                )
            )
    empty = False
    for node in _walk(root):
        if node.attrs.get("id", "").casefold() != "topstuff" or _hidden(node):
            continue
        value = _text(node).casefold()
        empty = any(
            marker in value
            for marker in (
                "did not match any documents",
                "no results found for",
                "ничего не найдено",
                "не найдено ни одного результата",
            )
        )
        if empty:
            break
    return rows, empty


def _yandex_rows(
    root: _HtmlNode,
) -> tuple[list[tuple[str, str, str, bool, str, str]], bool]:
    rows: list[tuple[str, str, str, bool, str, str]] = []
    result_lists = [
        node
        for node in _walk(root)
        if node.tag == "ul" and node.attrs.get("aria-label") == "Результаты поиска"
    ]
    if len(result_lists) == 1:
        for item in (node for node in result_lists[0].children if node.tag == "li"):
            organics = [
                node for node in item.children if node.tag == "div" and "organic" in _classes(node)
            ]
            organic = organics[0] if len(organics) == 1 else None
            titles = (
                [
                    node
                    for node in organic.children
                    if node.tag == "div"
                    and "organictitle" in _classes(node)
                    and node.attrs.get("data-initer") == "OrganicHeader"
                ]
                if organic is not None
                else []
            )
            title = titles[0] if len(titles) == 1 else None
            anchors = (
                [
                    node
                    for node in title.children
                    if node.tag == "a" and "organictitle-link" in _classes(node)
                ]
                if title is not None
                else []
            )
            anchor = anchors[0] if len(anchors) == 1 else None
            headings = (
                [
                    node
                    for node in anchor.children
                    if node.tag == "h2" and "organictitle-linktext" in _classes(node)
                ]
                if anchor is not None
                else []
            )
            heading = headings[0] if len(headings) == 1 else None
            row_excluded = (
                _hidden(item)
                or _excluded(item)
                or any(_excluded(node, stop=item) for node in _walk(item))
            )
            rows.append(
                (
                    anchor.attrs.get("href", "") if anchor is not None else "",
                    _text(heading) if heading is not None else "",
                    _snippet(organic, {"OrganicTextContentSpan"}) if organic is not None else "",
                    heading is not None
                    and not row_excluded
                    and not _hidden(anchor)
                    and not _hidden(heading),
                    "a:has(h2)",
                    "ul[aria-label='Результаты поиска'] > li",
                )
            )
    else:
        for item in _walk(root):
            if item.tag != "li" or "serp-item" not in _classes(item):
                continue
            headings = [node for node in _descendant(item, tag="h2")]
            heading = headings[0] if headings else None
            anchor = next(_descendant(heading, tag="a"), None) if heading is not None else None
            shape = "h2 a"
            if heading is not None and anchor is None:
                anchor = _ancestor(heading, "a", stop=item)
                shape = "a:has(h2)"
            row_excluded = _hidden(item) or _excluded(item)
            if any(_classes(node) & {"advlabel", "directlabel"} for node in _walk(item)):
                row_excluded = True
            rows.append(
                (
                    anchor.attrs.get("href", "") if anchor is not None else "",
                    _text(heading) if heading is not None else "",
                    _snippet(item, {"OrganicTextContentSpan", "TextContainer"}),
                    anchor is not None and not row_excluded and not _hidden(anchor),
                    shape,
                    "li.serp-item",
                )
            )
    empty = False
    empty_classes = {"emptysearchresults", "searchemptyresult", "serp-empty"}
    for node in _walk(root):
        if not (_classes(node) & empty_classes) or _hidden(node):
            continue
        value = _text(node).casefold()
        empty = any(
            marker in value
            for marker in (
                "ничего не нашли",
                "ничего не найдено",
                "результатов не найдено",
                "no results found",
            )
        )
        if empty:
            break
    return rows, empty


class _BingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.rows: list[tuple[str, str, str]] = []
        self.active: int | None = None
        self.href = ""
        self.title: list[str] = []
        self.snippet: list[str] = []
        self.title_depth: int | None = None
        self.caption_depth: int | None = None
        self.inputs: list[str] = []
        self.empty = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        if tag == "input" and attr.get("id") == "sb_form_q":
            self.inputs.append(attr.get("value") or "")
        if tag == "li" and "b_no" in classes:
            self.empty = True
        if tag not in {"input", "meta", "link", "br", "hr", "img", "source", "wbr"}:
            self.stack.append(tag)
        if tag == "li" and "b_algo" in classes and self.active is None:
            self.active = len(self.stack)
            self.href, self.title, self.snippet = "", [], []
        if self.active is not None:
            if tag == "a" and "h2" in self.stack and not self.href:
                self.href = attr.get("href") or ""
                self.title_depth = len(self.stack)
            if tag == "div" and "b_caption" in classes:
                self.caption_depth = len(self.stack)

    def handle_data(self, data: str) -> None:
        if self.active is not None:
            if self.title_depth is not None:
                self.title.append(data)
            if self.caption_depth is not None and "p" in self.stack:
                self.snippet.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.stack:
            return
        depth = len(self.stack) - self.stack[::-1].index(tag)
        if self.active is not None and depth <= self.active:
            self.rows.append(
                (
                    self.href,
                    " ".join("".join(self.title).split()),
                    " ".join("".join(self.snippet).split()),
                )
            )
            self.active = None
        if self.title_depth is not None and depth <= self.title_depth:
            self.title_depth = None
        if self.caption_depth is not None and depth <= self.caption_depth:
            self.caption_depth = None
        del self.stack[depth - 1 :]


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.text: list[str] = []
        self.challenge = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        markers = " ".join(
            (attributes.get(key) or "").casefold() for key in ("id", "class")
        ).split()
        if tag not in {"script", "style", "template", "noscript"} and (
            any(
                marker
                in {
                    "captcha",
                    "b_captcha",
                    "g-recaptcha",
                    "h-captcha",
                    "smart-captcha",
                }
                for marker in markers
            )
            or (
                tag == "iframe"
                and any(
                    marker in (attributes.get("src") or "").casefold()
                    for marker in ("/captcha", "/recaptcha/", "showcaptcha", "/challenge/")
                )
            )
        ):
            self.challenge = True
        if tag in {"script", "style", "template", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.text.append(data)


def _failure(
    engine: SearchEngine,
    query: str,
    status: Status,
    reason: Reason,
    *,
    observed_at: datetime,
    elapsed_ms: int = 0,
    navigation: Literal[0, 1] = 0,
) -> EngineAttempt:
    return EngineAttempt(
        engine=engine,
        query=query,
        source_url=source_url(engine, query),
        observed_at=observed_at,
        status=status,
        reason_code=reason,
        elapsed_ms=elapsed_ms,
        browser_navigation_count=navigation,
    )


def parse_supplier_serp(
    engine: SearchEngine,
    query: str,
    content: bytes,
    *,
    final_url: str,
    observed_at: datetime,
    http_status: int = 200,
    elapsed_ms: int = 0,
) -> EngineAttempt:
    _query(query)
    if engine not in ENGINES:
        raise ValueError("ENGINE_DISABLED")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("OBSERVATION_TIME_INVALID")
    if len(content) > MAX_DOM_BYTES:
        return _failure(
            engine,
            query,
            "SOURCE_CHANGED",
            "DOM_LIMIT",
            observed_at=observed_at,
            elapsed_ms=elapsed_ms,
            navigation=1,
        )
    digest = hashlib.sha256(content).hexdigest()
    text = content.decode("utf-8", errors="replace")
    visible = _VisibleText()
    visible.feed(text)
    folded = " ".join(visible.text).casefold()
    status: Status = "SOURCE_CHANGED"
    reason: Reason = "ORGANIC_STRUCTURE_UNVERIFIED"
    links: list[SerpLink] = []
    scanned = 0
    truncated = False
    parts = urlsplit(final_url)
    expected = urlsplit(source_url(engine, query))
    param = "text" if engine == SearchEngine.YANDEX else "q"
    blocked = any(
        s in folded
        for s in (
            "unusual traffic",
            "подозрительный трафик",
            "подтвердите, что вы не робот",
            "verify you are human",
            'id="captcha',
            "id='captcha",
        )
    )
    if http_status == 429:
        status, reason = "RATE_LIMITED", "RATE_LIMITED"
    elif (
        http_status == 403
        or blocked
        or visible.challenge
        or "/sorry" in parts.path
        or "showcaptcha" in parts.path
    ):
        status, reason = "BLOCKED", "ACCESS_BLOCKED"
    elif (
        parts.scheme != "https"
        or parts.netloc != expected.netloc
        or parts.path != expected.path
        or parse_qs(parts.query).get(param) != [query]
    ):
        reason = "QUERY_BINDING_INVALID"
    elif http_status != 200:
        status, reason = "SOURCE_ERROR", "SOURCE_ERROR"
    elif engine == SearchEngine.BING:
        parser = _BingParser()
        parser.feed(text)
        parser.close()
        scanned = min(50, len(parser.rows))
        truncated = len(parser.rows) > 50
        if any(value != query for value in parser.inputs):
            reason = "QUERY_BINDING_INVALID"
        else:
            seen: set[str] = set()
            for rank, (href, title, snippet) in enumerate(parser.rows, 1):
                url = _link_url(href, engine)
                if rank > 50 or len(links) == 10:
                    truncated = True
                    continue
                if not url or not title or url in seen:
                    continue
                seen.add(url)
                links.append(
                    SerpLink(
                        rank=rank,
                        title=title[:300],
                        snippet=snippet[:1200],
                        url=url,
                        dom_sha256=digest,
                        locator=f'locator("li.b_algo").nth({rank - 1}).locator("h2 a")',
                    )
                )
            if links:
                status, reason = "COMPLETED", "ORGANIC_LINKS_FOUND"
            elif parser.empty and not parser.rows:
                status, reason = "EMPTY", "EXPLICIT_EMPTY"
    elif engine in {SearchEngine.GOOGLE, SearchEngine.YANDEX}:
        parser = _TreeParser()
        parser.feed(text)
        parser.close()
        inputs = _input_values(parser.root, engine)
        if any(value != query for value in inputs):
            reason = "QUERY_BINDING_INVALID"
        else:
            if engine == SearchEngine.GOOGLE:
                raw_rows, empty = _google_rows(parser.root)
                rows = [(*row, "", "") for row in raw_rows]
            else:
                rows, empty = _yandex_rows(parser.root)
            scanned = min(50, len(rows))
            truncated = len(rows) > 50
            seen: set[str] = set()
            for rank, (href, title, snippet, eligible, shape, container) in enumerate(rows, 1):
                if rank > 50 or len(links) == 10:
                    truncated = True
                    continue
                url = _link_url(href, engine)
                if not eligible or not url or not title or url in seen:
                    continue
                seen.add(url)
                locator = (
                    f'locator("#search a:has(h3)").nth({rank - 1})'
                    if engine == SearchEngine.GOOGLE
                    else (
                        f'locator("{container}").nth({rank - 1})'
                        '.locator(":scope > div.Organic > '
                        "div.OrganicTitle[data-initer='OrganicHeader'] > "
                        'a.OrganicTitle-Link:has(> h2.OrganicTitle-LinkText)").first()'
                        if container.startswith("ul[")
                        else f'locator("{container}").nth({rank - 1}).locator("{shape}").first()'
                    )
                )
                links.append(
                    SerpLink(
                        rank=rank,
                        title=title[:300],
                        snippet=snippet[:1200],
                        url=url,
                        dom_sha256=digest,
                        locator=locator,
                    )
                )
            if links:
                status, reason = "COMPLETED", "ORGANIC_LINKS_FOUND"
            elif empty and not any(row[3] for row in rows):
                scanned, truncated = 0, False
                status, reason = "EMPTY", "EXPLICIT_EMPTY"
    if status not in {"COMPLETED", "EMPTY"}:
        scanned, truncated = 0, False
    return EngineAttempt(
        engine=engine,
        query=query,
        source_url=source_url(engine, query),
        observed_at=observed_at,
        status=status,
        reason_code=reason,
        dom_sha256=digest if content else None,
        byte_count=len(content) if content else None,
        links=tuple(links),
        scanned_count=scanned,
        returned_count=len(links),
        truncated=truncated,
        elapsed_ms=elapsed_ms,
        browser_navigation_count=1,
    )


def _batch(query: str, attempts: list[EngineAttempt], contents: list[bytes | None]) -> SerpCapture:
    done = sum(a.status in {"COMPLETED", "EMPTY"} for a in attempts)
    return SerpCapture(
        SearchBatch(
            query=query,
            attempts=tuple(attempts),
            status=("COMPLETED" if done == len(attempts) else "PARTIAL" if done else "UNAVAILABLE"),
        ),
        tuple(contents),
    )


async def _observe(query: str, cooldowns: tuple[SearchEngine, ...]) -> SerpCapture:
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeout
        from playwright.async_api import async_playwright
    except ImportError:
        return _batch(
            query,
            [
                _failure(
                    engine,
                    query,
                    "COOLDOWN" if engine in cooldowns else "BROWSER_UNAVAILABLE",
                    "ENGINE_COOLDOWN" if engine in cooldowns else "BROWSER_UNAVAILABLE",
                    observed_at=datetime.now(UTC),
                )
                for engine in ENGINES
            ],
            [None] * len(ENGINES),
        )

    attempts: list[EngineAttempt] = []
    contents: list[bytes | None] = []
    batch_timed_out = False
    active_engine: SearchEngine | None = None
    active_observed = datetime.now(UTC)
    active_tick = time.monotonic()
    navigation: Literal[0, 1] = 0
    try:
        async with asyncio.timeout(75):
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True, timeout=10000)
                try:
                    for engine in ENGINES:
                        observed = datetime.now(UTC)
                        tick = time.monotonic()
                        if engine in cooldowns:
                            attempts.append(
                                _failure(
                                    engine,
                                    query,
                                    "COOLDOWN",
                                    "ENGINE_COOLDOWN",
                                    observed_at=observed,
                                )
                            )
                            contents.append(None)
                            continue
                        active_engine, active_observed, active_tick = engine, observed, tick
                        navigation = 0
                        content: bytes | None = None
                        context = None
                        blocked_redirect = False
                        try:
                            async with asyncio.timeout(20):
                                context = await browser.new_context(
                                    accept_downloads=False, service_workers="block"
                                )
                                page = await context.new_page()

                                async def route_request(
                                    route: object,
                                    *,
                                    selected_engine: SearchEngine = engine,
                                    selected_page: Page = page,
                                ) -> None:
                                    from playwright.async_api import Route

                                    nonlocal blocked_redirect
                                    assert isinstance(route, Route)
                                    request = route.request
                                    parts = urlsplit(request.url)
                                    if request.is_navigation_request() and (
                                        "/sorry" in parts.path or "showcaptcha" in parts.path
                                    ):
                                        blocked_redirect = True
                                    allowed = request_allowed(
                                        selected_engine,
                                        query,
                                        request.url,
                                        request.resource_type,
                                        navigation=request.is_navigation_request(),
                                        main_frame=request.frame == selected_page.main_frame,
                                    )
                                    if allowed:
                                        await route.continue_()
                                    else:
                                        await route.abort()

                                await context.route("**/*", route_request)
                                navigation = 1
                                response = await page.goto(
                                    source_url(engine, query),
                                    wait_until="domcontentloaded",
                                    timeout=19000,
                                )
                                http_status = response.status if response else 0
                                markup = await page.evaluate(
                                    """() => {
                                    const s=document.documentElement.outerHTML;
                                    return new TextEncoder().encode(s).length <= MAX_BYTES
                                        ? s : null;
                                }""".replace("MAX_BYTES", str(MAX_DOM_BYTES))
                                )
                                if not isinstance(markup, str):
                                    attempt = _failure(
                                        engine,
                                        query,
                                        "SOURCE_CHANGED",
                                        "DOM_LIMIT",
                                        observed_at=observed,
                                        navigation=1,
                                    )
                                else:
                                    content = markup.encode("utf-8")
                                    attempt = parse_supplier_serp(
                                        engine,
                                        query,
                                        content,
                                        final_url=page.url,
                                        observed_at=observed,
                                        http_status=http_status,
                                    )
                        except (TimeoutError, PlaywrightTimeout):
                            attempt = _failure(
                                engine,
                                query,
                                "TIMEOUT",
                                "TIMEOUT",
                                observed_at=observed,
                                navigation=navigation,
                            )
                        except Exception:
                            attempt = _failure(
                                engine,
                                query,
                                "BLOCKED" if blocked_redirect else "SOURCE_ERROR",
                                "ACCESS_BLOCKED" if blocked_redirect else "SOURCE_ERROR",
                                observed_at=observed,
                                navigation=navigation,
                            )
                        finally:
                            if context is not None:
                                try:
                                    async with asyncio.timeout(1):
                                        await context.close()
                                except Exception:
                                    pass
                        if attempt.dom_sha256 is None:
                            content = None
                        attempts.append(
                            attempt.model_copy(
                                update={"elapsed_ms": int((time.monotonic() - tick) * 1000)}
                            )
                        )
                        contents.append(content)
                        active_engine = None
                finally:
                    try:
                        async with asyncio.timeout(1):
                            await browser.close()
                    except Exception:
                        pass
    except TimeoutError:
        batch_timed_out = True
    except Exception:
        pass
    if active_engine is not None:
        attempts.append(
            _failure(
                active_engine,
                query,
                "TIMEOUT" if batch_timed_out else "SOURCE_ERROR",
                "BATCH_TIMEOUT" if batch_timed_out else "SOURCE_ERROR",
                observed_at=active_observed,
                navigation=navigation,
                elapsed_ms=min(90000, int((time.monotonic() - active_tick) * 1000)),
            )
        )
        contents.append(None)
    for engine in ENGINES[len(attempts) :]:
        status: Status = "COOLDOWN" if engine in cooldowns else "BROWSER_UNAVAILABLE"
        reason: Reason = "ENGINE_COOLDOWN" if engine in cooldowns else "BROWSER_UNAVAILABLE"
        if batch_timed_out and engine not in cooldowns:
            status, reason = "TIMEOUT", "BATCH_TIMEOUT"
        attempts.append(_failure(engine, query, status, reason, observed_at=datetime.now(UTC)))
        contents.append(None)
    return _batch(query, attempts, contents)


def request_allowed(
    engine: SearchEngine,
    query: str,
    url: str,
    resource_type: str,
    *,
    navigation: bool,
    main_frame: bool,
) -> bool:
    if engine not in ENGINES:
        return False
    try:
        parts = urlsplit(url)
        allowed = (
            parts.scheme == "https"
            and not parts.username
            and not parts.password
            and not parts.port
            and _host_under(parts.hostname or "", ASSET_HOSTS[engine])
            and resource_type not in {"image", "font", "media"}
            and "/sorry" not in parts.path
            and "showcaptcha" not in parts.path
        )
        return allowed and (not navigation or (main_frame and url == source_url(engine, query)))
    except ValueError:
        return False


def browser_transport_provenance() -> dict[str, str]:
    """Immutable audit metadata; no profile paths, cookies or tenant secrets."""
    headed = "SUPPLIER_SERP_BROWSER_STATE_DIR" in os.environ
    result = {
        "browser_transport_revision": "headed-chrome-cdp-v1" if headed else "fresh-headless-v1",
        "browser_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if headed:
        result["browser_helper_sha256"] = hashlib.sha256(
            Path(__file__).with_name("supplier_serp_browser.py").read_bytes()
        ).hexdigest()
    return result


async def _observe_headed(
    query: str, cooldowns: tuple[SearchEngine, ...], company_id: str, root: Path
) -> SerpCapture:
    from procurement.sources.supplier_serp_browser import capture_headed_serp

    attempts: list[EngineAttempt] = []
    contents: list[bytes | None] = []
    async with asyncio.timeout(75):
        for engine in ENGINES:
            if engine in cooldowns:
                attempts.append(
                    _failure(
                        engine, query, "COOLDOWN", "ENGINE_COOLDOWN", observed_at=datetime.now(UTC)
                    )
                )
                contents.append(None)
                continue
            captured = await capture_headed_serp(company_id, engine, query, root=root)
            if captured.content is not None:
                attempt = parse_supplier_serp(
                    engine,
                    query,
                    captured.content,
                    final_url=captured.final_url,
                    observed_at=captured.observed_at,
                    http_status=captured.http_status,
                    elapsed_ms=captured.elapsed_ms,
                )
                content = captured.content if attempt.dom_sha256 else None
            else:
                status: Status = "COOLDOWN" if captured.status == "BUSY" else captured.status
                reasons: dict[str, Reason] = {
                    "COOLDOWN": "ENGINE_COOLDOWN",
                    "BLOCKED": "ACCESS_BLOCKED",
                    "RATE_LIMITED": "RATE_LIMITED",
                    "TIMEOUT": "TIMEOUT",
                    "BROWSER_UNAVAILABLE": "BROWSER_UNAVAILABLE",
                    "SOURCE_ERROR": "SOURCE_ERROR",
                    "SOURCE_CHANGED": "DOM_LIMIT",
                }
                attempt = _failure(
                    engine,
                    query,
                    status,
                    reasons.get(status, "SOURCE_ERROR"),
                    observed_at=captured.observed_at,
                    navigation=captured.navigation_count,
                    elapsed_ms=captured.elapsed_ms,
                )
                content = None
            attempts.append(attempt)
            contents.append(content)
    return _batch(query, attempts, contents)


def observe_supplier_serp(
    query: str, *, cooldowns: tuple[SearchEngine, ...] = (), company_id: str | None = None
) -> SerpCapture:
    """Observe three public engine pages; no candidate URL is visited."""
    _query(query)
    if any(not isinstance(engine, SearchEngine) for engine in cooldowns):
        raise ValueError("COOLDOWN_INVALID")
    if set(cooldowns) == set(ENGINES):
        return _batch(
            query,
            [
                _failure(
                    engine, query, "COOLDOWN", "ENGINE_COOLDOWN", observed_at=datetime.now(UTC)
                )
                for engine in ENGINES
            ],
            [None] * len(ENGINES),
        )
    # Unclassified errors must propagate: the caller retains STARTED/UNKNOWN.
    # Never erase evidence of dispatched navigation with a fabricated zero-count report.
    with asyncio.Runner() as runner:
        state_dir = os.environ.get("SUPPLIER_SERP_BROWSER_STATE_DIR")
        if state_dir is not None:
            if not state_dir or not Path(state_dir).is_absolute() or not company_id:
                raise ValueError("SUPPLIER_SERP_BROWSER_CONFIG_INVALID")
            return runner.run(_observe_headed(query, cooldowns, company_id, Path(state_dir)))
        return runner.run(_observe(query, cooldowns))
