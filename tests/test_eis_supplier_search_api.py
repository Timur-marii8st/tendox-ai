"""Supplier search HTTP routes authenticate before bounded strict JSON dispatch."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import cast

import httpx

from procurement.access import AccessRole
from procurement.api import app as api_module
from procurement.api.app import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.domain.provenance import Extractor, Provenance
from procurement.sources.eis_223_archive import TextFact
from procurement.sources.eis_characteristic_compare import PositionSelection
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_supplier_search import (
    SavedSupplierSearch,
    SupplierSearchReport,
    SupplierSearchRequest,
)
from procurement.storage.repository import PostgresStorage

PREPARE = "/v1/tender-discovery/eis-supplier-search/prepare"
READ = "/v1/tender-discovery/eis-supplier-search/read"
REF = NoticeDocumentRef(
    purchase_number="0848300054826000154",
    version_number=1,
    notice_xml_sha256="a" * 64,
)
SEARCH = SupplierSearchRequest(selection=PositionSelection(notice=REF, source_index=1))


class Auth:
    def __init__(self, role: AccessRole) -> None:
        self.role = role

    async def authenticate(self, credential: str) -> Principal | None:
        if credential != "test":
            return None
        return Principal(company_id="tenant-a", actor_id="actor-a", access_role=self.role)


def saved() -> SavedSupplierSearch:
    report = SupplierSearchReport(
        run_id="11111111-1111-4111-8111-111111111111",
        request=SEARCH,
        position_sha256="b" * 64,
        position_name=TextFact(
            value="Сервер HPE DL360",
            raw="Сервер HPE DL360",
            provenance=Provenance(
                document_id="a" * 64,
                locator="position[1]/name",
                extractor=Extractor.API,
            ),
        ),
        query="dl360",
        status="STARTED",
        reason_code="SOURCE_OUTCOME_UNKNOWN",
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
        observation=None,
        attempted_source_requests=None,
    )
    return SavedSupplierSearch(report=report, created=False, source_requests=0)


def send(
    path: str,
    body: bytes,
    *,
    role: AccessRole = AccessRole.OPERATOR,
    authorization: str | None = "Bearer test",
) -> httpx.Response:
    application = create_app(
        cast(CaseService, object()),
        cast(Authenticator, Auth(role)),
        eis_index_storage=cast(PostgresStorage, object()),
    )

    async def run() -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if authorization is not None:
            headers["Authorization"] = authorization
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            return await client.post(path, content=body, headers=headers)

    return asyncio.run(run())


def test_prepare_forwards_tenant_actor_request_and_refresh(monkeypatch):
    calls = []

    def prepare(storage, company, request, *, actor_id, refresh):
        calls.append((storage, company, request, actor_id, refresh))
        return saved()

    monkeypatch.setattr(api_module, "run_prepare_supplier_subprocess", prepare)
    body = (
        '{"request":'
        + SEARCH.model_dump_json()
        + ',"refresh":true}'
    ).encode()
    response = send(PREPARE, body)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert calls[0][1:] == ("tenant-a", SEARCH, "actor-a", True)


def test_read_allows_auditor_and_forwards_tenant(monkeypatch):
    calls = []

    def read(storage, company, request):
        calls.append((company, request))
        return saved()

    monkeypatch.setattr(api_module, "read_supplier_search", read)
    response = send(
        READ,
        ('{"request":' + SEARCH.model_dump_json() + "}").encode(),
        role=AccessRole.AUDITOR,
    )
    assert response.status_code == 200 and calls == [("tenant-a", SEARCH)]


def test_auth_role_and_strict_json_fail_before_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module, "run_prepare_supplier_subprocess", lambda *args, **kwargs: calls.append(1)
    )
    valid = ('{"request":' + SEARCH.model_dump_json() + "}").encode()
    for response in (
        send(PREPARE, valid, authorization=None),
        send(PREPARE, valid, role=AccessRole.AUDITOR),
        send(PREPARE, b'{"request":{},"request":{}}'),
        send(PREPARE, b'{"request":{},"refresh":1}'),
    ):
        assert response.status_code in {401, 403, 422}
        assert response.headers["cache-control"] == "no-store"
    assert calls == []


def test_body_size_nonfinite_and_strict_nested_version_never_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module, "run_prepare_supplier_subprocess", lambda *args, **kwargs: calls.append(1)
    )
    payload = SEARCH.model_dump(mode="json")
    payload["selection"]["notice"]["version_number"] = True
    invalid_version = ('{"request":' + json.dumps(payload) + "}").encode()
    for raw, expected in (
        (b"{" + b" " * 4096 + b"}", 413),
        (b'{"request":{},"refresh":NaN}', 422),
        (invalid_version, 422),
    ):
        response = send(PREPARE, raw)
        assert response.status_code == expected
        assert response.headers["cache-control"] == "no-store"
    assert calls == []


def test_supplier_request_openapi_schemas_are_fully_inlined():
    def references(value):
        if isinstance(value, dict):
            return [
                item
                for key, nested in value.items()
                for item in ([nested] if key in {"$ref", "$defs"} else references(nested))
            ]
        if isinstance(value, list):
            return [item for nested in value for item in references(nested)]
        return []

    assert references(api_module.EIS_SUPPLIER_SEARCH_PREPARE_OPENAPI_SCHEMA) == []
    assert references(api_module.EIS_SUPPLIER_SEARCH_READ_OPENAPI_SCHEMA) == []
