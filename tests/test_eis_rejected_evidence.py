"""Synthetic rejected-window retention only; no source or database calls."""

import hashlib
import json
import os
import stat
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import procurement.sources.eis_rejected_evidence as subject
from procurement.sources.eis_rejected_evidence import retain_rejected_window
from procurement.storage.eis_notice_index import EisReadyWindow

NOW = datetime(2026, 10, 4, 10, tzinfo=UTC)
TOKEN = "SyntheticToken-123456"


def archive(content: bytes = b"<root>synthetic</root>", name: str = "notice.xml") -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr(name, content)
    return output.getvalue()


def url(request: str, uid: str) -> str:
    return (
        "https://int44.zakupki.gov.ru/dstore/common/download/compound"
        f"?docRequestUid={request}&compoundUid={uid}"
    )


def window(*, response: str = "a" * 64, raw: bytes | None = None) -> EisReadyWindow:
    request = "11111111-1111-4111-8111-111111111111"
    return EisReadyWindow(
        window_key="getDocsIP/PRIZ/77/2026-10-02+03:00/epNotificationEOK2020",
        response_sha256=response,
        prepared_response_sha256="b" * 64,
        expected_archive_count=1,
        archives=(raw or archive(),),
        archive_urls=(url(request, "A" * 32),),
    )


def retain(root: Path | None, selected: EisReadyWindow | None = None, **kwargs):
    return retain_rejected_window(
        selected or window(),
        kwargs.pop("company_id", "tenant-a"),
        kwargs.pop("reason", "NOTICE_VERSION_CONFLICT"),
        kwargs.pop("token", TOKEN),
        kwargs.pop("observed_at", NOW),
        root,
    )


def test_disabled_retention_is_typed_and_never_writes(tmp_path):
    result = retain(None)
    assert result.status == "DISABLED" and not result.complete_set
    assert result.source_requests == 0 and result.manifest_sha256 is None
    assert not tuple(tmp_path.iterdir())


def test_complete_set_is_content_addressed_immutable_and_manifest_last(tmp_path):
    result = retain(tmp_path)
    assert result.status == "RETAINED" and result.complete_set
    assert len(result.archive_sha256s) == 1
    manifest = tmp_path / str(result.relative_manifest_path)
    blob = tmp_path / "tenant-a/blobs" / f"{result.archive_sha256s[0]}.zip"
    assert manifest.exists() and blob.exists()
    expected_mode = 0o444 if os.name == "nt" else 0o440
    assert os.stat(manifest).st_mode & 0o777 == expected_mode
    assert os.stat(blob).st_mode & 0o777 == expected_mode
    payload = json.loads(manifest.read_bytes())
    assert payload["complete_set"] is True and payload["archive_urls"] == list(result.archive_urls)
    assert "manifest_sha256" not in payload
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == result.manifest_sha256


def test_replay_returns_original_observation_without_rewrite(tmp_path):
    first = retain(tmp_path)
    later = retain(tmp_path, observed_at=datetime(2026, 10, 4, 12, tzinfo=UTC))
    assert later == first and later.observed_at == NOW


def test_new_response_and_tenant_have_separate_manifests(tmp_path):
    first = retain(tmp_path)
    changed = retain(tmp_path, window(response="c" * 64))
    other = retain(tmp_path, company_id="tenant-b")
    assert len({first.relative_manifest_path, changed.relative_manifest_path}) == 2
    assert str(first.relative_manifest_path).startswith("tenant-a/")
    assert str(other.relative_manifest_path).startswith("tenant-b/")


@pytest.mark.parametrize(
    "selected",
    [
        window(raw=archive(TOKEN.encode())),
        window(raw=archive(b"safe", name=f"{TOKEN}.xml")),
    ],
)
def test_reflection_in_compressed_member_or_metadata_rejects_before_writes(tmp_path, selected):
    result = retain(tmp_path, selected, token=TOKEN)
    assert result.status == "FAILED" and result.retention_reason == "REFLECTION_REJECTED"
    assert all(TOKEN not in value for value in result.archive_urls)
    assert not list(tmp_path.rglob("manifest.json")) and not list(tmp_path.rglob("*.zip"))


def test_quota_failure_has_no_partial_manifest_or_blob(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, "MAX_STORE_BYTES", 10)
    result = retain(tmp_path)
    assert result.status == "FAILED" and result.retention_reason == "QUOTA_REACHED"
    assert not list(tmp_path.rglob("manifest.json")) and not list(tmp_path.rglob("*.zip"))


