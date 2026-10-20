"""Bounded immutable retention of complete rejected EIS source windows."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from contextlib import suppress
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Literal
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from procurement.sources.eis_feed import EisFeedContractError, validate_eis_archive_url
from procurement.storage.eis_notice_index import EisReadyWindow

MAX_ARCHIVES = 20
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_XML_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 1000
MAX_MANIFEST_BYTES = 64 * 1024
MAX_STORE_BYTES = 5 * 1024**3
RejectionReason = Literal[
    "DUPLICATE_NOTICE_VERSION",
    "DUPLICATE_NOTICE_VERSION_IN_WINDOW",
    "NOTICE_VERSION_CONFLICT",
    "TRANSPORT_WINDOW_NOT_CANONICAL",
]
FailureReason = Literal[
    "BINDING_REJECTED",
    "IO_FAILED",
    "QUOTA_REACHED",
    "REFLECTION_REJECTED",
    "STORE_UNSAFE",
]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EisRejectedEvidence(EvidenceModel):
    status: Literal["RETAINED", "DISABLED", "FAILED"]
    reason: RejectionReason
    retention_reason: FailureReason | None = None
    company_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    window_key: str = Field(min_length=1, max_length=500)
    observed_at: datetime
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prepared_response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    archive_urls: tuple[str, ...]
    archive_sha256s: tuple[str, ...] = Field(default=(), max_length=MAX_ARCHIVES)
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    relative_manifest_path: str | None = Field(default=None, max_length=500)
    complete_set: bool
    source_requests: Literal[0] = 0

    @field_validator("observed_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("EVIDENCE_TIMEZONE_MISSING")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> EisRejectedEvidence:
        retained = self.status == "RETAINED"
        if retained != bool(
            self.manifest_sha256 and self.relative_manifest_path and self.archive_sha256s
        ):
            raise ValueError("EVIDENCE_REF_INVALID")
        if (self.status == "FAILED") != (self.retention_reason is not None):
            raise ValueError("EVIDENCE_REF_INVALID")
        if self.status == "DISABLED" and self.archive_sha256s:
            raise ValueError("EVIDENCE_REF_INVALID")
        if self.complete_set != retained:
            raise ValueError("EVIDENCE_REF_INVALID")
        return self


def retain_rejected_window(
    window: EisReadyWindow,
    company_id: str,
    reason: RejectionReason,
    token: str,
    observed_at: datetime,
    root: Path | None,
) -> EisRejectedEvidence:
    """Retain a complete rejected set; the manifest is always the final write."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("EVIDENCE_TIMEZONE_MISSING")
    if token and any(
        token in value
        for value in (
            company_id,
            window.window_key,
            window.response_sha256,
            window.prepared_response_sha256 or "",
            reason,
            str(observed_at),
        )
    ):
        # Required provenance fields cannot be removed or fabricated safely.
        raise ValueError("REFLECTION_REJECTED")
    base = _base(window, company_id, reason, observed_at)
    safe_base = _redact_reflection(base, token)
    # Validate caller-controlled reference fields before any filesystem mutation.
    EisRejectedEvidence(status="DISABLED", complete_set=False, **base)
    if root is None:
        return EisRejectedEvidence(
            status="DISABLED",
            complete_set=False,
            **safe_base,
        )
    try:
        digests = _preflight(window, token)
        safe_root = _safe_root(root)
        identity = _identity(window, company_id, reason, digests)
        relative = Path(company_id) / "rejected" / identity / "manifest.json"
        manifest_path = safe_root / relative
        if manifest_path.exists():
            replay = _read_replay(manifest_path, safe_root, identity)
            replay_blob = (
                safe_root / replay.company_id / "blobs" / f"{replay.archive_sha256s[0]}.zip"
            )
            _sync_tree_path(replay_blob, safe_root)
            _sync_tree_path(manifest_path, safe_root)
            return replay
        blob_paths = [safe_root / company_id / "blobs" / f"{digest}.zip" for digest in digests]
        manifest = {
            **base,
            "status": "RETAINED",
            "retention_reason": None,
            "archive_sha256s": list(digests),
            "relative_manifest_path": relative.as_posix(),
            "complete_set": True,
            "source_requests": 0,
        }
        encoded = _json(manifest)
        manifest_sha = hashlib.sha256(encoded).hexdigest()
        _quota(safe_root, blob_paths, window.archives, len(encoded))
        for path, raw, digest in zip(blob_paths, window.archives, digests, strict=True):
            _write_immutable(path, raw, digest, safe_root, MAX_ARCHIVE_BYTES)
        _sync_tree_path(blob_paths[0], safe_root)
        _write_immutable(
            manifest_path,
            encoded,
            hashlib.sha256(encoded).hexdigest(),
            safe_root,
            MAX_MANIFEST_BYTES,
        )
        _sync_tree_path(manifest_path, safe_root)
        return EisRejectedEvidence.model_validate({**manifest, "manifest_sha256": manifest_sha})
    except ReflectionError:
        reflected = dict(safe_base)
        reflected["archive_urls"] = ()
        return _failure(reflected, "REFLECTION_REJECTED")
    except QuotaError:
        return _failure(safe_base, "QUOTA_REACHED")
    except UnsafeStoreError:
        return _failure(safe_base, "STORE_UNSAFE")
    except (BindingError, EisFeedContractError, BadZipFile, ValueError):
        return _failure(safe_base, "BINDING_REJECTED")
    except OSError:
        return _failure(safe_base, "IO_FAILED")


