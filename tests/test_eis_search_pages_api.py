"""Continuation must retain authenticated scope and expose explicit restart errors."""

import asyncio
from importlib import import_module
from typing import cast

import httpx
import pytest

from procurement.api import create_app
from procurement.api.contracts import Authenticator, CaseService
from procurement.storage.eis_search_pagination import SearchPageError
from procurement.storage.repository import PostgresStorage
from test_eis_api import _Auth


def request(law, suffix, *, authorized=True):
    app = create_app(
        cast(CaseService, object()),
        cast(Authenticator, _Auth()),
        eis_index_storage=cast(PostgresStorage, object()),
    )

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(
                f"/v1/tender-discovery/eis{'-223' if law == '223' else ''}-index"
                f"?query=бумага{suffix}",
                headers={"Authorization": "Bearer test-token"} if authorized else {},
            )

    return asyncio.run(send())


@pytest.mark.parametrize("law", ["44", "223"])
@pytest.mark.parametrize(
    "code,status",
    [
        ("SEARCH_PAGE_CHANGED", 409),
        ("SEARCH_PAGE_EXPIRED", 410),
        ("SEARCH_PAGE_INVALID", 422),
    ],
)
def test_continuation_uses_authenticated_scope_and_explicit_error(monkeypatch, law, code, status):
    seen = []

    def search(_storage, company, query, *, now, paginate, limit, cursor, **options):
        seen.append((company, query, paginate, limit, cursor))
        assert now.tzinfo is not None
        if law == "44":
            assert options == {"search_scope": "NOT_EXPIRED_OR_UNKNOWN"}
        raise SearchPageError(code)

    monkeypatch.setattr(
        import_module("procurement.api.app"),
        "search_eis_index" if law == "44" else "search_notice223_index",
        search,
    )
    assert request(law, "&page_size=70&cursor=opaque", authorized=False).status_code == 401
    response = request(law, "&page_size=70&cursor=opaque")
    assert response.status_code == status and response.json()["detail"] == code
    assert seen == [("tenant-a", "бумага", True, 70, "opaque")]


@pytest.mark.parametrize("law", ["44", "223"])
@pytest.mark.parametrize(
    "suffix", ["&page_size=0", "&page_size=101", "&cursor=", "&cursor=" + "a" * 2049]
)
def test_invalid_page_bounds_never_reach_storage(monkeypatch, law, suffix):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid pagination reached storage")

    monkeypatch.setattr(
        import_module("procurement.api.app"),
        "search_eis_index" if law == "44" else "search_notice223_index",
        forbidden,
    )
    assert request(law, suffix).status_code == 422
