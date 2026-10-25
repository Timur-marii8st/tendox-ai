"""Synthetic HTTP-to-runtime-PostgreSQL beta flow and immutable/RLS regressions."""

from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_company_profile_pg import command
from test_eis_analogs_pg import archive
from test_eis_characteristic_pair_pg import storage as storage_fixture

from procurement.access import AccessRole
from procurement.api.app import create_app
from procurement.api.contracts import Principal
from procurement.domain.company_profile_snapshot import ProfileSelectionCommand
from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.storage.beta_quote_schema import beta_quote_records
from procurement.storage.company_profile import save_profile, select_profile
from procurement.storage.eis_notice_index import (
    EisReadyWindow,
    ingest_ready_window,
    preflight_ready_window,
)
from test_beta_quote import quote

storage = storage_fixture
NOW = datetime.now(UTC)


def ingest(storage, company, *, number="1" * 19, version=1, expired=False):
    with ZipFile(
        BytesIO(
            archive(
                number,
                version=version,
                deadline=(NOW + timedelta(days=-1 if expired else 30)).isoformat(),
            )
        )
    ) as source:
        xml = source.read("notice.xml").replace(
            b"</notificationInfo>",
            b"""<contractConditionsInfo><maxPriceInfo><maxPrice>120000</maxPrice><currency><code>RUB</code></currency></maxPriceInfo><deliveryPlaceInfo><deliveryPlace><region><name>Moscow</name></region></deliveryPlace></deliveryPlaceInfo></contractConditionsInfo></notificationInfo>""",
        )
    out = BytesIO()
    with ZipFile(out, "w") as target:
        target.writestr("notice.xml", xml)
    window = EisReadyWindow(
        EisDateSelection("50", date(2026, 1, version), 3).window_key, "a" * 64, 1, (out.getvalue(),)
    )
    notice = preflight_ready_window(window).inspections[0].records[0]
    ingest_ready_window(storage, company, window, actor_id="synthetic")
    return dict(
        notice=dict(
            law="44",
            purchase_number=number,
            version_number=version,
            notice_xml_sha256=notice.xml_sha256,
        ),
        lot_index=None,
    )


class Auth:
    def __init__(self, company, role=AccessRole.OPERATOR):
        self.company, self.role = company, role

    async def authenticate(self, credential):
        return (
            Principal(company_id=self.company, actor_id="synthetic", access_role=self.role)
            if credential == "test"
            else None
        )


def client(storage, company, role=AccessRole.OPERATOR):
    return TestClient(
        create_app(
            object(), Auth(company, role), eis_index_storage=storage, profile_storage=storage
        )
    )


def declaration(ref):
    data = quote(issued_at=NOW - timedelta(days=1), valid_until=NOW + timedelta(days=10))
    return ref | dict(record_id=str(uuid4()), quote=data.model_dump(mode="json"))


def profile(storage, company):
    p = save_profile(
        storage,
        company,
        "synthetic",
        AccessRole.OPERATOR,
        command(
            **{
                "identity.name": "Synthetic",
                "supplied_goods": ("Бумага",),
                "geography.all_russia": True,
            }
        ),
        str(uuid4()),
    )
    select_profile(
        storage,
        company,
        "synthetic",
        AccessRole.OPERATOR,
        ProfileSelectionCommand(version=p.version, snapshot_sha256=p.snapshot_sha256),
        str(uuid4()),
    )
    return p


def test_http_source_quote_costs_profile_and_financial_order_roundtrip(storage):
    company = "beta-e2e-" + uuid4().hex
    ref = ingest(storage, company)
    p = profile(storage, company)
    c = client(storage, company)
    headers = {"Authorization": "Bearer test"}
    nav = c.post(
        "/v1/tender-discovery/eis-navigation/read", json={"request": ref["notice"]}, headers=headers
    )
    assert nav.status_code == 200, nav.text
    assert nav.json()["delivery_regions"][0]["value"] == "Moscow"
    payload = declaration(ref)
    saved = c.post("/v1/beta-procurement/quote/save", json=payload, headers=headers)
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert result["calculation"]["status"] == "CALCULATED", result
    assert [s["profit"] for s in result["calculation"]["scenarios"]] == [
        "50000.00",
        "45000.00",
        "35000.00",
    ]
    assert result["calculation"]["participation"] == "UNKNOWN"
    read = client(storage, company).post(
        "/v1/beta-procurement/quote/read", json=ref, headers=headers
    )
    assert read.status_code == 200 and read.json()["record_id"] == payload["record_id"]
    ranked = c.post(
        "/v1/beta-procurement/shortlist",
        json={"notices": [ref], "region": "Moscow"},
        headers=headers,
    )
    assert ranked.status_code == 200, ranked.text
    assert ranked.json()["financial_order"] == [payload["record_id"]]
    assert ranked.json()["profile"]["snapshot_sha256"] == p.snapshot_sha256
    assert ranked.json()["rows"][0]["profile_status"] == "UNKNOWN"
    retry = c.post("/v1/beta-procurement/quote/save", json=payload, headers=headers)
    assert retry.status_code == 200, retry.text


