"""Pure, bounded raw declarations from the observed bumaga-s product layout."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procurement.sources.supplier_page import (
    MAX_BODY_BYTES,
    DeclaredFact,
    PageReadError,
    validate_page_url,
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SupplierCharacteristic(FrozenModel):
    label_raw: str = Field(min_length=1, max_length=150)
    value_raw: str = Field(min_length=1, max_length=500)
    label_locator: str = Field(min_length=1, max_length=200)
    value_locator: str = Field(min_length=1, max_length=200)
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SupplierOrderControl(FrozenModel):
    attribute: str = Field(min_length=1, max_length=80)
    raw_value: str = Field(max_length=150)
    locator: str = Field(min_length=1, max_length=200)
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SupplierProductDetails(FrozenModel):
    revision: Literal["bumaga-s-details-v1"] = "bumaga-s-details-v1"
    source_url: str = Field(max_length=2048)
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["EXTRACTED", "EMPTY", "UNSUPPORTED", "AMBIGUOUS", "LIMIT_EXCEEDED"]
    product_name: DeclaredFact | None = None
    characteristics: tuple[SupplierCharacteristic, ...] = Field(default=(), max_length=16)
    packaging_raw: DeclaredFact | None = None
    contents_raw: DeclaredFact | None = None
    price_basis_raw: DeclaredFact | None = None
    order_controls: tuple[SupplierOrderControl, ...] = Field(default=(), max_length=8)
    price_basis_status: Literal["UNKNOWN"] = "UNKNOWN"
    MOQ_status: Literal["UNKNOWN"] = "UNKNOWN"
    order_step_status: Literal["UNKNOWN"] = "UNKNOWN"
    technical_status: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def evidence(self) -> SupplierProductDetails:
        summaries = (self.product_name, self.packaging_raw, self.contents_raw, self.price_basis_raw)
        if self.status != "EXTRACTED" and any(summaries):
            raise ValueError("SUMMARY_UNVERIFIED")
        if self.status == "EXTRACTED" and self.product_name is None:
            raise ValueError("PRODUCT_NAME_REQUIRED")
        if self.status in {"EMPTY", "UNSUPPORTED", "LIMIT_EXCEEDED"} and (
            self.characteristics or self.order_controls
        ):
            raise ValueError("PARTIAL_EVIDENCE_INVALID")
        facts = (*summaries, *self.characteristics, *self.order_controls)
        if any(fact.html_sha256 != self.html_sha256 for fact in facts if fact is not None):
            raise ValueError("HTML_BINDING_INVALID")
        return self


class _Limit(Exception):
    pass


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | None]
    locator: str
    parent: _Node | None
    hidden: bool
    children: list[_Node | str] = field(default_factory=list)
    explicitly_closed: bool = False
    mismatched_close: bool = False

    def has(self, name: str) -> bool:
        return name in (self.attrs.get("class") or "").split()

    def inside(self, ancestor: _Node) -> bool:
        node: _Node | None = self
        while node is not None:
            if node is ancestor:
                return True
            node = node.parent
        return False

    def recommendation(self) -> bool:
        node: _Node | None = self
        while node is not None:
            if node.has("products-item"):
                return True
            node = node.parent
        return False


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[_Node] = []
        self.nodes: list[_Node] = []
        self.counts: dict[str, int] = {}
        self.malformed = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.nodes) >= 50000 or len(self.stack) >= 128:
            raise _Limit
        values = dict(attrs)
        if len(values) != len(attrs):
            self.malformed = True
        self.counts[tag] = self.counts.get(tag, 0) + 1
        parent = self.stack[-1] if self.stack else None
        style = re.sub(r"\s+", "", values.get("style") or "").casefold()
        hidden = (
            bool(parent and parent.hidden)
            or tag in {"script", "style", "template", "noscript"}
            or "hidden" in values
            or "inert" in values
            or (values.get("aria-hidden") or "").casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )
        node = _Node(tag, values, f'locator("{tag}").nth({self.counts[tag] - 1})', parent, hidden)
        self.nodes.append(node)
        if parent:
            parent.children.append(node)
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
            self.stack.append(node)

    def handle_data(self, data: str) -> None:
        if self.stack and not self.stack[-1].hidden:
            self.stack[-1].children.append(data)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                matched = self.stack[index]
                matched.explicitly_closed = True
                if index != len(self.stack) - 1:
                    matched.mismatched_close = True
                    for omitted in self.stack[index + 1 :]:
                        omitted.mismatched_close = True
                del self.stack[index:]
                return


def _text(node: _Node) -> str:
    values: list[str] = []
    pending: list[_Node | str] = [node]
    size = 0
    while pending:
        child = pending.pop()
        if isinstance(child, str):
            size += len(child)
            if size > 4096:
                raise _Limit
            values.append(child)
        elif not child.hidden:
            pending.extend(reversed(child.children))
    result = " ".join("".join(values).split())
    if len(result) > 500:
        raise _Limit
    return result


def parse_supplier_product_details(url: str, content: bytes) -> SupplierProductDetails:
    digest = hashlib.sha256(content).hexdigest()

    def empty(
        status: Literal["EMPTY", "UNSUPPORTED", "AMBIGUOUS", "LIMIT_EXCEEDED"],
    ) -> SupplierProductDetails:
        return SupplierProductDetails(source_url=url, html_sha256=digest, status=status)

    try:
        valid = validate_page_url(url)
        if (
            valid != url
            or urlsplit(url).hostname != "bumaga-s.ru"
            or not unquote(urlsplit(url).path).startswith("/товар/")
        ):
            return empty("UNSUPPORTED")
    except (PageReadError, UnicodeError):
        return empty("UNSUPPORTED")
    if not content or len(content) > MAX_BODY_BYTES:
        return empty("LIMIT_EXCEEDED")
    try:
        parser = _Parser()
        parser.feed(content.decode("utf-8", errors="strict"))
        parser.close()
        products = [
            node
            for node in parser.nodes
            if "itemscope" in node.attrs
            and node.attrs.get("itemtype")
            in {"http://schema.org/Product", "https://schema.org/Product"}
        ]
        if not products:
            return empty("EMPTY")
        if len(products) != 1 or products[0].hidden or parser.malformed:
            return empty("AMBIGUOUS")
        contexts = [
            node
            for node in parser.nodes
            if node.has("product-card-content-item") and products[0].inside(node)
        ]
        if len(contexts) != 1 or contexts[0].hidden:
            return empty("AMBIGUOUS")
        context = contexts[0]
        active = [
            node
            for node in parser.nodes
            if node.inside(context) and not node.hidden and not node.recommendation()
        ]
        headings = [node for node in active if node.tag == "h1"]
        names = [
            node
            for node in active
            if node.tag == "meta"
            and node.inside(products[0])
            and node.attrs.get("itemprop") == "name"
        ]
        if len(headings) != 1 or len(names) != 1:
            return empty("AMBIGUOUS")
        selected_scopes = [context, products[0], headings[0]]
        selected_scopes.extend(
            node
            for node in active
            if node.has("product-description-item") or node.has("product-main-info-item")
        )
        if any(not node.explicitly_closed or node.mismatched_close for node in selected_scopes):
            return empty("AMBIGUOUS")
        name = _text(headings[0])
        comparable_name = name
        leading = next(
            (
                child
                for child in headings[0].children
                if not isinstance(child, str) or child.strip()
            ),
            None,
        )
        if (
            isinstance(leading, _Node)
            and leading.tag == "span"
            and leading.has("SpecSkidka")
            and _text(leading) == "*"
        ):
            comparable_name = name.removeprefix("* ")
        if not name or comparable_name != " ".join((names[0].attrs.get("content") or "").split()):
            return empty("AMBIGUOUS")
        characteristics: list[SupplierCharacteristic] = []
        controls: list[SupplierOrderControl] = []
        packaging: list[DeclaredFact] = []
        contents: list[DeclaredFact] = []
        ambiguous = False
        for row in active:
            if row.has("product-description-item") or row.has("product-main-info-item"):
                children = [
                    child for child in row.children if isinstance(child, _Node) and not child.hidden
                ]
                titles = [child for child in children if child.has("title")]
                values = [child for child in children if child.has("value")]
                if len(titles) != 1 or len(values) != 1:
                    ambiguous = True
                    continue
                label, value = _text(titles[0]), _text(values[0])
                if not label or not value or len(label) > 150:
                    ambiguous = True
                    continue
                fact = DeclaredFact(value=value, html_sha256=digest, locator=values[0].locator)
                if row.has("product-description-item"):
                    characteristics.append(
                        SupplierCharacteristic(
                            label_raw=label,
                            value_raw=value,
                            label_locator=titles[0].locator,
                            value_locator=values[0].locator,
                            html_sha256=digest,
                        )
                    )
                    if len(characteristics) > 16:
                        raise _Limit
                    if label.casefold().rstrip(":") == "количество листов":
                        contents.append(fact)
                if label.casefold().rstrip(":") == "упаковка":
                    packaging.append(fact)
            if row.has("cart-product-form"):
                for attribute in ("data-package", "data-min", "data-step", "min", "step"):
                    if attribute in row.attrs:
                        raw = row.attrs[attribute] or ""
                        if len(raw) > 150:
                            raise _Limit
                        controls.append(
                            SupplierOrderControl(
                                attribute=attribute,
                                raw_value=raw,
                                locator=row.locator + "@" + attribute,
                                html_sha256=digest,
                            )
                        )
                        if len(controls) > 8:
                            raise _Limit
        if len(characteristics) > 16 or len(controls) > 8:
            raise _Limit
        labels = [item.label_raw.casefold().rstrip(":") for item in characteristics]
        ambiguous |= len(set(labels)) != len(labels) or len(packaging) > 1 or len(contents) > 1
        return SupplierProductDetails(
            source_url=url,
            html_sha256=digest,
            status="AMBIGUOUS" if ambiguous else "EXTRACTED",
            product_name=None
            if ambiguous
            else DeclaredFact(value=name, html_sha256=digest, locator=headings[0].locator),
            characteristics=tuple(characteristics),
            packaging_raw=packaging[0] if packaging and not ambiguous else None,
            contents_raw=contents[0] if contents and not ambiguous else None,
            order_controls=tuple(controls),
        )
    except _Limit:
        return empty("LIMIT_EXCEEDED")
    except UnicodeError:
        return empty("UNSUPPORTED")
