"""Shared source admission survives crashes and never admits unbounded work."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from procurement import eis_joint_budget as budget

NOW = datetime(2026, 10, 11, 19, 10, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch):
    state = {"seconds": 0.0}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (NOW + timedelta(seconds=state["seconds"])).astimezone(tz or UTC)

    monkeypatch.setattr(budget, "datetime", Clock)
    monkeypatch.setattr(budget.time, "monotonic", lambda: state["seconds"])
    return state


def test_shared_runtime_and_independent_recovery_shares_survive_restart(tmp_path, clock):
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        assert run.can_start("44")
        run.begin_window("44")
        clock["seconds"] += 65
        run.end_window()
        assert not run.can_start("44") and run.can_start("223")
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert restarted.state.used_seconds == 65
        assert not restarted.can_start("44") and restarted.can_start("223")
    with budget.JointStartBudget(tmp_path, "other") as foreign:
        assert foreign.state.used_seconds == 0 and foreign.can_start("44")


def test_crash_reservation_cannot_release_capacity_or_recovery_again(tmp_path, clock):
    run = budget.JointStartBudget(tmp_path, "tenant", reservation=540)
    # Simulated process loss: release the OS handle without writing completion.
    run.lock.close()
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert restarted.state.used_seconds == 540
        assert not restarted.can_start("44") and not restarted.can_start("223")


@pytest.mark.parametrize("invalid", ["bad json", "wrong_company", "future_hour"])
def test_invalid_state_fails_closed_without_rewriting_it(tmp_path, clock, invalid):
    path = tmp_path / "eis-joint-budget-tenant.json"
    with budget.JointStartBudget(tmp_path, "tenant"):
        pass
    raw = path.read_bytes()
    if invalid == "bad json":
        raw = b"{"
    else:
        data = json.loads(raw)
        if invalid == "wrong_company":
            data["company_id"] = "other"
        else:
            data["hour"] = (NOW + timedelta(hours=1)).replace(minute=0).isoformat()
        raw = json.dumps(data).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        budget.JointStartBudget(tmp_path, "tenant")
    assert path.read_bytes() == raw


def test_shared_exhaustion_atomic_tail_and_next_hour_reset(tmp_path, clock):
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        clock["seconds"] = 2990
        # UTC19:59:50: an atomic180s window cannot be admitted.
        assert not run.can_start()
    clock["seconds"] = 3600
    with budget.JointStartBudget(tmp_path, "tenant") as next_hour:
        assert next_hour.state.used_seconds == 0 and next_hour.can_start()


def test_concurrent_accounting_owner_refused(tmp_path, clock):
    with budget.JointStartBudget(tmp_path, "tenant"), pytest.raises(OSError):
        budget.JointStartBudget(tmp_path, "tenant")


def test_shared_54min_stops_starts_after_one_or_two_timeout_charges(tmp_path, clock):
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        # Backdate the period start relative to our fake wall clock so this
        # assertion isolates consumed-budget accounting, not end-of-hour gating.
        run.state = run.state.model_copy(update={"used_seconds": 3100})
        assert run.can_start()
        clock["seconds"] += 180
        assert not run.can_start()
        clock["seconds"] += 180
        assert not run.can_start()


def test_recovery_can_borrow_without_consuming_other_laws_reserved_admission(tmp_path, clock):
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        run.recovery["44"] = 60
        assert not run.can_start("44")
        assert run.can_start("44", borrow=True)
        run.state = run.state.model_copy(update={"used_seconds": 3200})
        assert not run.can_start("44", borrow=True)
        assert run.can_start("223")


@pytest.mark.parametrize("due,carry", [(94, 0), (189, 31), (135, 37)])
def test_recorded_burst_joint_budget_arithmetic_preserves_fresh44_headroom(
    tmp_path, clock, due, carry
):
    # Recorded mixed223 envelope; this is a budget replay, not production PASS.
    cost223 = 815.323888 / 183
    start = clock["seconds"]
    with budget.JointStartBudget(tmp_path, "tenant", reservation=540) as run:
        run.state = run.state.model_copy(update={"used_seconds": 1259.385903 + 70 + 120 + 32})
        for _ in range(due + carry):
            assert run.can_start()
            clock["seconds"] += cost223
        assert run.can_start()
        # One additional timeout consumes capacity; never fabricated success.
        clock["seconds"] += 180
        assert run.state.used_seconds + clock["seconds"] - start < 3240


def test_borrowed_atomic_tail_cannot_erase_other_law_start_reserve(tmp_path, clock):
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        run.recovery["44"] = 60
        run.state = run.state.model_copy(update={"used_seconds": 3100})
        assert not run.can_start("44", borrow=True)
        assert run.can_start("223")


def test_crash_accounting_charges_elapsed_beyond_nominal_reservation(tmp_path, clock):
    run = budget.JointStartBudget(tmp_path, "tenant", reservation=540)
    run.state = run.state.model_copy(update={"used_seconds": 2600})
    run._write(run.state.model_copy(update={"active_reservation": 540, "active_started_at": NOW}))
    run.lock.close()
    clock["seconds"] += 700
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert restarted.state.used_seconds == 3300
        assert not restarted.can_start()


def test_crash_from_previous_hour_does_not_assume_atomic_tail_hard_wall(tmp_path, clock):
    run = budget.JointStartBudget(tmp_path, "tenant")
    run.lock.close()
    clock["seconds"] = 4000
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert restarted.state.used_seconds == 1000
        assert not restarted.can_start("44")


def test_completed_synchronous_overrun_is_charged_to_current_hour(tmp_path, clock):
    run = budget.JointStartBudget(tmp_path, "tenant")
    clock["seconds"] = 4000
    run.close()
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert restarted.state.used_seconds == 1000
