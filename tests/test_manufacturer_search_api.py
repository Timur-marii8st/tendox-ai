"""Manufacturer search preserves authentication, roles and server-owned evidence."""

from __future__ import annotations

import asyncio
from typing import cast
from uuid import uuid4

import httpx
import pytest

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import CaseService, Principal
from procurement.storage.manufacturer_search import (
    ManufacturerSearchConflict,
    ManufacturerSearchNotFound,
    ManufacturerSearchRateLimited,
)
from procurement.storage.repository import PostgresStorage


class Auth:
    async def authenticate(self, credential: str) -> Principal | None:
        if credential in ("operator", "auditor"):
            return Principal(
                company_id="tenant-a",
                actor_id="actor-a",
                access_role=AccessRole.OPERATOR if credential == "operator" else AccessRole.AUDITOR,
            )
        return None


def application(*, configured: bool = True):
    return create_app(
        cast(CaseService, object()),
        Auth(),
        eis_index_storage=cast(PostgresStorage, object()) if configured else None,
    )


def test_authorization_validation_and_unconfigured_storage_before_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("no source/storage call allowed")

    monkeypatch.setattr("procurement.api.manufacturer_search.start_search", forbidden)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(application(configured=False)),
            base_url="http://test",
        ) as client:
            payload = {"query": "насос", "command_id": str(uuid4())}
            assert (await client.post("/v1/manufacturer-search", json=payload)).status_code == 401
            reader = {"Authorization": "Bearer auditor"}
            assert (
                await client.post(
                    "/v1/manufacturer-search",
                    json=payload,
                    headers=reader,
                )
            ).status_code == 403
            operator = {"Authorization": "Bearer operator"}
            for content, expected in (
                ('{"query":"a","query":"b","command_id":"' + str(uuid4()) + '"}', 422),
                ('{"query":"' + "x" * 4096 + '"}', 413),
            ):
                rejected = await client.post(
                    "/v1/manufacturer-search",
                    content=content,
                    headers={**operator, "Content-Type": "application/json"},
                )
                assert rejected.status_code == expected
                assert rejected.headers["cache-control"] == "no-store"
            for field in ("company_id", "actor_id", "url", "candidate", "response_sha256"):
                response = await client.post(
                    "/v1/manufacturer-search",
                    json={**payload, field: "injected"},
                    headers=operator,
                )
                assert response.status_code == 422
            response = await client.post(
                "/v1/manufacturer-search",
                json=payload,
                headers=operator,
            )
            assert response.status_code == 503
            assert response.headers["cache-control"] == "no-store"
            assert (
                await client.get(
                    "/v1/manufacturer-search/not-uuid",
                    headers=operator,
                )
            ).status_code == 422
            assert (
                await client.get(
                    f"/v1/manufacturer-search/{uuid4()}/candidates/not-record",
                    headers=operator,
                )
            ).status_code == 422

    asyncio.run(check())


@pytest.mark.parametrize(
    "error,status",
    [
        (ManufacturerSearchConflict, 409),
        (ManufacturerSearchRateLimited, 429),
        (ManufacturerSearchNotFound, 404),
        (ValueError, 422),
    ],
)
def test_command_uses_authenticated_identity_and_translates_errors(monkeypatch, error, status):
    command = str(uuid4())
    calls = []

    def attempt(storage, company_id, query, *, actor_id, command_id):
        calls.append((company_id, query, actor_id, command_id))
        raise error("private source diagnostic")

    monkeypatch.setattr("procurement.api.manufacturer_search.start_search", attempt)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(application()),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/manufacturer-search",
                json={"query": "насос", "command_id": command},
                headers={"Authorization": "Bearer operator"},
            )
            assert response.status_code == status
            assert "private source diagnostic" not in response.text
            assert calls == [("tenant-a", "насос", "actor-a", command)]

    asyncio.run(check())


def test_read_not_found_is_scoped_and_has_no_source_dispatch(monkeypatch):
    calls = []

    def missing(storage, company_id, run_id, *rest):
        calls.append((company_id, run_id, rest))
        raise ManufacturerSearchNotFound("private")

    monkeypatch.setattr("procurement.api.manufacturer_search.read_search", missing)
    monkeypatch.setattr("procurement.api.manufacturer_search.read_candidate", missing)
    monkeypatch.setattr("procurement.api.manufacturer_search.list_saved_searches", lambda *args: [])
    run_id = str(uuid4())
    record = "a" * 24

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(application()),
            base_url="http://test",
        ) as client:
            headers = {"Authorization": "Bearer auditor"}
            assert (await client.get("/v1/manufacturer-search", headers=headers)).json() == []
            for path in (run_id, f"{run_id}/candidates/{record}"):
                response = await client.get(f"/v1/manufacturer-search/{path}", headers=headers)
                assert response.status_code == 404
            assert calls == [("tenant-a", run_id, ()), ("tenant-a", run_id, (record,))]

    asyncio.run(check())
