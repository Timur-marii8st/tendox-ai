"""Requirement preview API is strict, authenticated and source zero."""

from __future__ import annotations

import asyncio
from typing import cast

import httpx

from procurement.access import AccessRole
from procurement.api import app as api_module
from procurement.api.app import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.storage.repository import PostgresStorage
from test_eis_requirement_preview import preview, request

PATH = "/v1/tender-discovery/eis-requirement-preview/preview"
REQUEST = request()


class Auth:
    def __init__(self, role):
        self.role = role

    async def authenticate(self, credential):
        return (
            Principal(company_id="tenant-a", actor_id="reader-a", access_role=self.role)
            if credential == "test"
            else None
        )


def send(body: bytes, role=AccessRole.AUDITOR, authorization="Bearer test"):
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
            return await client.post(PATH, content=body, headers=headers)

    return asyncio.run(run())


def test_authenticated_reader_gets_exact_source_zero_preview(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module,
        "read_requirement_preview",
        lambda storage, company, req: (calls.append((company, req)), preview())[1],
    )
    response = send(('{"request":' + REQUEST.model_dump_json() + "}").encode())
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert calls == [("tenant-a", REQUEST)]
    assert response.json()["database_writes"] == response.json()["source_requests"] == 0


def test_auth_and_strict_body_reject_before_read(monkeypatch):
    calls = []
    monkeypatch.setattr(api_module, "read_requirement_preview", lambda *a: calls.append(1))
    valid = ('{"request":' + REQUEST.model_dump_json() + "}").encode()
    for response in (
        send(valid, authorization=None),
        send(b'{"request":{},"request":{}}'),
        send(b'{"request":NaN}'),
        send(b"{" + b" " * 4096 + b"}"),
    ):
        assert response.status_code in {401, 413, 422}
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

    assert refs(api_module.EIS_REQUIREMENT_PREVIEW_OPENAPI_SCHEMA) == []
