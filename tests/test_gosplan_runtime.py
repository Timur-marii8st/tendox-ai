import asyncio
import runpy
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/server-gosplan-recovery.py"


def test_recovery_requires_host_lease_before_queue_or_source(monkeypatch):
    monkeypatch.delenv("GOSPLAN_IMPORT_LEASE_HELD", raising=False)
    code = runpy.run_path(str(SCRIPT))
    code["run"].__globals__["release_guard_active"] = lambda: False
    result = asyncio.run(code["run"]("44", "0122100003226000063"))
    assert result == {"status": "UNKNOWN", "reason": "IMPORT_LEASE_REQUIRED"}


def test_unknown_priority_blocks_before_claim_or_source(tmp_path, monkeypatch):
    code = runpy.run_path(str(SCRIPT))
    code["run"].__globals__["release_guard_active"] = lambda: False
    namespace = code["run"].__globals__
    queue = tmp_path / "queue.sqlite"
    queue.touch()
    namespace["QUEUE"] = queue
    namespace["PostgresStorage"] = SimpleNamespace(from_url=lambda *a, **kw: object())
    namespace["urgent44_status"] = lambda *a: "UNKNOWN"
    namespace["joint_mandatory_status"] = lambda *a: "IDLE"
    monkeypatch.setenv("GOSPLAN_IMPORT_LEASE_HELD", "1")
    monkeypatch.setenv("DATABASE_URL", "not-used")
    result = asyncio.run(code["run"]("44", "0122100003226000063"))
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "MANDATORY_WORK_NOT_IDLE"
    assert queue.stat().st_size == 0


def test_trusted_demand_blocks_before_claim_or_source(tmp_path, monkeypatch):
    code = runpy.run_path(str(SCRIPT))
    code["run"].__globals__["release_guard_active"] = lambda: False
    namespace = code["run"].__globals__
    queue = tmp_path / "queue.sqlite"
    queue.touch()
    namespace["QUEUE"] = queue
    namespace["PostgresStorage"] = SimpleNamespace(from_url=lambda *a, **kw: object())
    namespace["urgent44_status"] = lambda *a: "IDLE"
    namespace["joint_mandatory_status"] = lambda *a: "IDLE"
    namespace["read_history_demand"] = lambda *a, **kw: SimpleNamespace(
        classification=SimpleNamespace(status="BLOCKED")
    )
    monkeypatch.setenv("GOSPLAN_IMPORT_LEASE_HELD", "1")
    monkeypatch.setenv("DATABASE_URL", "not-used")
    result = asyncio.run(code["run"]("44", "0122100003226000063"))
    assert result["reason"] == "TRUSTED_DEMAND_NOT_IDLE"
    assert queue.stat().st_size == 0


def test_unsupported_44_family_is_rejected_before_claim_or_eis(tmp_path, monkeypatch):
    import json
    from contextlib import contextmanager
    from datetime import UTC, datetime, timedelta

    from procurement.sources.gosplan_discovery import parse_page
    from procurement.sources.gosplan_queue import GosplanQueue, Scope

    now = datetime(2026, 10, 30, tzinfo=UTC)
    path = tmp_path / "queue.sqlite"
    number = "0103300000426000007"
    queue = GosplanQueue(path)
    raw = json.dumps(
        [{"purchase_number": number, "purchase_type": "epNotificationEZT2020"}]
    ).encode()
    queue.record(Scope("local-eis-supplier", "44", now - timedelta(days=1), now, 0, 100),
                 parse_page(raw, "44", now, 100), now)
    queue.close()

    class Storage:
        @contextmanager
        def transaction(self, *_args, **_kwargs):
            yield SimpleNamespace(scalar=lambda _statement: 1)

    namespace = runpy.run_path(str(SCRIPT))["run"].__globals__
    namespace["release_guard_active"] = lambda: False
    namespace["QUEUE"] = path
    namespace["PostgresStorage"] = SimpleNamespace(from_url=lambda *_a, **_kw: Storage())
    namespace["urgent44_status"] = lambda *_a: "READY"
    namespace["joint_mandatory_status"] = lambda *_a: "READY"
    namespace["read_history_demand"] = lambda *_a, **_kw: SimpleNamespace(
        classification=SimpleNamespace(status="READY"),
        evidence_sha256="a" * 64, evidence={"ok": True}
    )
    namespace["shutil"] = SimpleNamespace(
        disk_usage=lambda _path: SimpleNamespace(free=100 * 1024**3)
    )
    monkeypatch.setenv("GOSPLAN_IMPORT_LEASE_HELD", "1")
    monkeypatch.setenv("DATABASE_URL", "unused")
    result = asyncio.run(namespace["run"]("44", number))
    assert result == {"status": "UNKNOWN", "reason": "UNSUPPORTED_FAMILY"}
    queue = GosplanQueue(path)
    assert queue.conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
    queue.close()


