# ruff: noqa: E402, E501
"""Catalog storage invariants and full persisted source lifecycle."""

from datetime import UTC, datetime, timedelta

from procurement.sources.supplier_catalog import CatalogSearchSpec
from procurement.sources.supplier_page import PageHop, PageObservation
from procurement.storage.eis_supplier_catalog import SupplierCatalogReport
from test_eis_supplier_catalog_api import REQUEST


def test_failed_search_observation_is_persistable_without_fabricated_links():
    blocked_body = b'<html><form action="/search"><a href="/product">captcha</a></form></html>'
    blocked_sha = hashlib.sha256(blocked_body).hexdigest()
    spec = CatalogSearchSpec(
        source_url="https://bumaga-s.ru/",
        query="Бумага A4",
        raw_action="/search",
        field="q",
        search_url="https://bumaga-s.ru/search?q=paper",
        html_sha256="a" * 64,
        locator="form[1]",
    )
    observation = PageObservation(
        source_url=spec.search_url,
        final_url=spec.search_url,
        observed_at=datetime(2026, 10, 6, tzinfo=UTC),
        status="BLOCKED",
        reason_code="ACCESS_BLOCKED",
        http_status=200,
        hops=(PageHop(url=spec.search_url, http_status=200),),
        dispatch_count=1,
        html_sha256=blocked_sha,
        byte_count=len(blocked_body),
    )
    report = SupplierCatalogReport(
        run_id="66666666-6666-4666-8666-666666666666",
        request=REQUEST,
        parent_page_report_sha256="b" * 64,
        position_sha256="c" * 64,
        created_at=datetime(2026, 10, 6, tzinfo=UTC),
        stage="SEARCH",
        search_spec=spec,
        selected_link=None,
        parent_search_report_sha256=None,
        status="COMPLETED",
        reason_code="FIXED_CATALOG_OBSERVATION",
        observation=observation,
        links=None,
        attempted_source_requests=1,
        source_body_sha256=blocked_sha,
        source_body_byte_count=len(blocked_body),
    )
    assert report.links is None and report.source_body_sha256 == blocked_sha


# Full persisted source chain: exact SERP root -> retained form -> search links -> product.
import copy
import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.exc import DBAPIError
from test_eis_notice_hold_pg import hold
from test_eis_supplier_search_pg import ingest
from test_eis_supplier_search_pg import storage as storage_fixture
from test_eis_supplier_serp_pg import capture as base_serp_capture

from procurement.sources.supplier_page import PageCapture
from procurement.sources.supplier_serp import SearchEngine, SerpCapture
from procurement.storage import eis_supplier_catalog as catalog_module
from procurement.storage import eis_supplier_page as page_module
from procurement.storage import eis_supplier_serp as serp_module
from procurement.storage.eis_supplier_catalog import (
    SupplierCatalogRequest,
    prepare_supplier_catalog,
    read_supplier_catalog,
)
from procurement.storage.eis_supplier_page import SupplierPageRequest, prepare_supplier_page
from procurement.storage.eis_supplier_serp import prepare_supplier_serp
from procurement.storage.models import eis_supplier_catalog_runs

storage = storage_fixture
ROOT = "https://bumaga-s.ru/"
FORM = b'<html><form action="/categories/search"><input id="global_search" name="q" type="text"></form></html>'
SEARCH_HTML = '<html><a href="/товар/paper">Бумага SvetoCopy Eco</a></html>'.encode()
PRODUCT_HTML = '<span itemscope itemtype="http://schema.org/Product"><meta itemprop="name" content="Бумага SvetoCopy Eco"><span itemprop="offers" itemscope itemtype="http://schema.org/Offer"><meta itemprop="price" content="299.6"><meta itemprop="priceCurrency" content="RUB"></span></span>'.encode()


def completed(url: str, content: bytes) -> PageCapture:
    digest = hashlib.sha256(content).hexdigest()
    obs = PageObservation(
        source_url=url,
        final_url=url,
        observed_at=datetime.now(UTC),
        status="COMPLETED",
        reason_code="HTML_OBSERVED",
        http_status=200,
        extraction_status="EMPTY",
        page_kind="UNKNOWN",
        html_sha256=digest,
        byte_count=len(content),
        hops=(PageHop(url=url, http_status=200),),
        dispatch_count=1,
    )
    return PageCapture(obs, content)