class BindingError(ValueError):
    pass


class ReflectionError(ValueError):
    pass


class QuotaError(ValueError):
    pass


class UnsafeStoreError(ValueError):
    pass


def _base(
    window: EisReadyWindow, company: str, reason: RejectionReason, observed: datetime
) -> dict[str, object]:
    return {
        "reason": reason,
        "company_id": company,
        "window_key": window.window_key,
        "observed_at": observed,
        "response_sha256": window.response_sha256,
        "prepared_response_sha256": window.prepared_response_sha256,
        "archive_urls": window.archive_urls,
    }


def _failure(base: dict[str, object], reason: FailureReason) -> EisRejectedEvidence:
    return EisRejectedEvidence(
        status="FAILED",
        retention_reason=reason,
        complete_set=False,
        **base,
    )


def _redact_reflection(base: dict[str, object], token: str) -> dict[str, object]:
    """Keep failure references useful without reflecting caller credentials."""
    if not token:
        return base
    redacted = dict(base)
    if token in str(redacted.get("window_key", "")):
        redacted["window_key"] = "REDACTED"
    archive_urls = redacted.get("archive_urls", ())
    if not isinstance(archive_urls, (tuple, list)):
        archive_urls = ()
    if any(token in str(value) for value in archive_urls):
        redacted["archive_urls"] = ()
    return redacted


def _preflight(window: EisReadyWindow, token: str) -> tuple[str, ...]:
    if (
        not token
        or not 1 <= len(window.archives) <= MAX_ARCHIVES
        or window.expected_archive_count != len(window.archives)
        or len(window.archive_urls) != len(window.archives)
        or len(set(window.archive_urls)) != len(window.archive_urls)
        or sum(map(len, window.archives)) > MAX_COMPRESSED_BYTES
        or any(len(raw) > MAX_ARCHIVE_BYTES for raw in window.archives)
    ):
        raise BindingError()
    secret = token.encode()
    metadata = "\n".join(
        (
            window.window_key,
            window.response_sha256,
            window.prepared_response_sha256 or "",
            *window.archive_urls,
        )
    ).encode()
    if secret in metadata or any(secret in raw for raw in window.archives):
        raise ReflectionError()
    expanded = 0
    digests: list[str] = []
    for url, raw in zip(window.archive_urls, window.archives, strict=True):
        validate_eis_archive_url(url)
        digest = hashlib.sha256(raw).hexdigest()
        if digest in digests:
            raise BindingError()
        digests.append(digest)
        with ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_MEMBERS:
                raise BindingError()
            for info in infos:
                if info.is_dir() or info.file_size > MAX_XML_BYTES or info.flag_bits & 1:
                    raise BindingError()
                expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise BindingError()
                with archive.open(info) as stream:
                    content = stream.read(MAX_XML_BYTES + 1)
                if len(content) != info.file_size:
                    raise BindingError()
                if secret in info.filename.encode(errors="replace") or secret in content:
                    raise ReflectionError()
    return tuple(digests)


def _safe_root(root: Path) -> Path:
    root = root.absolute()
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise UnsafeStoreError()
    missing: list[Path] = []
    current = root
    while not current.exists():
        missing.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise UnsafeStoreError()
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        _fsync_directory(directory.parent)
    if root.is_symlink():
        raise UnsafeStoreError()
    return root.resolve(strict=True)


def _ensure_parent(path: Path, root: Path) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists() and (current.is_symlink() or not current.is_dir()):
            raise UnsafeStoreError()
        if not current.exists():
            current.mkdir(mode=0o700)
            _fsync_directory(current.parent)


