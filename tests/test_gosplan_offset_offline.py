"""Offline split plans must use the same live cycle inode and exact payload."""

import fcntl
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from procurement.sources.gosplan_discovery import parse_page
from procurement.sources.gosplan_queue import GosplanQueue, QueueError, Scope

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "offset_resolver", ROOT / "scripts/server-gosplan-resolve-legacy-hold.py"
)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)
NOW = datetime(2026, 10, 29, tzinfo=UTC)


def fixture(tmp_path):
    q = GosplanQueue(tmp_path / "queue.sqlite")
    start = NOW - timedelta(days=1)
    scope = Scope(subject.COMPANY, "44", start, NOW, 1000, 100)
    raw = json.dumps(
        [
            {"purchase_number": f"{n:019}", "purchase_type": "epNotificationEF2020"}
            for n in range(100)
        ]
    ).encode()
    oid = q.record(scope, parse_page(raw, "44", NOW, 100), NOW)
    cursor = [NOW.isoformat(), start.isoformat(), NOW.isoformat(), 1100]
    with q.conn:
        q.conn.execute(
            "INSERT INTO scan_cursors VALUES (?,?,?,?,?,?)", (subject.COMPANY, "44", *cursor)
        )
        q.conn.execute(
            "INSERT INTO provider_holds VALUES (?,?,?)", (subject.COMPANY, "HTTP_422", None)
        )
    plan = dict(
        company_id=subject.COMPANY,
        authorization="USER_STANDING_AUTHORIZATION",
        operation="prepare",
        law="44",
        actor_id="owner",
        prepared_at=NOW.isoformat(),
        expected_cursor=cursor,
        source_observation_id=oid,
        coverage="UNKNOWN",
        original_cause="UNKNOWN",
        prepared_plan_id=None,
    )
    return q, plan


def test_prepare_activate_replay_and_changed_plan_rejected(tmp_path):
    q, plan = fixture(tmp_path)
    recovery_id = subject.resolve_offset_plan(q, plan, "prepare")
    assert subject.resolve_offset_plan(q, plan, "prepare") == recovery_id
    with pytest.raises(QueueError, match="OFFSET_PLAN_CHANGED"):
        subject.resolve_offset_plan(
            q, {**plan, "operation": "activate", "prepared_plan_id": "a" * 64}, "activate"
        )
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("HTTP_422",)
    activate = {**plan, "operation": "activate", "prepared_plan_id": recovery_id}
    assert subject.resolve_offset_plan(q, activate, "activate") == recovery_id
    assert subject.resolve_offset_plan(q, activate, "activate") == recovery_id
    assert q.conn.execute("SELECT reason FROM provider_holds").fetchone() == ("OFFSET_RECOVERY",)
    q.close()


def test_exact_digest_and_lock_are_required(tmp_path, monkeypatch, capsys):
    q, plan = fixture(tmp_path)
    q.close()
    lock = tmp_path / "cycle.lock"
    lock.touch()
    import_lock = tmp_path / "eis-import.lock"
    import_lock.touch()
    planfile = tmp_path / "offset-recovery-plan.json"
    data = json.dumps(plan).encode()
    planfile.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    identity = f"{lock.stat().st_dev}:{lock.stat().st_ino}"
    import_identity = f"{import_lock.stat().st_dev}:{import_lock.stat().st_ino}"
    monkeypatch.setattr(subject, "CYCLE_LOCK", lock)
    monkeypatch.setattr(subject, "IMPORT_LOCK", import_lock)
    monkeypatch.setattr(subject, "OFFSET_PLAN", planfile)
    monkeypatch.setattr(subject, "QUEUE", tmp_path / "queue.sqlite")
    monkeypatch.setattr(subject, "release_guard_active", lambda: False)
    monkeypatch.setattr(
        sys, "argv", ["resolver", "--offset-prepare-sha256", digest, "--lock-identity", identity,
                      "--import-lock-identity", import_identity]
    )
    with lock.open("r+") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(QueueError, match="CYCLE_LEASE_BUSY"):
            subject.main()
    with import_lock.open("r+") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(QueueError, match="IMPORT_LEASE_BUSY"):
            subject.main()
    planfile.write_bytes(data + b" ")
    with pytest.raises(QueueError, match="RESOLUTION_FILE_CHANGED"):
        subject.main()
    planfile.write_bytes(data)
    subject.main()
    assert json.loads(capsys.readouterr().out)["source_requests"] == 0


