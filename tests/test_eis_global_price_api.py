"""Authenticated global search context and restart errors; no caller tenant."""

import asyncio
from typing import cast

import httpx
import pytest

from procurement.api import create_app
from procurement.api.contracts import Authenticator, CaseService
from procurement.storage.eis_search_pagination import SearchPageError
from procurement.storage.repository import PostgresStorage
from test_eis_api import _Auth


def request(params, authorized=True):
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, _Auth()),
        eis_index_storage=cast(PostgresStorage, object()),
    )

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(
                "/v1/tender-discovery/global-price",
                params={"query": "бумага", **params},
                headers={"Authorization": "Bearer test-token"} if authorized else {},
            )

    return asyncio.run(send())


@pytest.mark.parametrize(
    "error,status",
    [("SEARCH_PAGE_CHANGED", 409), ("SEARCH_PAGE_EXPIRED", 410), ("SEARCH_PAGE_INVALID", 422)],
)
def test_global_filters_and_cursor_bound_to_authenticated_tenant(monkeypatch, error, status):
    seen = []

    def search(storage, company, options, *, now, cursor, limit):
        seen.append(company)
        assert (
            options.law == "all"
            and options.delivery_region == "Москва"
            and options.include_unknown_region
        )
        assert now.utcoffset() is not None and cursor == "opaque" and limit == 73
        raise SearchPageError(error)

    monkeypatch.setattr("procurement.api.tender_navigation.search_global_price", search)
    params = {
        "law": "all",
        "delivery_region": "Москва",
        "include_unknown_region": "true",
        "page_size": "73",
        "cursor": "opaque",
        "company_id": "other",
    }
    assert request(params, False).status_code == 401
    response = request(params)
    assert response.status_code == status and response.json()["detail"] == error
    assert response.headers["cache-control"] == "no-store" and seen == ["tenant-a"]


@pytest.mark.parametrize(
    "params",
    [
        {"query": " "},
        {"law": "bad"},
        {"page_size": "0"},
        {"page_size": "101"},
        {"cursor": "a" * 2049},
        {"delivery_region": "x" * 201},
    ],
)
def test_invalid_global_requests_do_not_reach_storage(monkeypatch, params):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid request reached storage")

    monkeypatch.setattr("procurement.api.tender_navigation.search_global_price", forbidden)
    assert request(params).status_code == 422