def blocked(url: str, content: bytes) -> PageCapture:
    digest = hashlib.sha256(content).hexdigest()
    return PageCapture(
        PageObservation(
            source_url=url,
            final_url=url,
            observed_at=datetime.now(UTC),
            status="BLOCKED",
            reason_code="ACCESS_BLOCKED",
            http_status=200,
            extraction_status="NOT_ATTEMPTED",
            page_kind="UNKNOWN",
            html_sha256=digest,
            byte_count=len(content),
            hops=(PageHop(url=url, http_status=200),),
            dispatch_count=1,
        ),
        content,
    )


def chain(storage, company, monkeypatch):
    position = ingest(storage, company, name="Бумага A4")

    def serp(query, *, cooldowns=(), company_id: str):
        assert company_id == company
        original = base_serp_capture(query)
        attempt = original.batch.attempts[0]
        link = attempt.links[0].model_copy(update={"url": ROOT, "title": "Каталог бумаги"})
        updated = attempt.model_copy(update={"links": (link,)})
        return SerpCapture(
            original.batch.model_copy(update={"attempts": (updated, *original.batch.attempts[1:])}),
            original.contents,
        )

    monkeypatch.setattr(serp_module, "observe_supplier_serp", serp)
    serp_report = prepare_supplier_serp(storage, company, position, actor_id="synthetic").report
    page_request = SupplierPageRequest(
        position=position, serp_run_id=serp_report.run_id, engine=SearchEngine.BING, rank=1
    )
    monkeypatch.setattr(page_module, "observe_supplier_page", lambda url: completed(url, FORM))
    page_report = prepare_supplier_page(storage, company, page_request, actor_id="synthetic").report
    return position, page_request, page_report