def test_worker_holds_same_inode_after_launcher_sigkill(tmp_path):
    lock = tmp_path / "cycle.lock"
    lock.touch()
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    worker = (
        'import fcntl,os,sys,time; f=open(sys.argv[1],"r+"); '
        'fcntl.flock(f,fcntl.LOCK_EX); open(sys.argv[2],"w").close(); '
        'exec("while not os.path.exists(sys.argv[3]): time.sleep(0.02)")'
    )
    launcher = (
        "import subprocess,sys,time; "
        'subprocess.Popen([sys.executable,"-c",sys.argv[1],*sys.argv[2:]]); '
        "time.sleep(30)"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", launcher, worker, str(lock), str(ready), str(release)]
    )
    try:
        limit = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < limit:
            time.sleep(0.02)
        assert ready.exists()
        parent.send_signal(signal.SIGKILL)
        parent.wait(timeout=5)
        with lock.open("r+") as contender, pytest.raises(BlockingIOError):
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release.touch()
        limit = time.monotonic() + 5
        while time.monotonic() < limit:
            with lock.open("r+") as contender:
                try:
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.02)
        else:
            pytest.fail("worker did not release lock")
    finally:
        release.touch()
        if parent.poll() is None:
            parent.kill()
            parent.wait()


def test_offline_launcher_only_mounts_plan_and_cycle_inode(tmp_path):
    repo, state, commands = (tmp_path / x for x in ("repo", "state", "bin"))
    for path in (repo, state, commands):
        path.mkdir()
    (state / "cycle.lock").touch()
    import_lock = tmp_path / "eis-import.lock"
    import_lock.touch()
    (state / "offset-recovery-plan.json").write_text("{}")
    source = (
        (ROOT / "scripts/server-gosplan-cycle.sh")
        .read_text()
        .replace("repo=/home/syurai/vibe-seller", f"repo={repo}")
        .replace("state=/home/syurai/vibe-seller-state/gosplan", f"state={state}")
        .replace("/home/syurai/vibe-seller-state/eis-import.lock", str(import_lock))
    )
    script = tmp_path / "cycle.sh"
    script.write_text(source)
    sudo = commands / "sudo"
    sudo.write_text("#!/usr/bin/env python3\nimport json,sys\n"
                    "print(json.dumps({'args':sys.argv[1:],'override':sys.stdin.read()}))\n")
    sudo.chmod(0o700)
    result = subprocess.run(
        ["bash", str(script), "--offline-offset-prepare", "a" * 64],
        env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=True,
    )
    output = json.loads(result.stdout)
    args = output['args']
    assert output['override'] == 'services:\n  worker:\n    network_mode: none\n'
    assert f"{state}/cycle.lock:/run/gosplan/cycle.lock" in args
    assert f"{import_lock}:/run/gosplan/eis-import.lock" in args
    assert f"{state}/offset-recovery-plan.json:/run/gosplan/offset-recovery-plan.json:ro" in args
    assert "--offset-prepare-sha256" in args and "a" * 64 in args
    assert "/app/gosplan/server-gosplan-resolve-legacy-hold.py" in args
    assert not any("/run/secrets/gosplan-key" in arg for arg in args)
    assert "--lock-identity" in args
    bad = subprocess.run(
        ["bash", str(script), "--offline-offset-prepare", "bad"],
        env={**os.environ, "PATH": f"{commands}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
    )
    assert bad.returncode != 0


@pytest.mark.parametrize('operation', ['page', 'null'])
def test_exact_offline_reconcile_retained_split_page(tmp_path, monkeypatch, operation):
    import httpx

    from procurement.sources.gosplan_scan import scan_page

    q, prepared = fixture(tmp_path)
    recovery_id = subject.resolve_offset_plan(q, prepared, 'prepare')
    subject.resolve_offset_plan(
        q, {**prepared, 'operation': 'activate', 'prepared_plan_id': recovery_id}, 'activate'
    )
    rows = ([{'purchase_number': '0000000000000000150', 'purchase_type': None}]
            if operation == 'null' else [])
    original = q.record

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('simulated interruption')

    with monkeypatch.context() as m, httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=rows))
    ) as client:
        if operation == 'page':
            m.setattr(q, 'record', crash)
            with pytest.raises(RuntimeError, match='interruption'):
                scan_page(client, 'key', q, subject.COMPANY, '44', NOW)
            oid = q.conn.execute('SELECT id FROM observations ORDER BY rowid DESC').fetchone()[0]
            table = 'observations'
        else:
            assert scan_page(client, 'key', q, subject.COMPANY, '44', NOW).reason == 'TYPE_INVALID'
            oid = q.conn.execute('SELECT observation_id FROM provider_hold_evidence').fetchone()[0]
            table = 'rejected_pages'
    sha = q.conn.execute(f'SELECT response_sha FROM {table} WHERE id=?', (oid,)).fetchone()[0]
    plan = {'company_id': subject.COMPANY, 'authorization': 'USER_STANDING_AUTHORIZATION',
            'operation': operation, 'law': '44', 'actor_id': 'owner',
            'resolved_at': NOW.isoformat(),
            'plan_id': recovery_id, 'observation_id': oid, 'response_sha256': sha,
            'coverage': 'UNKNOWN'}
    with pytest.raises(QueueError, match='SOURCE_CHANGED'):
        subject.resolve_offset_reconciliation(q, {**plan, 'response_sha256': 'a' * 64}, operation)
    assert subject.resolve_offset_reconciliation(q, plan, operation)
    assert subject.resolve_offset_reconciliation(q, plan, operation)
    assert q.conn.execute('SELECT reason FROM provider_holds').fetchone() == ('OFFSET_RECOVERY',)
    q.close()


