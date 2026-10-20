"""Recovery CLI has bounded planned scope, lazy transport and safe failures."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from procurement import eis_corpus_cli as cli


@pytest.fixture
def runtime(monkeypatch):
    disposed = []
    engine = SimpleNamespace(dispose=lambda: disposed.append(True))
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.delenv("EIS_GETDOCS_IP_TOKEN", raising=False)
    monkeypatch.setattr(cli, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(cli, "PostgresStorage", lambda e: object())
    return disposed


def args(action, *extra):
    return [action, "--company-id", "tenant-a", "--actor-id", "test", *extra]


def test_readonly_cli_needs_no_token_and_no_transport(runtime, monkeypatch, capsys):
    calls = []

    def read(journal, **kw):
        calls.append(kw)
        return SimpleNamespace(model_dump_json=lambda: '{"eligible_count":9,"coverage":"UNKNOWN"}')

    monkeypatch.setattr(cli, "read_attachment_recovery_plan", read)
    assert cli.main(args("attachment-recovery-status")) == 0
    assert json.loads(capsys.readouterr().out)["eligible_count"] == 9
    assert calls[0]["limit"] == 3 and calls[0]["now"].utcoffset() is not None
    assert runtime == [True]


@pytest.mark.parametrize(
    "extra",
    (
        ("--max-windows", "4"),
        ("--max-windows", "0"),
        ("--max-seconds", "601"),
        ("--max-seconds", "0"),
        ("--regions", "all"),
        ("--from-day", "2026-01-01"),
        ("--base-scope-sha256", "a" * 64),
    ),
)
def test_recovery_rejects_over_budget_or_scope_extension(extra, runtime):
    with pytest.raises(SystemExit) as error:
        cli.main(args("attachment-recovery", *extra))
    assert error.value.code == 2 and runtime == []


def test_write_cli_requires_token_before_transport_and_disposes(runtime):
    with pytest.raises(SystemExit) as error:
        cli.main(args("attachment-recovery"))
    assert error.value.code == 2 and runtime == [True]


@pytest.mark.parametrize(("status", "code"), (("FINISHED", 0), ("BLOCKED", 2)))
def test_write_cli_keeps_unknown_and_maps_blocked_exit(runtime, monkeypatch, capsys, status, code):
    monkeypatch.setenv("EIS_GETDOCS_IP_TOKEN", "synthetic-token-12345")

    async def run(*a, **kw):
        assert kw["max_windows"] == 3 and kw["max_seconds"] == 600
        return SimpleNamespace(
            status=status,
            model_dump_json=lambda: json.dumps({"status": status, "coverage": "UNKNOWN"}),
        )

    monkeypatch.setattr(cli, "_attachment_recovery_pass", run)
    assert cli.main(args("attachment-recovery")) == code
    assert json.loads(capsys.readouterr().out)["coverage"] == "UNKNOWN" and runtime == [True]


def test_pass_reuses_one_transport_and_closes_on_failure(monkeypatch):
    visits = []
    transport = object()

    @asynccontextmanager
    async def session():
        visits.append("entered")
        try:
            yield transport
        finally:
            visits.append("closed")

    runner = AsyncMock(side_effect=ValueError("synthetic"))
    monkeypatch.setattr(cli, "eis_browser_transport", session)
    monkeypatch.setattr(cli, "run_attachment_recovery", runner)
    with pytest.raises(ValueError):
        asyncio.run(
            cli._attachment_recovery_pass(
                object(),
                "synthetic-token",
                now=datetime.now(UTC),
                max_windows=3,
                max_seconds=600,
                max_database_bytes=100,
                min_free_bytes=40,
            )
        )
    assert visits == ["entered", "closed"] and runner.call_args.kwargs["transport"] is transport


@pytest.fixture
def leased_wrapper(tmp_path):
    from test_eis_source_leases_shell import regional_wrapper

    wrapper, marker, log, env = regional_wrapper.__wrapped__(tmp_path)
    root = Path(__file__).parents[1]
    source = (root / "scripts/server-eis-attachment-recovery.sh").read_text()
    source = source.replace("/home/syurai/vibe-seller-state", str(tmp_path / "state"))
    source = source.replace("/home/syurai/vibe-seller", str(tmp_path / "workspace"))
    source = source.replace("/var/lib/eis-browser/eis-priority.request", str(marker))
    source = source.replace("flock -w 300 8", "flock -w 1 8")
    source = source.replace("flock -w 300 9", "flock -w 1 9")
    wrapper.write_text(source)
    return wrapper, marker, log, env


@pytest.mark.skipif(os.name == "nt", reason="Linux flock gate")
def test_wrapper_fixed_bounds_and_cleanup_after_worker_failure(leased_wrapper):
    wrapper, marker, log, env = leased_wrapper
    import subprocess

    result = subprocess.run(
        ["bash", str(wrapper), "run", "3"],
        env={**env, "STUB_WORKER_EXIT": "2"},
        text=True,
        capture_output=True,
        timeout=8,
    )
    assert result.returncode == 2 and not marker.exists()
    assert "--max-windows 3 --max-seconds 600" in log.read_text()
    log.unlink()
    rejected = subprocess.run(
        ["bash", str(wrapper), "run", "4"], env=env, text=True, capture_output=True, timeout=8
    )
    assert rejected.returncode == 64 and not log.exists() and not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="Linux flock gate")
def test_wrapper_busy_priority_preserves_other_owner_marker(leased_wrapper, tmp_path):
    import subprocess

    from test_eis_source_leases_shell import hold_lock, wait_for

    wrapper, marker, log, env = leased_wrapper
    ready = tmp_path / "ready"
    lock = hold_lock(tmp_path / "state" / "eis-priority.lock", ready)
    try:
        wait_for(ready)
        marker.touch()
        result = subprocess.run(
            ["bash", str(wrapper), "run", "2"], env=env, text=True, capture_output=True, timeout=8
        )
        assert result.returncode == 75 and marker.exists() and not log.exists()
        assert json.loads(result.stdout)["reason"] == "PRIORITY_WORKER_BUSY"
    finally:
        lock.terminate()
        lock.wait(timeout=3)


@pytest.mark.skipif(os.name == "nt", reason="Linux signals/flock gate")
@pytest.mark.parametrize("after_publication", (0, 0.2))
def test_wrapper_term_after_marker_and_during_import_wait_reaps_leases(
    leased_wrapper, tmp_path, after_publication
):
    import signal
    import subprocess
    import time

    from test_eis_source_leases_shell import hold_lock, wait_for

    wrapper, marker, log, env = leased_wrapper
    ready = tmp_path / "import.ready"
    lock = hold_lock(tmp_path / "state" / "eis-import.lock", ready)
    worker = None
    try:
        wait_for(ready)
        worker = subprocess.Popen(
            ["bash", str(wrapper), "run", "2"],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        wait_for(marker)
        time.sleep(after_publication)
        worker.send_signal(signal.SIGTERM)
        worker.communicate(timeout=4)
        assert worker.returncode == 143 and not marker.exists()
        assert " compose " not in f" {log.read_text()} "
        lock.terminate()
        lock.wait(timeout=3)
        followup = subprocess.run(
            ["bash", str(wrapper), "run", "1"], env=env, text=True, capture_output=True, timeout=8
        )
        assert followup.returncode == 0 and not marker.exists()
    finally:
        if lock.poll() is None:
            lock.terminate()
            lock.wait(timeout=3)
        if worker is not None and worker.poll() is None:
            worker.terminate()
            worker.wait(timeout=3)
