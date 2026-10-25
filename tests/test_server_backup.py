"""Retention must never trade recoverability for free disk space."""

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "server_backup_under_test", Path(__file__).resolve().parents[1] / "scripts/server-backup.py"
)
backup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backup
spec.loader.exec_module(backup)
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
OLD = [f"procurement-202610{day}T030000Z.dump" for day in (15, 16, 22)]
NEW = "procurement-20261024T120000Z.dump"


class FakeOperations:
    def __init__(self):
        self.events = []
        self.dump_failure = False
        self.verify_failure = False
        self.audit_failure = False
        self.on_audit = lambda: None

    def database_size(self):
        return 100

    def dump(self, stream):
        self.events.append("dump")
        stream.write(b"VALID:new full data")
        if self.dump_failure:
            raise backup.BackupFailure("DUMP_FAILED")

    def verify(self, stream):
        self.events.append("verify")
        if self.verify_failure or not stream.read().startswith(b"VALID:"):
            raise backup.BackupFailure("ARCHIVE_UNREADABLE")

    def audit(self, payload):
        self.events.append(payload["status"])
        if self.audit_failure:
            raise backup.BackupFailure("AUDIT_UNAVAILABLE")
        if payload["status"] == "PREPARED":
            self.on_audit()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    original = b"VALID:original"
    paths = backup.Paths(
        tmp_path / "repo", tmp_path / "state", hashlib.sha256(original).hexdigest()
    )
    paths.backups.mkdir(parents=True, mode=0o700)
    (paths.backups / backup.ORIGINAL).write_bytes(original)
    for name in OLD:
        (paths.backups / name).write_bytes(b"VALID:" + name.encode())
    monkeypatch.setattr(
        backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=backup.RESERVE + 1000)
    )
    return paths, FakeOperations()


def names(paths):
    return {p.name for p in paths.backups.iterdir()}


def test_success_keeps_two_latest_verified_and_exact_original(setup):
    paths, ops = setup
    foreign = paths.backups / "pre-deploy.tar.gz"
    foreign.write_bytes(b"do not delete")
    result = backup.run_backup(paths, ops, NOW)
    assert names(paths) == {NEW, OLD[-1], backup.ORIGINAL, foreign.name}
    assert result["deleted"] == OLD[:2]
    assert ops.events == ["dump", "verify", "verify", "PREPARED", "COMPLETED"]
    plan = json.loads((paths.evidence / "20261024T120000Z.plan.json").read_text())
    assert len(plan["verified"]) == 2
    assert all(len(x["sha256"]) == 64 for x in plan["verified"])
    assert plan["company_id"] == backup.COMPANY
    assert len(list(paths.evidence.glob("*.deleted-*.json"))) == 2


def test_second_success_rotates_only_after_new_dump(setup):
    paths, ops = setup
    backup.run_backup(paths, ops, NOW)
    result = backup.run_backup(paths, ops, NOW + timedelta(days=1))
    assert result["deleted"] == [OLD[-1]]
    assert names(paths) == {backup.ORIGINAL, NEW, "procurement-20261025T120000Z.dump"}


@pytest.mark.parametrize("failure", ["dump_failure", "verify_failure", "audit_failure"])
def test_failure_preserves_every_old_backup(setup, failure):
    paths, ops = setup
    before = {p.name: p.read_bytes() for p in paths.backups.iterdir()}
    setattr(ops, failure, True)
    with pytest.raises(backup.BackupFailure):
        backup.run_backup(paths, ops, NOW)
    assert all((paths.backups / n).read_bytes() == raw for n, raw in before.items())
    assert not list(paths.backups.glob(".procurement-*"))
    if failure != "audit_failure":
        assert not (paths.backups / NEW).exists()


def test_corrupt_previous_backup_does_not_delete_older_fallbacks(setup):
    paths, ops = setup
    (paths.backups / OLD[-1]).write_bytes(b"broken")
    with pytest.raises(backup.BackupFailure, match="ARCHIVE_UNREADABLE"):
        backup.run_backup(paths, ops, NOW)
    assert names(paths) == set(OLD) | {NEW, backup.ORIGINAL}
    assert "PREPARED" not in ops.events


@pytest.mark.parametrize("target", [backup.ORIGINAL, OLD[-1], OLD[0]])
def test_mutation_between_verification_and_deletion_stops_retention(setup, target):
    paths, ops = setup
    ops.on_audit = lambda: (paths.backups / target).write_bytes(b"CHANGED")
    with pytest.raises(backup.BackupFailure, match="BACKUP_SET_CHANGED"):
        backup.run_backup(paths, ops, NOW)
    assert names(paths) == set(OLD) | {NEW, backup.ORIGINAL}