def test_cycle_routes_active_223_without_other_source_call(tmp_path, monkeypatch, capsys):
    discovery_spec = importlib.util.spec_from_file_location(
        'offset_discovery', ROOT / 'scripts/server-gosplan-discovery.py'
    )
    discovery = importlib.util.module_from_spec(discovery_spec)
    discovery_spec.loader.exec_module(discovery)
    monkeypatch.setattr(discovery, 'run', lambda law: {
        'status': 'UNKNOWN', 'reason': 'OFFSET_RECOVERY_NEXT_223', 'candidate': None,
    })
    monkeypatch.setattr(sys, 'argv', ['discovery', '--law', '44'])
    assert discovery.main() == 0
    capsys.readouterr()
    monkeypatch.setattr(sys, 'argv', ['discovery', '--law', '223'])
    assert discovery.main() == 1
    capsys.readouterr()

    repo, state, commands = (tmp_path / x for x in ('repo', 'state', 'bin'))
    for path in (repo, state, commands):
        path.mkdir()
    (state / 'cycle.lock').touch()
    script = tmp_path / 'cycle.sh'
    script.write_text((ROOT / 'scripts/server-gosplan-cycle.sh').read_text()
                      .replace('repo=/home/syurai/vibe-seller', f'repo={repo}')
                      .replace('state=/home/syurai/vibe-seller-state/gosplan', f'state={state}'))
    calls = tmp_path / 'calls'
    sudo = commands / 'sudo'
    sudo.write_text('#!/usr/bin/env python3\nimport json,sys\n'
                    f'f=open({str(calls)!r},"a"); a=sys.argv; law=a[a.index("--law")+1]; '
                    'f.write(law+"\\n"); f.close(); '
                    'print(json.dumps({"status":"UNKNOWN","candidate":None, '
                    '"reason":"OFFSET_RECOVERY_NEXT_223" if law=="44" '
                    'else "OFFSET_RECOVERY"}))\n')
    sudo.chmod(0o700)
    result = subprocess.run(['bash', str(script)], env={**os.environ,
        'PATH': f'{commands}:{os.environ["PATH"]}'}, text=True, capture_output=True, check=True)
    assert calls.read_text().splitlines() == ['44', '223']
    assert len(result.stdout.splitlines()) == 2