def test_search_product_replay_tenant_body_and_refresh(storage, monkeypatch):
    company = "catalog-" + uuid4().hex
    _, page_request, page_report = chain(storage, company, monkeypatch)
    calls = []

    def observe(url, *, allowed_host=None):
        calls.append((url, allowed_host))
        return completed(url, PRODUCT_HTML if "/товар/" in url else SEARCH_HTML)

    monkeypatch.setattr(catalog_module, "observe_supplier_page", observe)
    search_request = SupplierCatalogRequest(page=page_request, page_run_id=page_report.run_id)
    search = prepare_supplier_catalog(storage, company, search_request, actor_id="synthetic")
    assert search.report.links.returned_count == 1 and search.source_requests == 1
    search_statements = []

    def trace_search(conn, cursor, statement, parameters, context, many):
        search_statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", trace_search)
    try:
        cached_search = read_supplier_catalog(storage, company, search_request)
    finally:
        event.remove(storage._engine, "before_cursor_execute", trace_search)
    assert cached_search.report == search.report and cached_search.source_requests == 0
    assert not any("eis_supplier_catalog_runs.source_body AS" in sql for sql in search_statements)
    product_request = SupplierCatalogRequest(
        page=page_request,
        page_run_id=page_report.run_id,
        search_run_id=search.report.run_id,
        product_index=1,
    )
    product = prepare_supplier_catalog(storage, company, product_request, actor_id="synthetic")
    assert str(product.report.observation.products[0].prices[0].amount) == "299.6"
    statements = []

    def trace(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", trace)
    try:
        replay = read_supplier_catalog(storage, company, product_request)
    finally:
        event.remove(storage._engine, "before_cursor_execute", trace)
    assert replay.report == product.report and replay.source_requests == 0 and not replay.created
    assert not any("eis_supplier_catalog_runs.source_body AS" in sql for sql in statements)
    with storage.transaction("foreign-" + company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_supplier_catalog_runs)) == 0
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            update(eis_supplier_catalog_runs)
            .where(eis_supplier_catalog_runs.c.run_id == search.report.run_id)
            .values(product_index=2)
        )
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            eis_supplier_catalog_runs.delete().where(
                eis_supplier_catalog_runs.c.run_id == search.report.run_id
            )
        )
    with storage.transaction(company, consistent_read=True) as conn:
        search_row = dict(
            conn.execute(
                select(eis_supplier_catalog_runs).where(
                    eis_supplier_catalog_runs.c.run_id == search.report.run_id
                )
            )
            .mappings()
            .one()
        )
        product_row = dict(
            conn.execute(
                select(eis_supplier_catalog_runs).where(
                    eis_supplier_catalog_runs.c.run_id == product.report.run_id
                )
            )
            .mappings()
            .one()
        )
    bad_parent = copy.deepcopy(search_row)
    bad_parent_id = str(uuid4())
    bad_parent_run = str(uuid4())
    bad_parent["run_id"] = bad_parent_run
    bad_parent["cache_key"] = "1" * 64
    bad_parent["parent_page_run_id"] = bad_parent_id
    bad_parent["report"]["run_id"] = bad_parent_run
    bad_parent["report"]["request"]["page_run_id"] = bad_parent_id
    bad_parent["report_sha256"] = catalog_module._digest(bad_parent["report"])
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(insert(eis_supplier_catalog_runs).values(**bad_parent))
    bad_index = copy.deepcopy(product_row)
    bad_index_run = str(uuid4())
    bad_index["run_id"] = bad_index_run
    bad_index["cache_key"] = "2" * 64
    bad_index["product_index"] = 11
    bad_index["report"]["run_id"] = bad_index_run
    bad_index["report"]["request"]["product_index"] = 11
    bad_index["report"]["selected_link"]["index"] = 11
    bad_index["report_sha256"] = catalog_module._digest(bad_index["report"])
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(insert(eis_supplier_catalog_runs).values(**bad_index))
    with pytest.raises(ValueError, match="SUPPLIER_CATALOG_REFRESH_COOLDOWN"):
        prepare_supplier_catalog(
            storage, company, product_request, actor_id="synthetic", refresh=True
        )
    assert len(calls) == 2
    monkeypatch.setattr(catalog_module, "REFRESH_COOLDOWN", timedelta(0))
    monkeypatch.setattr(
        catalog_module,
        "observe_supplier_page",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed refresh")),
    )
    with pytest.raises(RuntimeError, match="failed refresh"):
        prepare_supplier_catalog(
            storage, company, product_request, actor_id="synthetic", refresh=True
        )
    assert read_supplier_catalog(storage, company, product_request).report.status == "STARTED"


def test_blocked_root_and_search_are_not_followed(storage, monkeypatch):
    company = "catalog-blocked-" + uuid4().hex
    position = ingest(storage, company, name="Бумага A4")

    def serp(query, *, cooldowns=(), company_id: str):
        assert company_id == company
        original = base_serp_capture(query)
        attempt = original.batch.attempts[0]
        link = attempt.links[0].model_copy(update={"url": ROOT, "title": "Каталог бумаги"})
        return SerpCapture(
            original.batch.model_copy(
                update={
                    "attempts": (
                        attempt.model_copy(update={"links": (link,)}),
                        *original.batch.attempts[1:],
                    )
                }
            ),
            original.contents,
        )

    monkeypatch.setattr(serp_module, "observe_supplier_serp", serp)
    serp_report = prepare_supplier_serp(storage, company, position, actor_id="synthetic").report
    page_request = SupplierPageRequest(
        position=position, serp_run_id=serp_report.run_id, engine=SearchEngine.BING, rank=1
    )
    monkeypatch.setattr(page_module, "observe_supplier_page", lambda url: blocked(url, FORM))
    blocked_page = prepare_supplier_page(
        storage, company, page_request, actor_id="synthetic"
    ).report
    root_request = SupplierCatalogRequest(page=page_request, page_run_id=blocked_page.run_id)
    calls = []
    monkeypatch.setattr(catalog_module, "observe_supplier_page", lambda *a, **k: calls.append(1))
    with pytest.raises(ValueError, match="SUPPLIER_CATALOG_PARENT_EVIDENCE_CONFLICT"):
        prepare_supplier_catalog(storage, company, root_request, actor_id="synthetic")
    assert calls == []

    monkeypatch.setattr(page_module, "REFRESH_COOLDOWN", timedelta(0))
    monkeypatch.setattr(page_module, "observe_supplier_page", lambda url: completed(url, FORM))
    good_page = prepare_supplier_page(
        storage, company, page_request, actor_id="synthetic", refresh=True
    ).report
    search_request = SupplierCatalogRequest(page=page_request, page_run_id=good_page.run_id)
    monkeypatch.setattr(
        catalog_module, "observe_supplier_page", lambda url, **kw: blocked(url, SEARCH_HTML)
    )
    search = prepare_supplier_catalog(storage, company, search_request, actor_id="synthetic").report
    assert search.observation.status == "BLOCKED" and search.links is None
    product_request = SupplierCatalogRequest(
        page=page_request,
        page_run_id=good_page.run_id,
        search_run_id=search.run_id,
        product_index=1,
    )
    calls.clear()
    monkeypatch.setattr(catalog_module, "observe_supplier_page", lambda *a, **k: calls.append(1))
    with pytest.raises(ValueError, match="SUPPLIER_CATALOG_SEARCH_EVIDENCE_CONFLICT"):
        prepare_supplier_catalog(storage, company, product_request, actor_id="synthetic")
    assert calls == []


