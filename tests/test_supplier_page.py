import hashlib
import json
import socket
import ssl
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from procurement.sources import supplier_page as p

URL = "https://supplier.ru/item"
NOW = datetime(2026, 10, 6, tzinfo=UTC)


def html(data: object) -> bytes:
    return (
        '<html><script type="application/ld+json">' + json.dumps(data) + "</script></html>"
    ).encode()


def product(offers: object = None) -> dict[str, object]:
    return {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Paper",
        "sku": "A1",
        "offers": offers,
    }


def parse(data: bytes) -> p.PageObservation:
    return p.parse_supplier_page(URL, data, observed_at=NOW)


def test_structural_prices_decimal_declarations_and_evidence() -> None:
    content = html(
        product(
            {
                "@type": "Offer",
                "price": "12.30",
                "priceCurrency": "RUB",
                "seller": {"name": "Declared seller"},
            }
        )
    )
    observation = parse(content)
    fact = observation.products[0]
    assert observation.status == "COMPLETED" and observation.page_kind == "PRODUCT"
    assert observation.dispatch_count == 1 and observation.hops[0].url == URL
    assert fact.prices[0].amount == Decimal("12.30")
    assert fact.prices[0].raw_amount == "12.30" and fact.prices[0].price_kind == "EXACT"
    assert fact.prices[0].locator == "jsonld[0]$.offers.price"
    assert fact.seller.value == "Declared seller"
    assert fact.seller.html_sha256 == hashlib.sha256(content).hexdigest()
    assert observation.quote_status == observation.identity_status == "UNKNOWN"
    p.PageCapture(observation, content)
    with pytest.raises(ValueError):
        p.PageCapture(observation, b"changed")


def test_range_is_not_exact_or_complete_quote() -> None:
    result = parse(
        html(
            product(
                {
                    "@type": "AggregateOffer",
                    "lowPrice": "10",
                    "highPrice": "99",
                    "priceCurrency": "USD",
                }
            )
        )
    )
    assert [price.price_kind for price in result.products[0].prices] == ["LOW", "HIGH"]
    assert result.configured_cost_status == "UNKNOWN"


@pytest.mark.parametrize(
    "amount", ["0", "-1", "12,30", "1.001", "1000000000000000000", "NaN", True]
)
def test_unsupported_money_not_inferred(amount: object) -> None:
    result = parse(html(product({"@type": "Offer", "price": amount, "priceCurrency": "руб"})))
    assert not result.products[0].prices


def test_unlinked_offer_and_multiple_products_ambiguous() -> None:
    result = parse(
        html([product(), {"@type": "Offer", "price": "99", "priceCurrency": "RUB"}, product()])
    )
    assert result.page_kind == "CATEGORY" and result.extraction_status == "AMBIGUOUS"
    assert all(not item.prices for item in result.products)


def test_duplicate_keys_and_depth_fail_closed() -> None:
    result = parse(
        b'<script type="application/ld+json">{"@type":"Product","name":"a","name":"b"}</script>'
    )
    assert result.extraction_status == "AMBIGUOUS" and not result.products
    deep = b'<script type="application/ld+json">' + b"[" * 65 + b"0" + b"]" * 65 + b"</script>"
    assert parse(deep).extraction_status == "LIMIT_EXCEEDED"
    many = b"".join(html(product()) for _ in range(17))
    assert parse(many).extraction_status == "LIMIT_EXCEEDED"


def test_captcha_dominates_product_and_http_status_separate() -> None:
    result = parse(b'<div class="g-recaptcha"></div>' + html(product()))
    assert result.status == "BLOCKED" and result.http_status == 200 and not result.products
    assert result.extraction_status == "NOT_ATTEMPTED"
    error = p.parse_supplier_page(URL, html(product()), observed_at=NOW, http_status=500)
    assert error.status == "SOURCE_ERROR" and error.products == ()


@pytest.mark.parametrize(
    "url",
    [
        "http://supplier.ru/",
        "https://127.0.0.1/",
        "https://private.lan/",
        "https://user:pass@supplier.ru/",
        "https://supplier.ru:444/",
        "https://supplier.ru\\@localhost/",
        "https://[::1]/",
    ],
)
def test_unsafe_url_rejected(url: str) -> None:
    with pytest.raises(p.PageReadError):
        p.validate_page_url(url)


