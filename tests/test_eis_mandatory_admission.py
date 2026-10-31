"""Execute the real223worker loop against bounded recorded-demand models."""

import asyncio
import importlib.util
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from procurement.sources.eis_223_sync import Eis223RefreshTarget

spec = importlib.util.spec_from_file_location(
    "mandatory_refresh223", Path(__file__).parents[1] / "scripts/server-eis-223-refresh.py"
)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_failure_diagnostic_exposes_only_allowlisted_metadata():
    from sqlalchemy.exc import IntegrityError

    class DatabaseFailure(Exception):
        sqlstate = "23505"

    error = IntegrityError("secret SQL", {"token": "secret"}, DatabaseFailure("secret"))
    assert worker.failure_diagnostic(error, "INGEST") == {
        "phase": "INGEST", "category": "SQL_INTEGRITY", "sqlstate": "23505", "code": None,
        "location": None,
    }
    other = RuntimeError("secret token and source contents")
    assert worker.failure_diagnostic(other, "FETCH") == {
        "phase": "FETCH", "category": "OTHER", "sqlstate": None, "code": None,
        "location": None,
    }
    diagnostic = worker.failure_diagnostic(
        worker.Eis223ContractError("FIELD_NAMESPACE_INVALID"), "FETCH"
    )
    assert diagnostic["code"] == "FIELD_NAMESPACE_INVALID"
    diagnostic = worker.failure_diagnostic(
        ValueError("223_POSITION_REPLAY_CONFLICT"), "INGEST"
    )
    assert diagnostic["code"] == "223_POSITION_REPLAY_CONFLICT"
    assert worker.failure_diagnostic(KeyError("secret"), "FETCH")["category"] == "KEY_ERROR"
    assert worker.failure_diagnostic(KeyError("secret"), "FETCH")["code"] is None
    namespace = {"__name__": "procurement.storage.eis_223_index"}
    exec("def trigger():\n    raise ValueError('secret')\n", namespace)
    try:
        namespace["trigger"]()
    except ValueError as error:
        diagnostic = worker.failure_diagnostic(error, "INGEST")
    assert diagnostic["location"] == "procurement.storage.eis_223_index:2"
    assert "secret" not in str(diagnostic)
    namespace = {"__name__": "procurement.sources.eis_223_joint_positions"}
    exec("def trigger():\n    raise ValueError('JOINT_UNMAPPED_ITEMS')\n", namespace)
    try:
        namespace["trigger"]()
    except ValueError as error:
        diagnostic = worker.failure_diagnostic(error, "INGEST")
    assert diagnostic["location"] == "procurement.sources.eis_223_joint_positions:2"
    assert diagnostic["code"] == "JOINT_UNMAPPED_ITEMS"
    with pytest.raises(ValueError, match="DIAGNOSTIC_PHASE_INVALID"):
        worker.failure_diagnostic(other, "secret")


def test_worker_records_failure_category_without_exception_contents(loop, monkeypatch):
    target = Eis223RefreshTarget(date(2026, 10, 11), "purchaseNotice", "77")
    recorded = []
    monkeypatch.setattr(
        worker, "regional_due_windows", lambda *a, **k: (target,) if not recorded else ()
    )

    async def fail(*args, **kwargs):
        raise ValueError("sensitive-source-content")

    monkeypatch.setattr(worker, "fetch_notice223_day", fail)
    monkeypatch.setattr(worker, "record_attempt", lambda *a, **k: recorded.append((a, k)))
    result = asyncio.run(worker.run())
    assert result["outcomes"][0]["reason"] == "SYNC_FAILED"
    assert result["outcomes"][0]["diagnostic"] == {
        "phase": "FETCH", "category": "VALUE_ERROR", "sqlstate": None, "code": None,
        "location": None,
    }
    assert "sensitive-source-content" not in str(result)
    assert recorded[0][0][3] == "FAILED"


