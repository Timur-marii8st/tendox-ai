import json
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from procurement.access import AccessRole
from procurement.api import public_unit_price as route
from procurement.api.contracts import Principal
from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_archive import DecimalFact, TextFact
from procurement.sources.eis_supplier_product import SupplierProductRequest
from procurement.sources.supplier_page import parse_supplier_page
from procurement.storage import public_unit_price as store
from test_public_unit_price import offer

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
FIXTURE = json.loads((Path(__file__).parent / "fixtures/eis-supplier-product.json").read_text())
REQUEST = SupplierProductRequest.model_validate(FIXTURE["report"]["request"])
XML = REQUEST.catalog.page.position.selection.notice.notice_xml_sha256
PATH = "/v1/tender-discovery/eis-public-unit-price/read"


class Storage:
    @contextmanager
    def transaction(self, company, *, consistent_read):
        assert company == "alpha" and consistent_read
        yield object()


def source(monkeypatch, value=None):
    value = offer() if value is None else value
    content = (
        '<h1>Synthetic bolt</h1><script type="application/ld+json">'
        + json.dumps(value)
        + "</script>"
    ).encode()
    obs = parse_supplier_page("https://supplier.example.com/product/one", content, observed_at=NOW)
    prov = Provenance(document_id=XML, locator="/synthetic/quantity", extractor=Extractor.API)
    pos = SimpleNamespace(
        position=SimpleNamespace(
            quantity=DecimalFact(value=Decimal("10"), raw="10", provenance=prov),
            unit=TextFact(value="шт", raw="шт", provenance=prov),
        )
    )

    def parent(conn, company, req, *, body):
        assert company == "alpha" and req == REQUEST and body
        return (
            SimpleNamespace(observation=obs, source_body_sha256=obs.html_sha256),
            "",
            content,
            pos,
            "c" * 64,
        )

    monkeypatch.setattr(store, "_product_parent", parent)


def app(monkeypatch):
    source(monkeypatch)
    original = store.read_public_unit_price

    def read(storage, company, req):
        return original(storage, company, req, now=NOW)

    monkeypatch.setattr(route, "read_public_unit_price", read)

    async def authenticate(request: Request):
        if request.headers.get("authorization") != "Bearer test":
            raise HTTPException(401, "unauthorized")
        return Principal(company_id="alpha", actor_id="operator", access_role=AccessRole.OPERATOR)

    api = FastAPI()
    api.include_router(route.public_unit_price_router(Storage(), authenticate))
    return TestClient(api)


def test_read_calculates_quantity_cost_without_caller_amounts(
    monkeypatch,
):
    client = app(monkeypatch)
    response = client.post(
        PATH,
        headers={"Authorization": "Bearer test"},
        json={"request": REQUEST.model_dump(mode="json")},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["company_id"] == "alpha"
    assert result["quantity_cost_rub"] == "120.00"
    assert result["status"] == "CALCULATED"
    assert result["source_requests"] == 0
    assert result["profit"] == result["technical"] == result["quote"] == "UNKNOWN"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "extra", [{"company_id": "beta"}, {"price": "1"}, {"url": "https://other.com"}]
)
def test_caller_cannot_choose_tenant_url_or_prices(monkeypatch, extra):
    client = app(monkeypatch)
    response = client.post(
        PATH,
        headers={"Authorization": "Bearer test"},
        json={"request": REQUEST.model_dump(mode="json"), **extra},
    )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


def test_auth_and_body_limit(monkeypatch):
    client = app(monkeypatch)
    assert client.post(PATH, json={"request": REQUEST.model_dump(mode="json")}).status_code == 401
    assert (
        client.post(
            PATH,
            headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
            content=" " * 5000,
        ).status_code
        == 413
    )


@pytest.mark.parametrize(
    "error,status", [(LookupError("private"), 404), (ValueError("private"), 409)]
)
def test_source_not_found_and_stale_errors_are_sanitized(monkeypatch, error, status):
    client = app(monkeypatch)

    def fail(*args):
        raise error

    monkeypatch.setattr(route, "read_public_unit_price", fail)
    response = client.post(
        PATH,
        headers={"Authorization": "Bearer test"},
        json={"request": REQUEST.model_dump(mode="json")},
    )
    assert response.status_code == status
    assert "private" not in response.text


def test_missing_reference_quantity_does_not_produce_zero_cost(monkeypatch):
    value = offer()
    del value["offers"]["priceSpecification"]["referenceQuantity"]
    source(monkeypatch, value)
    result = store.read_public_unit_price(Storage(), "alpha", REQUEST, now=NOW)
    assert result.status == "UNKNOWN" and result.quantity_cost_rub is None
    assert "EXPLICIT_PRICE_BASIS_UNAVAILABLE" in result.missing


def test_full_application_wires_authenticated_read_route(monkeypatch):
    app(monkeypatch)
    from procurement.api.app import create_app

    class Auth:
        async def authenticate(self, credential):
            if credential == "test":
                return Principal(company_id="alpha", actor_id="operator",
                                 access_role=AccessRole.OPERATOR)
            return None

    api = create_app(object(), Auth(), eis_index_storage=Storage())
    response = TestClient(api).post(PATH, headers={"Authorization": "Bearer test"},
                                   json={"request": REQUEST.model_dump(mode="json")})
    assert response.status_code == 200, response.text
    assert response.json()["quantity_cost_rub"] == "120.00"
