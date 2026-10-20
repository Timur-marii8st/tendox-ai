"""Supplier page HTTP routes strictly bind authenticated requests."""

from __future__ import annotations

import asyncio
import hashlib
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
from procurement.sources.eis_characteristic_compare import PositionSelection
from procurement.sources.supplier_page import PageHop, PageObservation
from procurement.sources.supplier_serp import SearchEngine, SerpLink
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_supplier_page import (
    SavedSupplierPage,
    SupplierPageReport,
    SupplierPageRequest,
)
from procurement.storage.eis_supplier_search import SupplierSearchRequest
from procurement.storage.repository import PostgresStorage

REF = NoticeDocumentRef(
    purchase_number="0848300054826000154", version_number=1, notice_xml_sha256="a" * 64
)
POSITION = SupplierSearchRequest(selection=PositionSelection(notice=REF, source_index=1))
REQUEST = SupplierPageRequest(
    position=POSITION,
    serp_run_id="11111111-1111-4111-8111-111111111111",
    engine=SearchEngine.BING,
    rank=1,
)
LINK = SerpLink(
    rank=1,
    title="Публичный результат",
    snippet="Непроверенная ссылка",
    url="https://supplier.ru/",
    dom_sha256="b" * 64,
    locator='locator("li.b_algo").nth(0)',
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
    content = b"<html>synthetic public page</html>"
    digest = hashlib.sha256(content).hexdigest()
    observation = PageObservation(
        source_url=LINK.url,
        final_url=LINK.url,
        observed_at=datetime(2026, 10, 6, tzinfo=UTC),
        status="COMPLETED",
        reason_code="HTML_OBSERVED",
        http_status=200,
        extraction_status="EMPTY",
        page_kind="UNKNOWN",
        html_sha256=digest,
        byte_count=len(content),
        hops=(PageHop(url=LINK.url, http_status=200),),
        dispatch_count=1,
    )
    report = SupplierPageReport(
        run_id="22222222-2222-4222-8222-222222222222",
        request=REQUEST,
        parent_report_sha256="c" * 64,
        position_sha256="d" * 64,
        link=LINK,
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
        status="COMPLETED",
        reason_code="FIXED_PUBLIC_PAGE_OBSERVATION",
        observation=observation,
        attempted_source_requests=1,
        source_body_sha256=digest,
        source_body_byte_count=len(content),
    )
    return SavedSupplierPage(report=report, created=False, source_requests=0)


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


PREPARE = "/v1/tender-discovery/eis-supplier-page/prepare"
READ = "/v1/tender-discovery/eis-supplier-page/read"


def test_prepare_and_read_forward_exact_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module,
        "run_prepare_supplier_page_subprocess",
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
    monkeypatch.setattr(api_module, "read_supplier_page", lambda storage, company, request: saved())
    assert (
        send(
            READ, ('{"request":' + REQUEST.model_dump_json() + "}").encode(), AccessRole.AUDITOR
        ).status_code
        == 200
    )


def test_auth_role_and_strict_body_prevent_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module, "run_prepare_supplier_page_subprocess", lambda *a, **k: calls.append(1)
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
        refs(api_module.EIS_SUPPLIER_PAGE_PREPARE_OPENAPI_SCHEMA)
        == refs(api_module.EIS_SUPPLIER_PAGE_READ_OPENAPI_SCHEMA)
        == []
    )


def test_fixture_has_exact_and_range_price_declarations():
    fixture = SavedSupplierPage.model_validate(
        json.loads(
            (Path(__file__).parent / "fixtures" / "eis-supplier-page.json").read_text(
                encoding="utf-8"
            )
        )
    )
    product = fixture.report.observation.products[0]
    assert [(price.price_kind, price.amount) for price in product.prices] == [
        ("EXACT", Decimal("562957.00")),
        ("LOW", Decimal("540000.00")),
        ("HIGH", Decimal("610000.00")),
    ]
    assert fixture.report.quote == fixture.report.price_comparability == "UNKNOWN"