def _write_immutable(path: Path, content: bytes, expected: str, root: Path, max_bytes: int) -> None:
    if not path.is_relative_to(root):
        raise UnsafeStoreError()
    if len(content) > max_bytes:
        raise BindingError()
    _ensure_parent(path, root)
    if path.exists():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > max_bytes
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            or not _is_immutable_mode(path)
        ):
            raise UnsafeStoreError()
        _fsync_file(path)
        return
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            if os.name != "nt":
                fchmod = getattr(os, "fchmod", None)
                if fchmod is None:
                    raise OSError("fchmod unavailable")
                fchmod(stream.fileno(), 0o440)
            os.fsync(stream.fileno())
        linked = False
        try:
            os.link(temporary, path)
            linked = True
        except FileExistsError:
            pass
        temporary.unlink(missing_ok=True)
        if linked and os.name == "nt":
            os.chmod(path, 0o440)
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise UnsafeStoreError()
        if not _is_immutable_mode(path):
            raise UnsafeStoreError()
        _fsync_directory(path.parent)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _quota(root: Path, paths: list[Path], raws: tuple[bytes, ...], manifest_bytes: int) -> None:
    current = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise UnsafeStoreError()
        if path.is_file():
            current += path.stat().st_size
    pending = manifest_bytes + sum(
        len(raw) for path, raw in zip(paths, raws, strict=True) if not path.exists()
    )
    if current + pending > MAX_STORE_BYTES:
        raise QuotaError()


def _is_immutable_mode(path: Path) -> bool:
    mode = stat.S_IMODE(path.stat().st_mode)
    # Windows maps its single read-only bit to all three read bits. Production
    # Linux storage must retain the exact owner/group-only contract.
    return mode == (0o444 if os.name == "nt" else 0o440)


def _fsync_directory(path: Path) -> None:
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, os.O_RDONLY | directory_flag)
    except OSError:
        if os.name == "nt":
            return
        raise
    try:
        os.fsync(descriptor)
    except OSError:
        if os.name != "nt":
            raise
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    except OSError:
        if os.name != "nt":
            raise
    finally:
        os.close(descriptor)


def _sync_tree_path(path: Path, root: Path) -> None:
    """Persist every directory link needed to reach a completed manifest."""
    if not path.is_relative_to(root) or not path.exists():
        raise UnsafeStoreError()
    directories = [*reversed(root.parents), root]
    current = root
    for part in path.relative_to(root).parts[:-1]:
        current /= part
        directories.append(current)
    seen: set[Path] = set()
    for directory in directories:
        if directory not in seen:
            _fsync_directory(directory)
            seen.add(directory)


def _identity(
    window: EisReadyWindow, company: str, reason: RejectionReason, digests: tuple[str, ...]
) -> str:
    return hashlib.sha256(
        _json(
            {
                "company_id": company,
                "window_key": window.window_key,
                "response_sha256": window.response_sha256,
                "prepared_response_sha256": window.prepared_response_sha256,
                "archive_urls": window.archive_urls,
                "blob_sha256s": digests,
                "reason": reason,
            }
        )
    ).hexdigest()


def _read_replay(path: Path, root: Path, identity: str) -> EisRejectedEvidence:
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise UnsafeStoreError()
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise UnsafeStoreError()
    raw = path.read_bytes()
    payload = json.loads(raw)
    if "manifest_sha256" in payload:
        raise UnsafeStoreError()
    manifest_sha = hashlib.sha256(raw).hexdigest()
    ref = EisRejectedEvidence.model_validate({**payload, "manifest_sha256": manifest_sha})
    expected = Path(ref.company_id) / "rejected" / identity / "manifest.json"
    if ref.relative_manifest_path != expected.as_posix():
        raise UnsafeStoreError()
    replay_identity = hashlib.sha256(
        _json(
            {
                "company_id": ref.company_id,
                "window_key": ref.window_key,
                "response_sha256": ref.response_sha256,
                "prepared_response_sha256": ref.prepared_response_sha256,
                "archive_urls": ref.archive_urls,
                "blob_sha256s": ref.archive_sha256s,
                "reason": ref.reason,
            }
        )
    ).hexdigest()
    if replay_identity != identity:
        raise UnsafeStoreError()
    if not _is_immutable_mode(path):
        raise UnsafeStoreError()
    _fsync_file(path)
    for digest in ref.archive_sha256s:
        blob = root / ref.company_id / "blobs" / f"{digest}.zip"
        if (
            blob.is_symlink()
            or blob.stat().st_size > MAX_ARCHIVE_BYTES
            or hashlib.sha256(blob.read_bytes()).hexdigest() != digest
            or not _is_immutable_mode(blob)
        ):
            raise UnsafeStoreError()
        _fsync_file(blob)
    return ref


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
