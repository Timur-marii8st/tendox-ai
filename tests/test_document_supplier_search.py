"""A DOCX tender reaches source search only after exact-plan approval."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from io import BytesIO
from typing import cast

import docx
import httpx
import pytest

from procurement.access import AccessRole
from procurement.api import create_app
from procurement.api.contracts import CaseService, DocumentRecord, Principal
from procurement.documents.extraction import (
    DocumentInput,
    ExtractionResult,
    ExtractionStatus,
    extract_document,
)
from procurement.documents.facts import DocumentRole
from procurement.sources.browser_catalog import BrowserAttempt, BrowserSite, BrowserStatus
from procurement.sources.direct_catalog import DirectCatalogAttempt, DirectCatalogStatus
from procurement.sources.document_search_plan import (
    DocumentSupplierSearchPlan,
    SearchPlanStatus,
    build_document_supplier_search_plan,
)
from procurement.sources.eaeu_registry import RegistryFetchStatus, RegistrySearchResult
from procurement.sources.yandex_business import YandexBusinessAttempt, YandexBusinessStatus


def _docx_bytes(*lines: str) -> bytes:
    source = docx.Document()
    for line in lines:
        source.add_paragraph(line)
    output = BytesIO()
    source.save(output)
    return output.getvalue()


def _document(*lines: str, role: DocumentRole = DocumentRole.TENDER_REQUIREMENTS) -> DocumentRecord:
    content = _docx_bytes(*lines)
    extraction = extract_document(
        DocumentInput(
            document_id="doc-1",
            filename="tender.docx",
            declared_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=content,
        )
    )
    assert extraction.status is ExtractionStatus.PASS
    return DocumentRecord(
        document_id="doc-1",
        original_filename="tender.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        document_role=role,
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        extraction=extraction,
        created_at=datetime(2026, 9, 21, tzinfo=UTC),
    )


class _Auth:
    async def authenticate(self, credential: str) -> Principal | None:
        if credential == "operator":
            return Principal(company_id="tenant-a", actor_id="operator-a")
        if credential == "auditor":
            return Principal(
                company_id="tenant-a", actor_id="auditor-a", access_role=AccessRole.AUDITOR
            )
        if credential == "other-tenant":
            return Principal(company_id="tenant-b", actor_id="operator-b")
        return None


class _Documents:
    def __init__(self, document: DocumentRecord | None = None) -> None:
        self.document = document

    async def store_document(
        self,
        *,
        company_id: str,
        actor_id: str,
        document_id: str,
        original_filename: str,
        media_type: str,
        document_role: DocumentRole,
        content: bytes,
        extraction: ExtractionResult,
        idempotency_key: str,
        request_digest: str,
    ) -> DocumentRecord:
        assert company_id == "tenant-a" and actor_id == "operator-a"
        assert idempotency_key and request_digest
        self.document = DocumentRecord(
            document_id=document_id,
            original_filename=original_filename,
            media_type=media_type,
            document_role=document_role,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            extraction=extraction,
            created_at=datetime(2026, 9, 21, tzinfo=UTC),
        )
        return self.document

    async def get_document(self, *, company_id: str, document_id: str) -> DocumentRecord | None:
        if self.document and company_id == "tenant-a" and document_id == self.document.document_id:
            return self.document
        return None


def test_pagination_policy_and_urls_are_bound_to_plan_digest():
    plan = build_document_supplier_search_plan(_document("Наименование товара: МФУ HP"))
    assert plan.schema_version == "supplier-search-plan-v8"
    destination = plan.destinations[1]
    assert destination.pagination_policy == "CATEGORY_LINK_OR_STATE_V1"
    assert len(destination.page_urls) == 2
    assert destination.page_urls[1].endswith("hid=138608&page=2")
    payload = plan.model_dump(mode="json")
    payload["destinations"][1]["pagination_policy"] = None
    with pytest.raises(ValueError):
        DocumentSupplierSearchPlan.model_validate(payload)


def test_supl_browser_destination_is_bound_and_http_mode_excludes_it():
    document = _document("Наименование товара: Насос центробежный")
    auto = build_document_supplier_search_plan(document, mode="AUTO")
    http = build_document_supplier_search_plan(document, mode="HTTP")
    destination = next(d for d in auto.destinations if d.site_id == "supl_biz_pumps")
    assert destination.transport == "BROWSER"
    assert destination.browser_loads_page_resources
    assert destination.page_urls == (destination.api_url,)
    assert all(d.site_id != "supl_biz_pumps" for d in http.destinations)
    payload = auto.model_dump(mode="json")
    payload["destinations"][-1]["api_url"] = "https://supl.biz/proposals/search/"
    with pytest.raises(ValueError):
        DocumentSupplierSearchPlan.model_validate(payload)


@pytest.mark.parametrize(
    ("product", "category", "path"),
    [
        ("Сервер Гравитон С2242ИУ", "серверы", "/servery-i-khranenie-dannykh/servery/"),
        ("Ноутбук Гравитон Н15А-Б", "ноутбуки", "/klientskie-ustroystva/noutbuki/"),
        ("МФУ Гравитон ГМ2501", "принтеры и МФУ", "/klientskie-ustroystva/printery/"),
        ("Компьютер Гравитон Д52И", "ПК", "/klientskie-ustroystva/pk/"),
    ],
)
def test_graviton_category_is_exactly_bound_to_plan(product, category, path):
    plan = build_document_supplier_search_plan(_document(f"Наименование товара: {product}"))
    destinations = [d for d in plan.destinations if d.site_id == "graviton_catalog"]
    assert len(destinations) == 1
    destination = destinations[0]
    assert category in destination.site_name
    assert destination.api_url.endswith(path)
    assert destination.page_urls == (destination.api_url,)
    assert destination.transport == "HTTP"
    payload = plan.model_dump(mode="json")
    payload["destinations"][-1]["api_url"] = "https://other.invalid/"
    with pytest.raises(ValueError):
        DocumentSupplierSearchPlan.model_validate(payload)


@pytest.mark.parametrize("mode", ["AUTO", "HTTP", "BROWSER"])
def test_graviton_is_planned_and_survives_registry_failure(monkeypatch, mode):
    from procurement.sources.graviton_catalog import GravitonAttempt, GravitonCandidate

    calls = []

    def graviton(query):
        calls.append(query)
        return GravitonAttempt(
            query=query,
            fetch_status="COMPLETED",
            observed_at=datetime.now(UTC),
            response_sha256="a" * 64,
            scanned_count=1,
            candidates=(
                GravitonCandidate(
                    title="Сервер Гравитон Тест",
                    url="https://graviton.ru/catalog/servery-i-khranenie-dannykh/servery/test/",
                    source_item_index=1,
                ),
            ),
        )

    def registry(query):
        return RegistrySearchResult(
            query=query,
            fetch_status=RegistryFetchStatus.SOURCE_ERROR,
            observed_at=datetime.now(UTC),
            request_sha256="a" * 64,
        )

    monkeypatch.setattr("procurement.api.app.search_graviton_catalog", graviton)
    monkeypatch.setattr("procurement.api.app.search_eaeu_registry", registry)
    for name in ["search_direct_catalog", "search_yandex_business_category", "run_browser_source"]:
        monkeypatch.setattr(
            f"procurement.api.app.{name}", lambda *a, **k: pytest.fail("unplanned source")
        )
    app = create_app(
        cast(CaseService, _Documents(_document("Наименование товара: Сервер Гравитон"))), _Auth()
    )

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer operator"}
            response = await client.get(
                f"/v1/documents/doc-1/supplier-search-plan?mode={mode}", headers=headers
            )
            plan = response.json()
            assert [d["site_id"] for d in plan["destinations"]] == [
                "eaeu_products",
                "graviton_catalog",
            ]
            assert plan["destinations"][1]["transport"] == "HTTP"
            assert calls == []
            payload = {
                "mode": mode,
                "plan_sha256": plan["plan_sha256"],
                "approve_exact_payload": True,
            }
            wrong_tenant = await client.post(
                "/v1/documents/doc-1/supplier-search-runs",
                headers={"Authorization": "Bearer other-tenant"},
                json=payload,
            )
            assert wrong_tenant.status_code == 404 and calls == []
            response = await client.post(
                "/v1/documents/doc-1/supplier-search-runs", headers=headers, json=payload
            )
            assert response.status_code == 200
            result = response.json()
            assert result["graviton_catalog"]["fetch_status"] == "COMPLETED"
            assert result["graviton_catalog"]["candidates"][0]["suitability"] == "UNKNOWN"
            assert result["eaeu_products"]["fetch_status"] == "SOURCE_ERROR"
            assert result["direct_catalog"] is None and result["yandex_business"] is None
            assert calls == ["Сервер Гравитон"]

    asyncio.run(check())


@pytest.mark.parametrize("mode", ["AUTO", "HTTP", "BROWSER"])
def test_depo_is_exactly_planned_and_survives_registry_failure(monkeypatch, mode):
    from procurement.sources.depo_catalog import DEPO_SERVERS_URL, DepoAttempt, DepoCandidate

    calls = []

    def depo(query):
        calls.append(query)
        return DepoAttempt(
            query=query,
            fetch_status="COMPLETED",
            observed_at=datetime.now(UTC),
            response_sha256="a" * 64,
            scanned_count=1,
            candidates=(
                DepoCandidate(
                    title="Сервер DEPO Storm 1430B1R",
                    url=DEPO_SERVERS_URL + "depo-storm-1000/server-depo-storm-1430b1r/",
                    source_item_index=1,
                ),
            ),
        )

    def registry(query):
        return RegistrySearchResult(
            query=query,
            fetch_status=RegistryFetchStatus.SOURCE_ERROR,
            observed_at=datetime.now(UTC),
            request_sha256="a" * 64,
        )

    monkeypatch.setattr("procurement.api.app.search_depo_catalog", depo)
    monkeypatch.setattr("procurement.api.app.search_eaeu_registry", registry)
    for name in [
        "search_direct_catalog", "search_yandex_business_category", "run_browser_source",
        "search_graviton_catalog",
    ]:
        monkeypatch.setattr(
            f"procurement.api.app.{name}", lambda *a, **k: pytest.fail("unplanned source")
        )
    app = create_app(
        cast(CaseService, _Documents(_document("Наименование товара: Сервер DEPO Storm 1430B1R"))),
        _Auth(),
    )

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            headers = {"Authorization": "Bearer operator"}
            response = await client.get(
                f"/v1/documents/doc-1/supplier-search-plan?mode={mode}", headers=headers
            )
            plan = response.json()
            assert [d["site_id"] for d in plan["destinations"]] == [
                "eaeu_products", "depo_servers",
            ]
            assert plan["destinations"][1]["api_url"] == DEPO_SERVERS_URL
            assert plan["destinations"][1]["transport"] == "HTTP"
            payload = {
                "mode": mode,
                "plan_sha256": plan["plan_sha256"],
                "approve_exact_payload": True,
            }
            wrong_tenant = await client.post(
                "/v1/documents/doc-1/supplier-search-runs",
                headers={"Authorization": "Bearer other-tenant"},
                json=payload,
            )
            assert wrong_tenant.status_code == 404 and calls == []
            response = await client.post(
                "/v1/documents/doc-1/supplier-search-runs", headers=headers, json=payload
            )
            assert response.status_code == 200
            result = response.json()
            assert result["depo_catalog"]["fetch_status"] == "COMPLETED"
            assert result["depo_catalog"]["candidates"][0]["suitability"] == "UNKNOWN"
            assert result["eaeu_products"]["fetch_status"] == "SOURCE_ERROR"
            assert result["graviton_catalog"] is None
            assert calls == ["Сервер DEPO Storm 1430B1R"]

    asyncio.run(check())


def test_docx_to_approved_search_route(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _docx_bytes("Наименование товара: Насос центробежный", "Срок поставки: 20 дней")
    calls: list[tuple[str, str]] = []

    def registry(query: str) -> RegistrySearchResult:
        calls.append(("registry", query))
        return RegistrySearchResult(
            query=query,
            fetch_status=RegistryFetchStatus.COMPLETED,
            observed_at=datetime(2026, 9, 21, tzinfo=UTC),
            request_sha256="a" * 64,
            response_sha256="b" * 64,
            response_byte_size=42,
            matched_count=0,
        )

    def catalog(query: str) -> DirectCatalogAttempt:
        calls.append(("catalog", query))
        return DirectCatalogAttempt(
            query=query,
            fetch_status=DirectCatalogStatus.COMPLETED,
            observed_at=datetime(2026, 9, 21, tzinfo=UTC),
            response_sha256="c" * 64,
            response_byte_size=42,
        )

    def yandex(query: str) -> YandexBusinessAttempt:
        calls.append(("yandex", query))
        return YandexBusinessAttempt(
            query=query,
            category_url="https://business.market.yandex.ru/catalog--nasosy-i-komplektuiushchie/18060427/list",
            fetch_status=YandexBusinessStatus.COMPLETED,
            observed_at=datetime(2026, 9, 21, tzinfo=UTC),
            response_sha256="d" * 64,
            response_byte_size=42,
            scanned_count=0,
        )

    async def browser(*, company_id, site, query):
        calls.append(("supl", query))
        assert company_id == "tenant-a" and site is BrowserSite.SUPL_BIZ
        return BrowserAttempt(
            company_id=company_id,
            site=site,
            query=query,
            source_url="https://supl.biz/promyishlennyie-nasosyi-category4240/",
            status=BrowserStatus.COMPLETED,
            observed_at=datetime.now(UTC),
            query_mode="TITLE_TERMS",
        )

    monkeypatch.setattr("procurement.api.app.search_eaeu_registry", registry)
    monkeypatch.setattr("procurement.api.app.search_direct_catalog", catalog)
    monkeypatch.setattr("procurement.api.app.search_yandex_business_category", yandex)
    monkeypatch.setattr("procurement.api.app.run_browser_source", browser)
    app = create_app(cast(CaseService, _Documents()), _Auth())

    async def check() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            uploaded = await client.post(
                "/v1/documents",
                headers={"Authorization": "Bearer operator", "Idempotency-Key": "search-docx"},
                files={
                    "file": (
                        "tender.docx",
                        content,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
                data={"document_role": DocumentRole.TENDER_REQUIREMENTS.value},
            )
            assert uploaded.status_code == 201
            document_id = uploaded.json()["document_id"]
            assert uploaded.json()["extraction"]["status"] == "PASS"
            url = f"/v1/documents/{document_id}/supplier-search-plan"
            anonymous = await client.get(url)
            assert anonymous.status_code == 401
            other = await client.get(url, headers={"Authorization": "Bearer other-tenant"})
            assert other.status_code == 404
            response = await client.get(url, headers={"Authorization": "Bearer operator"})
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            plan = response.json()
            assert plan["status"] == "READY"
            assert plan["query"] == "Насос центробежный"
            assert plan["query_evidence"]["provenance"]["document_id"] == document_id
            assert [d["site_id"] for d in plan["destinations"]] == [
                "eaeu_products", "yandex_market_business", "supl_biz_pumps"
            ]
            assert plan["destinations"][2]["transport"] == "BROWSER"
            assert calls == []

            run_url = f"/v1/documents/{document_id}/supplier-search-runs"
            headers = {"Authorization": "Bearer operator"}
            stale = await client.post(
                run_url,
                headers=headers,
                json={
                    "plan_sha256": "0" * 64,
                    "approve_exact_payload": True,
                },
            )
            assert stale.status_code == 409
            assert calls == []
            forbidden = await client.post(
                run_url,
                headers={"Authorization": "Bearer auditor"},
                json={
                    "plan_sha256": plan["plan_sha256"],
                    "approve_exact_payload": True,
                },
            )
            assert forbidden.status_code == 403
            assert calls == []
            unapproved = await client.post(
                run_url,
                headers=headers,
                json={
                    "plan_sha256": plan["plan_sha256"],
                    "approve_exact_payload": False,
                },
            )
            assert unapproved.status_code == 422
            assert calls == []
            executed = await client.post(
                run_url,
                headers=headers,
                json={
                    "plan_sha256": plan["plan_sha256"],
                    "approve_exact_payload": True,
                },
            )
            assert executed.status_code == 200
            assert executed.headers["cache-control"] == "no-store"
            result = executed.json()
            assert result["plan"]["plan_sha256"] == plan["plan_sha256"]
            assert result["eaeu_products"]["fetch_status"] == "COMPLETED"
            assert result["direct_catalog"] is None
            assert result["yandex_business"]["fetch_status"] == "COMPLETED"
            assert result["browser_attempts"][0]["site"] == "supl_biz"
            assert sorted(calls) == sorted(
                [
                    ("registry", "Насос центробежный"),
                    ("yandex", "Насос центробежный"),
                    ("supl", "Насос центробежный"),
                ]
            )

    asyncio.run(check())


def test_direct_catalog_preview_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def catalog(query: str) -> DirectCatalogAttempt:
        calls.append(query)
        return DirectCatalogAttempt(
            query=query,
            fetch_status=DirectCatalogStatus.SOURCE_ERROR,
            observed_at=datetime(2026, 9, 21, tzinfo=UTC),
            error_code="CATALOG_UNAVAILABLE_OR_CHANGED",
        )

    monkeypatch.setattr("procurement.api.app.search_direct_catalog", catalog)
    app = create_app(cast(CaseService, _Documents()), _Auth())

    async def check() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            url = "/v1/supplier-discovery/direct-catalog?query=HPE%20Gen12"
            anonymous = await client.get(url)
            assert anonymous.status_code == 401
            assert calls == []
            response = await client.get(url, headers={"Authorization": "Bearer operator"})
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["fetch_status"] == "SOURCE_ERROR"
            assert calls == ["HPE Gen12"]

    asyncio.run(check())


def test_yandex_category_preview_reports_uncovered_query(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def yandex(query: str) -> YandexBusinessAttempt:
        calls.append(query)
        return YandexBusinessAttempt(
            query=query,
            fetch_status=YandexBusinessStatus.QUERY_NOT_COVERED,
            observed_at=datetime(2026, 9, 22, tzinfo=UTC),
            error_code="NO_VERIFIED_CATEGORY_FOR_QUERY",
        )

    monkeypatch.setattr("procurement.api.app.search_yandex_business_category", yandex)
    app = create_app(cast(CaseService, _Documents()), _Auth())

    async def check() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            url = "/v1/supplier-discovery/yandex-business?query=Server%20HPE"
            anonymous = await client.get(url)
            assert anonymous.status_code == 401
            assert calls == []
            response = await client.get(url, headers={"Authorization": "Bearer operator"})
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["fetch_status"] == "QUERY_NOT_COVERED"
            assert calls == ["Server HPE"]

    asyncio.run(check())


@pytest.mark.parametrize(
    ("lines", "role", "status"),
    [
        (
            ("Мощность: 2 кВт", "Срок поставки: 20 дней"),
            DocumentRole.TENDER_REQUIREMENTS,
            SearchPlanStatus.NO_PRODUCT_ANCHOR,
        ),
        (
            ("Товар: Насос", "Товар: Компрессор"),
            DocumentRole.TENDER_REQUIREMENTS,
            SearchPlanStatus.AMBIGUOUS,
        ),
        (("Товар: Насос",), DocumentRole.SUPPLIER_QUOTE, SearchPlanStatus.EXTRACTION_UNAVAILABLE),
    ],
)
def test_uncertain_document_blocks_search(
    lines: tuple[str, ...],
    role: DocumentRole,
    status: SearchPlanStatus,
) -> None:
    plan = build_document_supplier_search_plan(_document(*lines, role=role))
    assert plan.status is status
    assert plan.query is None
    assert plan.destinations == ()


@pytest.mark.parametrize(
    ("mode", "http_fails", "expected_sites"),
    [
        ("HTTP", True, []),
        ("AUTO", False, ["supl_biz"]),
        ("AUTO", True, ["yandex_business", "supl_biz"]),
        ("BROWSER", False, ["yandex_business", "supl_biz"]),
    ],
)
def test_document_browser_routing_is_approved_and_tenant_scoped(
    monkeypatch, mode, http_fails, expected_sites
) -> None:
    browser_calls = []
    http_calls = []
    document = _document("Наименование товара: Насос центробежный")

    def registry(query):
        return RegistrySearchResult(
            query=query,
            fetch_status=RegistryFetchStatus.SOURCE_ERROR,
            observed_at=datetime.now(UTC),
            request_sha256="a" * 64,
        )

    def direct(query):
        http_calls.append("servermall")
        return DirectCatalogAttempt(
            query=query,
            observed_at=datetime.now(UTC),
            fetch_status=DirectCatalogStatus.SOURCE_ERROR
            if http_fails
            else DirectCatalogStatus.COMPLETED,
        )

    def yandex(query):
        http_calls.append("yandex")
        return YandexBusinessAttempt(
            query=query,
            observed_at=datetime.now(UTC),
            fetch_status=YandexBusinessStatus.SOURCE_ERROR
            if http_fails
            else YandexBusinessStatus.COMPLETED,
        )

    async def browser(*, company_id, site, query):
        browser_calls.append((company_id, site.value, query))
        # Частичная блокировка не отменяет второй источник.
        return BrowserAttempt(
            company_id=company_id,
            site=site,
            query=query,
            source_url="https://servermall.ru/"
            if site == BrowserSite.SERVERMALL
            else "https://supl.biz/promyishlennyie-nasosyi-category4240/"
            if site == BrowserSite.SUPL_BIZ
            else "https://business.market.yandex.ru/",
            status=BrowserStatus.COMPLETED
            if site == BrowserSite.SERVERMALL
            else BrowserStatus.BLOCKED,
            observed_at=datetime.now(UTC),
            query_mode="CATEGORY_PREVIEW",
        )

    monkeypatch.setattr("procurement.api.app.search_eaeu_registry", registry)
    monkeypatch.setattr("procurement.api.app.search_direct_catalog", direct)
    monkeypatch.setattr("procurement.api.app.search_yandex_business_category", yandex)
    monkeypatch.setattr("procurement.api.app.run_browser_source", browser)
    app = create_app(cast(CaseService, _Documents(document)), _Auth())

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            path = "/v1/documents/doc-1/supplier-search"
            headers = {"Authorization": "Bearer operator"}
            response = await c.get(path + "-plan", params={"mode": mode}, headers=headers)
            assert response.status_code == 200
            plan = response.json()
            assert plan["mode"] == mode
            assert plan["destinations"][0]["transport"] == "HTTP"
            assert any(d["site_id"] == "supl_biz_pumps" for d in plan["destinations"]) == (
                mode != "HTTP"
            )
            assert browser_calls == [] and http_calls == []
            body = {"mode": mode, "plan_sha256": plan["plan_sha256"], "approve_exact_payload": True}
            for bad_headers, expected_status in [
                ({}, 401),
                ({"Authorization": "Bearer auditor"}, 403),
                ({"Authorization": "Bearer other-tenant"}, 404),
            ]:
                r = await c.post(path + "-runs", headers=bad_headers, json=body)
                assert r.status_code == expected_status
            forged = await c.post(path + "-runs", headers=headers, json={**body, "company_id": "b"})
            assert forged.status_code == 422
            changed = await c.post(
                path + "-runs",
                headers=headers,
                json={**body, "mode": "HTTP" if mode != "HTTP" else "BROWSER"},
            )
            assert changed.status_code == 409
            assert browser_calls == [] and http_calls == []
            run = await c.post(path + "-runs", headers=headers, json=body)
            assert run.status_code == 200
            data = run.json()
            assert data["eaeu_products"]["fetch_status"] == "SOURCE_ERROR"
            assert [call[1] for call in browser_calls] == expected_sites
            assert all(call[0] == "tenant-a" and call[2] == plan["query"] for call in browser_calls)
            assert http_calls == ([] if mode == "BROWSER" else ["yandex"])
            assert data["direct_catalog"] is None
            if expected_sites:
                assert [a["status"] for a in data["browser_attempts"]] == ["BLOCKED"] * len(
                    expected_sites
                )

    asyncio.run(check())


def test_browser_transport_changes_exact_plan_digest() -> None:
    document = _document("Товар: HPE DL360 Gen12")
    plans = [
        build_document_supplier_search_plan(document, mode=mode)
        for mode in ("HTTP", "AUTO", "BROWSER")
    ]
    assert len({p.plan_sha256 for p in plans}) == 3
    assert all(len(p.destinations) == 2 for p in plans)
    assert plans[1].destinations[1].browser_loads_page_resources is True
    assert plans[0].destinations[1].browser_loads_page_resources is False
