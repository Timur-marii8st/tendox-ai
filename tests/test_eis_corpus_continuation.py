"""Real Linux leases, bounded fake worker. No source/database/network."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="Linux host dispatch uses flock")


def payload(attempted=1, reason=None, **updates):
    return {
        "status": "BLOCKED" if reason else "PARTIAL",
        "reason": reason,
        "selected": attempted,
        "attempted": attempted,
        "synced": 0,
        "skipped": 0,
        "new_versions": 0,
        "new_events": 0,
        "rejected_windows": [],
        "partial_windows": 0,
        "held_pairs": 0,
        "replayed_projection_batches": 0,
        "coverage": "UNKNOWN",
        **updates,
    }


@pytest.fixture
def module():
    name = "corpus_continuation_tests"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/server-eis-corpus-run.py")
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


@pytest.mark.parametrize(
    "args,budget",
    [(["run"], 60), (["run", "--max-windows", "4"], 4), (["run", "--max-windows=60"], 60)],
)
def test_budget_parsing(module, args, budget):
    argv, actual = module.arguments(args)
    assert argv == ["run"] and actual == budget


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["plan"],
        ["run", "--max-windows"],
        ["run", "--max-windows=61"],
        ["run", "--max-windows=0"],
        ["run", "--max-windows=-1"],
        ["run", "--max-windows=1.0"],
        ["run", "--max-windows=2", "--max-windows", "2"],
    ],
)
def test_invalid_or_duplicate_budget_never_dispatches(module, args):
    with pytest.raises(ValueError):
        module.arguments(args)


@pytest.mark.parametrize(
    "updates",
    [
        {"attempted": True},
        {"attempted": -1},
        {"attempted": 4},
        {"selected": 4},
        {"synced": 2},
        {"skipped": 2},
        {"partial_windows": 2},
        {"rejected_windows": [1, 2]},
        {"coverage": "COMPLETE"},
        {"extra": "SECRET"},
        {"reason": "SOURCE https://secret"},
        {"reason": "PRIORITY_REFRESH_REQUESTED"},
    ],
)
def test_untrusted_counter_or_status_never_allows_resume(module, updates):
    with pytest.raises(ValueError):
        module.validate_output(json.dumps(payload(**updates)).encode(), 3, 0)


def test_duplicate_key_or_exit_mismatch_rejected(module):
    raw = json.dumps(payload()).encode()
    with pytest.raises(ValueError):
        module.validate_output(raw[:-1] + b',"attempted":0}', 3, 0)
    with pytest.raises(ValueError):
        module.validate_output(raw, 3, 2)


@pytest.fixture
def dispatch(tmp_path):
    repo, state, binary = (tmp_path / name for name in ("repo", "state", "bin"))
    scripts = repo / "scripts"
    for directory in (scripts, state, binary):
        directory.mkdir(parents=True)
    for name in ("server-eis-corpus.sh", "server-eis-corpus-run.py", "server-eis-metrics.py"):
        source = (ROOT / "scripts" / name).read_text()
        source = source.replace("/home/syurai/vibe-seller-state", str(state))
        source = source.replace("/home/syurai/vibe-seller", str(repo))
        source = source.replace("HORIZON = 840", "HORIZON = 5")
        source = source.replace("POLL_SECONDS = 2.0", "POLL_SECONDS = 0.02")
        (scripts / name).write_text(source)
    plan = tmp_path / "plan.json"
    calls = state / "calls.jsonl"
    sudo = binary / "sudo"
    sudo.write_text("""#!/usr/bin/env python3
import json,os,sys,time
from pathlib import Path
args=sys.argv[1:]
if 'inspect' in args:
 print('healthy');sys.exit(0)
