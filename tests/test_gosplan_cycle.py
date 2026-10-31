"""Scheduler admits only validated discovery hints to the guarded host wrapper."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/server-gosplan-cycle.sh"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("eligible44", ["--law 44 --number " + "1" * 19]),
        ("eligible223", ["--law 223 --number " + "2" * 11]),
        ("invalid_number", []),
        ("unknown", []),
    ],
)
def test_scheduler_only_hands_validated_hints_to_guard(tmp_path, mode, expected):
    repo, state, commands = (tmp_path / x for x in ("repo", "state", "bin"))
    for path in (repo, state, commands):
        path.mkdir()
    source = SCRIPT.read_text().replace(
        "repo=/home/syurai/vibe-seller", f"repo={repo}"
    ).replace("state=/home/syurai/vibe-seller-state/gosplan", f"state={state}")
    script = tmp_path / "cycle.sh"
    script.write_text(source)
    sudo = commands / "sudo"
    sudo.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "law=sys.argv[-1]; mode=os.environ['SCENARIO']\n"
        "number=('1'*19 if law=='44' else '2'*11)\n"
        "eligible=mode=='eligible'+law\n"
        "if mode=='invalid_number': number='1'*19+';bad'; eligible=True\n"
        "status='UNKNOWN' if mode=='unknown' else 'STOPPED'\n"
        "print(json.dumps(dict(status=status,law=law,candidate=number,recovery_eligible=eligible)))\n"
    )
    sudo.chmod(0o700)
    recovery = state / "server-gosplan-recovery.sh"
    recovery.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALLS"\nexit 1\n')
    recovery.chmod(0o700)
    calls = tmp_path / "calls"
    env = {**os.environ, "PATH": f"{commands}:{os.environ['PATH']}", "SCENARIO": mode,
           "CALLS": str(calls)}
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert (calls.read_text().splitlines() if calls.exists() else []) == expected
    output = [json.loads(line) for line in result.stdout.splitlines()]
    if expected:
        assert sum(item.get("reason") == "RECOVERY_NOT_SYNCED" for item in output) == 1

