"""One public HTML observation, pinned DNS/TLS transport, no supplier verification."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer, model_validator

from procurement.sources.supplier_serp import safe_public_url

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_SCRIPTS = 16
MAX_NODES = 50000
MAX_DEPTH = 64
Status = Literal[
    "COMPLETED",
    "BLOCKED",
    "RATE_LIMITED",
    "TIMEOUT",
    "SOURCE_ERROR",
    "UNSAFE_URL",
    "RESOURCE_LIMIT",
    "UNSUPPORTED_CONTENT",
]
Reason = Literal[
    "HTML_OBSERVED",
    "ACCESS_BLOCKED",
    "RATE_LIMITED",
    "DEADLINE_EXCEEDED",
    "TRANSPORT_FAILED",
    "URL_UNSAFE",
    "DNS_UNSAFE",
    "REDIRECT_LIMIT",
    "BODY_LIMIT",
    "CONTENT_ENCODING_UNSUPPORTED",
    "CONTENT_TYPE_UNSUPPORTED",
    "HTTP_ERROR",
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DeclaredFact(FrozenModel):
    value: str = Field(min_length=1, max_length=500)
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1, max_length=200)


class DisplayedPrice(FrozenModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    raw_amount: str = Field(min_length=1, max_length=80)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    price_kind: Literal["EXACT", "LOW", "HIGH"]
    html_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1, max_length=200)

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return format(value, "f")

    @model_validator(mode="after")
    def valid_money(self) -> DisplayedPrice:
        try:
            raw = Decimal(self.raw_amount)
        except InvalidOperation as exc:
            raise ValueError("PRICE_INVALID") from exc
        if (
            not self.amount.is_finite()
            or self.amount <= 0
            or not raw.is_finite()
            or raw != self.amount
        ):
            raise ValueError("PRICE_INVALID")
        return self


class ProductObservation(FrozenModel):
    locator: str = Field(min_length=1, max_length=200)
    name: DeclaredFact | None = None
    brand: DeclaredFact | None = None
    manufacturer: DeclaredFact | None = None
    seller: DeclaredFact | None = None
    sku: DeclaredFact | None = None
    prices: tuple[DisplayedPrice, ...] = Field(default=(), max_length=20)


class PageHop(FrozenModel):
    url: str = Field(max_length=2048)
    http_status: int | None = Field(default=None, ge=100, le=599, strict=True)
    location: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def valid_url(self) -> PageHop:
        try:
            valid = validate_page_url(self.url)
        except PageReadError as exc:
            raise ValueError("HOP_URL_INVALID") from exc
        if valid != self.url:
            raise ValueError("HOP_URL_INVALID")
        return self


class PageObservation(FrozenModel):
    source_url: str = Field(max_length=2048)
    final_url: str = Field(max_length=2048)
    observed_at: AwareDatetime
    status: Status
    reason_code: Reason
    http_status: int | None = Field(default=None, ge=100, le=599, strict=True)
    extraction_status: Literal[
        "EXTRACTED", "EMPTY", "AMBIGUOUS", "LIMIT_EXCEEDED", "NOT_ATTEMPTED"
    ] = "NOT_ATTEMPTED"
    page_kind: Literal["PRODUCT", "CATEGORY", "ARTICLE", "UNKNOWN"] = "UNKNOWN"
    html_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    byte_count: int | None = Field(default=None, ge=1, le=MAX_BODY_BYTES, strict=True)
    hops: tuple[PageHop, ...] = Field(default=(), max_length=3)
    dispatch_count: int = Field(default=0, ge=0, le=3, strict=True)
    redirect_count: int = Field(default=0, ge=0, le=2, strict=True)
    products: tuple[ProductObservation, ...] = Field(default=(), max_length=20)
    technical_status: Literal["UNKNOWN"] = "UNKNOWN"
    quote_status: Literal["UNKNOWN"] = "UNKNOWN"
    configured_cost_status: Literal["UNKNOWN"] = "UNKNOWN"
    identity_status: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def evidence(self) -> PageObservation:
        if (self.html_sha256 is None) != (self.byte_count is None):
            raise ValueError("HTML_BINDING_INVALID")
        if self.dispatch_count != len(self.hops):
            raise ValueError("HOP_COUNT_INVALID")
        if self.hops:
            if self.final_url != self.hops[-1].url or self.source_url != self.hops[0].url:
                raise ValueError("HOP_URL_BINDING_INVALID")
            if self.http_status != self.hops[-1].http_status:
                raise ValueError("HOP_STATUS_INVALID")
        elif self.final_url != self.source_url or self.http_status is not None:
            raise ValueError("UNDISPATCHED_INVALID")
        if self.redirect_count != max(0, self.dispatch_count - 1):
            raise ValueError("DISPATCH_INVALID")
        if self.status == "COMPLETED" and (
            self.http_status != 200
            or self.extraction_status == "NOT_ATTEMPTED"
            or self.html_sha256 is None
            or self.dispatch_count == 0
        ):
            raise ValueError("COMPLETED_INVALID")
        if self.status != "COMPLETED" and (
            self.products
            or self.extraction_status != "NOT_ATTEMPTED"
            or self.page_kind != "UNKNOWN"
        ):
            raise ValueError("EXTRACTION_INVALID")
        if self.extraction_status in {"EMPTY", "LIMIT_EXCEEDED"} and self.products:
            raise ValueError("PRODUCTS_UNEXPECTED")
        if self.extraction_status == "EXTRACTED" and not self.products:
            raise ValueError("PRODUCTS_REQUIRED")
        reasons = {
            "COMPLETED": {"HTML_OBSERVED"},
            "BLOCKED": {"ACCESS_BLOCKED"},
            "RATE_LIMITED": {"RATE_LIMITED"},
            "TIMEOUT": {"DEADLINE_EXCEEDED"},
            "SOURCE_ERROR": {"TRANSPORT_FAILED", "HTTP_ERROR"},
            "UNSAFE_URL": {"URL_UNSAFE", "DNS_UNSAFE"},
            "RESOURCE_LIMIT": {"REDIRECT_LIMIT", "BODY_LIMIT"},
            "UNSUPPORTED_CONTENT": {"CONTENT_ENCODING_UNSUPPORTED", "CONTENT_TYPE_UNSUPPORTED"},
        }
        if self.reason_code not in reasons[self.status]:
            raise ValueError("STATUS_REASON_INVALID")
        for product in self.products:
            facts = (product.name, product.brand, product.manufacturer, product.seller, product.sku)
            if any(fact.html_sha256 != self.html_sha256 for fact in facts if fact):
                raise ValueError("FACT_BINDING_INVALID")
            if any(price.html_sha256 != self.html_sha256 for price in product.prices):
                raise ValueError("PRICE_BINDING_INVALID")
        return self


@dataclass(frozen=True)
class PageCapture:
    observation: PageObservation
    content: bytes | None

    def __post_init__(self) -> None:
        if self.content is None:
            if self.observation.html_sha256 is not None:
                raise ValueError("HTML_MISSING")
        elif (
            type(self.content) is not bytes
            or len(self.content) != self.observation.byte_count
            or hashlib.sha256(self.content).hexdigest() != self.observation.html_sha256
        ):
            raise ValueError("HTML_BINDING_INVALID")


class PageReadError(Exception):
    def __init__(self, status: Status, reason: Reason) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


def validate_page_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.port not in {None, 443}:
            raise ValueError
        host = (parts.hostname or "").encode("idna").decode("ascii")
        normalized = urlunsplit(("https", host, parts.path or "/", parts.query, ""))
        if parts.username or parts.password or safe_public_url(normalized) is None:
            raise ValueError
        if len(url) > 2048 or any(ord(c) < 33 for c in url) or "\\" in url:
            raise ValueError
        return normalized
    except (ValueError, UnicodeError) as exc:
        raise PageReadError("UNSAFE_URL", "URL_UNSAFE") from exc


def resolve_public_addresses(host: str) -> tuple[tuple[int, tuple[object, ...]], ...]:
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    result: list[tuple[int, tuple[object, ...]]] = []
    if not answers or len(answers) > 64:
        raise PageReadError("UNSAFE_URL", "DNS_UNSAFE")
    for family, _, _, _, address in answers:
        ip = ipaddress.ip_address(address[0])
        if family not in {socket.AF_INET, socket.AF_INET6} or not ip.is_global or ip.is_multicast:
            raise PageReadError("UNSAFE_URL", "DNS_UNSAFE")
        item = (family, tuple(address))
        if item not in result:
            result.append(item)
    return tuple(result)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


class _PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: tuple[int, tuple[object, ...]], deadline: float) -> None:
        super().__init__(
            host, 443, timeout=_remaining(deadline), context=ssl.create_default_context()
        )
        self.tls_context = ssl.create_default_context()
        self.address = address
        self.deadline = deadline

    def connect(self) -> None:
        family, address = self.address
        raw = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        try:
            raw.settimeout(_remaining(self.deadline))
            raw.connect(address)
            raw.settimeout(_remaining(self.deadline))
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
            self.sock.settimeout(_remaining(self.deadline))
        except BaseException:
            raw.close()
            raise


class _Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self.current: list[str] | None = None
        self.hidden = 0
        self.text: list[str] = []
        self.challenge = False
        self.limit = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        markers = ((values.get("id") or "") + " " + (values.get("class") or "")).casefold().split()
        if any(x in {"captcha", "g-recaptcha", "h-captcha", "smart-captcha"} for x in markers):
            self.challenge = True
        if tag == "iframe" and any(
            x in (values.get("src") or "").casefold()
            for x in ("recaptcha", "showcaptcha", "/challenge/")
        ):
            self.challenge = True
        if tag in {"script", "style", "template", "noscript"}:
            self.hidden += 1
        if (
            tag == "script"
            and (values.get("type") or "").lower().split(";")[0].strip() == "application/ld+json"
        ):
            if len(self.scripts) >= MAX_SCRIPTS:
                self.limit = True
            else:
                self.current = []

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current.append(data)
        if not self.hidden:
            self.text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None
        if tag in {"script", "style", "template", "noscript"}:
            self.hidden = max(0, self.hidden - 1)


def _json_depth_safe(text: str) -> bool:
    depth = 0
    structural_tokens = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            structural_tokens += 1
            if depth > MAX_DEPTH:
                return False
        elif char in "]}":
            depth -= 1
        elif char in ",:":
            structural_tokens += 1
        if structural_tokens > MAX_NODES:
            return False
    return True


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise ValueError("JSON_NONFINITE")


def _kind(value: object, kind: str) -> bool:
    if isinstance(value, list):
        return any(_kind(item, kind) for item in value)
    return (
        value in {kind, "https://schema.org/" + kind, "http://schema.org/" + kind}
        if isinstance(value, str)
        else False
    )


def _fact(value: object, digest: str, locator: str) -> DeclaredFact | None:
    if isinstance(value, dict):
        value = value.get("name")
        locator += ".name"
    if isinstance(value, str) and value.strip() and len(value.strip()) <= 500:
        return DeclaredFact(value=value.strip(), html_sha256=digest, locator=locator)
    return None


def _product(value: dict[str, object], digest: str, locator: str) -> ProductObservation:
    prices: list[DisplayedPrice] = []
    offers = value.get("offers")
    offers_list = offers if isinstance(offers, list) else [offers]
    seller: DeclaredFact | None = None
    for index, offer in enumerate(offers_list):
        if not isinstance(offer, dict):
            continue
        path = locator + ".offers" + (f"[{index}]" if isinstance(offers, list) else "")
        aggregate = _kind(offer.get("@type"), "AggregateOffer")
        if not aggregate and not _kind(offer.get("@type"), "Offer"):
            continue
        declared_seller = _fact(offer.get("seller"), digest, path + ".seller")
        if len(offers_list) == 1:
            seller = declared_seller
        fields: tuple[tuple[str, Literal["EXACT", "LOW", "HIGH"]], ...] = (
            (("lowPrice", "LOW"), ("highPrice", "HIGH")) if aggregate else (("price", "EXACT"),)
        )
        for field, price_kind in fields:
            raw = offer.get(field)
            if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
                continue
            raw_text = str(raw)
            if len(raw_text) > 80 or not re.fullmatch(
                r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", raw_text
            ):
                continue
            amount = Decimal(raw_text)
            if (
                amount <= 0
                or amount.adjusted() >= 16
                or (
                    isinstance(amount.as_tuple().exponent, int)
                    and int(amount.as_tuple().exponent) < -2
                )
                or len(amount.as_tuple().digits) > 18
            ):
                continue
            currency = offer.get("priceCurrency")
            currency = (
                currency
                if isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency)
                else None
            )
            prices.append(
                DisplayedPrice(
                    amount=amount,
                    raw_amount=raw_text,
                    currency=currency,
                    price_kind=price_kind,
                    html_sha256=digest,
                    locator=path + "." + field,
                )
            )
    if len(prices) > 20:
        raise PageReadError("RESOURCE_LIMIT", "BODY_LIMIT")
    return ProductObservation(
        locator=locator,
        name=_fact(value.get("name"), digest, locator + ".name"),
        brand=_fact(value.get("brand"), digest, locator + ".brand"),
        manufacturer=_fact(value.get("manufacturer"), digest, locator + ".manufacturer"),
        sku=_fact(value.get("sku"), digest, locator + ".sku"),
        seller=seller,
        prices=tuple(prices),
    )


def parse_supplier_page(
    url: str, content: bytes, *, observed_at: datetime, http_status: int = 200
) -> PageObservation:
    url = validate_page_url(url)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("OBSERVATION_TIME_INVALID")
    if type(content) is not bytes or not content or len(content) > MAX_BODY_BYTES:
        raise PageReadError("RESOURCE_LIMIT", "BODY_LIMIT")
    digest = hashlib.sha256(content).hexdigest()
    markup = _Markup()
    markup.feed(content.decode("utf-8", errors="replace"))
    visible = " ".join(markup.text).casefold()
    status: Status = "COMPLETED"
    reason: Reason = "HTML_OBSERVED"
    if http_status == 429:
        status, reason = "RATE_LIMITED", "RATE_LIMITED"
    elif (
        http_status == 403
        or markup.challenge
        or any(
            x in visible
            for x in ("verify you are human", "подтвердите, что вы не робот", "unusual traffic")
        )
    ):
        status, reason = "BLOCKED", "ACCESS_BLOCKED"
    elif http_status != 200:
        status, reason = "SOURCE_ERROR", "HTTP_ERROR"
    products: list[ProductObservation] = []
    extraction: Literal["EXTRACTED", "EMPTY", "AMBIGUOUS", "LIMIT_EXCEEDED", "NOT_ATTEMPTED"] = (
        "NOT_ATTEMPTED"
    )
    page_kind: Literal["PRODUCT", "CATEGORY", "ARTICLE", "UNKNOWN"] = "UNKNOWN"
    if status == "COMPLETED":
        extraction = "EMPTY"
        malformed = markup.current is not None
        limited = markup.limit
        nodes = 0
        article_context = False
        category_context = False
        direct_product = False
        for index, script in enumerate(markup.scripts):
            if not _json_depth_safe(script):
                limited = True
                break
            try:
                root = json.loads(
                    script,
                    parse_float=Decimal,
                    object_pairs_hook=_unique_pairs,
                    parse_constant=_invalid_constant,
                )
            except (ValueError, RecursionError):
                malformed = True
                continue
            stack = [(root, f"jsonld[{index}]$")]
            while stack:
                value, path = stack.pop()
                nodes += 1
                if nodes > MAX_NODES:
                    limited = True
                    break
                if isinstance(value, dict):
                    if _kind(value.get("@type"), "Product"):
                        if len(products) >= 20 or len(path) > 120:
                            limited = True
                            break
                        try:
                            products.append(_product(value, digest, path))
                            if value is root:
                                direct_product = True
                        except PageReadError:
                            limited = True
                            break
                    if _kind(value.get("@type"), "Article"):
                        article_context = True
                    if _kind(value.get("@type"), "CollectionPage") or _kind(
                        value.get("@type"), "ItemList"
                    ):
                        category_context = True
                    for key, child in reversed(value.items()):
                        if key == "@context":
                            continue
                        # Check components before concatenation or enqueuing a wide subtree.
                        if len(path) + 1 + len(key) > 200:
                            limited = True
                            break
                        stack.append((child, path + "." + key))
                elif isinstance(value, list):
                    for i in range(len(value) - 1, -1, -1):
                        component = f"[{i}]"
                        if len(path) + len(component) > 200:
                            limited = True
                            break
                        stack.append((value[i], path + component))
                if limited:
                    break
            if limited:
                break
        if limited:
            extraction, products = "LIMIT_EXCEEDED", []
        elif products:
            extraction = "AMBIGUOUS" if malformed or len(products) > 1 else "EXTRACTED"
            if article_context and category_context:
                page_kind = "UNKNOWN"
                extraction = "AMBIGUOUS"
            elif category_context:
                page_kind = "CATEGORY"
            elif article_context:
                page_kind = "ARTICLE"
            elif len(products) > 1:
                page_kind = "CATEGORY"
            elif direct_product and not malformed:
                page_kind = "PRODUCT"
        elif malformed:
            extraction = "AMBIGUOUS"
        elif category_context != article_context:
            page_kind = "CATEGORY" if category_context else "ARTICLE"
    return PageObservation(
        source_url=url,
        final_url=url,
        observed_at=observed_at,
        status=status,
        reason_code=reason,
        http_status=http_status,
        extraction_status=extraction,
        page_kind=page_kind,
        html_sha256=digest,
        byte_count=len(content),
        hops=(PageHop(url=url, http_status=http_status),),
        dispatch_count=1,
        products=tuple(products),
    )


def observe_supplier_page(url: str, *, allowed_host: str | None = None) -> PageCapture:
    """Blocking DNS is additionally bounded by the caller's 40-second child runner."""
    observed = datetime.now(UTC)
    deadline = time.monotonic() + 30
    source = url
    current = url
    dispatches = redirects = 0
    hops: list[PageHop] = []
    pending_url: str | None = None
    http_status: int | None = None
    try:
        source = current = validate_page_url(url)
        if allowed_host is not None and urlsplit(current).hostname != allowed_host:
            raise PageReadError("UNSAFE_URL", "URL_UNSAFE")
        while True:
            target_url = pending_url or current
            parts = urlsplit(target_url)
            host = parts.hostname
            assert host is not None
            addresses = resolve_public_addresses(host)
            _remaining(deadline)
            connection = _PinnedConnection(host, addresses[0], deadline)
            try:
                target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
                if parts.query:
                    target += "?" + quote(parts.query, safe="%/:?@!$&'()*+,;=-._~")
                if hops:
                    redirects += 1
                current = target_url
                http_status = None
                hops.append(PageHop(url=current))
                dispatches += 1
                connection.request(
                    "GET",
                    target,
                    headers={
                        "Host": host,
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                        "User-Agent": "SyuraiSupplierObservation/1.0",
                    },
                )
                if connection.sock:
                    connection.sock.settimeout(_remaining(deadline))
                active_socket = connection.sock
                response = connection.getresponse()
                http_status = response.status
                hops[-1] = PageHop(url=current, http_status=http_status)
                location = response.getheader("Location")
                if location is not None and len(location) > 2048:
                    raise PageReadError("RESOURCE_LIMIT", "BODY_LIMIT")
                hops[-1] = PageHop(url=current, http_status=http_status, location=location)
                if http_status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location:
                        raise PageReadError("SOURCE_ERROR", "HTTP_ERROR")
                    if redirects >= 2:
                        raise PageReadError("RESOURCE_LIMIT", "REDIRECT_LIMIT")
                    pending_url = validate_page_url(urljoin(current, location))
                    if allowed_host is not None and urlsplit(pending_url).hostname != allowed_host:
                        raise PageReadError("UNSAFE_URL", "URL_UNSAFE")
                    continue
                if http_status in {403, 429}:
                    raise PageReadError(
                        "BLOCKED" if http_status == 403 else "RATE_LIMITED",
                        "ACCESS_BLOCKED" if http_status == 403 else "RATE_LIMITED",
                    )
                encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
                if encoding != "identity":
                    raise PageReadError("UNSUPPORTED_CONTENT", "CONTENT_ENCODING_UNSUPPORTED")
                content_type = (
                    (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
                )
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    raise PageReadError("UNSUPPORTED_CONTENT", "CONTENT_TYPE_UNSUPPORTED")
                length = response.getheader("Content-Length")
                if length and (
                    not length.isdecimal() or len(length) > 10 or int(length) > MAX_BODY_BYTES
                ):
                    raise PageReadError("RESOURCE_LIMIT", "BODY_LIMIT")
                chunks: list[bytes] = []
                total = 0
                while True:
                    # HTTPResponse closes its file as soon as Content-Length is exhausted.
                    # Its final nonempty read may therefore release the underlying socket.
                    if response.isclosed():
                        break
                    if active_socket:
                        active_socket.settimeout(_remaining(deadline))
                    _remaining(deadline)
                    chunk = response.read1(min(65536, MAX_BODY_BYTES + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_BODY_BYTES:
                        raise PageReadError("RESOURCE_LIMIT", "BODY_LIMIT")
                content = b"".join(chunks)
                if length is not None and total != int(length):
                    raise PageReadError("SOURCE_ERROR", "TRANSPORT_FAILED")
                observation = parse_supplier_page(
                    current, content, observed_at=observed, http_status=http_status
                )
                return PageCapture(
                    observation.model_copy(
                        update={
                            "source_url": source,
                            "dispatch_count": dispatches,
                            "redirect_count": redirects,
                            "hops": tuple(hops),
                        }
                    ),
                    content,
                )
            finally:
                connection.close()
    except PageReadError as exc:
        status, reason = exc.status, exc.reason
    except TimeoutError:
        status, reason = "TIMEOUT", "DEADLINE_EXCEEDED"
    except (OSError, http.client.HTTPException, InvalidOperation):
        status, reason = "SOURCE_ERROR", "TRANSPORT_FAILED"
    return PageCapture(
        PageObservation(
            source_url=source,
            final_url=current,
            observed_at=observed,
            status=status,
            reason_code=reason,
            http_status=http_status,
            dispatch_count=dispatches,
            redirect_count=redirects,
            hops=tuple(hops),
        ),
        None,
    )
