"""Linux process-level lease tests with stubbed Docker and no source access."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="requires Linux flock and signals")

ROOT = Path(__file__).parents[1]


@pytest.fixture
def regional_wrapper(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    workspace = tmp_path / "workspace"
    scripts = workspace / "scripts"
    state = tmp_path / "state"
    marker = tmp_path / "browser" / "eis-223-refresh.request"
    bindir = tmp_path / "bin"
    scripts.mkdir(parents=True)
    state.mkdir()
    marker.parent.mkdir()
    bindir.mkdir()
    for name in ("server-eis-metrics.sh", "server-eis-metrics.py"):
        helper = (ROOT / "scripts" / name).read_text()
        helper = helper.replace("/home/syurai/vibe-seller-state", str(state))
        (scripts / name).write_text(helper)
    source = (ROOT / "scripts/server-eis-223-refresh.sh").read_text()
    source = source.replace("/home/syurai/vibe-seller-state", str(state))
    source = source.replace("/home/syurai/vibe-seller", str(workspace))
    source = source.replace("/var/lib/eis-browser/eis-223-refresh.request", str(marker))
    source = source.replace("flock -w 300 9", "flock -w 2 9")
    wrapper = scripts / "server-eis-223-refresh.sh"
    wrapper.write_text(source)
    wrapper.chmod(0o700)
    (scripts / "server-eis-223-refresh.py").write_text("# synthetic probe input\n")
    sudo = bindir / "sudo"
    sudo.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
[[ ${1:-} == -n ]] && shift
[[ ${1:-} == docker ]] || exit 90
shift
printf '%s\\n' "$*" >> "$STUB_LOG"
case ${1:-} in
  inspect) printf '%s\\n' healthy ;;
  exec)
    shift
    [[ ${1:-} == -i ]] && shift
    shift
    if [[ " $* " == *" --probe "* ]]; then
      [[ ${STUB_PROBE_FAIL:-0} == 1 ]] && exit 41
      if [[ -n ${STUB_PROBE_JSON:-} ]]; then printf '%s\\n' "$STUB_PROBE_JSON"
      else printf '%s\\n' '{"status":"READY","source_requests":0}'; fi
    elif [[ " $* " == *" python -c "* ]]; then
      while [[ ${1:-} != -c ]]; do shift; done
      shift
      python3 -c "$1"
    else
      exit 91
    fi ;;
  compose)
    [[ -n ${STUB_WORKER_SLEEP:-} ]] && sleep "$STUB_WORKER_SLEEP"
    if [[ -n ${STUB_WORKER_JSON:-} ]]; then printf '%s\\n' "$STUB_WORKER_JSON"
    else printf '%s\\n' '{"status":"PARTIAL","attempted":1}'; fi
    exit "${STUB_WORKER_EXIT:-0}" ;;
  *) exit 92 ;;
esac
"""
    )
    sudo.chmod(0o700)
    log = tmp_path / "docker.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "STUB_LOG": str(log),
    }
    return wrapper, marker, log, env


def run(wrapper: Path, env: dict[str, str], **updates: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(wrapper)],
        env={**env, **updates},
        text=True,
        capture_output=True,
        timeout=8,
        check=False,
    )


def wait_for(path: Path, *, timeout: float = 3) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path}")


def hold_lock(path: Path, ready: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            "bash",
            "-c",
            'exec 9>"$1"; flock -x 9; touch "$2"; sleep 30',
            "holder",
            str(path),
            str(ready),
        ],
        text=True,
    )


@pytest.mark.parametrize(
    ("probe", "expected_reason", "expected_code"),
    [
        ('{"status":"IDLE","source_requests":0}', None, 0),
        ('{"status":"READY","source_requests":1,"detail":"SECRET"}', "REGIONAL_PROBE_INVALID", 65),
        ("not-json-SECRET", "REGIONAL_PROBE_INVALID", 65),
    ],
)
def test_idle_or_invalid_probe_never_creates_marker_or_runs_worker(
    regional_wrapper, probe, expected_reason, expected_code
) -> None:
    wrapper, marker, log, env = regional_wrapper
    result = run(wrapper, env, STUB_PROBE_JSON=probe)
    assert result.returncode == expected_code and not marker.exists()
    assert " compose " not in f" {log.read_text() if log.exists() else ''} "
    assert "SECRET" not in result.stderr
    payload = json.loads(result.stdout)
    if expected_reason:
        assert payload["reason"] == expected_reason
    else:
        assert payload["status"] == "IDLE"