def test_dns_entire_answer_rejects_mixed_private(monkeypatch: pytest.MonkeyPatch) -> None:
    def answer(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", answer)
    with pytest.raises(p.PageReadError, match="DNS_UNSAFE"):
        p.resolve_public_addresses("supplier.ru")


class Response:
    def __init__(
        self,
        status: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"<html></html>",
    ) -> None:
        self.status = status
        self.headers = headers or {"Content-Type": "text/html"}
        self.content = content

    def getheader(self, name: str) -> str | None:
        return self.headers.get(name)

    def isclosed(self) -> bool:
        return not self.content

    def read1(self, size: int) -> bytes:
        chunk, self.content = self.content[:size], self.content[size:]
        return chunk


def transport(
    monkeypatch: pytest.MonkeyPatch, responses: list[Response]
) -> list[tuple[str, str, dict[str, str]]]:
    calls: list[tuple[str, str, dict[str, str]]] = []
    monkeypatch.setattr(
        p, "resolve_public_addresses", lambda host: ((socket.AF_INET, ("8.8.8.8", 443)),)
    )

    class Connection:
        sock = None

        def __init__(self, host: str, address: object, deadline: float) -> None:
            self.host = host

        def request(self, method: str, target: str, headers: dict[str, str]) -> None:
            assert method == "GET"
            calls.append((self.host, target, headers))

        def getresponse(self) -> Response:
            return responses.pop(0)

        def close(self) -> None:
            pass

    monkeypatch.setattr(p, "_PinnedConnection", Connection)
    return calls


def test_redirect_rejected_preserves_dispatched_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = transport(monkeypatch, [Response(302, {"Location": "http://127.0.0.1/private"})])
    capture = p.observe_supplier_page(URL)
    result = capture.observation
    assert len(calls) == result.dispatch_count == 1
    assert result.status == "UNSAFE_URL" and result.final_url == URL
    assert result.hops[0].location == "http://127.0.0.1/private"
    assert result.redirect_count == 0 and capture.content is None


def test_redirect_limit_and_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = transport(monkeypatch, [Response(302, {"Location": "/next"}) for _ in range(3)])
    result = p.observe_supplier_page(URL).observation
    assert result.reason_code == "REDIRECT_LIMIT" and len(calls) == 3
    assert result.dispatch_count == 3 and result.redirect_count == 2
    assert all(call[2]["Accept-Encoding"] == "identity" for call in calls)
    assert all("Cookie" not in call[2] and "Authorization" not in call[2] for call in calls)


@pytest.mark.parametrize(
    ("headers", "content", "reason"),
    [
        (
            {"Content-Type": "text/html", "Content-Encoding": "gzip"},
            b"x",
            "CONTENT_ENCODING_UNSUPPORTED",
        ),
        ({"Content-Type": "application/pdf"}, b"x", "CONTENT_TYPE_UNSUPPORTED"),
        ({"Content-Type": "text/html", "Content-Length": "9999999"}, b"x", "BODY_LIMIT"),
        ({"Content-Type": "text/html"}, b"x" * (p.MAX_BODY_BYTES + 1), "BODY_LIMIT"),
    ],
    ids=["compression", "pdf", "content_length", "stream_limit"],
)
def test_transport_content_bounds(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], content: bytes, reason: str
) -> None:
    transport(monkeypatch, [Response(headers=headers, content=content)])
    result = p.observe_supplier_page(URL)
    assert result.observation.reason_code == reason and result.content is None


def test_success_redirect_final_source_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    content = html(product())
    transport(monkeypatch, [Response(302, {"Location": "/final"}), Response(content=content)])
    capture = p.observe_supplier_page(URL)
    assert capture.observation.source_url == URL
    assert capture.observation.final_url == "https://supplier.ru/final"
    assert capture.observation.redirect_count == 1 and capture.observation.dispatch_count == 2
    assert capture.content == content