def test_release_guard_blocks_both_worker_entrypoints_before_side_effects():
    discovery = SCRIPT.with_name("server-gosplan-discovery.py")
    for script in (SCRIPT, discovery):
        code = runpy.run_path(str(script))
        namespace = code["run"].__globals__
        namespace["release_guard_active"] = lambda: True
        namespace["PostgresStorage"] = SimpleNamespace(
            from_url=lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("DB touched"))
        )
        if script == SCRIPT:
            result = asyncio.run(code["run"]("44", "0122100003226000063"))
        else:
            namespace["read_secret"] = lambda *_a: (_ for _ in ()).throw(AssertionError("key read"))
            result = code["run"]("44")
        assert result == {"status": "UNKNOWN", "reason": "RELEASE_GUARD"}


def test_release_guard_filesystem_fail_closed(tmp_path, monkeypatch):
    from procurement.sources.gosplan_queue import release_guard_active
    directory = tmp_path / "state"
    assert release_guard_active(directory)
    directory.mkdir()
    assert not release_guard_active(directory)
    guard = directory / "release.guard"
    guard.symlink_to(directory / "missing")
    assert release_guard_active(directory)
    guard.unlink()
    guard.touch()
    assert release_guard_active(directory)
    guard.unlink()
    import os
    def denied(*_args, **_kwargs):
        raise PermissionError("denied")
    monkeypatch.setattr(os, "stat", denied)
    assert release_guard_active(directory)


def test_resolver_cli_refuses_inaccessible_state_before_plan_or_queue(tmp_path):
    import os
    import subprocess
    import sys
    script = SCRIPT.with_name("server-gosplan-resolve-legacy-hold.py")
    state = tmp_path / "state"
    state.mkdir()
    (state / "release.guard").touch()
    launch = (
        "import runpy,sys; from pathlib import Path; "
        "import procurement.sources.gosplan_queue as q; "
        "original=q.release_guard_active; "
        "q.release_guard_active=lambda: original(Path(sys.argv[1])); "
        "sys.argv=[sys.argv[2], '--null-plan-sha256', 'a'*64]; "
        "runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-c", launch, str(state), str(script)],
        env={**os.environ, "GOSPLAN_CYCLE_LEASE_HELD": "1"},
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "RELEASE_GUARD" in result.stderr
    assert list(tmp_path.iterdir()) == [state]
    assert [p.name for p in state.iterdir()] == ["release.guard"]


