"""SERP runs preserve exact source bundles and source0 replay."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import event, func, insert, select
from sqlalchemy.exc import DBAPIError
from test_eis_supplier_search_pg import ingest
from test_eis_supplier_search_pg import storage as storage_fixture

from procurement.sources.supplier_serp import (
    ENGINES,
    HISTORICAL_EXPANDED_ENGINES,
    EngineAttempt,
    SearchBatch,
    SerpCapture,
    SerpLink,
    source_url,
)
from procurement.storage import eis_supplier_serp as module
from procurement.storage.eis_supplier_serp import prepare_supplier_serp, read_supplier_serp
from procurement.storage.models import eis_supplier_serp_runs

storage = storage_fixture


class _EmptyRows:
    def all(self):
        return []


class _BudgetConnection:
    def __init__(self, used: int) -> None:
        self.values = iter((0, used))
        self.statement = None

    def scalar(self, statement):
        return next(self.values)

    def execute(self, statement):
        self.statement = statement
        return _EmptyRows()


def test_daily_reservation_boundary_and_terminal_cooldown_filter_precedes_limit():
    now = datetime.now(UTC)
    allowed = _BudgetConnection(module.DAILY_BUNDLE_BYTES - module.ACTIVE_MAX_BUNDLE_BYTES)
    assert module._budgets_and_cooldowns(allowed, "tenant", now) == ()
    sql = str(allowed.statement.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "batch" in sql and "is not null" in sql
    assert sql.index("batch") < sql.index("limit")

    blocked = _BudgetConnection(module.DAILY_BUNDLE_BYTES - module.ACTIVE_MAX_BUNDLE_BYTES + 1)
    with pytest.raises(ValueError, match="SUPPLIER_SERP_DAILY_BUNDLE_LIMIT"):
        module._budgets_and_cooldowns(blocked, "tenant", now)
    assert blocked.statement is None


def capture(query: str) -> SerpCapture:
    now = datetime.now(UTC)
    content = b'<html><li class="b_algo">synthetic public result</li></html>'
    digest = hashlib.sha256(content).hexdigest()
    bing = EngineAttempt(
        engine=ENGINES[0],
        query=query,
        source_url=source_url(ENGINES[0], query),
        observed_at=now,
        status="COMPLETED",
        reason_code="ORGANIC_LINKS_FOUND",
        dom_sha256=digest,
        byte_count=len(content),
        scanned_count=1,
        returned_count=1,
        browser_navigation_count=1,
        links=(
            SerpLink(
                rank=1,
                title="Публичная страница",
                snippet="Непроверенный результат",
                url="https://supplier.ru/",
                dom_sha256=digest,
                locator='locator("li.b_algo").nth(0)',
            ),
        ),
    )
    attempts = [bing]
    for engine in ENGINES[1:]:
        attempts.append(
            EngineAttempt(
                engine=engine,
                query=query,
                source_url=source_url(engine, query),
                observed_at=now,
                status="BLOCKED",
                reason_code="ACCESS_BLOCKED",
                browser_navigation_count=1,
            )
        )
    batch = SearchBatch(query=query, attempts=tuple(attempts), status="PARTIAL")
    return SerpCapture(batch=batch, contents=(content, *(None for _ in ENGINES[1:])))


def test_final_replay_is_source0_and_never_hydrates_bundle(storage, monkeypatch):
    company = "serp-" + uuid4().hex
    request = ingest(storage, company)
    calls: list[tuple[str, tuple[object, ...]]] = []
    monkeypatch.setattr(
        module,
        "observe_supplier_serp",
        lambda query, *, cooldowns=(), company_id=None: (
            calls.append((query, cooldowns)),
            capture(query),
        )[1],
    )
    result = prepare_supplier_serp(storage, company, request, actor_id="synthetic")
    assert result.created and result.source_requests == len(ENGINES)
    assert result.report.status == "PARTIAL" and result.report.source_bundle_byte_count
    statements: list[str] = []

    def trace(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(storage._engine, "before_cursor_execute", trace)
    try:
        replay = read_supplier_serp(storage, company, request)
    finally:
        event.remove(storage._engine, "before_cursor_execute", trace)
    assert replay.report == result.report and not replay.created and replay.source_requests == 0
    assert len(calls) == 1
    assert not any("eis_supplier_serp_runs.source_bundle AS" in sql for sql in statements)
    with storage.transaction(company, consistent_read=True) as conn:
        bundle = conn.scalar(
            select(eis_supplier_serp_runs.c.source_bundle).where(
                eis_supplier_serp_runs.c.run_id == result.report.run_id
            )
        )
    assert hashlib.sha256(bundle).hexdigest() == result.report.source_bundle_sha256
    with ZipFile(BytesIO(bundle)) as zipped:
        assert zipped.namelist() == ["bing.html"]
        assert (
            zipped.read("bing.html")
            == b'<html><li class="b_algo">synthetic public result</li></html>'
        )
    with storage.transaction("foreign-" + company, consistent_read=True) as conn:
        assert conn.scalar(select(func.count()).select_from(eis_supplier_serp_runs)) == 0
    with pytest.raises(DBAPIError), storage.transaction(company) as conn:
        conn.execute(eis_supplier_serp_runs.delete())


def save_historical(storage, company, request, *, age, policy=module.HISTORICAL_POLICY):
    from procurement.storage.eis_supplier_search import _position

    with storage.transaction(company) as conn:
        position = _position(conn, company, request)
        position_sha, key = module._basis(position, policy)
        observed = capture(module.build_supplier_query(position.position.name.value))
        previous = {a.engine: a for a in observed.batch.attempts}
        order = ENGINES if policy == module.POLICY else HISTORICAL_EXPANDED_ENGINES
        attempts = tuple(
            previous.get(engine)
            or EngineAttempt(
                engine=engine,
                query=observed.batch.query,
                source_url=source_url(engine, observed.batch.query),
                observed_at=datetime.now(UTC),
                status="BLOCKED",
                reason_code="ACCESS_BLOCKED",
                browser_navigation_count=1,
            )
            for engine in order
        )
        legacy = SerpCapture(
            batch=SearchBatch(query=observed.batch.query, attempts=attempts, status="PARTIAL"),
            contents=(observed.contents[0], *(None for _ in attempts[1:])),
        )
        bundle = module._bundle(legacy)
        report = module.SupplierSerpReport(
            policy_version=policy,
            run_id=str(uuid4()),
            request=request,
            position_sha256=position_sha,
            position_name=position.position.name,
            query=legacy.batch.query,
            status="PARTIAL",
            reason_code="FIXED_MULTI_ENGINE_SERP",
            created_at=datetime.now(UTC) - age,
            batch=legacy.batch,
            attempted_source_requests=len(attempts),
            source_bundle_sha256=hashlib.sha256(bundle).hexdigest(),
            source_bundle_byte_count=len(bundle),
        )
        module._append(conn, company, report, key, bundle=bundle, actor_id="synthetic")
        return report


def test_withdrawn_sources_remain_readable_and_never_run_again(storage, monkeypatch):
    company = "serp-legacy-" + uuid4().hex
    request = ingest(storage, company)
    original = save_historical(storage, company, request, age=timedelta(minutes=20))
    calls = []
    monkeypatch.setattr(
        module,
        "observe_supplier_serp",
        lambda query, *, cooldowns=(), company_id=None: (calls.append(cooldowns), capture(query))[
            1
        ],
    )
    replay = read_supplier_serp(storage, company, request)
    assert replay.report == original and replay.source_requests == 0 and calls == []
    upgraded = prepare_supplier_serp(storage, company, request, actor_id="synthetic")
    assert upgraded.report.policy_version == module.POLICY
    assert upgraded.source_requests == 3 and len(calls) == 1
    # Only active engine cooldowns carry over from archived policy.
    assert set(calls[0]) == set(ENGINES[1:])
    assert read_supplier_serp(storage, company, request).report == upgraded.report
    with storage.transaction(company) as conn:
        saved = conn.scalar(
            select(eis_supplier_serp_runs.c.report).where(
                eis_supplier_serp_runs.c.run_id == original.run_id
            )
        )
    assert saved == original.model_dump(mode="json")

    recent_company = "serp-recent-" + uuid4().hex
    recent = ingest(storage, recent_company)
    save_historical(storage, recent_company, recent, age=timedelta(minutes=1))
    with pytest.raises(ValueError, match="REFRESH_COOLDOWN"):
        prepare_supplier_serp(storage, recent_company, recent, actor_id="synthetic")
    assert len(calls) == 1

    rolling_company = "serp-rolling-" + uuid4().hex
    rolling = ingest(storage, rolling_company)
    save_historical(
        storage, rolling_company, rolling, age=timedelta(minutes=20), policy=module.POLICY
    )
    save_historical(storage, rolling_company, rolling, age=timedelta(minutes=1))
    with pytest.raises(ValueError, match="REFRESH_COOLDOWN"):
        prepare_supplier_serp(storage, rolling_company, rolling, actor_id="synthetic", refresh=True)
    assert len(calls) == 1


def test_post_dispatch_failure_leaves_latest_started_unknown(storage, monkeypatch):
    company = "serp-failed-" + uuid4().hex
    request = ingest(storage, company)
    monkeypatch.setattr(
        module,
        "observe_supplier_serp",
        lambda query, *, cooldowns=(), company_id=None: (_ for _ in ()).throw(
            RuntimeError("browser died")
        ),
    )
    try:
        prepare_supplier_serp(storage, company, request, actor_id="synthetic")
    except RuntimeError:
        pass
    else:
        raise AssertionError("post-dispatch failure must propagate")
    replay = read_supplier_serp(storage, company, request)
    assert replay.report.status == "STARTED"
    assert replay.report.attempted_source_requests is None
    assert replay.source_requests == 0 and not replay.created

    with storage.transaction(company) as conn:
        original = (
            conn.execute(
                select(eis_supplier_serp_runs).where(
                    eis_supplier_serp_runs.c.run_id == replay.report.run_id
                )
            )
            .mappings()
            .one()
        )
        for _ in range(19):
            run_id = str(uuid4())
            payload = dict(original["report"])
            payload["run_id"] = run_id
            conn.execute(
                insert(eis_supplier_serp_runs).values(
                    **{
                        **dict(original),
                        "run_id": run_id,
                        "report": payload,
                        "report_sha256": module._digest(payload),
                    }
                )
            )
    next_request = ingest(storage, company, version=2)
    calls = []
    monkeypatch.setattr(
        module,
        "observe_supplier_serp",
        lambda query, *, cooldowns=(), company_id=None: calls.append(query),
    )
    with pytest.raises(ValueError, match="SUPPLIER_SERP_HOURLY_LIMIT"):
        prepare_supplier_serp(storage, company, next_request, actor_id="synthetic")
    assert calls == []
