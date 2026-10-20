"""Supplier observations cannot bypass exact EIS source, tenant or source-I/O bounds."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from itertools import count
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from test_eis_analogs_pg import archive
from test_eis_characteristic_pair_pg import storage as storage_fixture
from test_eis_notice_hold_pg import hold

from procurement.sources.eis_characteristic_compare import PositionSelection
from procurement.sources.eis_feed_sync import EisDateSelection
from procurement.sources.eis_supplier_catalog import (
    SupplierCatalogCapture,
    SupplierCatalogSourceError,
    build_servermall_supplier_observation,
)
from procurement.sources.servermall import (
    SERVERMALL_HPE_GEN12_URL,
    ServerMallObservation,
    parse_servermall_hpe_gen12,
)
from procurement.storage import eis_supplier_search as module
from procurement.storage.eis_document_store import NoticeDocumentRef
from procurement.storage.eis_notice_index import (
    EisReadyWindow,
    ingest_ready_window,
    preflight_ready_window,
)
from procurement.storage.eis_supplier_search import (
    SupplierSearchRequest,
    prepare_supplier_search,
    read_supplier_search,
)
from procurement.storage.models import audit_events, eis_document_jobs, eis_supplier_search_runs

COUNTER = count()
storage = storage_fixture
NUMBER = "1" * 19
PRODUCT = "https://servermall.ru/catalog/servers/dl360/"


def ingest(storage, company, *, version=1, name="Сервер HPE DL360 Gen12"):
    with ZipFile(BytesIO(archive(NUMBER, version=version))) as zipped:
        xml = zipped.read("notice.xml").replace("Бумага A4".encode(), name.encode())
    out = BytesIO()
    with ZipFile(out, "w") as zipped:
        zipped.writestr("notice.xml", xml)
    selection = EisDateSelection("50", date(2026, 2, 1) + timedelta(days=next(COUNTER)), 3)
    window = EisReadyWindow(selection.window_key, "a" * 64, 1, (out.getvalue(),))
    notice = preflight_ready_window(window).inspections[0].records[0]
    ingest_ready_window(storage, company, window, actor_id="synthetic")
    return SupplierSearchRequest(
        selection=PositionSelection(
            notice=NoticeDocumentRef(
                purchase_number=NUMBER, version_number=version, notice_xml_sha256=notice.xml_sha256
            ),
            source_index=1,
        )
    )


def capture(query):
    graph = {
        "@graph": [
            {
                "@type": "OfferCatalog",
                "itemListElement": [
                    {"@type": "Offer", "name": "Сервер HPE DL360 Gen12", "url": PRODUCT}
                ],
            }
        ]
    }
    content = (
        '<script type="application/ld+json">'
        + json.dumps(graph)
        + '</script><article class="product-card"><a href="'
        + PRODUCT
        + '">Сервер HPE DL360 Gen12</a><p class="list-price-title">Цена базы:</p>'
        + '<div class="product-card__price-VAT">от 100 000 ₽</div></article>'
    ).encode()
    now = datetime.now(UTC)
    source = ServerMallObservation(
        source_url=SERVERMALL_HPE_GEN12_URL,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        observed_at=now,
        leads=parse_servermall_hpe_gen12(content, query=query, observed_at=now),
    )
    return SupplierCatalogCapture(build_servermall_supplier_observation(source, query), content)


def counts(storage, company):
    with storage.transaction(company, consistent_read=True) as conn:
        return tuple(
            conn.scalar(select(func.count()).select_from(table))
            for table in (eis_supplier_search_runs, audit_events, eis_document_jobs)
        )


def test_capture_then_source0_replay_no_blob_hydration(storage, monkeypatch):
    company = "supplier-" + uuid4().hex
    req = ingest(storage, company)
    calls = []
    monkeypatch.setattr(
        module,
        "observe_servermall_hpe_gen12",
        lambda query: (calls.append(query), capture(query))[1],
    )
    before = counts(storage, company)
    result = prepare_supplier_search(storage, company, req, actor_id="synthetic")
    assert calls == ["dl360"] and result.created and result.source_requests == 1
    assert result.report.observation.leads[0].published_prices[0].kind == "BASE_PRICE_FROM"
    assert result.report.quote == result.report.profit == result.report.participation == "UNKNOWN"
    assert counts(storage, company) == (before[0] + 2, before[1] + 2, before[2])
    statements = []

    def trace(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", trace)
    try:
        replay = prepare_supplier_search(storage, company, req, actor_id="synthetic")
        read = read_supplier_search(storage, company, req)
    finally:
        event.remove(storage._engine, "before_cursor_execute", trace)
    assert replay.report == read.report == result.report
    assert not replay.created and replay.source_requests == read.source_requests == 0
    assert calls == ["dl360"] and counts(storage, company) == (
        before[0] + 2,
        before[1] + 2,
        before[2],
    )
    assert not any(
        sql.startswith("SELECT eis_supplier_search_runs.source_content") for sql in statements
    )
    with storage.transaction(company, consistent_read=True) as conn:
        assert (
            conn.scalar(
                select(eis_supplier_search_runs.c.source_byte_count).where(
                    eis_supplier_search_runs.c.run_id == result.report.run_id
                )
            )
            > 0
        )
    with storage.transaction("foreign-" + company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_supplier_search_runs)) == 0
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(eis_supplier_search_runs.delete())


@pytest.mark.parametrize("kind", ["tenant", "sha", "stale", "position", "hold"])
def test_source_guard_before_http_and_read(storage, monkeypatch, tmp_path, kind):
    company = "supplier-" + uuid4().hex
    req = ingest(storage, company)
    if kind == "tenant":
        company = "foreign-" + company
    elif kind == "sha":
        req = req.model_copy(
            update={
                "selection": req.selection.model_copy(
                    update={
                        "notice": req.selection.notice.model_copy(
                            update={"notice_xml_sha256": "f" * 64}
                        )
                    }
                )
            }
        )
    elif kind == "stale":
        ingest(storage, company, version=2)
    elif kind == "position":
        req = req.model_copy(
            update={"selection": req.selection.model_copy(update={"source_index": 2})}
        )
    else:
        hold(storage, company, tmp_path, req.selection.notice)
    calls = []
    monkeypatch.setattr(module, "observe_servermall_hpe_gen12", lambda q: calls.append(q))
    before = counts(storage, company)
    with pytest.raises(ValueError):
        prepare_supplier_search(storage, company, req, actor_id="synthetic")
    with pytest.raises(ValueError):
        read_supplier_search(storage, company, req)
    assert not calls and counts(storage, company) == before


@pytest.mark.parametrize(
    "name",
    [
        "Бумага A4",
        "Сервер Dell",
        "",
        "Сервер " + "x" * 401,
        "Выполнение работ по ремонту серверной помещения",
        "Услуги аренды сервера HPE DL360",
    ],
)
def test_unsupported_name_is_source0_not_supplier_absence(storage, monkeypatch, name):
    company = "supplier-" + uuid4().hex
    # Empty source name has a separate parser fallback, tested by typed query unit tests.
    if not name:
        name = "Поставка"
    req = ingest(storage, company, name=name)
    monkeypatch.setattr(
        module, "observe_servermall_hpe_gen12", lambda q: pytest.fail("unsupported source I/O")
    )
    result = prepare_supplier_search(storage, company, req, actor_id="synthetic")
    assert result.report.status == "QUERY_NOT_COVERED" and result.source_requests == 0
    assert result.report.observation is None and result.report.technical == "UNKNOWN"
    assert read_supplier_search(storage, company, req).report == result.report


def test_source_changed_during_http_prevents_final_append(storage, monkeypatch):
    company = "supplier-" + uuid4().hex
    req = ingest(storage, company)

    def changed(query):
        ingest(storage, company, version=2)
        return capture(query)

    monkeypatch.setattr(module, "observe_servermall_hpe_gen12", changed)
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        prepare_supplier_search(storage, company, req, actor_id="synthetic")
    with storage.transaction(company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_supplier_search_runs)) == 1
        assert conn.scalar(select(eis_supplier_search_runs.c.report))["status"] == "STARTED"


def test_failed_and_interrupted_refresh_never_reuse_old_success(storage, monkeypatch):
    company = "supplier-" + uuid4().hex
    req = ingest(storage, company)
    monkeypatch.setattr(module, "observe_servermall_hpe_gen12", capture)
    first = prepare_supplier_search(storage, company, req, actor_id="synthetic")
    with pytest.raises(ValueError, match="REFRESH_COOLDOWN"):
        prepare_supplier_search(storage, company, req, actor_id="synthetic", refresh=True)
    monkeypatch.setattr(module, "REFRESH_COOLDOWN", timedelta(0))

    def failed(query):
        raise SupplierCatalogSourceError("synthetic failure")

    monkeypatch.setattr(module, "observe_servermall_hpe_gen12", failed)
    result = prepare_supplier_search(storage, company, req, actor_id="synthetic", refresh=True)
    assert result.report.status == "SOURCE_ERROR" and result.report.run_id != first.report.run_id
    assert read_supplier_search(storage, company, req).report == result.report

    def interrupted(query):
        raise SystemExit("synthetic process interruption")

    monkeypatch.setattr(module, "observe_servermall_hpe_gen12", interrupted)
    with pytest.raises(SystemExit):
        prepare_supplier_search(storage, company, req, actor_id="synthetic", refresh=True)
    read = read_supplier_search(storage, company, req)
    assert read.report.status == "STARTED" and read.report.attempted_source_requests is None
    assert read.report.observation is None and read.source_requests == 0
    # The session lease was released even though no final source outcome was saved.
    monkeypatch.setattr(module, "observe_servermall_hpe_gen12", capture)
    assert prepare_supplier_search(
        storage, company, req, actor_id="synthetic", refresh=True
    ).created


def test_per_search_lease_prevents_second_http(storage, monkeypatch):
    company = "supplier-" + uuid4().hex
    req = ingest(storage, company)
    with storage.transaction(company, consistent_read=True) as conn:
        saved = module._position(conn, company, req)
        _, key = module._basis(saved)
    lock_key = "supplier-search/" + company + "/" + key
    monkeypatch.setattr(
        module, "observe_servermall_hpe_gen12", lambda q: pytest.fail("duplicate HTTP")
    )
    with storage._engine.connect() as lease:
        lease.execute(text("SELECT pg_advisory_lock(hashtextextended(:key,0))"), {"key": lock_key})
        lease.commit()
        try:
            with pytest.raises(ValueError, match="SUPPLIER_SEARCH_BUSY"):
                prepare_supplier_search(storage, company, req, actor_id="synthetic")
        finally:
            lease.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), {"key": lock_key}
            )
            lease.commit()


def test_corrupt_latest_report_has_no_fallback_and_blob_digest_is_enforced(storage, monkeypatch):
    company = "supplier-" + uuid4().hex
    req = ingest(storage, company)
    monkeypatch.setattr(module, "observe_servermall_hpe_gen12", capture)
    first = prepare_supplier_search(storage, company, req, actor_id="synthetic")
    with storage.transaction(company, consistent_read=True) as conn:
        row = dict(
            conn.execute(
                select(eis_supplier_search_runs).where(
                    eis_supplier_search_runs.c.run_id == first.report.run_id
                )
            )
            .mappings()
            .one()
        )
    row["run_id"] = str(uuid4())
    row["created_at"] = datetime.now(UTC) + timedelta(seconds=1)
    row["report"] = {
        **row["report"],
        "run_id": row["run_id"],
        "created_at": row["created_at"].isoformat(),
    }
    for field in ("source_sha256", "source_byte_count"):
        with pytest.raises(DBAPIError), storage.transaction(company) as conn:
            conn.execute(eis_supplier_search_runs.insert().values(**{**row, field: None}))
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(
            eis_supplier_search_runs.insert().values(**{**row, "source_content": b"not original"})
        )
    row["report_sha256"] = "f" * 64
    with storage.transaction(company) as conn:
        conn.execute(eis_supplier_search_runs.insert().values(**row))
    with pytest.raises(ValueError, match="SUPPLIER_SEARCH_DIGEST_CONFLICT"):
        read_supplier_search(storage, company, req)
    with pytest.raises(ValueError, match="SUPPLIER_SEARCH_DIGEST_CONFLICT"):
        prepare_supplier_search(storage, company, req, actor_id="synthetic")
