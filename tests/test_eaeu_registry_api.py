"""Authenticated read-only boundary for live manufacturer candidates."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest

from procurement.api import create_app
from procurement.api.contracts import CaseService, Principal
from procurement.sources.eaeu_registry import RegistryFetchStatus, RegistrySearchResult


class _Auth:
    async def authenticate(self, credential: str) -> Principal | None:
        if credential == "valid":
            return Principal(company_id="tenant-a", actor_id="operator-a")
        return None


def test_registry_search_requires_auth_and_does_not_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_search(query: str) -> RegistrySearchResult:
        calls.append(query)
        return RegistrySearchResult(
            query=query,
            fetch_status=RegistryFetchStatus.COMPLETED,
            observed_at=datetime(2026, 9, 21, tzinfo=UTC),
            request_sha256="a" * 64,
            response_sha256="b" * 64,
            response_byte_size=45,
            matched_count=0,
        )

    monkeypatch.setattr("procurement.api.app.search_eaeu_registry", fake_search)
    app = create_app(cast(CaseService, object()), _Auth())

    async def check() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            anonymous = await client.get("/v1/supplier-discovery/eaeu?query=насос")
            assert anonymous.status_code == 401
            assert calls == []
            invalid = await client.get(
                "/v1/supplier-discovery/eaeu?query=one%20two%20three%20four%20five%20six",
                headers={"Authorization": "Bearer valid"},
            )
            assert invalid.status_code == 422
            assert calls == []
            response = await client.get(
                "/v1/supplier-discovery/eaeu?query=насос",
                headers={"Authorization": "Bearer valid"},
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["matched_count"] == 0
            assert calls == ["насос"]

    asyncio.run(check())
