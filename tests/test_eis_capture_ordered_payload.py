"""Regressions for sorting keys before projecting a wide 44-FZ notice."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from procurement.sources.eis_search_capture import load_capture_plan
from procurement.storage import eis_search_capture as capture

ROOT = Path(__file__).resolve().parents[1]


def _plan():
    return load_capture_plan(ROOT / "scripts/benchmarks/eis-search-capture-plan.v3.json")[0]


def _sql(statement):
    return " ".join(
        str(
            statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        ).split()
    )


def _old_order(spec, statement):
    columns = {column.name: column for column in spec.columns}
    table = capture._table(spec.name)
    return statement.order_by(
        *[
            (table.c[name].collate("C") if columns[name].kind == "TEXT" else table.c[name]).asc()
            for name in spec.primary_key
        ]
    )


def test_wide_projection_is_after_narrow_key_sort_with_full_outer_order():
    plan = _plan()
    spec = next(r for r in plan.relations if r.name == "eis_notice_versions")
    statement = capture._selection(spec, plan.tenant)
    sql = _sql(capture._ordered_capture_statement(spec, statement, version3=True))
    before_payload, payload = sql.split(" JOIN LATERAL ", 1)
    keys = before_payload.split(" FROM (", 1)[1]
    assert "CAST(" not in keys
    assert "lot_items" not in keys and "attachments" not in keys
    assert "CAST(public.eis_notice_versions.lot_items AS TEXT) AS lot_items" in payload
    assert "CAST(public.eis_notice_versions.attachments AS TEXT) AS attachments" in payload
    assert sql.count("LIMIT ALL OFFSET 0") == 2
    assert sql.count("company_id = 'local-eis-supplier'") == 2
    for name in spec.primary_key:
        assert f"public.eis_notice_versions.{name} = ordered_keys.{name}" in payload
    assert sql.endswith(
        'ORDER BY ordered_keys.company_id COLLATE "C" ASC, '
        'ordered_keys.purchase_number COLLATE "C" ASC, ordered_keys.version_number ASC'
    )


def test_original_selection_predicates_survive_in_both_query_branches():
    plan = _plan()
    spec = next(r for r in plan.relations if r.name == "eis_notice_versions")
    statement = capture._selection(spec, plan.tenant).where(
        capture._table(spec.name).c.title == "selection-marker"
    )
    sql = _sql(capture._ordered_capture_statement(spec, statement, version3=True))
    assert sql.count("title = 'selection-marker'") == 2


def test_all_legacy_queries_and_other_v3_relations_keep_exact_sql():
    plan = _plan()
    for spec in plan.relations:
        statement = capture._selection(spec, plan.tenant)
        old = _sql(_old_order(spec, statement))
        assert _sql(capture._ordered_capture_statement(spec, statement, version3=False)) == old
        if spec.name != "eis_notice_versions":
            assert _sql(capture._ordered_capture_statement(spec, statement, version3=True)) == old


@pytest.mark.parametrize("sqlstate", [None, "secret-57014", "57014\n", "Î©7014", "123456"])
def test_database_failure_context_refuses_untrusted_sqlstate_without_secrets(sqlstate):
    driver_error = RuntimeError("DSN=secret; SQL=secret; parameters=secret")
    driver_error.sqlstate = sqlstate
    error = OperationalError("secret SQL", {"secret": "credential"}, driver_error)
    converted = capture._v3_database_failure(error, "eis_notice_versions", "CURSOR_FETCH", 123)
    assert str(converted) == "PG_ERROR:eis_notice_versions:CURSOR_FETCH:UNKNOWN:BACKEND_123"
    assert "secret" not in capture._safe_collection_reason(converted)


def test_database_failure_context_uses_driver_state_and_preobserved_backend_only():
    driver_error = RuntimeError("secret")
    driver_error.sqlstate = "57014"
    converted = capture._v3_database_failure(
        OperationalError("secret SQL", {}, driver_error),
        "eis_notice_versions",
        "CURSOR_FETCH",
        987,
    )
    assert str(converted) == "PG_ERROR:eis_notice_versions:CURSOR_FETCH:57014:BACKEND_987"
    original = capture.CaptureCollectionError("RAW_BATCH_SIZE_LIMIT")
    assert (
        capture._v3_database_failure(original, "eis_notice_versions", "CURSOR_FETCH", 987)
        is original
    )


def test_failure_context_never_trusts_arbitrary_relation_phase_or_backend():
    driver_error = RuntimeError("secret")
    driver_error.sqlstate = "57014"
    error = OperationalError("secret SQL", {}, driver_error)
    converted = capture._v3_database_failure(error, "secret relation", "secret phase", True)
    assert str(converted) == "PG_ERROR:UNKNOWN_RELATION:UNKNOWN_PHASE:57014:BACKEND_UNKNOWN"


def test_driver_sqlstate_property_failure_does_not_mask_original_database_error():
    class Broken(RuntimeError):
        @property
        def sqlstate(self):
            raise RuntimeError("secret")

    error = OperationalError("secret", {}, Broken())
    converted = capture._v3_database_failure(error, "eis_notice_versions", "CURSOR_DECLARE", None)
    assert str(converted) == "PG_ERROR:eis_notice_versions:CURSOR_DECLARE:UNKNOWN:BACKEND_UNKNOWN"


@pytest.mark.parametrize(
    "fault,secondary",
    [
        (None, None),
        ("PREFLIGHT", None),
        ("CURSOR_DECLARE", None),
        ("CURSOR_FETCH", None),
        ("TIMEOUT_SET", None),
        ("CURSOR_CLOSE", None),
        ("CURSOR_FETCH", "CLOSE"),
        ("CURSOR_FETCH", "ABORT"),
        ("CURSOR_FETCH", "BOTH"),
        ("TIMEOUT_SET", "ALL_TIMEOUT_CLEANUP"),
    ],
)
def test_v3_collector_uses_query_and_keeps_first_failure_without_postfault_diagnostics(
    tmp_path, monkeypatch, fault, secondary
):
    plan = _plan()
    spec = next(r for r in plan.relations if r.name == "eis_notice_versions")
    plan = plan.model_copy(update={"relations": (spec,)})
    driver_error = RuntimeError("secret SQL/DSN/params")
    driver_error.sqlstate = "57014"
    error = OperationalError("secret SQL", {"secret": "canary"}, driver_error)
    calls = []
    rows = []
    raw = {
        c.name: "[]"
        if c.kind == "JSON"
        else 1
        if c.kind == "INTEGER"
        else None
        if c.nullable
        else "x"
        for c in spec.columns
    }
    raw["company_id"] = plan.tenant
    timeout_calls = 0
    backend_id = 2_147_483_647 if secondary == "ALL_TIMEOUT_CLEANUP" else 321

    class Result:
        closed = 0

        def mappings(self):
            return self

        def partitions(self, size):
            assert size <= 8
            calls.append("fetch")
            if fault == "CURSOR_FETCH":
                raise error
            yield [raw]

        def close(self):
            self.closed += 1
            calls.append("close")
            if fault == "CURSOR_CLOSE":
                raise error
            if secondary in {"CLOSE", "BOTH", "ALL_TIMEOUT_CLEANUP"}:
                raise RuntimeError("secret cleanup")

    result = Result()

    class Connection:
        def execution_options(self, **options):
            assert options == {"stream_results": True, "yield_per": 8}
            return self

        def execute(self, statement):
            if str(statement) == "SELECT pg_backend_pid()":
                calls.append("backend")
                return SimpleNamespace(scalar_one=lambda: backend_id)
            calls.append("declare")
            assert "JOIN LATERAL" in str(statement)
            if fault == "CURSOR_DECLARE":
                raise error
            return result

    class Writer:
        pending_peak_bytes = 0

        def __init__(self, *args):
            pass

        def write(self, row):
            rows.append(row)

        def finish(self, count):
            return SimpleNamespace(rows=len(rows))

        def abort(self):
            calls.append("abort")
            if secondary in {"ABORT", "BOTH", "ALL_TIMEOUT_CLEANUP"}:
                raise RuntimeError("secret cleanup")

    def timeout(*args):
        nonlocal timeout_calls
        timeout_calls += 1
        if fault == "TIMEOUT_SET" and timeout_calls == 4:
            if secondary == "ALL_TIMEOUT_CLEANUP":
                raise capture._TimeoutResultCleanupError(error)
            raise error

    def preflight(*args):
        if fault == "PREFLIGHT":
            raise error
        return 1, 1

    monkeypatch.setattr(capture, "_bound_statement_timeout", timeout)
    monkeypatch.setattr(capture, "_source_count_and_max_row_bytes", preflight)
    monkeypatch.setattr(capture, "_RelationWriterV3", Writer)
    monkeypatch.setattr(capture, "_record_current", lambda *args: None)
    monkeypatch.setattr(
        capture.shutil, "disk_usage", lambda *args: SimpleNamespace(free=100 * 1024**3)
    )
    budget = SimpleNamespace(check_time=lambda: None)

    def invoke():
        return capture._capture_relations(
            Connection(), plan, tmp_path, datetime(2026, 10, 8, tzinfo=UTC), budget, None
        )

    if fault is None:
        descriptors, counts, _ = invoke()
        assert counts == {spec.name: 1} and descriptors[0].rows == 1
        assert result.closed == 1 and rows[0]["lot_items"] == []
    else:
        with pytest.raises(capture.CaptureCollectionError) as raised:
            invoke()
        reason = str(raised.value)
        primary = f"PG_ERROR:eis_notice_versions:{fault}:57014:BACKEND_{backend_id}"
        if secondary is None:
            assert reason == primary
        else:
            assert primary in reason
            if secondary in {"CLOSE", "BOTH", "ALL_TIMEOUT_CLEANUP"}:
                assert ";CURSOR_CLOSE_FAILED" in reason
            if secondary in {"ABORT", "BOTH", "ALL_TIMEOUT_CLEANUP"}:
                assert ";WRITER_ABORT_FAILED" in reason
        if secondary == "ALL_TIMEOUT_CLEANUP":
            diagnostic = capture._safe_collection_reason(raised.value)
            assert primary in diagnostic
            assert ";TIMEOUT_RESULT_CLOSE_FAILED" in diagnostic
            assert ";CURSOR_CLOSE_FAILED" in diagnostic
            assert ";WRITER_ABORT_FAILED" in diagnostic
            assert diagnostic.count("CaptureCollectionError:") == 1
        assert "secret" not in str(raised.value)
        assert calls.count("backend") == 1
        if fault != "PREFLIGHT":
            assert calls[-1] == "abort"
        if fault not in {"PREFLIGHT", "CURSOR_DECLARE"}:
            assert result.closed == 1


def test_v3_timeout_results_are_buffered_consumed_closed_without_connection_mutation():
    results = []
    inherited = {"stream_results": True, "yield_per": 8}

    class Result:
        consumed = 0
        closed = 0

        def scalar_one(self):
            self.consumed += 1
            return "30000"

        def close(self):
            self.closed += 1

    class Connection:
        def execute(self, statement, parameters, *, execution_options=None):
            assert str(statement) == "SELECT set_config('statement_timeout', :value, true)"
            assert parameters == {"value": "30000"}
            assert execution_options == {"stream_results": False, "yield_per": None}
            result = Result()
            results.append(result)
            return result

        def execution_options(self, **options):
            pytest.fail("must not mutate live payload connection options")

    budget = SimpleNamespace(plan=_plan(), remaining_statement_timeout_ms=lambda: 30000)
    for _ in range(3):
        capture._bound_statement_timeout(Connection(), budget)
    assert len(results) == 3
    assert all(r.consumed == r.closed == 1 for r in results)
    assert inherited == {"stream_results": True, "yield_per": 8}


@pytest.mark.parametrize(
    "fault,close_fails", [("execute", False), ("scalar", False), ("scalar", True), (None, True)]
)
def test_v3_timeout_primary_failure_survives_result_cleanup(fault, close_fails):
    driver_error = RuntimeError("secret DSN SQL params")
    driver_error.sqlstate = "57014"
    primary = OperationalError("secret SQL", {"secret": "canary"}, driver_error)
    calls = []

    class Result:
        def scalar_one(self):
            calls.append("scalar")
            if fault == "scalar":
                raise primary
            return "30000"

        def close(self):
            calls.append("close")
            if close_fails:
                raise RuntimeError("secret secondary close")

    class Connection:
        def execute(self, *args, **kwargs):
            calls.append("execute")
            if fault == "execute":
                raise primary
            return Result()

    budget = SimpleNamespace(plan=_plan(), remaining_statement_timeout_ms=lambda: 30000)
    with pytest.raises(Exception) as raised:
        capture._bound_statement_timeout(Connection(), budget)
    failure = capture._v3_database_failure(raised.value, "eis_notice_versions", "TIMEOUT_SET", 321)
    if fault:
        assert (
            "PG_ERROR:eis_notice_versions:TIMEOUT_SET:57014:BACKEND_321"
            in capture._safe_collection_reason(failure)
        )
        if close_fails:
            assert ";TIMEOUT_RESULT_CLOSE_FAILED" in capture._safe_collection_reason(failure)
        else:
            assert raised.value is primary
    else:
        assert type(raised.value) is RuntimeError
    assert calls == (["execute"] if fault == "execute" else ["execute", "scalar", "close"])
    assert "secret" not in capture._safe_collection_reason(failure)


def test_legacy_timeout_call_remains_unchanged_and_expired_budget_never_executes():
    calls = []
    legacy, _ = load_capture_plan(ROOT / "scripts/benchmarks/eis-search-capture-plan.v2.json")

    class Connection:
        def execute(self, statement, parameters, **kwargs):
            calls.append((parameters, kwargs))
            return SimpleNamespace()

    budget = SimpleNamespace(plan=legacy, remaining_statement_timeout_ms=lambda: 17)
    capture._bound_statement_timeout(Connection(), budget)
    assert calls == [({"value": "17"}, {})]

    def expired():
        raise capture.CaptureCollectionError("CAPTURE_TIMEOUT")

    budget = SimpleNamespace(plan=_plan(), remaining_statement_timeout_ms=expired)
    with pytest.raises(capture.CaptureCollectionError, match="CAPTURE_TIMEOUT"):
        capture._bound_statement_timeout(Connection(), budget)
    assert len(calls) == 1