def test_tls_uses_pinned_ip_with_original_sni_and_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class Socket:
        def settimeout(self, seconds: float) -> None:
            assert seconds > 0

        def connect(self, address: object) -> None:
            events.append(address)

        def close(self) -> None:
            events.append("closed")

    class TLS:
        def wrap_socket(self, raw: object, *, server_hostname: str) -> object:
            events.append(server_hostname)
            raise ssl.SSLCertVerificationError("untrusted cert")

    monkeypatch.setattr(socket, "socket", lambda *args: Socket())
    connection = p._PinnedConnection(
        "supplier.ru", (socket.AF_INET, ("8.8.8.8", 443)), p.time.monotonic() + 30
    )
    assert connection.tls_context.check_hostname
    assert connection.tls_context.verify_mode == ssl.CERT_REQUIRED
    connection.tls_context = TLS()
    with pytest.raises(ssl.SSLCertVerificationError):
        connection.connect()
    assert events == [("8.8.8.8", 443), "supplier.ru", "closed"]


def test_dns_revalidated_after_public_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = transport(monkeypatch, [Response(302, {"Location": "https://other.ru/"})])
    hosts: list[str] = []

    def resolver(host: str) -> tuple[object, ...]:
        hosts.append(host)
        if len(hosts) > 1:
            raise p.PageReadError("UNSAFE_URL", "DNS_UNSAFE")
        return ((socket.AF_INET, ("8.8.8.8", 443)),)

    monkeypatch.setattr(p, "resolve_public_addresses", resolver)
    result = p.observe_supplier_page(URL).observation
    assert hosts == ["supplier.ru", "other.ru"]
    assert len(calls) == result.dispatch_count == 1
    assert result.final_url == URL and result.reason_code == "DNS_UNSAFE"


def test_truncated_declared_body_not_extracted(monkeypatch: pytest.MonkeyPatch) -> None:
    transport(
        monkeypatch,
        [
            Response(
                headers={"Content-Type": "text/html", "Content-Length": "900"},
                content=html(product()),
            )
        ],
    )
    result = p.observe_supplier_page(URL)
    assert result.observation.reason_code == "TRANSPORT_FAILED"
    assert result.content is None and result.observation.products == ()


def test_json_node_budget_precedes_json_load(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("large JSON must not allocate parser tree")

    monkeypatch.setattr(p.json, "loads", forbidden)
    large = b'<script type="application/ld+json">[' + b"0," * p.MAX_NODES + b"0]</script>"
    assert parse(large).extraction_status == "LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    "updates",
    [
        {"html_sha256": None, "byte_count": None},
        {"dispatch_count": 0, "hops": ()},
        {"http_status": 201},
        {"source_url": "https://other.ru/"},
        {"final_url": "https://other.ru/"},
        {"redirect_count": 1},
        {"reason_code": "ACCESS_BLOCKED"},
        {"extraction_status": "EMPTY"},
        {"products": ()},
    ],
)
def test_observation_rejects_incoherent_evidence(updates: dict[str, object]) -> None:
    from pydantic import ValidationError

    data = parse(html(product())).model_dump()
    data.update(updates)
    with pytest.raises(ValidationError):
        p.PageObservation.model_validate(data)


def test_failed_observation_cannot_claim_page_kind_or_extraction() -> None:
    from pydantic import ValidationError

    data = p.parse_supplier_page(
        URL, b"<html>Denied</html>", observed_at=NOW, http_status=403
    ).model_dump()
    data["page_kind"] = "PRODUCT"
    with pytest.raises(ValidationError):
        p.PageObservation.model_validate(data)


def test_hop_and_raw_price_fail_with_validation_error() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        p.PageHop(url="http://private.lan/")
    with pytest.raises(ValidationError):
        p.DisplayedPrice(
            amount=Decimal("1"),
            raw_amount="not money",
            currency="RUB",
            price_kind="EXACT",
            html_sha256="a" * 64,
            locator="jsonld[0]$.price",
        )


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ("Article", "ARTICLE"),
        ("CollectionPage", "CATEGORY"),
        ("ItemList", "CATEGORY"),
    ],
)
def test_explicit_page_context_not_overridden_by_one_product(context: str, expected: str) -> None:
    result = parse(html({"@type": context, "item": product()}))
    assert len(result.products) == 1
    assert result.page_kind == expected


