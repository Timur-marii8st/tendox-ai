"""Evidence retention for a single already failed official 223-FZ window."""

import hashlib
import importlib.util
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from test_eis_223_sync import TOKEN, Transport, fetch

path = Path(__file__).parents[1] / "scripts/server-eis-223-refresh.py"
spec = importlib.util.spec_from_file_location("capture223", path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class Storage:
    def __init__(self):
        self.attempt = str(uuid4())
        self.basis = None
        self.object_id = None
        self.audit_fields = {}
        self.fail_audit = False

    @contextmanager
    def transaction(self, company, **kwargs):
        assert company == worker.COMPANY
        yield self

    def execute(self, stmt):
        if stmt.__class__.__name__ == "Insert":
            if self.fail_audit:
                raise OSError("synthetic database outage")
            params = stmt.compile().params
            self.basis = params["basis"]
            self.object_id = params["object_id"]
            self.audit_fields = {key: params[key] for key in
                                 ("actor_id", "event_type", "object_type", "occurred_at")}
            return None
        if "audit_events" in str(stmt):
            return SimpleNamespace(
                one=lambda: SimpleNamespace(
                    basis=self.basis, object_id=self.object_id, **self.audit_fields
                )
            )
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [self.attempt]))


@pytest.fixture
def case(monkeypatch, tmp_path):
    window = fetch(Transport()).window
    monkeypatch.setattr(worker, "CAPTURE_KEY", window.window_key)
    return Storage(), window, datetime.now(UTC), tmp_path / "capture"


def test_capture_reconciles_audit_after_outage_without_source_request(case):
    storage, window, checked_at, root = case
    storage.fail_audit = True
    with pytest.raises(OSError, match="database outage"):
        worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    manifest = root / worker.COMPANY / storage.attempt / "manifest.json"
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    storage.fail_audit = False
    assert worker.reconcile_failed_223(storage, root, TOKEN) == before
    assert worker.reconcile_failed_223(storage, root, TOKEN) == before
    assert storage.basis["manifest_sha256"] == before
    assert json.loads(manifest.read_bytes())["soap_bytes_retained"] is False


def test_replay_at_exact_quota_does_not_count_manifest_twice(case, monkeypatch):
    import procurement.sources.eis_rejected_evidence as evidence

    storage, window, checked_at, root = case
    digest = worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    used = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    monkeypatch.setattr(evidence, "MAX_STORE_BYTES", used)
    assert worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root) == digest
    assert sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) == used

    fresh = root.parent / "fresh"
    monkeypatch.setattr(evidence, "MAX_STORE_BYTES", used - 1)
    with pytest.raises(evidence.QuotaError):
        worker.retain_failed_223(storage, window, TOKEN, checked_at, root=fresh)
    assert not list(fresh.rglob("*.zip"))


def test_replay_at_quota_still_rejects_changed_manifest(case, monkeypatch):
    from datetime import timedelta

    import procurement.sources.eis_rejected_evidence as evidence

    storage, window, checked_at, root = case
    worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    used = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    monkeypatch.setattr(evidence, "MAX_STORE_BYTES", used)
    with pytest.raises(evidence.UnsafeStoreError):
        worker.retain_failed_223(
            storage, window, TOKEN, checked_at + timedelta(seconds=1), root=root
        )


def test_another_attempt_still_respects_single_capture_limit(case):
    storage, window, checked_at, root = case
    digest = worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    first = storage.attempt
    storage.attempt = str(uuid4())
    with pytest.raises(ValueError, match="CAPTURE_QUOTA_REACHED"):
        worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    manifest = root / worker.COMPANY / first / "manifest.json"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == digest
    assert not (root / worker.COMPANY / storage.attempt).exists()


def test_concurrent_processes_cannot_capture_two_attempts(case):
    import multiprocessing

    _storage, window, checked_at, root = case
    ctx = multiprocessing.get_context("fork")
    start, results = ctx.Event(), ctx.Queue()

    def capture():
        storage = Storage()
        start.wait(5)
        try:
            worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
            results.put("retained")
        except Exception as exc:
            results.put(str(exc))

    processes = [ctx.Process(target=capture) for _ in range(2)]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    assert sorted(results.get(timeout=2) for _ in processes) == [
        "CAPTURE_QUOTA_REACHED", "retained"
    ]
    assert len(list((root / worker.COMPANY).iterdir())) == 1


def test_capture_refuses_symlink_lock(case, tmp_path):
    storage, window, checked_at, root = case
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_bytes(b"untouched")
    (root / ".capture.lock").symlink_to(outside)
    with pytest.raises(OSError):
        worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    assert outside.read_bytes() == b"untouched"


def test_capture_failure_classification_never_returns_error_text():
    from procurement.sources.eis_rejected_evidence import QuotaError

    assert worker._capture_failure_reason(QuotaError()) == "QUOTA_REACHED"
    assert worker._capture_failure_reason(ValueError("CAPTURE_QUOTA_REACHED")) == "QUOTA_REACHED"
    assert worker._capture_failure_reason(FileNotFoundError("secret/path")) == "INCOMPLETE"
    assert worker._capture_failure_reason(OSError("secret/path")) == "OTHER"
    assert worker._capture_failure_reason(ValueError("CAPTURE_QUOTA_REACHED secret")) == "OTHER"