@pytest.mark.parametrize("flag, expected", [
    ("false", "JOINT_FLAG_FALSE_WITH_CONTENT"), ("0", "JOINT_FLAG_NUMERIC_FALSE"),
    ("1", "JOINT_FLAG_NUMERIC_TRUE"), ("secret", "JOINT_FLAG_OTHER"),
])
def test_joint_flag_diagnostic_is_bounded(flag, expected):
    namespace = {"__name__": "procurement.sources.eis_223_joint_positions"}
    exec("def trigger(flag):\n    raise ValueError('JOINT_FLAG_UNSUPPORTED')\n", namespace)
    try:
        namespace["trigger"](flag)
    except ValueError as error:
        diagnostic = worker.failure_diagnostic(error, "INGEST")
    assert diagnostic["code"] == expected
    assert "secret" not in str(diagnostic)


@pytest.mark.parametrize("child, expected", [
    ("lotCustomers", "CONTAINER_ONLY"), ("lotCustomer", "CUSTOMER_PRESENT"),
    ("lotItem", "ITEM_PRESENT"), ("untrusted", "OTHER"),
])
def test_joint_false_diagnostic_only_reports_bounded_shape(child, expected):
    from xml.etree.ElementTree import Element, SubElement

    joint = Element("jointLotData")
    SubElement(joint, child).text = "sensitive data"
    namespace = {"__name__": "procurement.sources.eis_223_joint_positions"}
    exec(
        "def trigger(joint):\n    flag = 'false'\n    raise ValueError('JOINT_FLAG_UNSUPPORTED')\n",
        namespace,
    )
    try:
        namespace["trigger"](joint)
    except ValueError as error:
        diagnostic = worker.failure_diagnostic(error, "INGEST")
    assert diagnostic["joint_shape"] == expected
    assert "sensitive data" not in str(diagnostic)


def test_worker_distinguishes_ingest_error_and_preserves_response_hash(loop, monkeypatch):
    target = Eis223RefreshTarget(date(2026, 10, 11), "purchaseNotice", "77")
    recorded = []
    monkeypatch.setattr(
        worker, "regional_due_windows", lambda *a, **k: (target,) if not recorded else ()
    )

    async def fetched(*args, **kwargs):
        return SimpleNamespace(status="SYNCED", window=object(), response_sha256="a" * 64)

    def fail_ingest(*args, **kwargs):
        raise worker.Eis223IndexConflict("WINDOW_REPLAY_CONFLICT")

    monkeypatch.setattr(worker, "fetch_notice223_day", fetched)
    monkeypatch.setattr(worker, "ingest_notice223_window", fail_ingest)
    monkeypatch.setattr(worker, "record_attempt", lambda *a, **k: recorded.append((a, k)))
    result = asyncio.run(worker.run())
    assert result["outcomes"][0]["diagnostic"] == {
        "phase": "INGEST", "category": "EIS_223_INDEX", "sqlstate": None,
        "code": "WINDOW_REPLAY_CONFLICT", "location": None,
    }
    assert recorded[0][0][3] == "FAILED"
    assert recorded[0][1]["response_sha256"] == "a" * 64


@pytest.fixture
def loop(monkeypatch):
    seconds = [0.0]
    monkeypatch.setenv("EIS_223_REGIONAL_ENABLED", "1")
    monkeypatch.delenv("EIS_JOINT_BUDGET_ENABLED", raising=False)
    monkeypatch.setenv("EIS_GETDOCS_IP_TOKEN", "synthetic")
    engine = Mock()
    engine.connect.return_value.__enter__ = Mock(return_value=Mock(scalar=lambda *a: 1))
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(worker, "create_engine", lambda *a, **k: engine)
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setattr(worker, "PostgresStorage", lambda *a: None)
    monkeypatch.setattr(worker.shutil, "disk_usage", lambda *a: SimpleNamespace(free=100 * 1024**3))
    monkeypatch.setattr(worker, "perf_counter", lambda: seconds[0])
    monkeypatch.setattr(worker, "ensure_region_wave", lambda *a, **k: "wave")
    monkeypatch.setattr(
        worker, "read_region_coverage", lambda *a, **k: Mock(model_dump=lambda **k: {})
    )
    monkeypatch.setattr(worker, "optional_quality", lambda *a, **k: {})
    monkeypatch.setattr(worker, "priority_requested", lambda *a, **k: False)
    monkeypatch.setattr(worker, "urgent44_status", lambda *a, **k: "IDLE")
    monkeypatch.setattr(worker, "joint_mandatory_status", lambda *a, **k: "READY")

    async def catalog(*a):
        return {"status": "NOT_DUE", "source_requests": 0}

    monkeypatch.setattr(worker, "refresh_catalog", catalog)

    @asynccontextmanager
    async def transport():
        yield Mock()

    monkeypatch.setattr(worker, "eis_browser_transport", transport)
    return seconds