def test_single_nested_product_does_not_establish_primary_page() -> None:
    result = parse(html({"@type": "WebPage", "related": product()}))
    assert len(result.products) == 1 and result.page_kind == "UNKNOWN"
    assert parse(html(product())).page_kind == "PRODUCT"


def test_long_key_wide_array_stops_before_path_expansion() -> None:
    result = parse(html({"first": product(), "x" * 10000: [0] * 1000}))
    assert result.extraction_status == "LIMIT_EXCEEDED"
    assert result.products == () and result.page_kind == "UNKNOWN"


def test_next_hop_tls_failure_does_not_reuse_redirect_http_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = transport(monkeypatch, [Response(301, {"Location": "/next"})])
    original = p._PinnedConnection

    class FailingConnection(original):
        def request(self, method: str, target: str, headers: dict[str, str]) -> None:
            super().request(method, target, headers)
            if len(calls) == 2:
                raise ssl.SSLCertVerificationError("certificate rejected")

    monkeypatch.setattr(p, "_PinnedConnection", FailingConnection)
    observation = p.observe_supplier_page(URL).observation
    assert observation.dispatch_count == 2 and observation.http_status is None
    assert observation.hops[0].http_status == 301 and observation.hops[1].http_status is None
    assert observation.status == "SOURCE_ERROR"


def test_scientific_json_price_serializes_plain_decimal_without_losing_raw() -> None:
    content = (
        b'<script type="application/ld+json">{"@type":"Product",'
        b'"offers":{"@type":"Offer","price":1e3,"priceCurrency":"RUB"}}</script>'
    )
    observation = parse(content)
    price = observation.products[0].prices[0]
    assert price.amount == Decimal("1000") and price.raw_amount == "1E+3"
    encoded = observation.model_dump_json()
    assert json.loads(encoded)["products"][0]["prices"][0]["amount"] == "1000"
    assert p.PageObservation.model_validate_json(encoded) == observation


@pytest.mark.parametrize("framing", ["content_length", "chunked", "connection_close"])
def test_real_http_response_eof_does_not_reconfigure_closed_socket(
    monkeypatch: pytest.MonkeyPatch, framing: str
) -> None:
    import http.client
    import io

    content = b"<html>Supplier page</html>"
    if framing == "content_length":
        headers = b"Content-Length: " + str(len(content)).encode() + b"\r\n"
        wire_body = content
    elif framing == "chunked":
        headers = b"Transfer-Encoding: chunked\r\n"
        wire_body = hex(len(content))[2:].encode() + b"\r\n" + content + b"\r\n0\r\n\r\n"
    else:
        headers = b""
        wire_body = content
    wire = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
        + headers
        + b"\r\n"
        + wire_body
    )

    class Socket:
        closed = False

        class File(io.BytesIO):
            def close(inner_self) -> None:
                sock.closed = True
                super().close()

        def makefile(self, mode: str) -> io.BytesIO:
            return self.File(wire)

        def settimeout(self, seconds: float) -> None:
            if self.closed:
                raise OSError("closed descriptor after HTTPResponse EOF")

    sock = Socket()

    class Connection:
        def __init__(self, *args: object) -> None:
            self.sock = sock

        def request(self, *args: object, **kwargs: object) -> None:
            pass

        def getresponse(self) -> http.client.HTTPResponse:
            response = http.client.HTTPResponse(sock)
            response.begin()
            return response

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        p, "resolve_public_addresses", lambda host: ((socket.AF_INET, ("8.8.8.8", 443)),)
    )
    monkeypatch.setattr(p, "_PinnedConnection", Connection)
    capture = p.observe_supplier_page(URL)
    assert capture.observation.status == "COMPLETED"
    assert capture.content == content
    assert sock.closed


def test_allowed_host_blocks_initial_and_redirect_before_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = transport(monkeypatch, [Response(302, {"Location": "https://other.ru/item"})])
    result = p.observe_supplier_page(URL, allowed_host="supplier.ru").observation
    assert len(calls) == 1 and result.reason_code == "URL_UNSAFE"
    assert result.final_url == URL and result.dispatch_count == 1
    result = p.observe_supplier_page(URL, allowed_host="other.ru").observation
    assert result.dispatch_count == 0 and len(calls) == 1