def test_capture_refuses_insecure_root_before_writing(case):
    storage, window, checked_at, root = case
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    with pytest.raises(ValueError, match="CAPTURE_ROOT_UNSAFE"):
        worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    assert list(root.iterdir()) == []


def test_reconcile_rejects_modified_archive(case):
    storage, window, checked_at, root = case
    worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    blob = next((root / worker.COMPANY / storage.attempt).glob("*.zip"))
    blob.chmod(0o600)
    blob.write_bytes(b"altered")
    blob.chmod(0o440)
    with pytest.raises(ValueError, match="CAPTURE_BLOB_INVALID"):
        worker.reconcile_failed_223(storage, root, TOKEN)


def test_capture_rejects_token_reflection_before_writing(case):
    storage, window, checked_at, root = case
    reflected = window.model_copy(update={"window_key": window.window_key + TOKEN})
    with pytest.raises(ValueError, match="CAPTURE_BINDING_INVALID"):
        worker.retain_failed_223(storage, reflected, TOKEN, checked_at, root=root)
    assert not root.exists()


def test_partial_capture_stays_pending_without_audit_or_network(case, monkeypatch):
    storage, window, checked_at, root = case
    original = worker._write_immutable

    def fail_before_manifest(path, *args):
        if path.name == "manifest.json":
            raise OSError("synthetic manifest interruption")
        return original(path, *args)

    monkeypatch.setattr(worker, "_write_immutable", fail_before_manifest)
    with pytest.raises(OSError, match="manifest interruption"):
        worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    with pytest.raises(ValueError, match="CAPTURE_MANIFEST_INVALID"):
        worker.reconcile_failed_223(storage, root, TOKEN)
    assert storage.basis is None
    assert list((root / worker.COMPANY / storage.attempt).glob("*.zip"))


def test_symlink_ancestor_refused(case, tmp_path):
    storage, window, checked_at, _root = case
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="CAPTURE_PATH_UNSAFE"):
        worker.retain_failed_223(storage, window, TOKEN, checked_at, root=link / "capture")
    assert not list(real.iterdir())


def test_reconcile_rejects_unsafe_tenant_directory(case):
    storage, window, checked_at, root = case
    worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
    (root / worker.COMPANY).chmod(0o755)
    with pytest.raises(ValueError, match="CAPTURE_DIRECTORY_UNSAFE"):
        worker.reconcile_failed_223(storage, root, TOKEN)


def test_capture_refuses_reflected_secret_in_valid_zip(case):
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    storage, window, checked_at, root = case
    buffer = BytesIO()
    with (
        ZipFile(BytesIO(window.archives[0])) as original,
        ZipFile(buffer, "w", ZIP_DEFLATED) as out,
    ):
        for member in original.infolist():
            data = original.read(member)
            out.writestr(
                member.filename,
                data.replace(b"</p:body>", b"<!--" + TOKEN.encode() + b"--></p:body>"),
            )
    reflected = window.model_copy(update={"archives": (buffer.getvalue(),)})
    with pytest.raises(ValueError, match="CAPTURE_TOKEN_REFLECTION"):
        worker.retain_failed_223(storage, reflected, TOKEN, checked_at, root=root)
    assert not root.exists()


def test_capture_binds_reordered_prepared_references_by_uid(monkeypatch, tmp_path):
    from dataclasses import replace

    from procurement.storage.eis_223_index import bind_notice223_window
    from test_eis_223_sync import MultiArchiveTransport

    original = fetch(MultiArchiveTransport(2)).window
    binding = original.source_binding
    prepared = replace(
        binding.prepared, prepared_archives=tuple(reversed(binding.prepared.prepared_archives))
    )
    window = bind_notice223_window(
        original.window_key,
        binding.initial,
        prepared,
        dict(zip(original.archive_urls, original.archives, strict=True)),
    )
    monkeypatch.setattr(worker, "CAPTURE_KEY", window.window_key)
    storage = Storage()
    root = tmp_path / "capture"
    digest = worker.retain_failed_223(storage, window, TOKEN, datetime.now(UTC), root=root)
    assert worker.reconcile_failed_223(storage, root, TOKEN) == digest


@pytest.mark.parametrize("after_writes", [1, 2])
def test_sigkill_during_capture_is_recovered_or_stays_pending(case, monkeypatch, after_writes):
    import os
    import signal

    storage, window, checked_at, root = case
    real_write = worker._write_immutable
    parent = os.getpid()
    count = 0

    def interrupted_write(*args):
        nonlocal count
        real_write(*args)
        count += 1
        if os.getpid() != parent and count == after_writes:
            os.kill(os.getpid(), signal.SIGKILL)

    monkeypatch.setattr(worker, "_write_immutable", interrupted_write)
    pid = os.fork()
    if pid == 0:
        worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
        os._exit(1)
    _, status = os.waitpid(pid, 0)
    assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    if after_writes == 1:
        with pytest.raises(ValueError, match="CAPTURE_MANIFEST_INVALID"):
            worker.reconcile_failed_223(storage, root, TOKEN)
        assert storage.basis is None
        # A killed writer releases the store lock; the same exact attempt can resume.
        digest = worker.retain_failed_223(storage, window, TOKEN, checked_at, root=root)
        assert storage.basis["manifest_sha256"] == digest
    else:
        digest = worker.reconcile_failed_223(storage, root, TOKEN)
        assert storage.basis["manifest_sha256"] == digest