@pytest.mark.parametrize("ready", [37, 63])
def test_real_worker_reselects_after32_without_repolling_completed(loop, monkeypatch, ready):
    targets = [
        Eis223RefreshTarget(date(2026, 10, 11), "purchaseNotice", f"{i + 1:02}")
        for i in range(ready)
    ]
    recorded = set()
    calls = []

    def due(*a, limit, fresh_only=False, recovery_only=False, **k):
        if recovery_only:
            return ()
        result = tuple(t for t in targets if worker.refresh_window_key(t) not in recorded)[:limit]
        calls.append(len(result))
        return result

    async def fetch(*a, **k):
        loop[0] += 2.56
        return SimpleNamespace(status="NO_DATA", response_sha256="a" * 64)

    def record(storage, company, key, status, **k):
        assert key not in recorded and status == "NO_DATA"
        recorded.add(key)

    monkeypatch.setattr(worker, "regional_due_windows", due)
    monkeypatch.setattr(worker, "fetch_notice223_day", fetch)
    monkeypatch.setattr(worker, "record_attempt", record)
    result = asyncio.run(worker.run())
    assert result["attempted"] == ready and len(recorded) == ready
    assert result["selected_batches"] == 2 and max(calls) == 32
    assert result["seconds"] < 180


@pytest.mark.parametrize("status", ["READY", "BLOCKED"])
def test_outage_recovery_cannot_start_when_fresh44_ready_or_unknown(loop, monkeypatch, status):
    target = Eis223RefreshTarget(date(2026, 10, 9), "purchaseNotice", "50")
    monkeypatch.setattr(worker, "urgent44_status", lambda *a, **k: status)
    monkeypatch.setattr(
        worker,
        "regional_due_windows",
        lambda *a, recovery_only=False, **k: (target,) if recovery_only else (),
    )
    fetch = Mock(side_effect=AssertionError("Fresh44 takes priority"))
    monkeypatch.setattr(worker, "fetch_notice223_day", fetch)
    result = asyncio.run(worker.run())
    assert result["attempted"] == 0 and result["stop_reason"] == "FRESH_44_WORK_READY"
    fetch.assert_not_called()


def test_outage_recovery_is_not_blocked_by_hourly_outage_joint_debt(loop, monkeypatch):
    target = Eis223RefreshTarget(date(2026, 10, 9), "purchaseNotice", "50")
    done = []
    monkeypatch.setattr(
        worker,
        "regional_due_windows",
        lambda *a, recovery_only=False, **k: (target,) if recovery_only and not done else (),
    )

    async def fetch(*a, **k):
        loop[0] += 2.56
        return SimpleNamespace(status="NO_DATA", response_sha256="a" * 64)

    monkeypatch.setattr(worker, "fetch_notice223_day", fetch)
    monkeypatch.setattr(worker, "record_attempt", lambda *a, **k: done.append(a[2]))
    result = asyncio.run(worker.run())
    assert result["attempted"] == 1 and done == [worker.refresh_window_key(target)]


