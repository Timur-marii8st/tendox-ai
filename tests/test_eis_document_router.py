"""Linux shell routing under synthetic docker output; no server or source requests."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not shutil.which("flock"), reason="Linux shell gate"
)


@pytest.mark.parametrize(
    "status,reason,expected",
    [
        ("BLOCKED", "ROBOTS_CRAWL_DELAY", "223"),
        ("BLOCKED", "SOURCE_BUSY", "223"),
        ("PROCESSED", None, "44"),
        ("IDLE", None, "44"),
        ("BLOCKED", "ATTACHMENT_UNAVAILABLE", "44"),
    ],
)
def test_deferred_family_keeps_turn_and_completed_or_failed_io_rotates(
    tmp_path, status, reason, expected
):
    work = tmp_path / "work"
    state = tmp_path / "state"
    binaries = tmp_path / "bin"
    for folder in (work, state, binaries):
        folder.mkdir()
    router = state / "eis-documents/local-eis-supplier"
    router.mkdir(parents=True)
    (router / "next-law").write_text("223\n")
    script = Path(__file__).parents[1] / "scripts/server-eis-documents.sh"
    raw = (
        script.read_text()
        .replace("/home/syurai/vibe-seller-state", str(state))
        .replace("/home/syurai/vibe-seller", str(work))
    )
    selected = work / "router.sh"
    selected.write_text(raw)
    sudo = binaries / "sudo"
    sudo.write_text('#!/bin/sh\nshift\nexec "$@"\n')
    docker = binaries / "docker"
    docker.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        "inspect*) echo healthy;;\n"
        '*eis_document_dispatch_cli*) echo \'{"status":"READY","law":"223"}\';;\n'
        "*touch*|*unlink*) exit 0;;\n"
        '*) printf "%s\\n" "$ROUTER_RESULT";;\nesac\n'
    )
    for p in (sudo, docker):
        p.chmod(0o700)
    env = {
        **os.environ,
        "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
        "ROUTER_RESULT": json.dumps({"status": status, "reason": reason}),
    }
    result = subprocess.run(
        ["bash", str(selected)], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert (router / "next-law").read_text().strip() == expected


@pytest.fixture
def dispatcher(tmp_path):
    work, state, binaries = (tmp_path / p for p in ("work", "state", "bin"))
    for p in (work, state, binaries):
        p.mkdir()
    router = state / "eis-documents/local-eis-supplier"
    router.mkdir(parents=True)
    (router / "next-law").write_text("44\n")
    raw = (Path(__file__).parents[1] / "scripts/server-eis-documents.sh").read_text()
    raw = raw.replace("/home/syurai/vibe-seller-state", str(state))
    raw = raw.replace("/home/syurai/vibe-seller", str(work))
    (work / "router.sh").write_text(raw)
    (binaries / "sudo").write_text('#!/bin/sh\nshift\nexec "$@"\n')
    (binaries / "docker").write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\ncase "$*" in\n'
        "inspect*) echo healthy;;\n"
        '*eis_document_dispatch_cli*) printf "%s\\n" "$PROBE_RESULT";;\n'
        '*touch*) touch "$MARKER";;\n*unlink*) rm -f "$MARKER";;\n'
        '*doc223.py*) echo \'{"status":"PROCESSED","attempted":1}\';;\n'
        '*eis_documents_cli*) printf "%s\\n" "$WORKER_RESULT"; exit "$WORKER_EXIT";;\n'
        "*) exit 99;;\nesac\n"
    )
    for p in binaries.iterdir():
        p.chmod(0o700)
    env = {
        **os.environ,
        "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
        "PROBE_RESULT": '{"status":"READY","law":"44"}',
        "WORKER_RESULT": '{"status":"PROCESSED","attempted":1}',
        "WORKER_EXIT": "0",
        "MARKER": str(state / "marker"),
        "CALLS": str(state / "calls"),
    }
    return work / "router.sh", state, router, env


def run_router(dispatcher):
    script, _, _, env = dispatcher
    return subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, timeout=10
    )


def test_idle_does_not_preempt_source_or_rotate_cursor(dispatcher):
    _, state, router, env = dispatcher
    env["PROBE_RESULT"] = '{"status":"IDLE","law":null}'
    result = run_router(dispatcher)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "IDLE"
    assert "touch" not in (state / "calls").read_text()
    assert "compose" not in (state / "calls").read_text()
    assert (router / "next-law").read_text() == "44\n"


def test_other_due_family_runs_without_wasting_idle_turn(dispatcher):
    _, state, router, env = dispatcher
    env["PROBE_RESULT"] = '{"status":"READY","law":"223"}'
    result = run_router(dispatcher)
    assert result.returncode == 0
    assert json.loads(result.stdout)["dispatch_law"] == "223"
    assert (router / "next-law").read_text() == "44\n"
    assert not (state / "marker").exists()


def test_freshness_owner_marker_is_preserved(dispatcher):
    import fcntl

    _, state, _, _ = dispatcher
    (state / "marker").write_text("freshness")
    with (state / "eis-priority.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = run_router(dispatcher)
    assert result.returncode == 75
    assert json.loads(result.stdout)["reason"] == "PRIORITY_WORKER_BUSY"
    assert (state / "marker").read_text() == "freshness"
    assert "unlink" not in (state / "calls").read_text()


def test_busy_import_yields_then_document_runs_and_cleans_marker(dispatcher):
    import fcntl

    script, state, _, env = dispatcher
    with (state / "eis-import.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        proc = subprocess.Popen(
            ["bash", str(script)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            until = time.monotonic() + 3
            while not (state / "marker").exists() and time.monotonic() < until:
                time.sleep(0.02)
            assert (state / "marker").exists()
            assert proc.poll() is None
            # A second cron tick never joins the waiting line.
            second = run_router(dispatcher)
            assert json.loads(second.stdout)["reason"] == "DOCUMENT_DISPATCH_BUSY"
            fcntl.flock(lock, fcntl.LOCK_UN)
            stdout, stderr = proc.communicate(timeout=5)
            assert proc.returncode == 0, stderr
            assert json.loads(stdout)["status"] == "PROCESSED"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    assert not (state / "marker").exists()


def test_worker_failure_cleans_hint_and_keeps_cooldown_turn(dispatcher):
    _, state, router, env = dispatcher
    env["WORKER_RESULT"] = '{"status":"BLOCKED","reason":"ROBOTS_CRAWL_DELAY"}'
    env["WORKER_EXIT"] = "2"
    result = run_router(dispatcher)
    assert result.returncode == 2
    assert (router / "next-law").read_text() == "44\n"
    assert not (state / "marker").exists()


def test_handoff_timeout_cleans_own_marker_without_worker(dispatcher):
    _, state, _, env = dispatcher
    fake = Path(env["PATH"].split(os.pathsep)[0]) / "flock"
    real = shutil.which("flock")
    fake.write_text(f'#!/bin/sh\nif [ "$1" = -w ]; then exit 1; fi\nexec "{real}" "$@"\n')
    fake.chmod(0o700)
    result = run_router(dispatcher)
    assert result.returncode == 75
    assert json.loads(result.stdout)["reason"] == "SERVER_IMPORT_BUSY"
    assert "compose" not in (state / "calls").read_text()
    assert not (state / "marker").exists()


@pytest.mark.parametrize("payload", ["garbage", '{"status":"READY","law":"evil"}'])
def test_invalid_probe_never_sets_hint_or_launches_worker(dispatcher, payload):
    _, state, _, env = dispatcher
    env["PROBE_RESULT"] = payload
    result = run_router(dispatcher)
    assert result.returncode == 65
    assert "touch" not in (state / "calls").read_text()
    assert "compose" not in (state / "calls").read_text()
