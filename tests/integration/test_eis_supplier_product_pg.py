"""Persisted supplier details remain exact, tenant scoped and source zero."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import DBAPIError
from test_eis_notice_hold_pg import hold
from test_eis_supplier_catalog_pg import SEARCH_HTML, chain, completed
from test_eis_supplier_search_pg import ingest
from test_eis_supplier_search_pg import storage as storage_fixture

from procurement.storage import eis_supplier_catalog as catalog_module
from procurement.storage.eis_supplier_catalog import (
    SupplierCatalogRequest,
    prepare_supplier_catalog,
)
from procurement.storage.eis_supplier_product import (
    SupplierProductRequest,
    prepare_supplier_product,
    read_supplier_product,
)
from procurement.storage.models import eis_supplier_product_reports

storage = storage_fixture


def product_html() -> bytes:
    def row(label: str, value: str) -> str:
        return (
            '<div class="product-description-item"><div class="title">'
            + label
            + '</div><div class="value productProperties"><a>'
            + value
            + "</a></div></div>"
        )

    return (
        '<div class="product-card-content-item"><h1>Бумага SvetoCopy</h1>'
        '<span itemscope itemtype="http://schema.org/Product">'
        '<meta itemprop="name" content="Бумага SvetoCopy"></span>'
        + row("формат", "А4")
        + row("плотность бумаги", "80 +/- 3г/кв.м")
        + row("количество листов", "500 листов")
        + row("класс бумаги", "С")
        + '<div class="cart-product-form product-btn" data-package="5"></div></div>'
    ).encode()


def ancestry(storage, company, monkeypatch):
    position, page_request, page_report = chain(storage, company, monkeypatch)
    content = product_html()
    monkeypatch.setattr(
        catalog_module,
        "observe_supplier_page",
        lambda url, *, allowed_host=None: completed(
            url, content if "/товар/" in url else SEARCH_HTML
        ),
    )
    search_request = SupplierCatalogRequest(page=page_request, page_run_id=page_report.run_id)
    search = prepare_supplier_catalog(storage, company, search_request, actor_id="synthetic").report
    catalog_request = SupplierCatalogRequest(
        page=page_request,
        page_run_id=page_report.run_id,
        search_run_id=search.run_id,
        product_index=1,
    )
    product = prepare_supplier_catalog(
        storage, company, catalog_request, actor_id="synthetic"
    ).report
    return (
        position,
        SupplierProductRequest(catalog=catalog_request, product_run_id=product.run_id),
        content,
    )


def test_prepare_replay_no_body_hydration_tenant_and_immutability(storage, monkeypatch):
    company = "supplier-product-" + uuid4().hex
    _, request, content = ancestry(storage, company, monkeypatch)
    result = prepare_supplier_product(storage, company, request, actor_id="synthetic")
    assert result.created and result.source_requests == 0
    assert result.report.details.html_sha256 == hashlib.sha256(content).hexdigest()
    assert result.report.technical == result.report.unit_cost == "UNKNOWN"
    statements = []

    def trace(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", trace)
    try:
        replay = read_supplier_product(storage, company, request)
    finally:
        event.remove(storage._engine, "before_cursor_execute", trace)
    assert replay.report == result.report and not replay.created
    assert not any("eis_supplier_catalog_runs.source_body AS" in sql for sql in statements)
    with storage.transaction("foreign-" + company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_supplier_product_reports)) == 0
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(eis_supplier_product_reports.delete())


def test_current_and_hold_gates_block_before_parser(storage, monkeypatch, tmp_path):
    company = "supplier-product-gates-" + uuid4().hex
    position, request, _ = ancestry(storage, company, monkeypatch)
    hold(storage, company, tmp_path, position.selection.notice)
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        prepare_supplier_product(storage, company, request, actor_id="synthetic")
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        read_supplier_product(storage, company, request)


def test_new_notice_version_and_unknown_parent_are_source_zero(storage, monkeypatch):
    company = "supplier-product-stale-" + uuid4().hex
    _, request, _ = ancestry(storage, company, monkeypatch)
    unknown = request.model_copy(update={"product_run_id": str(uuid4())})
    with pytest.raises(LookupError, match="SUPPLIER_PRODUCT_PARENT_NOT_FOUND"):
        prepare_supplier_product(storage, company, unknown, actor_id="synthetic")
    ingest(storage, company, version=2)
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        prepare_supplier_product(storage, company, request, actor_id="synthetic")
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        read_supplier_product(storage, company, request)
