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