@pytest.mark.skipif(os.name == "nt", reason="Linux directory durability semantics")
def test_directory_fsync_failure_never_reports_retained(tmp_path, monkeypatch):
    real_fsync = os.fsync

    def fail_directory(descriptor: int) -> None:
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("synthetic directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory)
    result = retain(tmp_path / "new-store")
    assert result.status == "FAILED" and result.retention_reason == "IO_FAILED"
    assert not list(tmp_path.rglob("manifest.json"))


@pytest.mark.skipif(os.name == "nt", reason="Linux directory durability semantics")
def test_retry_resyncs_tree_left_by_directory_fsync_failure(tmp_path, monkeypatch):
    real_sync = subject._fsync_directory
    directory_attempts = 0
    fail_once = True
    root = tmp_path / "new-parent" / "new-store"

    def fail_after_manifest(directory: Path) -> None:
        nonlocal directory_attempts, fail_once
        directory_attempts += 1
        if fail_once and list(root.rglob("manifest.json")):
            fail_once = False
            raise OSError("synthetic post-manifest directory fsync failure")
        real_sync(directory)

    monkeypatch.setattr(subject, "_fsync_directory", fail_after_manifest)
    first = retain(root)
    attempts_after_failure = directory_attempts
    second = retain(root)
    assert first.status == "FAILED" and first.retention_reason == "IO_FAILED"
    assert second.status == "RETAINED"
    assert directory_attempts > attempts_after_failure


@pytest.mark.skipif(os.name == "nt", reason="Linux directory durability semantics")
def test_retry_resyncs_blob_directory_after_fsync_failure(tmp_path, monkeypatch):
    real_sync = subject._fsync_directory
    directory_attempts = 0
    fail_once = True
    root = tmp_path / "new-store"

    def fail_after_blob(directory: Path) -> None:
        nonlocal directory_attempts, fail_once
        directory_attempts += 1
        if fail_once and list(root.rglob("*.zip")) and not list(root.rglob("manifest.json")):
            fail_once = False
            raise OSError("synthetic blob directory fsync failure")
        real_sync(directory)

    monkeypatch.setattr(subject, "_fsync_directory", fail_after_blob)
    first = retain(root)
    attempts_after_failure = directory_attempts
    second = retain(root)
    assert first.status == "FAILED" and first.retention_reason == "IO_FAILED"
    assert not first.complete_set
    assert second.status == "RETAINED"
    assert directory_attempts > attempts_after_failure


@pytest.mark.skipif(os.name == "nt", reason="Linux inode durability semantics")
def test_read_only_mode_is_applied_before_final_file_fsync(tmp_path, monkeypatch):
    real_fchmod = os.fchmod
    real_fsync = os.fsync
    events: list[tuple[str, int]] = []

    def record_fchmod(descriptor: int, mode: int) -> None:
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            events.append(("chmod", mode))
        real_fchmod(descriptor, mode)

    def record_fsync(descriptor: int) -> None:
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            events.append(("fsync", stat.S_IMODE(os.fstat(descriptor).st_mode)))
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fchmod", record_fchmod)
    monkeypatch.setattr(os, "fsync", record_fsync)
    result = retain(tmp_path / "store")
    assert result.status == "RETAINED"
    assert events
    for index, event in enumerate(events):
        if event[0] == "chmod":
            assert event == ("chmod", 0o440)
            assert events[index + 1] == ("fsync", 0o440)


def test_symlink_component_is_rejected_before_write(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "store"
    root.mkdir()
    try:
        (root / "tenant-a").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    result = retain(root)
    assert result.status == "FAILED" and result.retention_reason == "STORE_UNSAFE"
    assert not list(outside.iterdir())


def test_corrupt_existing_blob_makes_replay_fail_closed(tmp_path):
    first = retain(tmp_path)
    blob = tmp_path / "tenant-a/blobs" / f"{first.archive_sha256s[0]}.zip"
    os.chmod(blob, 0o640)
    blob.write_bytes(b"corrupt")
    result = retain(tmp_path)
    assert result.status == "FAILED" and result.retention_reason == "STORE_UNSAFE"
    assert result.manifest_sha256 is None and not result.complete_set


def test_invalid_binding_and_naive_time_are_rejected(tmp_path):
    invalid = window()
    invalid = EisReadyWindow(**{**invalid.__dict__, "expected_archive_count": 2})
    result = retain(tmp_path, invalid)
    assert result.status == "FAILED" and result.retention_reason == "BINDING_REJECTED"
    with pytest.raises(ValueError, match="EVIDENCE_TIMEZONE_MISSING"):
        retain(tmp_path, observed_at=datetime(2026, 10, 4, 10))


def test_invalid_cardinality_cannot_reflect_token_in_failure(tmp_path):
    invalid = replace(
        window(),
        expected_archive_count=2,
        archive_urls=(f"https://eis/{TOKEN}",),
    )
    result = retain(tmp_path, invalid)
    assert result.status == "FAILED" and result.retention_reason == "BINDING_REJECTED"
    assert TOKEN not in json.dumps(result.model_dump(mode="json"))


def test_reflected_required_provenance_raises_safe_exception(tmp_path):
    invalid = replace(window(), window_key=f"window/{TOKEN}")
    with pytest.raises(ValueError, match=r"^REFLECTION_REJECTED$"):
        retain(tmp_path, invalid)


def test_existing_blob_digest_and_manifest_sha_are_exact(tmp_path):
    result = retain(tmp_path)
    blob = tmp_path / "tenant-a/blobs" / f"{result.archive_sha256s[0]}.zip"
    assert hashlib.sha256(blob.read_bytes()).hexdigest() == result.archive_sha256s[0]
    manifest = tmp_path / str(result.relative_manifest_path)
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == result.manifest_sha256
    assert "manifest_sha256" not in json.loads(manifest.read_bytes())
