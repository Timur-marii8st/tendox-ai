"""223 read route takes tenant from authentication, with no mutation permissions."""

from datetime import UTC, datetime
from importlib import import_module

import pytest

from procurement.access import AccessRole
from procurement.storage.eis_223_index import Eis223SearchResult
from test_eis_document_jobs_api import send

PATH = "/v1/tender-discovery/eis-223-index"


def test_read_route_is_tenant_scoped_no_store_and_available_to_auditor(monkeypatch):
    calls = []

    def read(storage, company, query, *, now):
        calls.append((company, query))
        assert now.tzinfo is not None
        return Eis223SearchResult(
            query=query,
            checked_at=datetime.now(UTC),
            indexed_current_notices=0,
            indexed_windows=0,
            evaluated_candidates=0,
            matched_count=0,
            matched=(),
            latest_ingested_at=None,
        )

    monkeypatch.setattr(import_module("procurement.api.app"), "search_notice223_index", read)
    assert send("GET", PATH + "?query=бумага", token="invalid").status_code == 401
    response = send("GET", PATH + "?query=бумага&company_id=other", role=AccessRole.AUDITOR)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    assert calls == [("tenant-a", "бумага")]
    assert response.json()["coverage"] == response.json()["freshness"] == "UNKNOWN"
    assert send("POST", PATH, body={"query": "бумага"}).status_code == 405


@pytest.mark.parametrize("query", ["", "x" * 121])
def test_query_length_is_rejected(query):
    assert send("GET", PATH + "?query=" + query).status_code == 422


def test_invalid_lexical_query_is_422(monkeypatch):
    def invalid(*args, **kwargs):
        raise ValueError("INVALID_QUERY")

    monkeypatch.setattr(import_module("procurement.api.app"), "search_notice223_index", invalid)
    assert send("GET", PATH + "?query=!!!").status_code == 422
