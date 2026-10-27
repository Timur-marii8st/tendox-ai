import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from procurement.access import AccessRole
from procurement.api import beta_procurement as api
from procurement.api.contracts import Principal
from procurement.storage.beta_quote import BetaQuoteReport

REF = {
    "notice": {
        "law": "44",
        "purchase_number": "1" * 19,
        "version_number": 1,
        "notice_xml_sha256": "a" * 64,
    },
    "lot_index": None,
}


def client(monkeypatch):
    calls = []

    async def authenticate(request: Request):
        if request.headers.get("authorization") != "Bearer personal":
            raise HTTPException(401, "invalid_credentials")
        return Principal(
            company_id="server-tenant", actor_id="server-actor", access_role=AccessRole.OPERATOR
        )

    def read(storage, company, ref, *, actor):
        calls.append((company, actor, ref))
        return BetaQuoteReport(ref=ref, source_status="NO_QUOTE")

    monkeypatch.setattr(api, "quote_report", read)
    app = FastAPI()
    app.include_router(api.beta_procurement_router(object(), authenticate))
    return TestClient(app), calls


def test_identity_is_server_derived_and_no_quote_is_explicit(monkeypatch):
    c, calls = client(monkeypatch)
    r = c.post(
        "/v1/beta-procurement/quote/read", headers={"Authorization": "Bearer personal"}, json=REF
    )
    assert r.status_code == 200 and r.json()["source_status"] == "NO_QUOTE"
    assert r.headers["cache-control"] == "no-store"
    assert calls[0][:2] == ("server-tenant", "server-actor")


@pytest.mark.parametrize(
    "extra", [{"company_id": "foreign"}, {"actor": "foreign"}, {"ceiling_rub": "999999999"}]
)
def test_caller_cannot_supply_identity_or_source_ceiling(monkeypatch, extra):
    c, calls = client(monkeypatch)
    r = c.post(
        "/v1/beta-procurement/quote/read",
        headers={"Authorization": "Bearer personal"},
        json=REF | extra,
    )
    assert r.status_code == 422 and not calls


def test_unauthorized_and_oversized_payloads_never_reach_storage(monkeypatch):
    c, calls = client(monkeypatch)
    assert c.post("/v1/beta-procurement/quote/read", json=REF).status_code == 401
    r = c.post(
        "/v1/beta-procurement/quote/read",
        headers={"Authorization": "Bearer personal", "Content-Type": "application/json"},
        content=b" " * 32769,
    )
    assert r.status_code == 413 and not calls


def test_history_read_is_private_server_derived_and_rejects_client_eligibility(monkeypatch):
    from procurement.domain.regional_discount import regional_discount
    from procurement.storage.beta_quote import BetaHistoryReport
    from test_regional_discount import NOW, history

    calls = []

    def read_history(storage, company, ref, *, actor):
        calls.append((company, actor))
        data = history(
            observations=[],
            company_id=company,
            target_id=f"44:{ref.notice.purchase_number}:0",
        )
        return BetaHistoryReport(ref=ref, history=regional_discount(data, now=NOW))

    monkeypatch.setattr(api, "history_report", read_history)
    c, _ = client(monkeypatch)
    url = "/v1/beta-procurement/history/read"
    assert c.post(url, json=REF).status_code == 401
    headers = {"Authorization": "Bearer personal"}
    for extra in ({"company_id": "foreign"}, {"observations": []}, {"current_result": True}):
        assert c.post(url, json=REF | extra, headers=headers).status_code == 422
    assert not calls
    result = c.post(url, json=REF, headers=headers)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert calls == [("server-tenant", "server-actor")]
    assert result.json()["history"]["status"] == "UNKNOWN"
    assert result.json()["history"]["realistic_discount"] is None