def test_foreign_backup_added_during_run_is_not_adopted_or_deleted(setup):
    paths, ops = setup
    added = "procurement-20261023T010000Z.dump"
    ops.on_audit = lambda: (paths.backups / added).write_bytes(b"unknown")
    with pytest.raises(backup.BackupFailure, match="BACKUP_SET_CHANGED"):
        backup.run_backup(paths, ops, NOW)
    assert set(OLD) | {backup.ORIGINAL, NEW, added} == names(paths)


@pytest.mark.parametrize("target", [backup.ORIGINAL, OLD[0]])
def test_symlink_backup_refuses_without_following_or_deleting(setup, tmp_path, target):
    paths, ops = setup
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    (paths.backups / target).unlink()
    (paths.backups / target).symlink_to(outside)
    with pytest.raises(backup.BackupFailure, match="UNSAFE_BACKUP_FILE"):
        backup.run_backup(paths, ops, NOW)
    assert outside.read_bytes() == b"private" and not ops.events


def test_bad_original_hash_blocks_even_creation(setup):
    paths, ops = setup
    (paths.backups / backup.ORIGINAL).write_bytes(b"VALID:replaced")
    with pytest.raises(backup.BackupFailure, match="ORIGINAL_BACKUP_CHANGED"):
        backup.run_backup(paths, ops, NOW)
    assert not ops.events


def test_missing_original_blocks_rotation(setup):
    paths, ops = setup
    (paths.backups / backup.ORIGINAL).unlink()
    with pytest.raises(FileNotFoundError):
        backup.run_backup(paths, ops, NOW)
    assert names(paths) == set(OLD) and not ops.events


def test_no_second_recent_copy_creates_without_removing_original(setup):
    paths, ops = setup
    for n in OLD:
        (paths.backups / n).unlink()
    result = backup.run_backup(paths, ops, NOW)
    assert names(paths) == {backup.ORIGINAL, NEW} and not result["deleted"]


def test_full_disk_never_deletes_first_to_make_room(setup, monkeypatch):
    paths, ops = setup
    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _: SimpleNamespace(free=backup.RESERVE))
    with pytest.raises(backup.BackupFailure, match="DISK_RESERVE_REACHED"):
        backup.run_backup(paths, ops, NOW)
    assert names(paths) == set(OLD) | {backup.ORIGINAL} and not ops.events


def test_concurrent_run_fails_before_dump(setup):
    paths, ops = setup
    with backup.backup_lock(paths), pytest.raises(backup.BackupFailure, match="BACKUP_BUSY"):
        backup.run_backup(paths, ops, NOW)
    assert not ops.events


def test_future_dated_backup_is_not_a_retention_candidate(setup):
    paths, ops = setup
    (paths.backups / "procurement-20261025T000000Z.dump").write_bytes(b"VALID:future")
    with pytest.raises(backup.BackupFailure, match="BACKUP_DATE_IN_FUTURE"):
        backup.run_backup(paths, ops, NOW)
    assert not ops.events


def test_collision_does_not_overwrite_completed_backup(setup):
    paths, ops = setup
    (paths.backups / NEW).write_bytes(b"VALID:existing")
    with pytest.raises(backup.BackupFailure, match="BACKUP_NAME_EXISTS"):
        backup.run_backup(paths, ops, NOW)
    assert (paths.backups / NEW).read_bytes() == b"VALID:existing"


def test_plan_write_failure_preserves_old_backups(setup, monkeypatch):
    paths, ops = setup

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(backup, "persist", fail)
    with pytest.raises(OSError):
        backup.run_backup(paths, ops, NOW)
    assert names(paths) == set(OLD) | {backup.ORIGINAL, NEW}


def test_failure_after_one_unlink_keeps_verified_pair_and_original(setup, monkeypatch):
    paths, ops = setup
    real = backup.persist

    def fail(path, payload):
        if ".deleted-" in path.name:
            raise OSError("journal unavailable")
        real(path, payload)

    monkeypatch.setattr(backup, "persist", fail)
    with pytest.raises(OSError):
        backup.run_backup(paths, ops, NOW)
    assert names(paths) == {OLD[1], OLD[2], NEW, backup.ORIGINAL}
    assert list(paths.evidence.glob("*.plan.json"))


def test_verification_command_reads_entire_archive_without_restore_writes(setup, monkeypatch):
    paths, _ = setup
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=b"")

    monkeypatch.setattr(backup.subprocess, "run", run)
    with (paths.backups / OLD[0]).open("rb") as f:
        backup.Operations(paths).verify(f)
    assert calls[0][0][-2:] == ["pg_restore", "--file=/dev/null"]
    assert "-l" not in calls[0][0] and "-d" not in calls[0][0]
