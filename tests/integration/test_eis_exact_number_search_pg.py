"""Real PostgreSQL/API regression; only isolated synthetic notice XML."""

from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_eis_223_index_pg import counts
from test_eis_223_index_pg import storage as storage
from test_eis_notice_index_pg import _archive, _scope_archive, _window

from procurement.api import create_app
from procurement.api.contracts import Authenticator, CaseService, Principal
from procurement.storage.eis_223_index import ingest_notice223_window, search_notice223_index
from procurement.storage.eis_index_query import search_eis_index
from procurement.storage.eis_notice_index import ingest_ready_window
from test_eis_223_archive import xml, zip_bytes
from test_eis_223_index import NOW, window


class TenantAuth:
    def __init__(self, company):
        self.company = company

    async def authenticate(self, credential):
        if credential not in {"current", "foreign"}:
            return None
        return Principal(
            company_id=self.company if credential == "current" else self.company + "-foreign",
            actor_id="synthetic-operator",
        )


def client_for(storage, company):
    return TestClient(
        create_app(
            cast(CaseService, object()),
            cast(Authenticator, TenantAuth(company)),
            eis_index_storage=storage,
        )
    )


@pytest.mark.parametrize("number", ["32616445250", "32616445747", "00016445250"])
def test_223_exact_api_and_storage_keep_tenant_latest_text_and_read_only(storage, number):
    company = "exact223-" + uuid4().hex
    raw = (
        xml()
        .replace(b"32600000001", number.encode())
        .replace("Поставка бумаги".encode(), "Поставка кранов шаровых".encode())
    )
    ingest_notice223_window(
        storage, company, window(zip_bytes([("notice.xml", raw)])), actor_id="test", now=NOW
    )
    # Another tenant has a newer version of the SAME number. It cannot shadow ours.
    foreign = raw.replace(b"<p:version>2", b"<p:version>3")
    ingest_notice223_window(
        storage,
        company + "-foreign",
        window(zip_bytes([("foreign.xml", foreign)])),
        actor_id="test",
        now=NOW,
    )
    before = counts(storage, company)
    text = search_notice223_index(storage, company, "кранов шаровых", now=NOW)
    assert [lead.notice.purchase_number for lead in text.matched] == [number]
    with client_for(storage, company) as client:
        for query in (number, " \t" + number + "\n "):
            response = client.get(
                "/v1/tender-discovery/eis-223-index",
                params={
                    "query": query,
                    "page_size": 100,
                    "company_id": company + "-foreign",
                },
                headers={"Authorization": "Bearer current"},
            )
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            result = response.json()
            assert result["matched_count"] == result["evaluated_candidates"] == 1
            assert result["matched"][0]["notice"]["purchase_number"] == number
            assert result["matched"][0]["notice"]["version_number"] == 2
            assert result["next_cursor"] is None
        assert (
            client.get("/v1/tender-discovery/eis-223-index", params={"query": number}).status_code
            == 401
        )
        missing = client.get(
            "/v1/tender-discovery/eis-223-index",
            params={"query": "32699999999"},
            headers={"Authorization": "Bearer current"},
        )
        assert missing.status_code == 200 and missing.json()["matched"] == []
    assert search_notice223_index(storage, company + "-empty", number, now=NOW).matched == ()
    assert counts(storage, company) == before


def test_44_exact_api_and_storage_use_current_tenant_and_visibility_filters(storage):
    company = "exact44-" + uuid4().hex
    number = "0000000000000000001"
    ingest_ready_window(
        storage,
        company,
        _window("17", _archive(number, title="Краны")),
        actor_id="test",
        received_at=NOW,
    )
    ingest_ready_window(
        storage,
        company,
        _window("18", _archive(number, title="Серверы", version=2)),
        actor_id="test",
        received_at=NOW,
    )
    ingest_ready_window(
        storage,
        company + "-foreign",
        _window("17", _archive(number, version=3)),
        actor_id="test",
        received_at=NOW,
    )
    assert search_eis_index(storage, company, "краны", now=NOW).matched == ()
    assert len(search_eis_index(storage, company, "серверы", now=NOW).matched) == 1
    assert search_eis_index(storage, company, number, now=NOW, require_documents=True).matched == ()
    with client_for(storage, company) as client:
        response = client.get(
            "/v1/tender-discovery/eis-index",
            params={
                "query": " " + number + " ",
                "page_size": 100,
            },
            headers={"Authorization": "Bearer current"},
        )
        assert response.status_code == 200
        lead = response.json()["matched"][0]
        assert lead["purchase_number"] == number and lead["version_number"] == 2
        assert lead["application_status"] == "UNKNOWN"
    assert search_eis_index(storage, company + "-empty", number, now=NOW).matched == ()


def test_44_exact_number_respects_expiry_and_existing_history_switch(storage):
    company = "exact44-expiry-" + uuid4().hex
    number = "0000000000000000001"
    ingest_ready_window(
        storage,
        company,
        _window("17", _scope_archive(number, "2026-09-26T00:00:00Z")),
        actor_id="test",
        received_at=NOW,
    )
    with client_for(storage, company) as client:
        for scope, expected in (("NOT_EXPIRED_OR_UNKNOWN", 0), ("ALL_CACHED", 1)):
            response = client.get(
                "/v1/tender-discovery/eis-index",
                params={"query": number, "search_scope": scope},
                headers={"Authorization": "Bearer current"},
            )
            assert response.status_code == 200
            assert response.json()["matched_count"] == expected
            if expected:
                assert response.json()["matched"][0]["application_status"] == "FAIL"
    assert search_eis_index(storage, company, number, now=NOW, exclude_failed=True).matched == ()


def test_44_exact_number_does_not_bypass_source_hold(storage, tmp_path):
    from test_eis_notice_hold_pg import hold

    from procurement.storage.eis_document_store import NoticeDocumentRef

    company = "exact44-hold-" + uuid4().hex
    number = "0000000000000000001"
    ingest_ready_window(
        storage, company, _window("17", _archive(number)), actor_id="test", received_at=NOW
    )
    lead = search_eis_index(storage, company, number, now=NOW).matched[0]
    hold(
        storage,
        company,
        tmp_path,
        NoticeDocumentRef(
            purchase_number=number,
            version_number=lead.version_number,
            notice_xml_sha256=lead.xml_sha256,
        ),
    )
    result = search_eis_index(storage, company, number, now=NOW)
    assert result.matched == () and result.held_current_notices == 1


def test_44_exact_number_does_not_require_derived_text_keys(storage, monkeypatch):
    from procurement.storage import eis_notice_index

    company = "exact44-unindexed-" + uuid4().hex
    number = "0000000000000000001"
    with monkeypatch.context() as patch:
        patch.setattr(eis_notice_index, "insert_search_keys", lambda *args: False)
        ingest_ready_window(
            storage, company, _window("17", _archive(number)), actor_id="test", received_at=NOW
        )
    result = search_eis_index(storage, company, number, now=NOW)
    assert result.matched_count == result.evaluated_candidate_notices == 1
    assert result.matched[0].purchase_number == number
