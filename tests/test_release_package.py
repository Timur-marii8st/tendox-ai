"""Release snapshots preserve source identity and exclude private tracked state."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "release_package", Path(__file__).resolve().parents[1] / "scripts/package-server-release.py"
)
assert _SPEC is not None and _SPEC.loader is not None
release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(release)


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
    (root / "src").mkdir()
    (root / "src/main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src/deleted.py").write_text("OLD = 1\n", encoding="utf-8")
    (root / "src/.env").write_text("PRIVATE_SYNTHETIC_FIXTURE=do-not-archive\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    (root / "src/deleted.py").unlink()
    (root / "src/main.py").write_text("VALUE = 2\n", encoding="utf-8")
    (root / "src/new.py").write_text("NEW = 1\n", encoding="utf-8")
    return root


def test_snapshot_is_repeatable_and_hashes_exact_archived_bytes(source_repo: Path, tmp_path: Path):
    first, second = tmp_path / "first.tar.gz", tmp_path / "second.tar.gz"
    a = release.build_snapshot(source_repo, first)
    b = release.build_snapshot(source_repo, second)
    assert a == b and first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        manifest_file = archive.extractfile("release-manifest.json")
        assert manifest_file is not None
        manifest = json.load(manifest_file)
        assert manifest["source_kind"] == "WORKTREE_SNAPSHOT" and manifest["git_dirty"]
        assert manifest["deleted_paths"] == ["src/deleted.py"]
        assert "src/.env" not in archive.getnames()
        assert {f["path"] for f in manifest["files"]} == {"src/main.py", "src/new.py"}
        for file in manifest["files"]:
            extracted = archive.extractfile(file["path"])
            assert extracted is not None
            data = extracted.read()
            assert hashlib.sha256(data).hexdigest() == file["sha256"]
            assert len(data) == file["bytes"]
            member = archive.getmember(file["path"])
            assert member.mtime == member.uid == member.gid == 0


@pytest.mark.parametrize(
    "path",
    [
        "src/a.key",
        "web/.env.production",
        "src/private/x.py",
        "web/node_modules/x.js",
        "web/build/discovery-tests/x.js",
        "src/.pytest_cache/README.md",
        "docs/history/legacy/source.docx",
        "картинки с текстом/x.png",
    ],
)
def test_private_paths_stay_excluded_even_if_git_tracks_them(path: str):
    assert not release.allowed_source(path)


@pytest.mark.parametrize("path", ["../src/x.py", "/src/x.py", "src\\x.py"])
def test_unsafe_archive_paths_fail_closed(path: str):
    with pytest.raises(RuntimeError, match="RELEASE_PATH_INVALID"):
        release.allowed_source(path)


def test_synthetic_documents_and_shell_modes_are_explicit():
    assert release.allowed_source("data/goldenset/v1/tz_001.docx")
    assert release.allowed_source(".env.example")
    assert release.allowed_source("web/src/app/favicon.ico")
    assert release.source_mode("scripts/server-eis-priority.sh") == 0o700
    assert release.source_mode("src/main.py") == 0o644


def test_changed_source_changes_snapshot_digest(source_repo: Path, tmp_path: Path):
    before = release.build_snapshot(source_repo, tmp_path / "before.tar.gz")
    (source_repo / "src/main.py").write_text("VALUE = 3\n", encoding="utf-8")
    after = release.build_snapshot(source_repo, tmp_path / "after.tar.gz")
    assert before["tree_sha256"] != after["tree_sha256"]
    assert before["bundle_sha256"] != after["bundle_sha256"]


def test_output_cannot_overwrite_source(source_repo: Path):
    target = source_repo / "src/main.py"
    before = target.read_bytes()
    with pytest.raises(RuntimeError, match="RELEASE_OUTPUT_OVERLAPS_SOURCE"):
        release.build_snapshot(source_repo, target)
    assert target.read_bytes() == before


@pytest.mark.parametrize("parent_link", [False, True])
def test_symlink_file_and_parent_fail_before_archiving(
    source_repo: Path,
    tmp_path: Path,
    parent_link: bool,
):
    if parent_link:
        original = source_repo / "src"
        destination = tmp_path / "outside-src"
        original.rename(destination)
        link, target = original, destination
    else:
        link = source_repo / "src/main.py"
        link.unlink()
        target = tmp_path / "outside.py"
        target.write_text("PRIVATE_SYNTHETIC = 1\n", encoding="utf-8")
    try:
        link.symlink_to(target, target_is_directory=parent_link)
    except OSError:
        pytest.skip("symlink creation privilege unavailable on this platform")
    with pytest.raises(RuntimeError, match="RELEASE_SOURCE_SYMLINK"):
        release.build_snapshot(source_repo, tmp_path / "snapshot.tar.gz")
