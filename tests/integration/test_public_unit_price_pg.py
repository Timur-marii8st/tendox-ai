"""Actual PostgreSQL ancestry/current/RLS guards for automatic public price reads."""

from uuid import uuid4

import pytest
from sqlalchemy import event
from test_eis_notice_hold_pg import hold
from test_eis_supplier_product_pg import ancestry
from test_eis_supplier_search_pg import ingest
from test_eis_supplier_search_pg import storage as storage_fixture

from procurement.storage import public_unit_price as module
from procurement.storage.public_unit_price import read_public_unit_price

storage = storage_fixture


def test_exact_saved_source_read_is_readonly_and_source_zero(storage, monkeypatch):
    company = "public-price-" + uuid4().hex
    _, request, _ = ancestry(storage, company, monkeypatch)
    statements = []

    def trace(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lstrip().upper())

    event.listen(storage._engine, "before_cursor_execute", trace)
    try:
        report = read_public_unit_price(storage, company, request)
    finally:
        event.remove(storage._engine, "before_cursor_execute", trace)
    assert report.company_id == company and report.request == request
    assert report.source_requests == 0
    assert report.status == report.profit == report.quote == "UNKNOWN"
    assert report.quantity_cost_rub is None
    assert "EXPLICIT_PRICE_BASIS_UNAVAILABLE" in report.missing
    assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)


def test_foreign_tenant_and_unknown_parent_block_before_parser(storage, monkeypatch):
    company = "public-price-tenant-" + uuid4().hex
    _, request, _ = ancestry(storage, company, monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("foreign or unknown source reached the parser")

    monkeypatch.setattr(module, "extract_public_unit_price", forbidden)
    with pytest.raises(ValueError, match="CHARACTERISTIC_NOTICE_NOT_FOUND_OR_MISMATCH"):
        read_public_unit_price(storage, "foreign-" + company, request)
    unknown = request.model_copy(update={"product_run_id": str(uuid4())})
    with pytest.raises(LookupError, match="SUPPLIER_PRODUCT_PARENT_NOT_FOUND"):
        read_public_unit_price(storage, company, unknown)


def test_notice_hold_blocks_before_price_parser(storage, monkeypatch, tmp_path):
    company = "public-price-hold-" + uuid4().hex
    position, request, _ = ancestry(storage, company, monkeypatch)
    hold(storage, company, tmp_path, position.selection.notice)
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        read_public_unit_price(storage, company, request)


def test_new_version_blocks_before_price_parser(storage, monkeypatch):
    company = "public-price-stale-" + uuid4().hex
    _, request, _ = ancestry(storage, company, monkeypatch)
    ingest(storage, company, version=2)
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        read_public_unit_price(storage, company, request)


def test_explicit_saved_price_computes_quantity_cost_in_postgres(storage, monkeypatch):
    import json
    from datetime import UTC, datetime
    from decimal import Decimal
    from io import BytesIO
    from zipfile import ZipFile

    import test_eis_supplier_product_pg as product_fixture
    import test_eis_supplier_search_pg as notice_fixture

    from procurement.sources.supplier_page import PageCapture, parse_supplier_page

    original_archive = notice_fixture.archive
    original_html = product_fixture.product_html

    def piece_archive(*args, **kwargs):
        output = BytesIO()
        with (
            ZipFile(BytesIO(original_archive(*args, **kwargs))) as source,
            ZipFile(output, "w") as target,
        ):
            for name in source.namelist():
                target.writestr(
                    name,
                    source.read(name).replace(
                        "<name>пачка</name>".encode(), "<name>шт</name>".encode()
                    ),
                )
        return output.getvalue()

    price = {
        "@type": "Product",
        "name": "Бумага SvetoCopy",
        "offers": {
            "@type": "Offer",
            "price": "120.00",
            "priceCurrency": "RUB",
            "priceSpecification": {
                "@type": "UnitPriceSpecification",
                "price": "120.00",
                "priceCurrency": "RUB",
                "valueAddedTaxIncluded": False,
                "referenceQuantity": {
                    "@type": "QuantitativeValue",
                    "value": "10",
                    "unitText": "шт",
                },
            },
        },
    }
    content = (
        original_html()
        + ('<script type="application/ld+json">' + json.dumps(price) + "</script>").encode()
    )
    monkeypatch.setattr(notice_fixture, "archive", piece_archive)
    monkeypatch.setattr(product_fixture, "product_html", lambda: content)
    monkeypatch.setattr(
        product_fixture,
        "completed",
        lambda url, body: PageCapture(
            parse_supplier_page(url, body, observed_at=datetime.now(UTC)), body
        ),
    )
    company = "public-price-numeric-" + uuid4().hex
    _, request, _ = ancestry(storage, company, monkeypatch)
    report = read_public_unit_price(storage, company, request)
    assert report.status == "CALCULATED", report.missing
    assert report.required_quantity.value == Decimal("100")
    assert report.quantity_cost_rub == Decimal("1200.00")
    assert report.price.quantity_per_price.value == Decimal("10")
    assert report.price.price.provenance.document_id == report.source_sha256
    assert report.profit == report.technical == report.quote == "UNKNOWN"
    assert report.source_requests == 0