def test_split_progress_finishes_one_cycle_without_starting_other_law(tmp_path):
    import json
    import os
    import subprocess

    script = SCRIPT.with_name("server-gosplan-cycle.sh").read_text()
    state = tmp_path / "state"
    state.mkdir()
    script = script.replace("/home/syurai/vibe-seller-state/gosplan", str(state))
    script = script.replace("/home/syurai/vibe-seller", str(tmp_path))
    cycle = tmp_path / "cycle.sh"
    cycle.write_text(script)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    sudo = bindir / "sudo"
    sudo.write_text(
        "#!/bin/sh\n"
        f"echo call >> '{tmp_path / 'calls'}'\n"
        "printf '%s\\n' '{\"status\":\"UNKNOWN\",\"reason\":\"OFFSET_RECOVERY\","
        "\"candidate\":null}'\n"
    )
    sudo.chmod(0o755)
    result = subprocess.run(
        ["bash", str(cycle)], cwd=tmp_path,
        env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["reason"] == "OFFSET_RECOVERY"
    assert (tmp_path / "calls").read_text().splitlines() == ["call"]


def test_split_progress_cli_exit_is_narrow(monkeypatch, capsys):
    import sys

    code = runpy.run_path(str(SCRIPT.with_name("server-gosplan-discovery.py")))
    namespace = code["main"].__globals__
    monkeypatch.setattr(sys, "argv", ["discovery", "--law", "44"])
    for response, expected in [
        ({"status": "UNKNOWN", "reason": "OFFSET_RECOVERY", "candidate": None}, 0),
        ({"status": "UNKNOWN", "reason": "OFFSET_RECOVERY_UNKNOWN", "candidate": None}, 1),
        ({"status": "UNKNOWN", "reason": "OFFSET_RECOVERY", "candidate": "123"}, 1),
        ({"status": "UNKNOWN", "reason": "PROVIDER_HOLD", "candidate": None}, 1),
    ]:
        namespace["run"] = lambda _law, result=response: result
        assert code["main"]() == expected
        capsys.readouterr()


def test_split_reservation_race_closes_started_turn_before_official_source(tmp_path, monkeypatch):
    import json
    import sqlite3
    from contextlib import asynccontextmanager, contextmanager
    from datetime import UTC, datetime, timedelta

    import procurement.sources.eis_223_number_sync as sync223
    import procurement.sources.gosplan_recovery as recovery
    from procurement.sources.gosplan_discovery import parse_page
    from procurement.sources.gosplan_queue import GosplanQueue, Scope

    class Storage:
        @contextmanager
        def transaction(self, *_args, **_kwargs):
            yield SimpleNamespace(scalar=lambda _statement: 1)

    class Budget:
        protected_reconciliation = True

        def __init__(self, *_args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def can_start(self, **_kwargs):
            return True

        def begin_window(self, _value):
            pass

        def end_window(self):
            pass

    @asynccontextmanager
    async def transport():
        yield object()

    async def no_source(*_args, **_kwargs):
        raise AssertionError('official source must not be contacted')

    monkeypatch.setattr(recovery, 'sync_eis_number', no_source)
    monkeypatch.setattr(sync223, 'sync_223_number', no_source)
    monkeypatch.setenv('GOSPLAN_IMPORT_LEASE_HELD', '1')
    monkeypatch.setenv('DATABASE_URL', 'unused')
    monkeypatch.setenv('EIS_GETDOCS_IP_TOKEN', 'unused')
    for law, number, family in [
        ('44', '0103300000426000007', 'epNotificationEF2020'),
        ('223', '32616349722', 'purchaseNoticeKESMBO'),
    ]:
        path = tmp_path / f'{law}.sqlite'
        queue = GosplanQueue(path)
        now = datetime.now(UTC)
        raw = json.dumps([{'purchase_number': number, 'purchase_type': family}]).encode()
        scope = Scope('local-eis-supplier', law, now - timedelta(days=1), now, 0, 100)
        queue.record(scope, parse_page(raw, law, now, 100), now)
        queue.close()
        ns = runpy.run_path(str(SCRIPT))['run'].__globals__
        ns['release_guard_active'] = lambda: False
        ns['QUEUE'] = path
        ns['PostgresStorage'] = SimpleNamespace(from_url=lambda *_a, **_kw: Storage())
        ns['urgent44_status'] = lambda *_a: 'READY'
        ns['joint_mandatory_status'] = lambda *_a: 'READY'
        ns['read_history_demand'] = lambda *_a, checked=now, **_kw: SimpleNamespace(
            classification=SimpleNamespace(status='READY', checked_at=checked),
            evidence_sha256='a' * 64, evidence={'ok': True},
        )
        ns['_reconciliation_days'] = lambda *_a: 'same'
        ns['shutil'] = SimpleNamespace(disk_usage=lambda _p: SimpleNamespace(free=100 * 1024**3))
        ns['JointStartBudget'] = Budget
        ns['eis_browser_transport'] = transport
        turns = []

        def start(*_args, events=turns, queue_path=path, reserved_scope=scope, at=now):
            events.append(('STARTED', 'turn'))
            # A split reserves the queue after the turn starts but before claim().
            with sqlite3.connect(queue_path) as c:
                c.execute('INSERT INTO offset_recovery_reservations VALUES (?,?,?,?)',
                          ('local-eis-supplier', 'attempt', reserved_scope.json(), at.isoformat()))
            return 'turn'

        ns['start_turn'] = start
        def finish(_s, _c, turn, outcome, events=turns):
            events.append((outcome, turn))

        ns['finish_turn'] = finish
        result = asyncio.run(ns['run'](law, number))
        assert result == {'status': 'UNKNOWN', 'reason': 'OFFSET_RECOVERY_RESERVED'}
        assert turns == [('STARTED', 'turn'), ('NOT_STARTED', 'turn')]
        with sqlite3.connect(path) as c:
            assert c.execute('SELECT count(*) FROM attempts').fetchone() == (0,)
            assert c.execute('SELECT count(*) FROM offset_recovery_reservations').fetchone() == (1,)
