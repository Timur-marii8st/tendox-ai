"""Synthetic Docker lifecycle failures; no daemon, source or server is contacted."""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not shutil.which("bash") or not shutil.which("flock"),
    reason="host lifecycle requires POSIX bash/flock",
)

MOCK = r"""
import os,signal,sys,time,fcntl
from pathlib import Path
root=Path(os.environ['MOCK_ROOT']);state=root/'container';log=root/'calls'
a=sys.argv[1:]
if a[0]=='-n':a=a[1:]
assert a.pop(0)=='docker'
with log.open('a') as out:out.write(' '.join(a)+'\n')
if a[0]=='inspect':
    transient=root/'inspect-fail-once'
    if transient.exists():transient.unlink();sys.exit(1)
    if not state.exists():sys.exit(1)
    print(state.read_text());sys.exit(0)
if a[:2]==['container','ls']:
    if state.exists():print('vibe-seller-contract-history')
    sys.exit(0)
if a[0]=='stop':
    with (root/'state/eis-import.lock').open('a+b') as lease:
        try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:pass
        else:raise AssertionError('shared lease released before source cleanup')
    assert state.read_text()=='contract-history-managed-v1'
    state.unlink();sys.exit(0)
if a[0]=='rm':
    state.unlink(missing_ok=True);sys.exit(0)
assert a[0]=='compose'
scenario=os.environ['MOCK_SCENARIO']
if scenario=='create-on-term':
    def end(*args):
        state.write_text('contract-history-managed-v1');sys.exit(143)
    signal.signal(signal.SIGTERM,end)
    (root/'producer-ready').touch()
    while True:time.sleep(.05)
state.write_text('contract-history-managed-v1')
if scenario=='failed-client':sys.exit(37)
state.unlink();sys.exit(0)
"""


def wrapper(tmp_path, scenario):
    source = Path("scripts/server-eis-contract-refresh.sh").read_text()
    source = source.replace("/home/syurai/vibe-seller-state", str(tmp_path / "state"))
    source = source.replace("/home/syurai/vibe-seller", str(tmp_path))
    (tmp_path / "state").mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    sudo = binary / "sudo"
    sudo.write_text(f"#!{sys.executable}\n" + MOCK)
    sudo.chmod(0o700)
    script = tmp_path / "run.sh"
    script.write_text(source)
    env = {
        **os.environ,
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "MOCK_ROOT": str(tmp_path),
        "MOCK_SCENARIO": scenario,
    }
    return script, env


def test_client_failure_cleans_exact_owned_container_before_return(tmp_path):
    script, env = wrapper(tmp_path, "failed-client")
    run = subprocess.run(["bash", str(script), "--registry", "1" * 19], env=env, timeout=5)
    assert run.returncode == 37
    assert not (tmp_path / "container").exists()
    calls = (tmp_path / "calls").read_text()
    assert "stop --time 15 vibe-seller-contract-history" in calls
    assert "--volumes" not in calls and "prune" not in calls


def test_failed_inspect_is_not_confirmed_absence(tmp_path):
    script, env = wrapper(tmp_path, "normal")
    (tmp_path / "container").write_text("contract-history-managed-v1")
    (tmp_path / "inspect-fail-once").touch()
    run = subprocess.run(["bash", str(script), "--registry", "1" * 19], env=env, timeout=5)
    assert run.returncode == 69
    calls = (tmp_path / "calls").read_text()
    assert "container ls --all --filter name=^/vibe-seller-contract-history$" in calls
    assert "stop --time 15 vibe-seller-contract-history" in calls
    assert "compose " not in calls and not (tmp_path / "container").exists()


def test_foreign_name_collision_is_never_stopped_or_removed(tmp_path):
    script, env = wrapper(tmp_path, "normal")
    (tmp_path / "container").write_text("foreign-owner")
    run = subprocess.run(["bash", str(script), "--registry", "1" * 19], env=env, timeout=5)
    assert run.returncode == 65
    assert (tmp_path / "container").read_text() == "foreign-owner"
    calls = (tmp_path / "calls").read_text()
    assert "stop " not in calls and "rm " not in calls and "compose " not in calls


def test_term_during_create_reconciles_after_producer_exit(tmp_path):
    script, env = wrapper(tmp_path, "create-on-term")
    process = subprocess.Popen(["bash", str(script), "--registry", "1" * 19], env=env)
    try:
        deadline = time.monotonic() + 3
        while not (tmp_path / "producer-ready").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / "producer-ready").exists()
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 143
        assert not (tmp_path / "container").exists()
        assert "stop --time 15 vibe-seller-contract-history" in (tmp_path / "calls").read_text()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
