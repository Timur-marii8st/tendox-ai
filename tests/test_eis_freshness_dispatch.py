"""A read-only probe must include foreground work and fail closed on resource stops."""

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from procurement import eis_freshness_dispatch_cli as dispatch
from procurement.sources.eis_freshness import EisFreshnessScope

NOW = datetime(2026, 10, 3, 10, 15, tzinfo=UTC)
SCOPE = EisFreshnessScope(("50",))


@pytest.mark.parametrize("regional,new_wave", [(2, False), (0, True)])
def test_joint_probe_blocks_history_for_223_demand(monkeypatch, regional, new_wave):
    monkeypatch.setattr(dispatch, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "read_due_freshness", lambda *a, **k: ())
    monkeypatch.setattr(dispatch, "pending_refresh_targets", lambda *a, **k: ())
    monkeypatch.setattr(dispatch, "_regional_demand", lambda *a, **k: (regional, new_wave))
    result = dispatch.probe_dispatch(None, "tenant", SCOPE, now=NOW, include_regional=True)
    assert result.status == "READY" and result.regional_due == regional
    assert result.regional_new_wave_due == new_wave and result.attempted == 0


def test_joint_probe_unknown_regional_state_cannot_admit_history(monkeypatch):
    monkeypatch.setattr(dispatch, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "read_due_freshness", lambda *a, **k: ())
    monkeypatch.setattr(dispatch, "pending_refresh_targets", lambda *a, **k: ())

    def unknown(*a, **k):
        raise ValueError("OFFICIAL_REGION_CATALOG_MISSING")

    monkeypatch.setattr(dispatch, "_regional_demand", unknown)
    result = dispatch.probe_dispatch(None, "tenant", SCOPE, now=NOW, include_regional=True)
    assert result.status == "BLOCKED" and result.reason == "REGIONAL_DEMAND_UNAVAILABLE"


@pytest.mark.parametrize(
    "baseline,foreground,status",
    [(0, 0, "IDLE"), (1, 0, "READY"), (0, 1, "READY"), (1, 1, "READY")],
)
def test_probe_checks_baseline_and_foreground_without_planning(
    monkeypatch, baseline, foreground, status
):
    monkeypatch.setattr(dispatch, "resource_gate", lambda *a, **k: None)
    read = Mock(return_value=tuple(range(baseline)))
    requests = Mock(return_value=tuple(range(foreground)))
    monkeypatch.setattr(dispatch, "read_due_freshness", read)
    monkeypatch.setattr(dispatch, "pending_refresh_targets", requests)
    report = dispatch.probe_dispatch(None, "tenant", SCOPE, now=NOW)
    assert report.status == status
    assert (report.baseline_due, report.foreground_due, report.attempted) == (
        baseline,
        foreground,
        0,
    )
    assert report.coverage == report.freshness == "UNKNOWN"
    assert requests.call_args.kwargs == {"now": NOW, "plan": False}
    assert read.call_args.args[0].company_id == "tenant"
    assert read.call_args.kwargs == {"now": NOW, "limit": 24}


def test_budget_stop_does_not_inspect_or_plan(monkeypatch):
    monkeypatch.setattr(dispatch, "resource_gate", lambda *a, **k: "DATABASE_BUDGET_REACHED")
    read = Mock(side_effect=AssertionError("Must not inspect queues"))
    monkeypatch.setattr(dispatch, "read_due_freshness", read)
    monkeypatch.setattr(dispatch, "pending_refresh_targets", read)
    report = dispatch.probe_dispatch(None, "tenant", SCOPE, now=NOW)
    assert report.status == "BLOCKED" and report.reason == "DATABASE_BUDGET_REACHED"
    assert report.attempted == 0
    read.assert_not_called()


def test_invalid_time_never_gets_as_far_as_resource_gate(monkeypatch):
    gate = Mock()
    monkeypatch.setattr(dispatch, "resource_gate", gate)
    with pytest.raises(ValueError, match="NOW_TIMEZONE_MISSING"):
        dispatch.probe_dispatch(None, "tenant", SCOPE, now=NOW.replace(tzinfo=None))
    gate.assert_not_called()


def test_cli_failure_reports_no_connection_secret(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example/db")
    monkeypatch.setattr(dispatch, "create_engine", Mock(side_effect=RuntimeError("secret")))
    assert dispatch.main(["--company-id", "tenant", "--regions", "50"]) == 2
    output = capsys.readouterr().out
    assert "FRESHNESS_PROBE_UNAVAILABLE" in output and "secret" not in output


@pytest.mark.skipif(os.name == "nt", reason="Operational script runs on Linux VPS")
@pytest.mark.parametrize("status,expected", [("IDLE", 0), ("BLOCKED", 69), ("READY", 0)])
def test_real_scheduler_script_only_hands_off_when_ready(tmp_path, status, expected):
    script = Path("scripts/server-eis-priority.sh").read_bytes()
    script = script.replace(b"/home/syurai/vibe-seller-state", str(tmp_path).encode()).replace(
        b"/home/syurai/vibe-seller", str(tmp_path).encode()
    )
    helper = tmp_path / "priority.sh"
    helper.write_bytes(script)
    helper.chmod(0o700)
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls"
    marker = tmp_path / "marker"
    marker.write_text("foreign owner")
    # Model Docker/lock boundaries while executing the actual Bash control flow.
    sudo = binary / "sudo"
    sudo.write_text(
        """#!/usr/bin/env python3
import os,sys,json
from pathlib import Path
a=' '.join(sys.argv[1:])
with open(os.environ['LOG'],'a') as f: f.write(a+'\\n')
if 'eis_freshness_dispatch_cli' in a:
 print(json.dumps({'status':os.environ['STATUS']}))
 sys.exit(2 if os.environ['STATUS']=='BLOCKED' else 0)
if 'inspect' in a: print('healthy')
if '.touch()' in a: Path(os.environ['MARKER']).write_text('owned')
if '.unlink(' in a: Path(os.environ['MARKER']).unlink(missing_ok=True)
"""
    )
    sudo.chmod(0o700)
    flock = binary / "flock"
    flock.write_text('#!/bin/sh\necho "flock $*" >> "$LOG"\n')
    flock.chmod(0o700)
    result = subprocess.run(
        [str(helper)],
        env={
            **os.environ,
            "PATH": f"{binary}:{os.environ['PATH']}",
            "LOG": str(log),
            "MARKER": str(marker),
            "STATUS": status,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == expected, result.stderr
    calls = log.read_text()
    if status == "READY":
        assert "flock -w 300 9" in calls and "eis_corpus_cli fresh" in calls
        assert not marker.exists()
    else:
        assert marker.read_text() == "foreign owner"
        assert "flock -w 300 9" not in calls and "eis_corpus_cli fresh" not in calls
        assert "touch" not in calls and "unlink" not in calls and "inspect" not in calls
