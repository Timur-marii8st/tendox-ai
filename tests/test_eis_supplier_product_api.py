"""Supplier product routes enforce auth, strict bodies and exact result binding."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

import httpx

from procurement.access import AccessRole
from procurement.api import app as api_module
from procurement.api.app import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.sources.eis_supplier_product import (
    SavedSupplierProduct,
    build_supplier_product_report,
)
from procurement.storage.repository import PostgresStorage
from test_eis_characteristic_compare import characteristic
from test_eis_characteristic_compare import saved as saved_position
from test_eis_supplier_product import SHA, details, request


class Auth:
    def __init__(self, role):
        self.role = role

    async def authenticate(self, credential):
        return (
            Principal(company_id="tenant-a", actor_id="actor-a", access_role=self.role)
            if credential == "test"
            else None
        )


def result(created: bool = False) -> SavedSupplierProduct:
    position = saved_position(SHA, (characteristic("Плотность", SHA),))
    report = build_supplier_product_report(
        request(position),
        position,
        details("Плотность бумаги"),
        parent_product_report_sha256="b" * 64,
        position_sha256="c" * 64,
        source_body_sha256=SHA,
        run_id="55555555-5555-4555-8555-555555555555",
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
    )
    return SavedSupplierProduct(report=report, created=created)


REQUEST = result().report.request
PREPARE = "/v1/tender-discovery/eis-supplier-product/prepare"
READ = "/v1/tender-discovery/eis-supplier-product/read"


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


def test_prepare_and_auditor_read_forward_exact_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module,
        "prepare_supplier_product",
        lambda storage, company, req, actor_id: (
            calls.append((company, req, actor_id)),
            result(True),
        )[1],
    )
    body = ('{"request":' + REQUEST.model_dump_json() + "}").encode()
    response = send(PREPARE, body)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert calls == [("tenant-a", REQUEST, "actor-a")]
    monkeypatch.setattr(api_module, "read_supplier_product", lambda *a: result())
    assert send(READ, body, AccessRole.AUDITOR).status_code == 200


def test_auth_and_strict_body_reject_before_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(api_module, "prepare_supplier_product", lambda *a, **k: calls.append(1))
    valid = ('{"request":' + REQUEST.model_dump_json() + "}").encode()
    for response in (
        send(PREPARE, valid, authorization=None),
        send(PREPARE, valid, AccessRole.AUDITOR),
        send(PREPARE, b'{"request":{},"request":{}}'),
        send(PREPARE, b'{"request":NaN}'),
        send(PREPARE, b"{" + b" " * 4096 + b"}"),
    ):
        assert response.status_code in {401, 403, 413, 422}
        assert response.headers["cache-control"] == "no-store"
    assert calls == []


def test_openapi_is_fully_inlined():
    def refs(value):
        if isinstance(value, dict):
            return [
                item
                for key, nested in value.items()
                for item in ([nested] if key in {"$ref", "$defs"} else refs(nested))
            ]
        if isinstance(value, list):
            return [item for nested in value for item in refs(nested)]
        return []

    assert refs(api_module.EIS_SUPPLIER_PRODUCT_OPENAPI_SCHEMA) == []
