"""Requirement preview reads an exact saved product and prepared DOCX without writes."""

from __future__ import annotations

import hashlib
from datetime import date
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from docx import Document
from sqlalchemy import event
from test_eis_analogs_pg import archive
from test_eis_notice_hold_pg import hold
from test_eis_supplier_catalog_pg import SEARCH_HTML, chain, completed
from test_eis_supplier_product_pg import product_html
from test_eis_supplier_search_pg import NUMBER
from test_eis_supplier_search_pg import ingest as ingest_new_version
from test_eis_supplier_search_pg import storage as storage_fixture

from procurement.sources.eis_characteristic_compare import PositionSelection
from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.sources.eis_requirement_preview import RequirementPreviewRequest
from procurement.storage import eis_supplier_catalog as catalog_module
from procurement.storage.eis_document_review import ReviewDocumentRequest, prepare_review_document
from procurement.storage.eis_document_store import (
    NoticeDocumentRef,
    plan_document_job,
    record_document_outcome,
)
from procurement.storage.eis_notice_index import (
    EisReadyWindow,
    ingest_ready_window,
    preflight_ready_window,
)
from procurement.storage.eis_requirement_preview import read_requirement_preview
from procurement.storage.eis_supplier_catalog import (
    SupplierCatalogRequest,
    prepare_supplier_catalog,
)
from procurement.storage.eis_supplier_product import (
    SupplierProductRequest,
    prepare_supplier_product,
)
from procurement.storage.eis_supplier_search import SupplierSearchRequest

storage = storage_fixture
UID = "A" * 32


def docx_table() -> bytes:
    document = Document()
    table = document.add_table(rows=2, cols=5)
    headers = (
        "Наименование характеристики",
        "Тип характеристики (количественная/качественная)",
        "Значение характеристики",
        "Единица измерения характеристики",
        "Инструкция по заполнению характеристик",
    )
    for index, value in enumerate(headers):
        table.rows[0].cells[index].text = value
    table.rows[1].cells[0].text = "Плотность"
    table.rows[1].cells[2].text = ">= 80"
    table.rows[1].cells[3].text = "г/м²"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def ingest_with_attachment(storage, company, content, *, name="Бумага A4"):
    raw = archive(NUMBER)
    with ZipFile(BytesIO(raw)) as zipped:
        xml = zipped.read("notice.xml").replace("Бумага A4".encode(), name.encode())
    attachment = f"""<attachmentsInfo><attachmentInfo>
<publishedContentId>{UID}</publishedContentId><fileName>requirements.docx</fileName>
<fileSize>{len(content)}</fileSize>
<url>https://zakupki.gov.ru/44fz/filestore/public/1.0/download/priz/file.html?uid={UID}</url>
<docKindInfo><code>POD</code></docKindInfo></attachmentInfo></attachmentsInfo>""".encode()
    xml = xml.replace(b"</commonInfo>", b"</commonInfo>" + attachment)
    output = BytesIO()
    with ZipFile(output, "w") as zipped:
        zipped.writestr("notice.xml", xml)
    selection = EisDateSelection("50", date(2026, 5, 1), 3)
    window = EisReadyWindow(selection.window_key, "a" * 64, 1, (output.getvalue(),))
    notice = preflight_ready_window(window).inspections[0].records[0]
    ingest_ready_window(storage, company, window, actor_id="synthetic")
    return SupplierSearchRequest(
        selection=PositionSelection(
            notice=NoticeDocumentRef(
                purchase_number=NUMBER,
                version_number=1,
                notice_xml_sha256=notice.xml_sha256,
            ),
            source_index=1,
        )
    )


def setup(storage, company, monkeypatch, *, prepare_analysis=True):
    content = docx_table()
    import test_eis_supplier_catalog_pg as catalog_pg

    monkeypatch.setattr(
        catalog_pg,
        "ingest",
        lambda storage, company, name="Бумага A4": ingest_with_attachment(
            storage, company, content, name=name
        ),
    )
    position, page_request, page_report = chain(storage, company, monkeypatch)
    monkeypatch.setattr(
        catalog_module,
        "observe_supplier_page",
        lambda url, *, allowed_host=None: completed(
            url, product_html() if "/товар/" in url else SEARCH_HTML
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
    catalog = prepare_supplier_catalog(
        storage, company, catalog_request, actor_id="synthetic"
    ).report
    product_request = SupplierProductRequest(catalog=catalog_request, product_run_id=catalog.run_id)
    prepare_supplier_product(storage, company, product_request, actor_id="synthetic")
    plan_document_job(storage, company, position.selection.notice, actor_id="synthetic")
    record_document_outcome(
        storage,
        company,
        position.selection.notice,
        UID,
        actor_id="synthetic",
        content=content,
    )
    document_request = ReviewDocumentRequest(
        notice=position.selection.notice,
        content_uid=UID,
        expected_document_sha256=hashlib.sha256(content).hexdigest(),
    )
    if prepare_analysis:
        prepare_review_document(storage, company, document_request, actor_id="synthetic")
    return RequirementPreviewRequest(
        product=product_request, document=document_request, table_index=1
    )


def test_repeatable_source_zero_preview_does_not_hydrate_bytes_or_write(storage, monkeypatch):
    company = "requirement-preview-" + uuid4().hex
    request = setup(storage, company, monkeypatch)
    statements = []

    def trace(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", trace)
    try:
        first = read_requirement_preview(storage, company, request)
        second = read_requirement_preview(storage, company, request)
    finally:
        event.remove(storage._engine, "before_cursor_execute", trace)
    assert first == second and first.preview_sha256 == second.preview_sha256
    assert first.source_requests == first.jobs_created == first.database_writes == 0
    assert first.table.rows[0].mandatory_status == first.technical == "UNKNOWN"
    assert not any(
        "source_body AS" in sql or "eis_document_blobs.content" in sql for sql in statements
    )
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )


def test_foreign_tenant_and_unknown_table_fail_without_fallback(storage, monkeypatch):
    company = "requirement-preview-negative-" + uuid4().hex
    request = setup(storage, company, monkeypatch)
    with pytest.raises(ValueError, match=r"^CHARACTERISTIC_NOTICE_NOT_FOUND_OR_MISMATCH$"):
        read_requirement_preview(storage, "foreign-" + company, request)
    with pytest.raises(ValueError, match="TABLE_NOT_RETAINED"):
        read_requirement_preview(storage, company, request.model_copy(update={"table_index": 2}))


@pytest.mark.parametrize("gate", ["hold", "stale", "unprepared"])
def test_current_hold_and_prepared_analysis_gates(storage, monkeypatch, tmp_path, gate):
    company = "requirement-preview-gate-" + gate + "-" + uuid4().hex
    request = setup(storage, company, monkeypatch, prepare_analysis=gate != "unprepared")
    if gate == "hold":
        hold(storage, company, tmp_path, request.document.notice)
        expected = ValueError
    elif gate == "stale":
        ingest_new_version(storage, company, version=2)
        expected = ValueError
    else:
        expected = LookupError
    with pytest.raises(expected):
        read_requirement_preview(storage, company, request)
