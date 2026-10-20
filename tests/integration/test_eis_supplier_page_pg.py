"""Supplier page runs bind an exact current position, parent link and source body."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import DBAPIError
from test_eis_notice_hold_pg import hold
from test_eis_supplier_search_pg import ingest
from test_eis_supplier_search_pg import storage as storage_fixture
from test_eis_supplier_serp_pg import capture as serp_capture

from procurement.sources.supplier_page import PageCapture, PageHop, PageObservation
from procurement.sources.supplier_serp import SearchEngine
from procurement.storage import eis_supplier_page as module
from procurement.storage import eis_supplier_serp as serp_module
from procurement.storage.eis_supplier_page import (
    SupplierPageRequest,
    prepare_supplier_page,
    read_supplier_page,
)
from procurement.storage.eis_supplier_serp import prepare_supplier_serp
from procurement.storage.models import eis_supplier_page_runs

storage = storage_fixture


class _BudgetConnection:
    def __init__(self, used: int) -> None:
        self.values = iter((0, 0, used, 0))

    def scalar(self, statement):
        return next(self.values)


def test_body_reservation_boundary_is_fail_closed_before_source():
    now = datetime.now(UTC)
    module._budget(
        _BudgetConnection(module.DAILY_BODY_BYTES - module.MAX_BODY_BYTES),
        "tenant",
        now,
    )
    with pytest.raises(ValueError, match="SUPPLIER_PAGE_DAILY_BODY_LIMIT"):
        module._budget(
            _BudgetConnection(module.DAILY_BODY_BYTES - module.MAX_BODY_BYTES + 1),
            "tenant",
            now,
        )


def page_capture(url):
    content = b"<html><body><h1>Public declaration</h1></body></html>"
    digest = hashlib.sha256(content).hexdigest()
    now = datetime.now(UTC)
    observation = PageObservation(
        source_url=url,
        final_url=url,
        observed_at=now,
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
    return PageCapture(observation, content)


def parent(storage, company, monkeypatch):
    position = ingest(storage, company)

    def observe(query, *, cooldowns=(), company_id: str):
        assert company_id == company
        return serp_capture(query)

    monkeypatch.setattr(serp_module, "observe_supplier_serp", observe)
    report = prepare_supplier_serp(storage, company, position, actor_id="synthetic").report
    return SupplierPageRequest(
        position=position, serp_run_id=report.run_id, engine=SearchEngine.BING, rank=1
    )


def test_exact_parent_capture_replay_body_binding_rls_and_immutability(storage, monkeypatch):
    company = "page-" + uuid4().hex
    request = parent(storage, company, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module, "observe_supplier_page", lambda url: (calls.append(url), page_capture(url))[1]
    )
    result = prepare_supplier_page(storage, company, request, actor_id="synthetic")
    assert result.created and result.source_requests == 1 and calls == [result.report.link.url]
    statements = []

    def trace(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", trace)
    try:
        replay = read_supplier_page(storage, company, request)
    finally:
        event.remove(storage._engine, "before_cursor_execute", trace)
    assert replay.report == result.report and not replay.created and replay.source_requests == 0
    assert not any("eis_supplier_page_runs.source_body AS" in sql for sql in statements)
    with storage.transaction(company, consistent_read=True) as conn:
        body = conn.scalar(
            select(eis_supplier_page_runs.c.source_body).where(
                eis_supplier_page_runs.c.run_id == result.report.run_id
            )
        )
    assert hashlib.sha256(body).hexdigest() == result.report.source_body_sha256
    with storage.transaction("foreign-" + company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_supplier_page_runs)) == 0
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(eis_supplier_page_runs.delete())


def test_observer_failure_preserves_started_and_wrong_parent_is_source0(storage, monkeypatch):
    company = "page-fail-" + uuid4().hex
    request = parent(storage, company, monkeypatch)
    monkeypatch.setattr(
        module,
        "observe_supplier_page",
        lambda url: (_ for _ in ()).throw(RuntimeError("network detail")),
    )
    with pytest.raises(RuntimeError):
        prepare_supplier_page(storage, company, request, actor_id="synthetic")
    assert read_supplier_page(storage, company, request).report.status == "STARTED"
    foreign = request.model_copy(update={"serp_run_id": str(uuid4())})
    with pytest.raises(LookupError, match="SUPPLIER_PAGE_PARENT_NOT_FOUND"):
        read_supplier_page(storage, company, foreign)


def test_new_notice_version_makes_old_page_scope_stale_before_dispatch(storage, monkeypatch):
    company = "page-stale-" + uuid4().hex
    request = parent(storage, company, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module,
        "observe_supplier_page",
        lambda url: (calls.append(url), page_capture(url))[1],
    )
    prepare_supplier_page(storage, company, request, actor_id="synthetic")
    assert len(calls) == 1
    ingest(storage, company, version=2)
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        read_supplier_page(storage, company, request)
    with pytest.raises(ValueError, match="NOTICE_VERSION_STALE"):
        prepare_supplier_page(storage, company, request, actor_id="synthetic", refresh=True)
    assert len(calls) == 1


def test_notice_hold_blocks_page_before_dispatch(storage, monkeypatch, tmp_path):
    company = "page-hold-" + uuid4().hex
    request = parent(storage, company, monkeypatch)
    hold(storage, company, tmp_path, request.position.selection.notice)
    calls = []
    monkeypatch.setattr(module, "observe_supplier_page", lambda url: calls.append(url))
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        prepare_supplier_page(storage, company, request, actor_id="synthetic")
    with pytest.raises(ValueError, match="NOTICE_VARIANT_REVIEW_REQUIRED"):
        read_supplier_page(storage, company, request)
    assert calls == []


def test_refresh_cooldown_and_failed_refresh_latest_started_replay(storage, monkeypatch):
    company = "page-refresh-" + uuid4().hex
    request = parent(storage, company, monkeypatch)
    calls = []
    monkeypatch.setattr(
        module,
        "observe_supplier_page",
        lambda url: (calls.append(url), page_capture(url))[1],
    )
    first = prepare_supplier_page(storage, company, request, actor_id="synthetic")
    with pytest.raises(ValueError, match="SUPPLIER_PAGE_REFRESH_COOLDOWN"):
        prepare_supplier_page(storage, company, request, actor_id="synthetic", refresh=True)
    assert len(calls) == 1

    monkeypatch.setattr(module, "REFRESH_COOLDOWN", timedelta(0))
    monkeypatch.setattr(
        module,
        "observe_supplier_page",
        lambda url: (_ for _ in ()).throw(RuntimeError("post-dispatch failure")),
    )
    with pytest.raises(RuntimeError, match="post-dispatch failure"):
        prepare_supplier_page(storage, company, request, actor_id="synthetic", refresh=True)
    replay = read_supplier_page(storage, company, request)
    assert replay.report.status == "STARTED"
    assert replay.report.run_id != first.report.run_id
    assert replay.report.attempted_source_requests is None