def test_shared_page_catalog_hourly_budget_and_unknown_parent_are_source_zero(storage, monkeypatch):
    company = "catalog-budget-" + uuid4().hex
    _, page_request, page_report = chain(storage, company, monkeypatch)
    monkeypatch.setattr(catalog_module, "HOURLY_NEW_RUNS", 3)
    monkeypatch.setattr(catalog_module, "REFRESH_COOLDOWN", timedelta(0))
    calls = []

    def observe(url, *, allowed_host=None):
        calls.append(url)
        return completed(url, PRODUCT_HTML if "/товар/" in url else SEARCH_HTML)

    monkeypatch.setattr(catalog_module, "observe_supplier_page", observe)
    search_request = SupplierCatalogRequest(page=page_request, page_run_id=page_report.run_id)
    search = prepare_supplier_catalog(storage, company, search_request, actor_id="synthetic").report
    product_request = SupplierCatalogRequest(
        page=page_request,
        page_run_id=page_report.run_id,
        search_run_id=search.run_id,
        product_index=1,
    )
    prepare_supplier_catalog(storage, company, product_request, actor_id="synthetic")
    with pytest.raises(ValueError, match="SUPPLIER_CATALOG_HOURLY_LIMIT"):
        prepare_supplier_catalog(
            storage, company, product_request, actor_id="synthetic", refresh=True
        )
    unknown = product_request.model_copy(update={"search_run_id": str(uuid4())})
    with pytest.raises(LookupError, match="SUPPLIER_CATALOG_SEARCH_NOT_FOUND"):
        prepare_supplier_catalog(storage, company, unknown, actor_id="synthetic")
    with pytest.raises(LookupError, match="SUPPLIER_CATALOG_SEARCH_NOT_FOUND"):
        read_supplier_catalog(storage, company, unknown)
    assert len(calls) == 2


def test_catalog_current_and_hold_gates_before_dispatch(storage, monkeypatch, tmp_path):
    company = "catalog-gate-" + uuid4().hex
    position, page_request, page_report = chain(storage, company, monkeypatch)
    request = SupplierCatalogRequest(page=page_request, page_run_id=page_report.run_id)
    calls = []
    monkeypatch.setattr(catalog_module, "observe_supplier_page", lambda *a, **k: calls.append(1))
    hold(storage, company, tmp_path, position.selection.notice)
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        prepare_supplier_catalog(storage, company, request, actor_id="synthetic")
    assert calls == []


def test_catalog_stale_current_version_blocks_before_dispatch(storage, monkeypatch):
    company = "catalog-stale-" + uuid4().hex
    _, page_request, page_report = chain(storage, company, monkeypatch)
    request = SupplierCatalogRequest(page=page_request, page_run_id=page_report.run_id)
    ingest(storage, company, version=2)
    calls = []
    monkeypatch.setattr(
        catalog_module, "observe_supplier_page", lambda *args, **kwargs: calls.append(1)
    )
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        prepare_supplier_catalog(storage, company, request, actor_id="synthetic")
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        read_supplier_catalog(storage, company, request)
    assert calls == []