@pytest.mark.parametrize("timeouts", [1, 2])
def test_atomic_timeout_retains_failed_coordinate_and_yields_to44(loop, monkeypatch, timeouts):
    targets = [
        Eis223RefreshTarget(date(2026, 10, 11), "purchaseNotice", "50"),
        Eis223RefreshTarget(date(2026, 10, 11), "purchaseNotice", "77"),
    ]
    recorded = []
    monkeypatch.setattr(worker, "regional_due_windows", lambda *a, **k: tuple(targets))
    monkeypatch.setattr(worker, "priority_requested", lambda *a, **k: timeouts == 1)

    async def fetch(*a, **k):
        loop[0] += 180
        raise TimeoutError

    monkeypatch.setattr(worker, "fetch_notice223_day", fetch)
    monkeypatch.setattr(worker, "record_attempt", lambda *a, **k: recorded.append((a[2], a[3], k)))
    result = asyncio.run(worker.run())
    assert result["attempted"] == timeouts
    assert all(
        status == "FAILED" and details["response_sha256"] is None
        for key, status, details in recorded
    )
    assert all(item["new_versions"] == 0 for item in result["outcomes"])
    if timeouts == 1:
        assert result["stop_reason"] == "PRIORITY_REFRESH_REQUESTED"


def test_fresh223_appearing_during_recovery_preempts_next_old_window(loop, monkeypatch):
    old = Eis223RefreshTarget(date(2026, 10, 9), "purchaseNotice", "50")
    fresh = Eis223RefreshTarget(date(2026, 10, 11), "purchaseNotice", "77")
    done = []

    def due(*a, fresh_only=False, recovery_only=False, **k):
        if fresh_only:
            return (fresh,) if done and worker.refresh_window_key(fresh) not in done else ()
        return (old, old) if recovery_only and not done else ()

    async def fetch(*a, **k):
        loop[0] += 2.56
        return SimpleNamespace(status="NO_DATA", response_sha256="a" * 64)

    monkeypatch.setattr(worker, "regional_due_windows", due)
    monkeypatch.setattr(worker, "fetch_notice223_day", fetch)
    monkeypatch.setattr(worker, "record_attempt", lambda *a, **k: done.append(a[2]))
    result = asyncio.run(worker.run())
    assert done == [worker.refresh_window_key(old), worker.refresh_window_key(fresh)]
    assert [x["lane"] for x in result["outcomes"]] == ["OUTAGE_RECOVERY", "MANDATORY"]


def test_stale_selector_cannot_repoll_attempted_coordinate_within_turn(loop, monkeypatch):
    targets = (
        Eis223RefreshTarget(date(2026, 10, 11), "purchaseNotice", "50"),
        Eis223RefreshTarget(date(2026, 10, 11), "purchaseNotice", "77"),
    )
    calls = []
    recorded = []
    monkeypatch.setattr(worker, "regional_due_windows", lambda *a, **k: targets)

    async def fetch(*a, **k):
        calls.append(k["region"])
        loop[0] += 2.56
        if len(calls) == 1:
            raise ValueError("ARCHIVE_SET_MISMATCH")
        return SimpleNamespace(status="NO_DATA", response_sha256="a" * 64)

    monkeypatch.setattr(worker, "fetch_notice223_day", fetch)
    monkeypatch.setattr(worker, "record_attempt", lambda *a, **k: recorded.append(a[3]))
    result = asyncio.run(worker.run())
    assert result["attempted"] == 2 and calls == ["50", "77"]
    assert recorded == ["FAILED", "NO_DATA"] and result["selected_batches"] == 1


def test_fresh_lane_switch_respects_same_selection_cap(loop, monkeypatch):
    old = Eis223RefreshTarget(date(2026, 10, 9), "purchaseNotice", "50")
    fresh = Eis223RefreshTarget(date(2026, 10, 11), "purchaseNotice", "77")
    calls = []

    def due(*a, fresh_only=False, recovery_only=False, **k):
        if fresh_only:
            calls.append("fresh")
            return (fresh,) if len(calls) > 1 else ()
        return (old,) if recovery_only else ()

    monkeypatch.setattr(worker, "REGIONAL_MAX_BATCHES", 1)
    monkeypatch.setattr(worker, "regional_due_windows", due)
    fetch = Mock(side_effect=AssertionError("No second batch may start"))
    monkeypatch.setattr(worker, "fetch_notice223_day", fetch)
    result = asyncio.run(worker.run())
    assert result["selected_batches"] == result["max_selected_batches"] == 1
    assert result["stop_reason"] == "BATCH_RESELECTION_LIMIT" and result["attempted"] == 0
    fetch.assert_not_called()


