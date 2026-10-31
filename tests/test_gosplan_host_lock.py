"""The official source lease survives a killed launcher, including its sudo child."""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/server-gosplan-recovery.sh"


@pytest.mark.parametrize("kill_priority_child", [False, True])
def test_import_lock_survives_launcher_sigkill(tmp_path, kill_priority_child):
    import_lock = tmp_path / "import.lock"
    import_lock.touch()
    script = tmp_path / "recovery.sh"
    source = (
        SCRIPT.read_text()
        .replace(
            "/home/syurai/vibe-seller-state/eis-priority.lock", str(tmp_path / "priority.lock")
        )
        .replace("/home/syurai/vibe-seller-state/eis-import.lock", str(import_lock))
        .replace("repo=/home/syurai/vibe-seller", f"repo={tmp_path}")
    )
    script.write_text(source)
    script.chmod(0o700)
    sudo = tmp_path / "sudo"
    sudo.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"docker inspect"* ]]; then echo healthy; exit 0; fi\n'
        'if [[ "$*" == *"docker exec"* ]]; then exit 0; fi\n'
        'if [[ "$*" == *"docker compose"* ]]; then '
        "flock \"$PROOF_LOCK\" bash -c 'touch \"$PROOF_STARTED\"; sleep 3'; exit 0; fi\n"
        "exit 1\n"
    )
    sudo.chmod(0o700)
    started = tmp_path / "started"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "PROOF_STARTED": str(started),
        "PROOF_LOCK": str(import_lock),
    }
    process = subprocess.Popen(
        [str(script), "--law", "44", "--number", "0" * 19],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists()
        target = process.pid
        if kill_priority_child:
            children = Path(f"/proc/{process.pid}/task/{process.pid}/children").read_text().split()
            assert len(children) == 1
            target = int(children[0])
        os.kill(target, signal.SIGKILL)
        process.wait(timeout=3)
        # The nested flock, not the now-dead launcher, must still own this lease.
        assert (
            subprocess.run(["flock", "-n", str(import_lock), "true"], check=False).returncode != 0
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if (
                subprocess.run(["flock", "-n", str(import_lock), "true"], check=False).returncode
                == 0
            ):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("import lock was not released after child completed")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
