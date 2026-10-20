"""Supplier page HTTP routes strictly bind authenticated requests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx

from procurement.access import AccessRole
from procurement.api import app as api_module
from procurement.api.app import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.sources.supplier_catalog import CatalogSearchSpec
from procurement.storage.eis_supplier_catalog import (
    SavedSupplierCatalog,
    SupplierCatalogReport,
    SupplierCatalogRequest,
)
from procurement.storage.repository import PostgresStorage
from test_eis_supplier_page_api import REQUEST as PAGE_REQUEST

REQUEST = SupplierCatalogRequest(
    page=PAGE_REQUEST,
    page_run_id="22222222-2222-4222-8222-222222222222",
)


class Auth:
    def __init__(self, role):
        self.role = role

    async def authenticate(self, credential):
        return (
            Principal(company_id="tenant-a", actor_id="actor-a", access_role=self.role)
            if credential == "test"
            else None
        )


def saved():
    report = SupplierCatalogReport(
        run_id="33333333-3333-4333-8333-333333333333",
        request=REQUEST,
        parent_page_report_sha256="c" * 64,
        position_sha256="d" * 64,
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
        stage="SEARCH",
        search_spec=CatalogSearchSpec(
            source_url="https://bumaga-s.ru/",
            query="Бумага A4",
            raw_action="/search",
            search_url="https://bumaga-s.ru/search?q=%D0%91%D1%83%D0%BC%D0%B0%D0%B3%D0%B0+A4",
            html_sha256="e" * 64,
            locator="form[1]",
        ),
        selected_link=None,
        parent_search_report_sha256=None,
        status="STARTED",
        reason_code="SOURCE_OUTCOME_UNKNOWN",
        observation=None,
        links=None,
        attempted_source_requests=None,
    )
    return SavedSupplierCatalog(report=report, created=False, source_requests=0)


def send(path, body, role=AccessRole.OPERATOR, authorization="Bearer test"):
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, Auth(role)),
        eis_index_storage=cast(PostgresStorage, object()),
    )

    async def run():
        headers = {"Content-Type": "application/json"}
        if authorization is not None:
            headers["Authorization"] = authorization
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(path, content=body, headers=headers)

    return asyncio.run(run())


PREPARE = "/v1/tender-discovery/eis-supplier-catalog/prepare"
READ = "/v1/tender-discovery/eis-supplier-catalog/read"


def test_prepare_and_read_forward_exact_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module,
        "run_prepare_supplier_catalog_subprocess",
        lambda storage, company, request, actor_id, refresh: (
            calls.append((company, request, actor_id, refresh)),
            saved(),
        )[1],
    )
    body = ('{"request":' + REQUEST.model_dump_json() + ',"refresh":true}').encode()
    response = send(PREPARE, body)
    assert (
        response.status_code == 200
        and response.headers["cache-control"] == "no-store"
        and calls == [("tenant-a", REQUEST, "actor-a", True)]
    )
    monkeypatch.setattr(
        api_module, "read_supplier_catalog", lambda storage, company, request: saved()
    )
    assert (
        send(
            READ, ('{"request":' + REQUEST.model_dump_json() + "}").encode(), AccessRole.AUDITOR
        ).status_code
        == 200
    )


def test_auth_role_and_strict_body_prevent_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module, "run_prepare_supplier_catalog_subprocess", lambda *a, **k: calls.append(1)
    )
    valid = ('{"request":' + REQUEST.model_dump_json() + "}").encode()
    for response in (
        send(PREPARE, valid, authorization=None),
        send(PREPARE, valid, AccessRole.AUDITOR),
        send(PREPARE, b'{"request":{},"request":{}}'),
        send(PREPARE, b'{"request":{},"refresh":1}'),
        send(PREPARE, b'{"request":NaN}'),
        send(PREPARE, b"{" + b" " * 4096 + b"}"),
    ):
        assert response.status_code in {401, 403, 413, 422}
        assert response.headers["cache-control"] == "no-store"
    assert calls == []


def test_openapi_is_fully_inlined():
    def refs(v):
        if isinstance(v, dict):
            return [x for k, n in v.items() for x in ([n] if k in {"$ref", "$defs"} else refs(n))]
        if isinstance(v, list):
            return [x for n in v for x in refs(n)]
        return []

    assert (
        refs(api_module.EIS_SUPPLIER_CATALOG_PREPARE_OPENAPI_SCHEMA)
        == refs(api_module.EIS_SUPPLIER_CATALOG_READ_OPENAPI_SCHEMA)
        == []
    )


def test_product_fixture_retains_exact_public_price_as_unknown_quote():
    fixture = SavedSupplierCatalog.model_validate(
        json.loads(
            (Path(__file__).parent / "fixtures" / "eis-supplier-catalog.json").read_text(
                encoding="utf-8"
            )
        )
    )
    price = fixture.report.observation.products[0].prices[0]
    assert (price.amount, price.currency, price.price_kind) == (
        Decimal("299.6"),
        "RUB",
        "EXACT",
    )
    assert fixture.report.quote == fixture.report.price_comparability == "UNKNOWN"