def test_foreign_tenant_cannot_read_navigation_or_quote_and_auditor_cannot_write(storage):
    company = "beta-rls-" + uuid4().hex
    ref = ingest(storage, company)
    payload = declaration(ref)
    headers = {"Authorization": "Bearer test"}
    assert (
        client(storage, company)
        .post("/v1/beta-procurement/quote/save", json=payload, headers=headers)
        .status_code
        == 200
    )
    foreign = client(storage, "foreign-" + company)
    assert (
        foreign.post(
            "/v1/tender-discovery/eis-navigation/read",
            json={"request": ref["notice"]},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        foreign.post("/v1/beta-procurement/quote/read", json=ref, headers=headers).json()[
            "source_status"
        ]
        == "NO_QUOTE"
    )
    assert (
        foreign.post("/v1/beta-procurement/quote/save", json=payload, headers=headers).status_code
        == 404
    )
    assert (
        client(storage, company, AccessRole.AUDITOR)
        .post("/v1/beta-procurement/quote/save", json=payload, headers=headers)
        .status_code
        == 403
    )
    with storage.transaction("foreign-" + company) as conn:
        assert (
            conn.execute(
                select(beta_quote_records).where(
                    beta_quote_records.c.record_id == payload["record_id"]
                )
            ).first()
            is None
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(text("DELETE FROM beta_quote_records WHERE company_id=:c"), {"c": company})


def test_expired_source_incomplete_costs_and_idempotency_conflict(storage):
    company = "beta-negative-" + uuid4().hex
    ref = ingest(storage, company, expired=True)
    headers = {"Authorization": "Bearer test"}
    c = client(storage, company)
    payload = declaration(ref)
    saved = c.post("/v1/beta-procurement/quote/save", json=payload, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["calculation"]["status"] == "BLOCKED"
    payload["quote"]["amount_ex_vat"] = "1"
    assert (
        c.post("/v1/beta-procurement/quote/save", json=payload, headers=headers).status_code == 409
    )
    company2 = "beta-incomplete-" + uuid4().hex
    ref2 = ingest(storage, company2)
    payload2 = declaration(ref2)
    payload2["quote"]["expenses"] = {}
    saved = client(storage, company2).post(
        "/v1/beta-procurement/quote/save", json=payload2, headers=headers
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["calculation"]["status"] == "UNKNOWN"


def test_no_selected_profile_or_different_region_never_gets_financial_position(storage):
    company = "beta-profile-" + uuid4().hex
    ref = ingest(storage, company)
    c = client(storage, company)
    headers = {"Authorization": "Bearer test"}
    assert (
        c.post(
            "/v1/beta-procurement/quote/save", json=declaration(ref), headers=headers
        ).status_code
        == 200
    )
    ranked = c.post("/v1/beta-procurement/shortlist", json={"notices": [ref]}, headers=headers)
    assert ranked.status_code == 200, ranked.text
    assert ranked.json()["financial_order"] == []
    profile(storage, company)
    ranked = c.post(
        "/v1/beta-procurement/shortlist",
        json={"notices": [ref], "region": "Other"},
        headers=headers,
    )
    assert ranked.status_code == 200, ranked.text
    assert ranked.json()["financial_order"] == []
    assert ranked.json()["rows"][0]["profile_status"] == "UNKNOWN"
    assert "SELECTED_DELIVERY_REGION_NOT_CONFIRMED" in ranked.json()["rows"][0]["reasons"]


def test_discovery_runtime_retains_cached_navigation_routes_after_filter(storage, monkeypatch):
    from procurement.api.discovery_runtime import create_discovery_app

    company = "beta-runtime-" + uuid4().hex
    ref = ingest(storage, company)
    token = "synthetic_runtime_navigation_token_20261021"
    monkeypatch.setenv("DATABASE_URL", storage._engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("EIS_PILOT_TOKEN", token)
    monkeypatch.setenv("EIS_PILOT_COMPANY", company)
    app = create_discovery_app()
    try:
        c = TestClient(app)
        paths = c.get("/openapi.json").json()["paths"]
        assert "/v1/tender-discovery/eis-navigation/read" in paths
        assert "/v1/tender-discovery/eis-public-unit-price/read" in paths
        result = c.post(
            "/v1/tender-discovery/eis-navigation/read",
            json={"request": ref["notice"]},
            headers={"Authorization": "Bearer " + token},
        )
        assert result.status_code == 200, result.text
        assert result.json()["delivery_regions"][0]["value"] == "Moscow"
        assert (
            c.post(
                "/v1/beta-procurement/quote/read",
                json=ref,
                headers={"Authorization": "Bearer " + token},
            ).status_code
            == 401
        )
    finally:
        app.state.eis_index_engine.dispose()


def test_223_navigation_uses_exact_snapshot_member_and_official_source_links(storage):
    from procurement.storage.eis_223_index import ingest_notice223_window
    from test_eis_223_archive import xml, zip_bytes
    from test_eis_223_index import window

    company = "beta-223-nav-" + uuid4().hex
    extra = (
        "<p:urlVSRZ>https://trade.example/auction/1</p:urlVSRZ>"
        "<p:urlEIS>https://zakupki.gov.ru/223/purchase/public/purchase/info/"
        "common-info.html?regNumber=32600000001</p:urlEIS>"
    )
    raw = xml(deadline="2030-01-01T10:00:00Z", extra=extra).replace(
        b"<t:lotData>", b"<t:lotData><t:deliveryPlace><t:region>Moscow</t:region></t:deliveryPlace>"
    )
    import hashlib

    from procurement.storage.eis_mixed_comparison import MixedNoticeRef
    from procurement.storage.tender_navigation import read_navigation

    ingest_notice223_window(
        storage, company, window(zip_bytes([("exact-source.xml", raw)])), actor_id="synthetic"
    )
    ref = MixedNoticeRef(
        law="223",
        purchase_number="32600000001",
        version_number=2,
        notice_xml_sha256=hashlib.sha256(raw).hexdigest(),
    )
    result = read_navigation(storage, company, ref)
    assert result.platform_url.value == "https://trade.example/auction/1"
    assert result.delivery_regions[0].value == "Moscow"
    with pytest.raises(LookupError):
        read_navigation(storage, "foreign-" + company, ref)
