"""Private best-effort metrics and Linux wrapper process contracts; source-free stubs."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
LINUX = pytest.mark.skipif(
    os.name == "nt", reason="requires Linux flock/signals/private file modes"
)


@pytest.fixture
def logger():
    spec = importlib.util.spec_from_file_location(
        "eis_worker_metrics", ROOT / "scripts/server-eis-metrics.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments():
    return ["local-eis-supplier", "corpus", "run", str(uuid.uuid4()), "dispatch_start", "", "", ""]


@pytest.mark.parametrize(
    "index,value",
    [
        (0, "../SECRET"),
        (1, "SECRET"),
        (2, "run SECRET"),
        (3, "SECRET"),
        (4, "SECRET"),
        (5, "SECRET"),
        (6, "-1"),
        (6, "256"),
        (7, "KILL"),
    ],
)
def test_rejected_fields_never_reflect_or_write(logger, monkeypatch, capsys, index, value):
    args = arguments()
    args[index] = value
    monkeypatch.setattr(logger, "append", lambda data: pytest.fail("invalid event accepted"))
    assert logger.main(args) == 0
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@LINUX
def test_private_rotation_nonblocking_contention_and_no_secret(logger, tmp_path, monkeypatch):
    import fcntl

    monkeypatch.setattr(logger, "DIRECTORY", tmp_path / "metrics")
    monkeypatch.setattr(logger, "MAX_BYTES", 1500)
    payload = logger.event(arguments())
    for _ in range(20):
        logger.append(payload)
    current = logger.DIRECTORY / "local-eis-supplier.jsonl"
    previous = logger.DIRECTORY / "local-eis-supplier.previous.jsonl"
    assert 0 < current.stat().st_size <= 1500 and 0 < previous.stat().st_size <= 1500
    assert logger.DIRECTORY.stat().st_mode & 0o777 == 0o700
    assert current.stat().st_mode & 0o777 == previous.stat().st_mode & 0o777 == 0o600
    for path in (current, previous):
        for line in path.read_bytes().splitlines(keepends=True):
            assert len(line) <= 2048
            event = json.loads(line)
            assert event["schema_version"] == 1 and event["monotonic_ns"] > 0
            assert len(event["boot_id_sha256"]) == 64
    before = current.read_bytes()
    with (logger.DIRECTORY / "local-eis-supplier.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        start = time.monotonic()
        assert logger.main(arguments()) == 0
        assert time.monotonic() - start < 1
    assert current.read_bytes() == before


@LINUX
def test_symlink_and_logger_io_failure_are_silent(logger, tmp_path, monkeypatch, capsys):
    directory = tmp_path / "metrics"
    directory.mkdir()
    secret = tmp_path / "secret"
    secret.write_text("SECRET")
    (directory / "local-eis-supplier.jsonl").symlink_to(secret)
    monkeypatch.setattr(logger, "DIRECTORY", directory)
    assert logger.main(arguments()) == 0 and secret.read_text() == "SECRET"
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.fixture
def wrappers(tmp_path):
    workspace = tmp_path / "workspace"
    scripts = workspace / "scripts"
    state = tmp_path / "state"
    browser = tmp_path / "browser"
    binary = tmp_path / "bin"
    for directory in (scripts, state, browser, binary):
        directory.mkdir(parents=True)
    for name in (
        "server-eis-metrics.py",
        "server-eis-metrics.sh",
        "server-eis-corpus.sh",
        "server-eis-corpus-run.py",
        "server-eis-priority.sh",
        "server-eis-documents.sh",
        "server-eis-223-refresh.sh",
    ):
        content = (ROOT / "scripts" / name).read_text()
        content = content.replace("/home/syurai/vibe-seller-state", str(state))
        content = content.replace("/home/syurai/vibe-seller", str(workspace))
        content = content.replace("/var/lib/eis-browser", str(browser))
        content = content.replace("flock -w 300 9", "flock -w 2 9")
        (scripts / name).write_text(content)
    (scripts / "server-eis-223-refresh.py").write_text("# fake probe input\n")
    sudo = binary / "sudo"
    sudo.write_text("""#!/usr/bin/env python3