def test_duplicate_dispatch_cannot_remove_owner_marker_and_owner_cleans_after_lock(
    regional_wrapper,
) -> None:
    wrapper, marker, _, env = regional_wrapper
    import_lock = wrapper.parents[2] / "state/eis-import.lock"
    ready = wrapper.parents[2] / "holder.ready"
    holder = hold_lock(import_lock, ready)
    owner = None
    try:
        wait_for(ready)
        owner = subprocess.Popen(
            ["bash", str(wrapper)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        wait_for(marker)
        duplicate = run(wrapper, env)
        assert duplicate.returncode == 75
        assert json.loads(duplicate.stdout)["reason"] == "REGIONAL_DISPATCH_BUSY"
        assert marker.exists()
        holder.terminate()
        holder.wait(timeout=3)
        stdout, stderr = owner.communicate(timeout=5)
        assert owner.returncode == 0 and not stderr and not marker.exists()
        payload = json.loads(stdout)
        assert payload["source_lock_wait_seconds"] >= 0
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=3)
        if owner is not None and owner.poll() is None:
            owner.terminate()
            owner.wait(timeout=3)


@pytest.mark.parametrize(
    ("worker_json", "worker_exit", "expected_code", "reason"),
    [
        ('{"status":"BLOCKED","reason":"SOURCE_FAILED","attempted":1}', "7", 7, "SOURCE_FAILED"),
        ("invalid-worker-output", "0", 65, "REGIONAL_WORKER_OUTPUT_INVALID"),
    ],
)
def test_worker_failure_or_invalid_output_always_cleans_marker(
    regional_wrapper, worker_json, worker_exit, expected_code, reason
) -> None:
    wrapper, marker, _, env = regional_wrapper
    result = run(
        wrapper,
        env,
        STUB_WORKER_JSON=worker_json,
        STUB_WORKER_EXIT=worker_exit,
    )
    assert result.returncode == expected_code and not marker.exists()
    assert json.loads(result.stdout)["reason"] == reason


def test_term_while_waiting_cleans_marker_and_leaves_no_waiter(regional_wrapper) -> None:
    wrapper, marker, _, env = regional_wrapper
    import_lock = wrapper.parents[2] / "state/eis-import.lock"
    ready = wrapper.parents[2] / "holder.ready"
    holder = hold_lock(import_lock, ready)
    waiter = None
    try:
        wait_for(ready)
        waiter = subprocess.Popen(
            ["bash", str(wrapper)],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        wait_for(marker)
        waiter.send_signal(signal.SIGTERM)
        waiter.communicate(timeout=4)
        assert waiter.returncode == 143 and not marker.exists()
        holder.terminate()
        holder.wait(timeout=3)
        followup = run(wrapper, env)
        assert followup.returncode == 0
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=3)
        if waiter is not None and waiter.poll() is None:
            waiter.terminate()
            waiter.wait(timeout=3)


def test_import_lock_timeout_cleans_marker(regional_wrapper) -> None:
    wrapper, marker, log, env = regional_wrapper
    import_lock = wrapper.parents[2] / "state/eis-import.lock"
    ready = wrapper.parents[2] / "holder.ready"
    holder = hold_lock(import_lock, ready)
    try:
        wait_for(ready)
        result = run(wrapper, env)
        assert result.returncode == 75 and not marker.exists()
        payload = json.loads(result.stdout)
        assert payload["reason"] == "SERVER_IMPORT_BUSY"
        assert payload["source_lock_wait_seconds"] >= 1
        assert " compose " not in f" {log.read_text()} "
    finally:
        holder.terminate()
        holder.wait(timeout=3)
