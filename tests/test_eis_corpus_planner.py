"""Durable cursor must never skip a date on failure or accept an unrelated plan."""

import importlib.util
import json
import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Production helper requires Linux")


@pytest.fixture
def helper(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "planner_state", ROOT / "scripts/server-eis-corpus-plan-state.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DIRECTORY = tmp_path / "state"
    return module


def response(prepared, new=393):
    return dict(
        status="PLANNED",
        new_targets=new,
        expected_windows=prepared["expected_windows"],
        scope_sha256=prepared["scope_sha256"],
        region_registry_status="UNKNOWN",
        coverage="UNKNOWN",
    )


def test_digest_matches_runtime_and_completed_receipt_skips(helper):
    from procurement.sources.eis_corpus import EisCorpusScope

    today = date(2026, 10, 5)
    prepared = helper.due(today)
    actual = EisCorpusScope(
        tuple(f"{i:02d}" for i in range(1, 100)), helper.KINDS, date(2026, 10, 2), date(2026, 10, 4)
    )
    assert prepared["scope_sha256"] == actual.sha256 and prepared["expected_windows"] == 1485
    helper.complete(prepared, response(prepared), today)
    assert helper.due(today)["status"] == "IDLE"
    assert helper.read_cursor(today)["new_targets"] == 393


def test_downtime_chunks_from_cursor_without_jumping_dates(helper):
    today = date(2026, 10, 5)
    prepared = helper.due(today)
    helper.complete(prepared, response(prepared), today)
    overdue = helper.due(date(2026, 10, 12))
    assert (overdue["first_day"], overdue["last_day"], overdue["expected_windows"]) == (
        "2026-10-05",
        "2026-10-07",
        1485,
    )
    assert helper.due(date(2026, 10, 6))["expected_windows"] == 495


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "PARTIAL"),
        ("scope_sha256", "a" * 64),
        ("expected_windows", 1484),
        ("new_targets", True),
        ("new_targets", 1486),
        ("coverage", "PASS"),
        ("region_registry_status", "PASS"),
        ("unexpected", "TOKEN_SECRET"),
    ],
)
def test_wrong_plan_never_advances_cursor(helper, field, value):
    prepared = helper.due(date(2026, 10, 5))
    bad = response(prepared) | {field: value}
    with pytest.raises((ValueError, TypeError)):
        helper.complete(prepared, bad, date(2026, 10, 5))
    assert not (helper.DIRECTORY / "last-success.json").exists()


def test_atomic_write_failure_keeps_previous_cursor(helper, monkeypatch):
    prepared = helper.due(date(2026, 10, 5))

    def fail(*args):
        raise OSError("synthetic failure")

    monkeypatch.setattr(helper.os, "replace", fail)
    with pytest.raises(OSError):
        helper.complete(prepared, response(prepared), date(2026, 10, 5))
    assert not list(helper.DIRECTORY.iterdir())


def test_corrupt_cursor_blocks(helper):
    helper.DIRECTORY.mkdir()
    (helper.DIRECTORY / "last-success.json").write_text("{broken")
    with pytest.raises(ValueError):
        helper.due(date(2026, 10, 5))


@pytest.mark.parametrize("kind", ["symlink", "fifo", "oversize", "future"])
def test_unsafe_cursor_cannot_skip_dates(helper, kind, tmp_path):
    helper.DIRECTORY.mkdir()
    path = helper.DIRECTORY / "last-success.json"
    if kind == "symlink":
        other = tmp_path / "other"
        other.write_text("{}")
        path.symlink_to(other)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "oversize":
        path.write_bytes(b"x" * 4097)
    else:
        prepared = helper.due(date(2026, 10, 5))
        helper.complete(prepared, response(prepared), date(2026, 10, 5))
    with pytest.raises((ValueError, OSError)):
        helper.due(date(2026, 10, 4) if kind == "future" else date(2026, 10, 5))


@pytest.mark.skipif(os.name != "posix", reason="Linux process/lock contract")
@pytest.mark.parametrize(
    "mode,code", [("busy", 75), ("partial", 7), ("invalid", 65), ("success", 0)]
)
def test_shell_retry_failure_then_repeat(tmp_path, mode, code):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    text = (
        (ROOT / "scripts/server-eis-corpus-daily.sh")
        .read_text()
        .replace("/home/syurai/vibe-seller/scripts", str(scripts))
        .replace("/home/syurai/vibe-seller-state", str(state))
    )
    wrapper = scripts / "server-eis-corpus-daily.sh"
    wrapper.write_text(text)
    body = (
        (ROOT / "scripts/server-eis-corpus-plan-state.py")
        .read_text()
        .replace(
            "/home/syurai/vibe-seller-state/eis-corpus-planner/local-eis-supplier",
            str(state / "cursor"),
        )
        # One successful three-day chunk is current only on this fixed day.
        # A later wall-clock date correctly leaves additional backlog to plan.
        .replace(
            "today = datetime.now(timezone(timedelta(hours=3))).date()",
            "today = date(2026, 10, 5)",
        )
    )
    (scripts / "server-eis-corpus-plan-state.py").write_text(body)
    # The command is synthetic; no sudo/Docker/source can be invoked in this fixture.
    stub = scripts / "server-eis-corpus.sh"
    stub.write_text("""#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
from datetime import date
import importlib.util
p=Path(__file__).with_name('server-eis-corpus-plan-state.py')
s=importlib.util.spec_from_file_location('state',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
args=sys.argv;first=date.fromisoformat(args[args.index('--from-day')+1]);last=date.fromisoformat(args[args.index('--through-day')+1])
v=m.scope(first,last)
mode=os.environ['STUB_MODE']
if mode=='busy': print('{"status":"BLOCKED"}');sys.exit(75)
if mode=='partial': Path(os.environ['PARTIAL_PROOF']).write_text('31 committed');sys.exit(7)
if mode=='invalid': print('TOKEN_SECRET');sys.exit(0)
print(json.dumps(dict(status='PLANNED',new_targets=0,expected_windows=v['expected_windows'],scope_sha256=v['scope_sha256'],region_registry_status='UNKNOWN',coverage='UNKNOWN')))
""")
    stub.chmod(0o700)
    env = os.environ | {"STUB_MODE": mode, "PARTIAL_PROOF": str(state / "partial")}

    def run():
        return subprocess.run(
            ["bash", str(wrapper)], env=env, capture_output=True, text=True, timeout=5
        )

    result = run()
    assert result.returncode == code
    assert "TOKEN_SECRET" not in result.stdout + result.stderr
    if mode != "success":
        assert not (state / "cursor/last-success.json").exists()
    env["STUB_MODE"] = "success"
    assert run().returncode == 0
    idle = run()
    assert idle.returncode == 0 and json.loads(idle.stdout)["status"] == "IDLE"