calls=Path(os.environ['CALLS'])
index=len(calls.read_text().splitlines()) if calls.exists() else 0
with calls.open('a') as stream:stream.write(json.dumps(args)+'\\n')
plan=json.loads(Path(os.environ['PLAN']).read_text())
item=plan[min(index,len(plan)-1)]
time.sleep(item.get('sleep',0))
print(item.get('raw',json.dumps(item.get('output',{}))))
sys.exit(item.get('exit',0))
""")
    sudo.chmod(0o700)
    env = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "PLAN": str(plan),
        "CALLS": str(calls),
    }
    return scripts / "server-eis-corpus.sh", state, plan, calls, env


def launch(dispatch, plan, *, budget=4):
    wrapper, _, plan_path, _, env = dispatch
    plan_path.write_text(json.dumps(plan))
    return subprocess.Popen(
        ["bash", str(wrapper), "run", "--max-windows", str(budget)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def finish(child, *, timeout=8):
    try:
        out, err = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise
    assert not err
    return child.returncode, out


def receipts(dispatch):
    return [
        json.loads(line)
        for line in (dispatch[1] / "eis-corpus-runs/local-eis-supplier/runs.jsonl")
        .read_text()
        .splitlines()
    ]


def calls(dispatch):
    path = dispatch[3]
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def wait_for(predicate):
    until = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < until
        time.sleep(0.01)


@pytest.mark.parametrize("reason", ["REGIONAL_REFRESH_REQUESTED", "PRIORITY_REFRESH_REQUESTED"])
def test_remaining_budget_metrics_and_safe_receipt(dispatch, reason):
    child = launch(dispatch, [{"exit": 2, "output": payload(2, reason)}, {"output": payload(2)}])
    assert finish(child)[0] == 0
    actual = calls(dispatch)
    assert [args[args.index("--max-windows") + 1] for args in actual] == ["4", "2"]
    proof = receipts(dispatch)[-1]
    assert proof["attempted"] == 4 and proof["reason"] == "PASS_FINISHED"
    assert len({s["run_id"] for s in proof["segments"]}) == 2
    assert all(len(s["stdout_sha256"]) == 64 for s in proof["segments"])
    metrics = [
        json.loads(line)
        for line in (dispatch[1] / "eis-worker-metrics/local-eis-supplier.jsonl")
        .read_text()
        .splitlines()
    ]
    assert [e["run_id"] for e in metrics if e["phase"] == "dispatch_start"] == [
        s["run_id"] for s in proof["segments"]
    ]
    assert len(metrics) == 12


@pytest.mark.parametrize(
    "reason",
    [
        "SOURCE_SERVICE_ERROR",
        "SOURCE_TRANSPORT_FAILED",
        "DATABASE_FAILED",
        "DATABASE_LIMIT_REACHED",
    ],
)
def test_noncooperative_failure_is_not_retried(dispatch, reason):
    child = launch(dispatch, [{"exit": 2, "output": payload(1, reason)}])
    assert finish(child)[0] == 2 and len(calls(dispatch)) == 1
    assert receipts(dispatch)[-1]["reason"] == reason


@pytest.mark.parametrize(
    "item,exit_code",
    [
        ({"exit": 2, "raw": "SECRET_INVALID"}, 2),
        ({"output": payload(5)}, 65),
        ({"exit": 7, "output": payload(1, "PRIORITY_REFRESH_REQUESTED")}, 7),
        ({"raw": "X" * (1024 * 1024 + 1)}, 65),
    ],
)
def test_bad_output_stops_and_does_not_enter_receipt(dispatch, item, exit_code):
    child = launch(dispatch, [item])
    assert finish(child)[0] == exit_code and len(calls(dispatch)) == 1
    proof = receipts(dispatch)[-1]
    assert proof["reason"] == "INVALID_WORKER_OUTPUT"
    assert proof["attempted"] is None and proof["known_attempted_lower_bound"] == 0
    assert proof["segments"][0]["attempted"] is None
    assert "SECRET" not in json.dumps(proof)


def test_all_budget_consumed_by_no_data_cannot_resume(dispatch):
    child = launch(dispatch, [{"exit": 2, "output": payload(4, "PRIORITY_REFRESH_REQUESTED")}])
    assert finish(child)[0] == 2 and len(calls(dispatch)) == 1
    assert receipts(dispatch)[-1]["reason"] == "WINDOW_BUDGET_EXHAUSTED"


def test_stale_marker_zero_progress_has_segment_bound(dispatch):
    # Exercise the segment cap independently of subprocess startup speed.
    # The separate horizon test still verifies the time cap and atomic work.
    helper = dispatch[0].with_name("server-eis-corpus-run.py")
    helper.write_text(helper.read_text().replace("HORIZON = 5", "HORIZON = 60"))
    child = launch(dispatch, [{"exit": 2, "output": payload(0, "REGIONAL_REFRESH_REQUESTED")}])
    assert finish(child, timeout=30)[0] == 2 and len(calls(dispatch)) == 6
    assert receipts(dispatch)[-1]["reason"] == "CONTINUATION_SEGMENT_LIMIT"


@pytest.mark.parametrize("lock", ["eis-priority.lock", "eis-223-dispatch.lock"])
def test_yield_wait_releases_import_and_finishes_dispatch_owner_first(dispatch, lock):
    import fcntl

    state = dispatch[1]
    with (state / lock).open("ab") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        child = launch(
            dispatch,
            [
                {"exit": 2, "output": payload(1, "PRIORITY_REFRESH_REQUESTED")},
                {"output": payload(1)},
            ],
        )
        try:
            wait_for(lambda: (state / "eis-corpus-runs/local-eis-supplier/runs.jsonl").exists())
            with (state / "eis-import.lock").open("ab") as import_owner:
                fcntl.flock(import_owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                assert len(calls(dispatch)) == 1
            fcntl.flock(owner, fcntl.LOCK_UN)
            assert finish(child)[0] == 0 and len(calls(dispatch)) == 2
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()


def test_duplicate_parent_and_term_wait_leave_foreign_owner_intact(dispatch):
    import fcntl

    state = dispatch[1]
    with (state / "eis-priority.lock").open("ab") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        plan = [{"exit": 2, "output": payload(1, "PRIORITY_REFRESH_REQUESTED")}]
        child = launch(dispatch, plan)
        try:
            wait_for(lambda: (state / "eis-corpus-runs/local-eis-supplier/runs.jsonl").exists())
            duplicate = launch(dispatch, plan)
            code, output = finish(duplicate)
            assert code == 75 and json.loads(output)["reason"] == "CORPUS_WORKER_BUSY"
            child.terminate()
            assert finish(child)[0] == 143 and len(calls(dispatch)) == 1
            assert receipts(dispatch)[-1]["reason"] == "INTERRUPTED"
            with (state / "eis-import.lock").open("ab") as check:
                fcntl.flock(check, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with (state / "eis-corpus-dispatch.lock").open("ab") as check:
                fcntl.flock(check, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()


def test_horizon_never_interrupts_running_atomic_work(dispatch):
    helper = dispatch[0].with_name("server-eis-corpus-run.py")
    helper.write_text(helper.read_text().replace("HORIZON = 5", "HORIZON = 1"))
    child = launch(
        dispatch, [{"sleep": 1.2, "exit": 2, "output": payload(1, "PRIORITY_REFRESH_REQUESTED")}]
    )
    assert finish(child)[0] == 75 and len(calls(dispatch)) == 1
    assert receipts(dispatch)[-1]["reason"] == "CONTINUATION_HORIZON_REACHED"


def test_foreign_dispatch_wait_has_time_bound(dispatch):
    import fcntl

    helper = dispatch[0].with_name("server-eis-corpus-run.py")
    helper.write_text(helper.read_text().replace("HORIZON = 5", "HORIZON = 1"))
    with (dispatch[1] / "eis-223-dispatch.lock").open("ab") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX)
        child = launch(dispatch, [{"exit": 2, "output": payload(1, "REGIONAL_REFRESH_REQUESTED")}])
        assert finish(child)[0] == 75 and len(calls(dispatch)) == 1
        assert receipts(dispatch)[-1]["reason"] == "CONTINUATION_HORIZON_REACHED"
