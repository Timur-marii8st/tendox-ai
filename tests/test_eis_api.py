"""The discovery preview is authenticated and bounded at the API edge."""

import asyncio
from datetime import UTC, datetime
from importlib import import_module
from typing import cast

import httpx
import pytest

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.sources.eis_feed_sync import EisSyncError
from procurement.sources.eis_number_sync import EisNumberSyncResult
from procurement.sources.eis_public import (
    EisPublicDocumentsResult,
    EisPublicSearchResult,
    public_search_url,
)
from procurement.storage.eis_index_query import EisIndexedSearchResult, EisIndexSearchScope
from procurement.storage.repository import PostgresStorage


class _Auth:
    async def authenticate(self, credential: str) -> Principal | None:
        if credential != "test-token":
            return None
        return Principal(
            company_id="tenant-a", actor_id="operator", access_role=AccessRole.OPERATOR
        )


def _request(headers: dict[str, str], *, content: bytes, query: str = "бумаги") -> httpx.Response:
    app = create_app(cast(CaseService, object()), cast(Authenticator, _Auth()))

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/v1/tender-discovery/eis-export",
                headers=headers,
                data={"query": query},
                files={"file": ("export.xml", content, "application/xml")},
            )

    return asyncio.run(send())


def test_eis_export_requires_bearer() -> None:
    response = _request({}, content=b"<epNotificationEF2020/>")
    assert response.status_code == 401


def test_eis_export_returns_provenance_but_no_profit_claim() -> None:
    xml = b"""<epNotificationEF2020><commonInfo>
      <purchaseNumber>0123456789012345678</purchaseNumber>
      <purchaseObjectInfo>Supply of paper</purchaseObjectInfo>
      </commonInfo></epNotificationEF2020>"""
    response = _request({"Authorization": "Bearer test-token"}, content=xml, query="paper")
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] == "UPLOADED_EXPORT_ONLY"
    assert body["source_authenticity"] == "UNKNOWN"
    assert body["matched"][0]["economic_status"] == "UNKNOWN"
    assert body["matched"][0]["application_status"] == "UNKNOWN"
    assert response.headers["cache-control"] == "no-store"


def test_live_eis_search_requires_auth_and_returns_bounded_result(monkeypatch) -> None:
    api_module = import_module("procurement.api.app")
    monkeypatch.setattr(
        api_module,
        "search_public_eis",
        lambda query: EisPublicSearchResult(
            query=query,
            search_url=public_search_url(query),
            status="COMPLETED",
            observed_at=datetime(2026, 9, 25, tzinfo=UTC),
            scanned_count=0,
        ),
    )
    app = create_app(cast(CaseService, object()), cast(Authenticator, _Auth()))

    async def send(headers: dict[str, str]) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/v1/tender-discovery/eis-live?query=бумага", headers=headers)

    assert asyncio.run(send({})).status_code == 401
    response = asyncio.run(send({"Authorization": "Bearer test-token"}))
    assert response.status_code == 200
    assert response.json()["coverage"] == "FIRST_PAGE_ONLY"
    assert response.headers["cache-control"] == "no-store"


def test_live_number_verification_is_tenant_scoped_and_one_number_only(monkeypatch) -> None:
    api_module = import_module("procurement.api.app")
    observed: list[tuple[str, str, str]] = []

    async def verify(_storage: object, company: str, actor: str, number: str, _token: str):
        observed.append((company, actor, number))
        return EisNumberSyncResult(number, "NO_DATA", "a" * 64)

    monkeypatch.setattr(api_module, "sync_eis_number_via_browser", verify)
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, _Auth()),
        eis_index_storage=cast(PostgresStorage, object()),
        eis_number_token="configured-token",
    )

    async def send(number: str, headers: dict[str, str]) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                f"/v1/tender-discovery/eis-live/{number}/verify", headers=headers
            )

    number = "0848300054826000154"
    assert asyncio.run(send(number, {})).status_code == 401
    assert asyncio.run(send("invalid", {"Authorization": "Bearer test-token"})).status_code == 422
    response = asyncio.run(send(number, {"Authorization": "Bearer test-token"}))
    assert response.status_code == 200
    assert response.json()["source"]["coverage"] == "ONE_NUMBER_ONLY"
    assert response.json()["document_job"] is None
    assert response.headers["cache-control"] == "no-store"
    assert observed == [("tenant-a", "operator", number)]


