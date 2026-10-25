"""Continuous fresh demand must not starve bounded completed-day reconciliation."""

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from procurement.eis_joint_budget import JointStartBudget
from procurement.sources import eis_freshness
from procurement.sources.eis_feed_sync import EisDateSelection, EisHourSelection, EisHourSyncResult
from procurement.sources.eis_freshness import EisFreshnessScope, FreshnessTarget

NOW = datetime(2026, 10, 22, 12, 10, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch):
    from procurement import eis_joint_budget

    state = {"seconds": 0.0}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (NOW + timedelta(seconds=state["seconds"])).astimezone(tz or UTC)

    monkeypatch.setattr(eis_joint_budget, "datetime", Clock)
    monkeypatch.setattr(eis_joint_budget.time, "monotonic", lambda: state["seconds"])
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    return state


def test_fresh_pressure_preserves_both_recent_daily_shares_and_restart(tmp_path, clock):
    with JointStartBudget(tmp_path, "tenant") as budget:
        budget.state = budget.state.model_copy(update={"used_seconds": 2400})
        assert not budget.can_start(pending_reconciliation=("44", "223"))
        assert budget.can_start()
        assert budget.can_start("44", pending_reconciliation=("44", "223"))
        budget.begin_window("44")
        clock["seconds"] += 360
        budget.end_window()
        assert not budget.recovery_reserved("44") and budget.recovery_reserved("223")
        assert not budget.can_start(pending_reconciliation=("223",))
        assert budget.can_start("223", pending_reconciliation=("223",))
        budget.begin_window("223")
        clock["seconds"] += 360
        budget.end_window()
    with JointStartBudget(tmp_path, "tenant") as restarted:
        assert restarted.state.used_seconds == 3120
        assert not restarted.recovery_reserved("44") and not restarted.recovery_reserved("223")
        assert restarted.can_start()
        clock["seconds"] += 180
        assert not restarted.can_start()


def test_crash_does_not_reissue_protected_shares(tmp_path, clock):
    budget = JointStartBudget(tmp_path, "tenant", reservation=540)
    budget.lock.close()
    with JointStartBudget(tmp_path, "tenant") as restarted:
        assert not restarted.recovery_reserved("44") and not restarted.recovery_reserved("223")
    with JointStartBudget(tmp_path, "other") as foreign:
        assert foreign.recovery_reserved("44")


@pytest.mark.parametrize("enabled", [False, True])
def test_full_fresh_batch_still_runs_daily_first_only_with_protected_share(
    tmp_path, clock, monkeypatch, enabled
):
    if not enabled:
        monkeypatch.delenv("EIS_RECONCILIATION_SHARE_ENABLED")
    daily = FreshnessTarget(
        EisDateSelection("50", NOW.date() - timedelta(days=1), 3),
        "RECONCILE_DAY",
        timedelta(days=1),
    )
    fresh = FreshnessTarget(
        EisHourSelection("50", NOW.date(), 12, 3), "RECENT_HOUR", timedelta(days=1)
    )
    journal = Mock(company_id="tenant", actor_id="worker")
    monkeypatch.setattr(eis_freshness, "eligible_freshness", lambda *a, **k: (fresh,))
    monkeypatch.setattr(eis_freshness, "read_due_reconciliation", lambda *a, **k: (daily,))
    monkeypatch.setattr(eis_freshness, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(
        "procurement.storage.eis_223_regions.regional_due_windows", lambda *a, **k: (daily,)
    )
    monkeypatch.setattr(eis_freshness, "read_due_freshness", lambda *a, **k: (fresh,))
    sync = AsyncMock(
        side_effect=lambda *a, **k: EisHourSyncResult(
            a[3].window_key, "NO_DATA", source_response_sha256="a" * 64
        )
    )
    monkeypatch.setattr(eis_freshness, "sync_eis_window", sync)
    with JointStartBudget(tmp_path, "tenant") as budget:
        report = asyncio.run(
            eis_freshness.run_freshness(
                journal,
                "synthetic",
                EisFreshnessScope(("50",), checkpointed=True, mandatory_only=True),
                now=NOW,
                max_windows=1,
                transport=object(),
                paced_transport=True,
                joint_budget=budget,
            )
        )
    assert report.attempted == 1
    assert report.window_keys == ((daily if enabled else fresh).selection.window_key,)
    assert report.no_data == 1 and report.coverage == "UNKNOWN"


def test_223_daily_selection_precedes_fresh_pressure_until_share_exhausted(
    tmp_path, clock, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "refresh223", Path(__file__).parents[1] / "scripts/server-eis-223-refresh.py"
    )
    refresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(refresh)
    daily, fresh = object(), object()
    monkeypatch.setattr(
        refresh,
        "regional_due_windows",
        lambda *a, **k: (daily,) if k.get("reconciliation_only") else (fresh,),
    )
    with JointStartBudget(tmp_path, "tenant") as budget:
        selected, lane = refresh.mandatory_targets(object(), NOW, limit=2, budget=budget)
        assert selected == (daily,) and lane == "RECONCILIATION"
        budget.recovery["223"] = 360
        selected, lane = refresh.mandatory_targets(object(), NOW, limit=2, budget=budget)
        assert selected == (fresh,) and lane == "MANDATORY"