import json,os,subprocess,sys
args=sys.argv[1:]
if args[0]=='-n':args=args[1:]
assert args.pop(0)=='docker'
command=args.pop(0)
if command=='inspect':print(os.environ.get('STUB_HEALTH','healthy'))
elif command=='exec':
 if '-c' in args:
  code=args[args.index('-c')+1]
  if 'unlink' in code and os.environ.get('STUB_CLEANUP_FAIL'):sys.exit(43)
  sys.exit(subprocess.call([sys.executable,'-c',code]))
 if os.environ.get('STUB_PROBE_FAIL'):sys.exit(41)
 default={'status':'READY','source_requests':0}
 if 'procurement.eis_document_dispatch_cli' in args:default['law']='44'
 print(os.environ.get('STUB_PROBE_JSON',json.dumps(default)))
elif command=='compose':
 print(os.environ.get('STUB_WORKER_JSON','{"status":"PROCESSED","attempted":1}'))
 sys.exit(int(os.environ.get('STUB_WORKER_EXIT','0')))
else:sys.exit(91)
""")
    sudo.chmod(0o700)
    return scripts, state, browser, {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}"}


def run_wrapper(fixture, name, *, args=(), **updates):
    scripts, _, _, env = fixture
    return subprocess.run(
        ["bash", str(scripts / name), *args],
        env={**env, **updates},
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )


def events(state):
    return [
        json.loads(line)
        for line in (state / "eis-worker-metrics/local-eis-supplier.jsonl").read_text().splitlines()
    ]


@LINUX
@pytest.mark.parametrize(
    "name,lane,args",
    [
        ("server-eis-corpus.sh", "corpus", ("run",)),
        ("server-eis-priority.sh", "priority", ()),
        ("server-eis-documents.sh", "documents", ()),
        ("server-eis-223-refresh.sh", "223_refresh", ()),
    ],
)
@pytest.mark.parametrize("worker_exit", [0, 7])
def test_success_error_stdout_exit_and_six_phases(wrappers, name, lane, args, worker_exit):
    _, state, _, _ = wrappers
    payload = '{"status":"PROCESSED","attempted":1,"private":"SECRET"}'
    if lane == "corpus" and worker_exit == 0:
        payload = json.dumps(
            {
                "status": "PARTIAL",
                "reason": None,
                "selected": 1,
                "attempted": 1,
                "synced": 0,
                "skipped": 0,
                "new_versions": 0,
                "new_events": 0,
                "rejected_windows": [],
                "partial_windows": 0,
                "held_pairs": 0,
                "replayed_projection_batches": 0,
                "coverage": "UNKNOWN",
            }
        )
    result = run_wrapper(
        wrappers, name, args=args, STUB_WORKER_JSON=payload, STUB_WORKER_EXIT=str(worker_exit)
    )
    assert result.returncode == worker_exit and result.stderr == ""
    if lane == "corpus":
        assert result.stdout.strip() == payload
    else:
        assert json.loads(result.stdout)["private"] == "SECRET"
    records = events(state)
    assert [e["phase"] for e in records] == [
        "dispatch_start",
        "import_wait_start",
        "import_acquired",
        "work_start",
        "work_finish",
        "dispatch_finish",
    ]
    assert len({e["run_id"] for e in records}) == 1
    assert {e["lane"] for e in records} == {lane}
    assert [e["monotonic_ns"] for e in records] == sorted(e["monotonic_ns"] for e in records)
    assert records[-1]["exit_code"] == worker_exit
    assert "SECRET" not in json.dumps(records)


@LINUX
@pytest.mark.parametrize(
    "name", ["server-eis-priority.sh", "server-eis-documents.sh", "server-eis-223-refresh.sh"]
)
def test_idle_and_probe_error_have_no_import_phases(wrappers, name):
    _, state, browser, _ = wrappers
    idle = run_wrapper(
        wrappers, name, STUB_PROBE_JSON='{"status":"IDLE","law":null,"source_requests":0}'
    )
    assert idle.returncode == 0 and json.loads(idle.stdout)["status"] == "IDLE"
    assert [e["phase"] for e in events(state)] == ["dispatch_start", "dispatch_finish"]
    assert events(state)[-1]["result"] == "IDLE"
    failed = run_wrapper(wrappers, name, STUB_PROBE_FAIL="1")
    assert failed.returncode == 69
    assert [e["phase"] for e in events(state)[-2:]] == ["dispatch_start", "dispatch_finish"]
    assert not list(browser.iterdir())


@LINUX
@pytest.mark.parametrize(
    "name,args",
    [
        ("server-eis-corpus.sh", ("run",)),
        ("server-eis-priority.sh", ()),
        ("server-eis-documents.sh", ()),
        ("server-eis-223-refresh.sh", ()),
    ],
)
def test_logger_failure_does_not_change_status_or_stdout(wrappers, name, args):
    scripts, _, _, _ = wrappers
    (scripts / "server-eis-metrics.py").write_text('raise RuntimeError("LOGGER_SECRET")\n')
    result = run_wrapper(wrappers, name, args=args, STUB_WORKER_EXIT="7")
    assert result.returncode == 7 and result.stderr == ""
    assert json.loads(result.stdout)["attempted"] == 1


@LINUX
@pytest.mark.parametrize("name", ["server-eis-priority.sh", "server-eis-documents.sh"])
def test_foreground_waiter_regression_and_async_term_cleanup(wrappers, name, tmp_path):
    import fcntl

    scripts, state, browser, env = wrappers
    lockfile = state / "eis-import.lock"
    with lockfile.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Preserve the original foreground flock shape to demonstrate delayed trap execution.
        legacy = subprocess.Popen(
            [
                "bash",
                "-c",
                'trap "exit 143" TERM; exec 9>"$1"; flock -w 2 9',
                "legacy",
                str(lockfile),
            ]
        )
        try:
            time.sleep(0.15)
            legacy.send_signal(signal.SIGTERM)
            time.sleep(0.15)
            assert legacy.poll() is None
        finally:
            legacy.wait(timeout=3)
        assert legacy.returncode == 143
        process = subprocess.Popen(
            ["bash", str(scripts / name)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        marker = browser / "eis-priority.request"
        try:
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert marker.exists()
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=2)
            assert process.returncode == 143 and stdout == stderr == "" and not marker.exists()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)
    assert run_wrapper(wrappers, name).returncode == 0
    records = events(state)
    interrupted = [e for e in records if e.get("signal") == "TERM"]
    assert len(interrupted) == 1 and interrupted[0]["result"] == "INTERRUPTED"
    assert interrupted[0]["exit_code"] == 143


@LINUX
@pytest.mark.parametrize(
    "name,args",
    [
        ("server-eis-corpus.sh", ("run",)),
        ("server-eis-priority.sh", ()),
        ("server-eis-documents.sh", ()),
        ("server-eis-223-refresh.sh", ()),
    ],
)
def test_import_busy_or_timeout_is_observed_without_worker_or_foreign_cleanup(wrappers, name, args):
    import fcntl

    _, state, browser, _ = wrappers
    with (state / "eis-import.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_wrapper(wrappers, name, args=args)
    assert result.returncode == 75
    assert json.loads(result.stdout)["reason"] == "SERVER_IMPORT_BUSY"
    records = events(state)
    assert [r["phase"] for r in records] == [
        "dispatch_start",
        "import_wait_start",
        "dispatch_finish",
    ]
    assert records[-1]["result"] == ("BUSY" if args else "TIMEOUT")
    assert not list(browser.iterdir())


@LINUX
@pytest.mark.parametrize(
    "name,lockname",
    [
        ("server-eis-priority.sh", "eis-priority.lock"),
        ("server-eis-documents.sh", "eis-document-dispatch.lock"),
        ("server-eis-223-refresh.sh", "eis-223-dispatch.lock"),
    ],
)
def test_dispatch_busy_preserves_foreign_marker(wrappers, name, lockname):
    import fcntl

    _, state, browser, _ = wrappers
    marker = browser / ("eis-223-refresh.request" if "223" in name else "eis-priority.request")
    marker.write_text("foreign owner")
    with (state / lockname).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_wrapper(wrappers, name)
    assert result.returncode == 75 and marker.read_text() == "foreign owner"
    assert [e["phase"] for e in events(state)] == ["dispatch_start", "dispatch_finish"]
    assert events(state)[-1]["result"] == "BUSY"


@LINUX
@pytest.mark.parametrize(
    "filename",
    ["local-eis-supplier.jsonl", "local-eis-supplier.lock", "local-eis-supplier.previous.jsonl"],
)
def test_fifo_logger_path_cannot_block_worker(logger, tmp_path, filename):
    import sys

    directory = tmp_path / "metrics"
    directory.mkdir()
    os.mkfifo(directory / filename)
    source = Path(logger.__file__).read_text().replace(str(logger.DIRECTORY), str(directory))
    script = tmp_path / "logger.py"
    script.write_text(source)
    result = subprocess.run(
        [sys.executable, str(script), *arguments()],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    assert result.returncode == 0 and result.stdout == result.stderr == ""


@LINUX
def test_preexisting_oversized_retention_is_rebounded(logger, tmp_path, monkeypatch):
    directory = tmp_path / "metrics"
    directory.mkdir()
    monkeypatch.setattr(logger, "DIRECTORY", directory)
    monkeypatch.setattr(logger, "MAX_BYTES", 1500)
    for filename in ("local-eis-supplier.jsonl", "local-eis-supplier.previous.jsonl"):
        (directory / filename).write_bytes(b"x" * 1501)
    assert logger.main(arguments()) == 0
    assert all(p.stat().st_size <= 1500 for p in directory.glob("*.jsonl"))


@LINUX
@pytest.mark.parametrize(
    "name,args",
    [
        ("server-eis-corpus.sh", ("run",)),
        ("server-eis-priority.sh", ()),
        ("server-eis-documents.sh", ()),
        ("server-eis-223-refresh.sh", ()),
    ],
)
def test_missing_helper_preserves_original_worker_contract(wrappers, name, args):
    scripts, _, _, _ = wrappers
    (scripts / "server-eis-metrics.sh").unlink()
    result = run_wrapper(wrappers, name, args=args, STUB_WORKER_EXIT="7")
    assert result.returncode == 7 and result.stderr == ""
    assert json.loads(result.stdout)["attempted"] == 1


@LINUX
@pytest.mark.parametrize("status,expected", [("BLOCKED", "ERROR"), ("OTHER", "UNKNOWN")])
def test_priority_nonready_is_not_falsely_idle(wrappers, status, expected):
    _, state, _, _ = wrappers
    result = run_wrapper(
        wrappers, "server-eis-priority.sh", STUB_PROBE_JSON=json.dumps({"status": status})
    )
    assert result.returncode == 0 and json.loads(result.stdout)["status"] == status
    assert events(state)[-1]["result"] == expected


@LINUX
def test_missing_host_python_during_metrics_init_does_not_abort_caller(tmp_path):
    script = ROOT / "scripts/server-eis-metrics.sh"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; python3() { return 91; }; source "$1"; '
            "eis_metrics_init corpus run; eis_metric dispatch_finish ERROR 7; printf preserved",
            "test",
            str(script),
        ],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    assert result.returncode == 0 and result.stdout == "preserved" and result.stderr == ""
