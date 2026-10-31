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


def seed_history(tmp_path, company):
    # Synthetic pre-provisioning only; production activation is not implemented.
    path = tmp_path / f"eis-history-turn-{company}.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "company_id": company,
        "hour": NOW.replace(minute=0, second=0, microsecond=0).isoformat(),
        "status": "UNUSED",
        "window_key": None,
        "demand_sha256": None,
        "claim_id": None,
    }))


def test_history_claim_requires_explicit_bootstrap_and_survives_restart(
    tmp_path, clock, monkeypatch
):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        with pytest.raises(ValueError, match="HISTORY_STATE_MISSING"):
            run.claim_history_turn("window/one", "a" * 64)
        seed_history(tmp_path, "tenant")
        assert run.claim_history_turn("window/one", "a" * 64)
        assert not run.claim_history_turn("window/two", "b" * 64)
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert not restarted.claim_history_turn("window/two", "b" * 64)


def test_history_claim_keeps_both_reconciliation_reserves(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        run.state = run.state.model_copy(update={"used_seconds": 2500})
        assert not run.claim_history_turn("window/one", "a" * 64)


@pytest.mark.parametrize("damage", ["missing", "bad_json", "wrong_tenant", "future_hour"])
def test_history_claim_fails_closed_on_lost_or_invalid_state(tmp_path, clock, monkeypatch, damage):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        path = tmp_path / "eis-history-turn-tenant.json"
        if damage == "missing":
            path.unlink()
        elif damage == "bad_json":
            path.write_text("{")
        else:
            state = json.loads(path.read_text())
            state["company_id" if damage == "wrong_tenant" else "hour"] = (
                "other"
                if damage == "wrong_tenant"
                else (NOW + timedelta(hours=1)).replace(minute=0).isoformat()
            )
            path.write_text(json.dumps(state))
        with pytest.raises(ValueError):
            run.claim_history_turn("window/one", "a" * 64)


@pytest.mark.parametrize("completed", [True, False])
def test_history_hour_rollover_preserves_uncertain_or_completed_work(
    tmp_path, clock, monkeypatch, completed
):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        assert run.claim_history_turn("window/one", "a" * 64)
        if completed:
            run.finish_history_turn()
    clock["seconds"] = 3600
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert restarted.claim_history_turn("window/two", "b" * 64) is completed


def test_history_state_is_tenant_scoped_and_requires_owned_lock(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "one") as first:
        seed_history(tmp_path, "one")
        assert first.claim_history_turn("window/one", "a" * 64)
        assert not hasattr(first, "initialize_history_turn")
    with budget.JointStartBudget(tmp_path, "two") as second:
        seed_history(tmp_path, "two")
        assert second.claim_history_turn("window/two", "b" * 64)
    with pytest.raises(ValueError, match="HISTORY_BUDGET_LOCK_REQUIRED"):
        first.claim_history_turn("window/three", "c" * 64)


def test_history_claim_survives_directory_fsync_error(tmp_path, clock, monkeypatch):
    import os
    import stat

    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        fsync = os.fsync

        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("injected directory fsync failure")
            return fsync(fd)

        with monkeypatch.context() as context:
            context.setattr(os, "fsync", fail_directory)
            with pytest.raises(OSError):
                run.claim_history_turn("window/one", "a" * 64)
        assert not run.claim_history_turn("window/two", "b" * 64)


def test_history_overrun_consumes_new_hour_and_uncertainty_stays_blocked(
    tmp_path, clock, monkeypatch
):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        assert run.claim_history_turn("window/one", "a" * 64)
        clock["seconds"] = 3600
        run.finish_history_turn()
        assert not run.claim_history_turn("window/two", "b" * 64)
    clock["seconds"] = 7200
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert restarted.claim_history_turn("window/three", "c" * 64)
    clock["seconds"] = 10800
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert not restarted.claim_history_turn("window/four", "d" * 64)
    clock["seconds"] = 14400
    with budget.JointStartBudget(tmp_path, "tenant") as restarted:
        assert not restarted.claim_history_turn("window/five", "e" * 64)


def test_history_symlink_and_disabled_reserves_cannot_admit(tmp_path, clock, monkeypatch):
    import os

    monkeypatch.delenv("EIS_RECONCILIATION_SHARE_ENABLED", raising=False)
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        with pytest.raises(ValueError, match="HISTORY_RECONCILIATION_GUARD_REQUIRED"):
            run.claim_history_turn("window/one", "a" * 64)
        path = tmp_path / "eis-history-turn-tenant.json"
        target = tmp_path / "foreign"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        run.protected_reconciliation = True
        with pytest.raises(OSError):
            run.claim_history_turn("window/one", "a" * 64)
        assert os.path.islink(path) and target.read_bytes()


@pytest.mark.parametrize(
    "window,digest", [("", "a" * 64), ("line\nbreak", "a" * 64), ("ok", "x" * 64)]
)
def test_history_rejects_invalid_claim_without_consuming_slot(
    tmp_path, clock, monkeypatch, window, digest
):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        with pytest.raises(ValueError, match="HISTORY_CLAIM_INVALID"):
            run.claim_history_turn(window, digest)
        assert run.claim_history_turn("window/valid", "a" * 64)


def test_history_crashed_claim_cannot_be_finished_by_new_owner(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    run = budget.JointStartBudget(tmp_path, "tenant")
    seed_history(tmp_path, "tenant")
    assert run.claim_history_turn("window/one", "a" * 64)
    run.lock.close()
    with (
        budget.JointStartBudget(tmp_path, "tenant") as restarted,
        pytest.raises(ValueError, match="HISTORY_TURN_NOT_OWNED"),
    ):
        restarted.finish_history_turn()


def test_history_deleted_claim_has_no_worker_bootstrap_api(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        assert run.claim_history_turn("window/one", "a" * 64)
        (tmp_path / "eis-history-turn-tenant.json").unlink()
        assert not hasattr(run, "initialize_history_turn")
        with pytest.raises(ValueError, match="HISTORY_STATE_MISSING"):
            run.claim_history_turn("window/two", "b" * 64)


def test_history_fifo_is_rejected_without_blocking(tmp_path, clock, monkeypatch):
    import os
    import time

    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        os.mkfifo(tmp_path / "eis-history-turn-tenant.json")
        start = time.perf_counter()
        with pytest.raises(ValueError, match="HISTORY_STATE_INVALID"):
            run.claim_history_turn("window/one", "a" * 64)
        assert time.perf_counter() - start < 1


@pytest.mark.parametrize("failure", ["file_fsync", "rename"])
def test_history_write_failure_does_not_grant_a_claim(tmp_path, clock, monkeypatch, failure):
    import os

    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        path = tmp_path / "eis-history-turn-tenant.json"
        before = path.read_bytes()

        def fail(*_args):
            raise OSError("injected history persistence failure")

        with monkeypatch.context() as context:
            context.setattr(os, "fsync" if failure == "file_fsync" else "replace", fail)
            with pytest.raises(OSError):
                run.claim_history_turn("window/one", "a" * 64)
        assert path.read_bytes() == before
        with pytest.raises(ValueError, match="HISTORY_TURN_NOT_PENDING"):
            run.finish_history_turn()


def test_history_does_not_extend_existing_budget_schema(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("EIS_RECONCILIATION_SHARE_ENABLED", "1")
    with budget.JointStartBudget(tmp_path, "tenant") as run:
        seed_history(tmp_path, "tenant")
        assert run.claim_history_turn("window/one", "a" * 64)
    state = json.loads((tmp_path / "eis-joint-budget-tenant.json").read_text())
    assert set(state) == set(budget.BudgetState.model_fields)
    assert budget.BudgetState.model_validate(state).company_id == "tenant"