def _check_capture_happens_only_after_failed_attempt(loop, monkeypatch, audit_available):
    target = Eis223RefreshTarget(date(2026, 10, 29), "purchaseNoticeKESMBO", "16")
    events = []
    calls = []
    monkeypatch.setattr(
        worker, "regional_due_windows", lambda *a, **k: (target,) if not events else ()
    )

    async def fetched(*args, **kwargs):
        calls.append("fetch")
        return SimpleNamespace(
            status="SYNCED",
            window=SimpleNamespace(window_key=worker.CAPTURE_KEY),
            response_sha256="a" * 64,
        )

    def fail_ingest(*args, **kwargs):
        raise ValueError("JOINT_AMBIGUOUS_LOT_SHAPES")

    def recorded(*args, **kwargs):
        assert args[3] == "FAILED"
        events.append("FAILED")

    def capture(*args, **kwargs):
        assert events == ["FAILED"]
        events.append("CAPTURE")
        raise OSError("retention unavailable")

    monkeypatch.setattr(worker, "fetch_notice223_day", fetched)
    monkeypatch.setattr(worker, "ingest_notice223_window", fail_ingest)
    monkeypatch.setattr(
        worker,
        "failure_diagnostic",
        lambda *_: {
            "code": "JOINT_AMBIGUOUS_LOT_SHAPES",
            "location": "procurement.sources.eis_223_joint_positions:219",
        },
    )
    monkeypatch.setattr(worker, "record_attempt", recorded)
    monkeypatch.setattr(worker, "retain_failed_223", capture)
    def audit(*args):
        events.append("AUDIT")
        if not audit_available:
            raise OSError("secret in audit exception")

    monkeypatch.setattr(worker, "_audit_capture_failure", audit)
    result = asyncio.run(worker.run())
    assert calls == ["fetch"] and events == ["FAILED", "CAPTURE", "AUDIT"]
    assert result["diagnostic_capture"] == {
        "status": "UNKNOWN",
        "reason": "OTHER",
        "audit": "RECORDED" if audit_available else "UNKNOWN",
    }
    assert result["outcomes"][0]["status"] == "FAILED"


def test_capture_happens_only_after_failed_attempt_and_never_extra_source_call(loop, monkeypatch):
    _check_capture_happens_only_after_failed_attempt(loop, monkeypatch, True)


def test_capture_audit_failure_stays_unknown(loop, monkeypatch):
    _check_capture_happens_only_after_failed_attempt(loop, monkeypatch, False)


@pytest.mark.parametrize(
    "case, expected",
    [("archive", "ARCHIVE_BYTES"), ("members", "MEMBER_COUNT"),
     ("expanded", "EXPANDED_BYTES"), ("member", "MEMBER_BYTES")],
)
def test_fetch_archive_resource_diagnostic_is_bounded(case, expected):
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    from procurement.storage.eis_223_index import preflight_notice223_window
    from test_eis_223_index import window

    if case == "archive":
        raw = b"x" * (16 * 1024**2 + 1)
    else:
        output = BytesIO()
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            if case == "members":
                for i in range(201):
                    archive.writestr(f"private-{i}.xml", b"x")
            elif case == "expanded":
                for i in range(3):
                    archive.writestr(f"private-{i}.xml", b"x" * (11 * 1024**2))
            else:
                archive.writestr("private.xml", b"x" * (12 * 1024**2 + 1))
        raw = output.getvalue()
    with pytest.raises(ValueError, match="ARCHIVE_RESOURCE_LIMIT") as caught:
        preflight_notice223_window("tenant-a", window(raw))
    detail = worker.failure_diagnostic(caught.value, "FETCH")["fetch_detail"]
    assert detail == {"kind": "ARCHIVE_RESOURCE", "cause": expected}
    assert "private" not in str(detail)