@pytest.mark.parametrize(
    "error,status,reason",
    [
        (EisSyncError("SOURCE_TRANSPORT_FAILED"), 502, "SOURCE_TRANSPORT_FAILED"),
        (ValueError("NOTICE_VARIANT_REVIEW_REQUIRED"), 422, "NOTICE_VARIANT_REVIEW_REQUIRED"),
    ],
)
def test_live_number_source_failure_is_explicit(monkeypatch, error, status, reason) -> None:
    api_module = import_module("procurement.api.app")

    async def fail(*_args: object) -> EisNumberSyncResult:
        raise error

    monkeypatch.setattr(api_module, "sync_eis_number_via_browser", fail)
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, _Auth()),
        eis_index_storage=cast(PostgresStorage, object()),
        eis_number_token="configured-token",
    )

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/v1/tender-discovery/eis-live/0848300054826000154/verify",
                headers={"Authorization": "Bearer test-token"},
            )

    response = asyncio.run(send())
    assert response.status_code == status
    assert response.json()["detail"] == reason
    if status == 422:
        assert response.headers["cache-control"] == "no-store"


def test_eis_documents_endpoint_requires_auth(monkeypatch) -> None:
    api_module = import_module("procurement.api.app")
    url = (
        "https://zakupki.gov.ru/epz/order/notice/ea20/view/documents.html"
        "?regNumber=0123456789012345678"
    )
    monkeypatch.setattr(
        api_module,
        "read_public_documents",
        lambda requested: EisPublicDocumentsResult(
            documents_url=requested,
            status="COMPLETED",
            observed_at=datetime(2026, 9, 25, tzinfo=UTC),
        ),
    )
    app = create_app(cast(CaseService, object()), cast(Authenticator, _Auth()))

    async def send(headers: dict[str, str]) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/v1/tender-discovery/eis-documents", headers=headers, json={"url": url}
            )

    assert asyncio.run(send({})).status_code == 401
    response = asyncio.run(send({"Authorization": "Bearer test-token"}))
    assert response.status_code == 200
    assert response.json()["documents"] == []
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("suffix", "expected_scope"),
    [
        ("", "NOT_EXPIRED_OR_UNKNOWN"),
        ("&search_scope=ALL_CACHED", "ALL_CACHED"),
        ("&search_scope=NOT_EXPIRED_OR_UNKNOWN", "NOT_EXPIRED_OR_UNKNOWN"),
    ],
)
def test_index_search_requires_auth_and_uses_authenticated_tenant(
    monkeypatch, suffix: str, expected_scope: EisIndexSearchScope
) -> None:
    api_module = import_module("procurement.api.app")
    observed: list[tuple[str, str, str]] = []

    def search(
        _storage: object,
        company: str,
        query: str,
        *,
        now: datetime,
        search_scope: EisIndexSearchScope,
    ) -> EisIndexedSearchResult:
        assert now.tzinfo is not None
        observed.append((company, query, search_scope))
        return EisIndexedSearchResult(
            query=query,
            inspected_current_notices=0,
            matched_count=0,
            indexed_windows=0,
            latest_ingested_at=None,
            matched=(),
            search_scope=search_scope,
        )

    monkeypatch.setattr(api_module, "search_eis_index", search)
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, _Auth()),
        eis_index_storage=cast(PostgresStorage, object()),
    )

    async def send(headers: dict[str, str]) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(
                "/v1/tender-discovery/eis-index?query=бумага" + suffix, headers=headers
            )

    assert asyncio.run(send({})).status_code == 401
    response = asyncio.run(send({"Authorization": "Bearer test-token"}))
    assert response.status_code == 200
    assert response.json()["corpus_coverage"] == "UNKNOWN"
    assert response.json()["source_freshness"] == "UNKNOWN"
    assert response.json()["search_scope"] == expected_scope
    assert observed == [("tenant-a", "бумага", expected_scope)]
    assert response.headers["cache-control"] == "no-store"


def test_index_search_rejects_unknown_scope_before_storage(monkeypatch) -> None:
    api_module = import_module("procurement.api.app")

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid scope reached storage")

    monkeypatch.setattr(api_module, "search_eis_index", forbidden)
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, _Auth()),
        eis_index_storage=cast(PostgresStorage, object()),
    )

    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(
                "/v1/tender-discovery/eis-index?query=бумага&search_scope=ACTIVE",
                headers={"Authorization": "Bearer test-token"},
            )

    assert asyncio.run(send()).status_code == 422
