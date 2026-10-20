"""Create a deterministic, manifested WORKTREE_SNAPSHOT, not installed-release proof."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "eis-pilot" / "server-release.tar.gz"
TOP_LEVEL_FILES = frozenset(
    {
        ".dockerignore",
        ".env.example",
        ".gitignore",
        ".gitattributes",
        "AGENTS.md",
        "CLAUDE.md",
        "Dockerfile.api",
        "Dockerfile.eis-proxy",
        "Dockerfile.web",
        "README.md",
        "alembic.ini",
        "docker-compose.yml",
        "docker-compose.server.yml",
        "pyproject.toml",
        "uv.lock",
    }
)
DIRECTORIES = (
    ".github/",
    "src/",
    "web/",
    "docker/",
    "docs/",
    "tests/",
    "migrations/",
    "scripts/",
    "data/goldenset/",
    "examples/",
)
PRIVATE_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        ".next",
        "__pycache__",
        "private",
        "tmp",
        "build",
        "dist",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
    }
)
PRIVATE_SUFFIXES = frozenset({".key", ".p12", ".pfx", ".pem", ".sqlite3", ".db"})
SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".mjs",
        ".json",
        ".md",
        ".html",
        ".css",
        ".yml",
        ".yaml",
        ".sh",
        ".ps1",
        ".toml",
        ".ini",
        ".lock",
        ".mako",
        ".crt",
    }
)


def allowed_source(name: str) -> bool:
    """Apply policy even to already-tracked files, before opening any bytes."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise RuntimeError("RELEASE_PATH_INVALID")
    if any(part.casefold() in PRIVATE_PARTS for part in path.parts):
        return False
    if any(part.casefold().startswith(".env") for part in path.parts):
        return name == ".env.example"
    if path.suffix.casefold() in PRIVATE_SUFFIXES:
        return False
    if name in TOP_LEVEL_FILES:
        return True
    if name == "web/src/app/favicon.ico":
        return True
    if not name.startswith(DIRECTORIES):
        return False
    # Only the explicitly synthetic golden set may include document binaries.
    if name.startswith("data/goldenset/"):
        return path.suffix.casefold() in SOURCE_SUFFIXES | {".pdf", ".docx", ".xlsx"}
    if name.startswith("web/public/"):
        return path.suffix.casefold() in SOURCE_SUFFIXES | {".ico", ".svg"}
    return path.suffix.casefold() in SOURCE_SUFFIXES


def source_mode(name: str) -> int:
    """Normalize modes independent of Windows filesystem metadata."""
    return 0o700 if name.startswith("scripts/server-") and name.endswith(".sh") else 0o644


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def _add_bytes(archive: tarfile.TarFile, name: str, data: bytes, mode: int) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mode = len(data), mode
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ""
    archive.addfile(info, io.BytesIO(data))


def build_snapshot(root: Path, output: Path) -> dict[str, object]:
    """Archive and hash the same bytes once; record deletions and publish atomically."""
    root = root.resolve()
    output = output.resolve()
    if output.is_relative_to(root) and allowed_source(output.relative_to(root).as_posix()):
        raise RuntimeError("RELEASE_OUTPUT_OVERLAPS_SOURCE")
    cached = {x.decode("utf-8") for x in _git(root, "ls-files", "-z", "--cached").split(b"\0") if x}
    others = {
        x.decode("utf-8")
        for x in _git(root, "ls-files", "-z", "--others", "--exclude-standard").split(b"\0")
        if x
    }
    names = sorted(cached | others)
    payload: list[tuple[str, bytes, int]] = []
    deleted: list[str] = []
    excluded = 0
    for name in names:
        if not allowed_source(name):
            excluded += 1
            continue
        source = root / name
        if source.is_symlink() or any(p.is_symlink() for p in source.parents if p != root):
            raise RuntimeError("RELEASE_SOURCE_SYMLINK")
        if not source.resolve().is_relative_to(root):
            raise RuntimeError("RELEASE_SOURCE_INVALID")
        if not source.exists() and name in cached:
            deleted.append(name)
            continue
        if not source.is_file():
            raise RuntimeError("RELEASE_SOURCE_INVALID")
        if source.stat().st_size > 25 * 1024 * 1024:
            raise RuntimeError("RELEASE_FILE_TOO_LARGE")
        data = source.read_bytes()
        if len(data) > 25 * 1024 * 1024:
            raise RuntimeError("RELEASE_FILE_TOO_LARGE")
        payload.append((name, data, source_mode(name)))
    files = [
        {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "mode": mode}
        for name, data, mode in payload
    ]
    canonical = json.dumps(
        files, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest: dict[str, object] = {
        "format_version": 1,
        "source_kind": "WORKTREE_SNAPSHOT",
        "git_head": _git(root, "rev-parse", "HEAD").decode().strip(),
        "git_dirty": bool(_git(root, "status", "--porcelain")),
        "tree_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": files,
        "deleted_paths": deleted,
        "excluded_count": excluded,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".partial", delete=False) as staging:
        temporary = Path(staging.name)
    try:
        with (
            temporary.open("wb") as stream,
            gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed,
            tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
        ):
            for name, data, mode in payload:
                _add_bytes(archive, name, data, mode)
            _add_bytes(archive, "release-manifest.json", manifest_bytes, 0o644)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "source_kind": "WORKTREE_SNAPSHOT",
        "files": len(files),
        "deleted_count": len(deleted),
        "excluded_count": excluded,
        "input_bytes": sum(len(data) for _, data, _ in payload),
        "bundle_bytes": output.stat().st_size,
        "bundle_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "tree_sha256": manifest["tree_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build_snapshot(ROOT, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