def test_fetch_window_bytes_reports_only_bounded_counts_and_stops_downloads():
    from test_eis_223_sync import MultiArchiveTransport, fetch

    class LargeTransport(MultiArchiveTransport):
        async def download(self, url, token):
            self.downloads += 1
            return 200, b"x" * (16 * 1024**2)

    transport = LargeTransport(4)
    with pytest.raises(ValueError, match="WINDOW_BYTES_LIMIT") as caught:
        fetch(transport)
    assert transport.downloads == 3
    detail = worker.failure_diagnostic(caught.value, "FETCH")["fetch_detail"]
    assert detail == {"kind": "WINDOW_BYTES", "downloaded_count": 3, "compressed_mib_floor": 48}
    assert "http" not in str(detail)


def test_fetch_archive_set_mismatch_reports_safe_cause_without_download():
    from test_eis_223_event_sync import Transport, fetch

    transport = Transport(failure="archive_set")
    with pytest.raises(ValueError, match="ARCHIVE_SET_MISMATCH") as caught:
        fetch(transport)
    assert transport.downloads == 0
    detail = worker.failure_diagnostic(caught.value, "FETCH")["fetch_detail"]
    assert detail == {"kind": "ARCHIVE_SET", "cause": "UID_MISMATCH"}
    assert "http" not in str(detail)


@pytest.mark.parametrize("detail", [
    {"kind": "WINDOW_BYTES", "downloaded_count": 3, "compressed_mib_floor": 48,
     "url": "secret"},
    {"kind": "WINDOW_BYTES", "downloaded_count": True, "compressed_mib_floor": 48},
    {"kind": "ARCHIVE_RESOURCE", "cause": "secret"},
    {"kind": "ARCHIVE_SET", "cause": "UID_MISMATCH"},
    {"kind": []},
])
def test_attempt_rejects_unbounded_or_wrong_family_diagnostic_before_transaction(detail):
    from datetime import UTC, datetime

    from procurement.storage.eis_223_sync import record_attempt

    class NoTransaction:
        def transaction(self, *_args, **_kwargs):
            pytest.fail("invalid metadata must not start a transaction")

    with pytest.raises(ValueError, match="FETCH_DIAGNOSTIC_INVALID"):
        record_attempt(NoTransaction(), "tenant-a", "getDocsIP/RI223/77/2026-10-30+03:00/"
                       "purchaseNotice", "FAILED", actor_id="test", checked_at=datetime.now(UTC),
                       response_sha256=None, reason="WINDOW_BYTES_LIMIT", fetch_detail=detail)


@pytest.mark.parametrize("case,expected", [
    ("empty", "INITIAL_COUNT"), ("duplicate_initial", "INITIAL_DUPLICATE"),
    ("too_many_prepared", "PREPARED_COUNT"), ("duplicate_prepared", "PREPARED_DUPLICATE"),
    ("missing_download", "DOWNLOADED_MISMATCH"),
])
def test_fetch_archive_set_detail_classifies_existing_bounded_checks(case, expected):
    from dataclasses import replace

    from procurement.sources.eis_223_event_sync import bind_purchase_rejection_window
    from test_eis_223_index import responses

    initial, prepared = responses()
    if case == "empty":
        initial = replace(initial, archive_urls=())
    elif case == "duplicate_initial":
        initial = replace(initial, archive_urls=initial.archive_urls * 2)
    elif case == "too_many_prepared":
        prepared = replace(prepared, prepared_archives=prepared.prepared_archives * 9)
    elif case == "duplicate_prepared":
        prepared = replace(prepared, prepared_archives=prepared.prepared_archives * 2)
    key = "getDocsIP/RI223/77/2026-10-30+03:00/purchaseRejection"
    with pytest.raises(ValueError, match="ARCHIVE_SET_MISMATCH") as caught:
        bind_purchase_rejection_window(key, initial, prepared, {})
    assert worker.failure_diagnostic(caught.value, "FETCH")["fetch_detail"] == {
        "kind": "ARCHIVE_SET", "cause": expected,
    }
