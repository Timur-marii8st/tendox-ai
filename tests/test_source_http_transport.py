"""Маршрут окружения не меняет URL, TLS-проверку или политику redirects."""

from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest

from procurement.sources.eaeu_manufacturers import search_eaeu_manufacturers
from procurement.sources.eaeu_registry import search_eaeu_registry
from procurement.sources.eat_classifier import fetch_eat_classifier
from procurement.sources.http_transport import public_source_client
from procurement.sources.manufacturer_catalog import fetch_official_manufacturer_catalog
from procurement.sources.servermall import fetch_servermall_hpe_gen12
from procurement.sources.yandex_business import search_yandex_business_category


@pytest.mark.parametrize(
    "call",
    [
        lambda: search_yandex_business_category("МФУ HP"),
        lambda: search_eaeu_registry("Насос"),
        lambda: search_eaeu_manufacturers("Завод"),
        lambda: fetch_servermall_hpe_gen12("HPE DL360 Gen12"),
        lambda: fetch_official_manufacturer_catalog("HPE DL360 Gen12"),
        fetch_eat_classifier,
    ],
)
def test_public_adapters_respect_configured_environment_by_default(monkeypatch, call):
    monkeypatch.delenv("SOURCE_HTTP_TRUST_ENV", raising=False)
    calls = []

    def client(**kwargs):
        calls.append(kwargs)
        assert kwargs["trust_env"] is True
        assert kwargs["follow_redirects"] is False
        assert kwargs["timeout"] == 15
        assert kwargs.get("verify", True) is True
        raise httpx.ConnectError("synthetic offline")

    monkeypatch.setattr(httpx, "Client", client)
    with suppress(ValueError, httpx.HTTPError):
        call()
    assert len(calls) == 1


def test_operator_can_disable_environment_without_disabling_tls(monkeypatch):
    monkeypatch.setenv("SOURCE_HTTP_TRUST_ENV", "false")
    calls = []
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: calls.append(kwargs))
    public_source_client()
    assert calls == [{"timeout": 15, "follow_redirects": False, "verify": True, "trust_env": False}]


def test_invalid_operator_setting_fails_before_client_creation(monkeypatch):
    monkeypatch.setenv("SOURCE_HTTP_TRUST_ENV", "maybe-private-value")
    monkeypatch.setattr(httpx, "Client", lambda **_: pytest.fail("must not create client"))
    with pytest.raises(httpx.TransportError, match=r"^SOURCE_HTTP_CONFIGURATION_INVALID$"):
        public_source_client()


@pytest.mark.parametrize("error", [ValueError, OSError, ImportError])
def test_bad_proxy_or_ca_configuration_does_not_expose_credentials(monkeypatch, error):
    monkeypatch.setenv("SOURCE_HTTP_TRUST_ENV", "true")

    def broken(**_):
        raise error("https://private-user:private-password@proxy.invalid")

    monkeypatch.setattr(httpx, "Client", broken)
    with pytest.raises(httpx.TransportError) as failure:
        public_source_client()
    assert str(failure.value) == "SOURCE_HTTP_CONFIGURATION_INVALID"
    assert failure.value.__suppress_context__


def test_real_client_uses_local_proxy_and_does_not_follow_redirect(monkeypatch):
    for name in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SOURCE_HTTP_TRUST_ENV", "true")
    requests = []

    class Proxy(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://unexpected.invalid/secret")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{server.server_port}")
        with public_source_client() as client:
            response = client.get("http://source.invalid/catalog?page=2")
        assert response.status_code == 302
        assert requests == ["http://source.invalid/catalog?page=2"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
