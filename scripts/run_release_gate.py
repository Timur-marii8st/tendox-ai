#!/usr/bin/env python3
"""Prepare and validate one full-source release candidate in disposable Docker.

The command has no selective-check or reuse-success option.  A submission either
completes the reviewed policy and emits one trusted PASS receipt, or exits nonzero
and leaves only a failure record and diagnostic evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from xml.etree import ElementTree

if __package__:
    from .release_gate_receipt import (
        Policy,
        ReceiptError,
        file_sha256,
        json_sha256,
        verify_release_receipt,
    )
else:  # pragma: no cover - exercised by the real script entry point
    from release_gate_receipt import (  # type: ignore[no-redef]
        Policy,
        ReceiptError,
        file_sha256,
        json_sha256,
        verify_release_receipt,
    )

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = Path(__file__).with_name("release_gate_policy.json")
SESSION_LABEL = "com.syurai.release-gate.run"
ROLE_LABEL = "com.syurai.release-gate.role"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,95}$")
ROOT_POSTGRES_PATTERN = re.compile(
    r"os\.getenv\([\"']DATABASE_URL[\"']|storage\s*=\s*storage_fixture"
)


class GateError(RuntimeError):
    """The candidate cannot produce a trusted PASS receipt."""


@dataclass(frozen=True)
class CandidateIdentity:
    kind: str
    archive_sha256: str
    tree_sha256: str
    manifest_sha256: str
    git_head: str
    git_dirty: bool
    deleted_paths: tuple[str, ...]
    file_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "archive_sha256": self.archive_sha256,
            "tree_sha256": self.tree_sha256,
            "manifest_sha256": self.manifest_sha256,
            "git_head": self.git_head,
            "git_dirty": self.git_dirty,
            "deleted_paths": list(self.deleted_paths),
            "file_count": self.file_count,
        }


@dataclass(frozen=True)
class GateContext:
    run_id: str
    run_dir: Path
    source_dir: Path
    reports_dir: Path
    raw_reports_dir: Path
    logs_dir: Path
    control_dir: Path
    policy: Policy
    candidate: CandidateIdentity


@dataclass(frozen=True)
class ExecutionOutcome:
    stages: tuple[Mapping[str, Any], ...]
    artifacts: Mapping[str, Mapping[str, Any]]
    inventory_sha256: str
    explicit_not_performed: tuple[str, ...]


class GateExecutor(Protocol):
    def execute(self, context: GateContext) -> ExecutionOutcome: ...

    def cleanup(self) -> Mapping[str, Any]: ...


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".partial"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_archive_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or path.as_posix() != name
        or ".." in path.parts
        or "." in path.parts
        or "\\" in name
        or "\x00" in name
        or ":" in path.parts[0]
    ):
        raise GateError(f"unsafe archive path: {name!r}")
    return path


def _copy_and_hash(source: Path, destination: Path, maximum_bytes: int) -> str:
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
            copied += len(chunk)
            if copied > maximum_bytes:
                raise GateError("candidate archive exceeds the policy byte limit")
            digest.update(chunk)
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    return digest.hexdigest()


def _validate_manifest(manifest_bytes: bytes, policy: Policy) -> Mapping[str, Any]:
    try:
        value = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError(f"release manifest is invalid: {error}") from error
    if not isinstance(value, dict) or value.get("format_version") != 1:
        raise GateError("release manifest format_version must be 1")
    if value.get("source_kind") not in policy.supported_candidate_kinds:
        raise GateError("release manifest source kind is not supported by policy")
    files = value.get("files")
    if not isinstance(files, list) or not files:
        raise GateError("release manifest must contain files")
    limits = policy.raw.get("limits", {})
    if len(files) > int(limits.get("maximum_files", 5000)):
        raise GateError("release manifest exceeds the policy file-count limit")
    canonical_files: list[Mapping[str, Any]] = []
    names: list[str] = []
    total = 0
    for index, entry_value in enumerate(files):
        if not isinstance(entry_value, dict):
            raise GateError(f"manifest file {index} is not an object")
        name = entry_value.get("path")
        if not isinstance(name, str):
            raise GateError(f"manifest file {index} has no path")
        _safe_archive_name(name)
        byte_count = entry_value.get("bytes")
        mode = entry_value.get("mode")
        sha256 = entry_value.get("sha256")
        if (
            isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count < 0
            or byte_count > int(limits.get("maximum_file_bytes", 25 * 1024 * 1024))
        ):
            raise GateError(f"manifest byte count is invalid: {name}")
        if mode not in {0o644, 0o700}:
            raise GateError(f"manifest mode is invalid: {name}")
        if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
            raise GateError(f"manifest SHA-256 is invalid: {name}")
        names.append(name)
        total += byte_count
        canonical_files.append(entry_value)
    if names != sorted(names) or len(set(names)) != len(names):
        raise GateError("manifest file paths must be sorted and unique")
    if total > int(limits.get("maximum_expanded_bytes", 1024 * 1024 * 1024)):
        raise GateError("release manifest exceeds the expanded-byte limit")
    declared_tree = value.get("tree_sha256")
    if declared_tree != json_sha256(canonical_files):
        raise GateError("release manifest tree SHA-256 is invalid")
    deleted = value.get("deleted_paths")
    if not isinstance(deleted, list) or any(not isinstance(item, str) for item in deleted):
        raise GateError("release manifest deleted_paths must be a string list")
    for name in deleted:
        _safe_archive_name(name)
    if len(set(deleted)) != len(deleted):
        raise GateError("release manifest deleted paths must be unique")
    git_head = value.get("git_head")
    if not isinstance(git_head, str) or not re.fullmatch(r"[0-9a-f]{40}", git_head):
        raise GateError("release manifest git_head is invalid")
    if not isinstance(value.get("git_dirty"), bool):
        raise GateError("release manifest git_dirty must be boolean")
    return value


def seal_candidate_bundle(
    bundle: Path,
    expected_sha256: str,
    context_root: Path,
    policy: Policy,
) -> tuple[CandidateIdentity, Path]:
    """Copy, verify and manually extract one regular-file-only release bundle."""

    if not SHA256_RE.fullmatch(expected_sha256):
        raise GateError("expected candidate SHA-256 must be 64 lowercase hex characters")
    bundle = bundle.resolve(strict=True)
    if bundle.is_symlink() or not bundle.is_file():
        raise GateError("candidate bundle must be a regular non-symlink file")
    control = context_root / "control"
    source_dir = context_root / "source"
    control.mkdir(mode=0o700)
    source_dir.mkdir(mode=0o700)
    sealed_bundle = control / "candidate.tar.gz"
    actual_archive_sha = _copy_and_hash(
        bundle,
        sealed_bundle,
        int(policy.raw.get("limits", {}).get("maximum_archive_bytes", 512 * 1024 * 1024)),
    )
    if actual_archive_sha != expected_sha256:
        raise GateError("candidate archive SHA-256 mismatch")

    try:
        archive = tarfile.open(sealed_bundle, mode="r:gz")  # noqa: SIM115
    except (tarfile.TarError, OSError) as error:
        raise GateError(f"candidate archive cannot be opened: {error}") from error
    with archive:
        limits = policy.raw.get("limits", {})
        maximum_files = int(limits.get("maximum_files", 5000))
        maximum_file_bytes = int(limits.get("maximum_file_bytes", 25 * 1024 * 1024))
        maximum_expanded_bytes = int(limits.get("maximum_expanded_bytes", 1024 * 1024 * 1024))
        members: list[tarfile.TarInfo] = []
        raw_expanded_total = 0
        for member in archive:
            members.append(member)
            if len(members) > maximum_files + 1:
                raise GateError("candidate archive exceeds the policy member-count limit")
            _safe_archive_name(member.name)
            if not member.isfile():
                raise GateError(f"candidate archive member is not a regular file: {member.name}")
            if member.size < 0 or (
                member.name != "release-manifest.json" and member.size > maximum_file_bytes
            ):
                raise GateError(f"candidate archive member exceeds its byte limit: {member.name}")
            raw_expanded_total += member.size
            if raw_expanded_total > maximum_expanded_bytes + 16 * 1024 * 1024:
                raise GateError("candidate archive headers exceed the expanded-byte limit")
        names = [member.name for member in members]
        if len(set(names)) != len(names):
            raise GateError("candidate archive contains duplicate member paths")
        if "release-manifest.json" not in names:
            raise GateError("candidate archive has no release-manifest.json")
        manifest_member = next(
            member for member in members if member.name == "release-manifest.json"
        )
        if manifest_member.size > 16 * 1024 * 1024:
            raise GateError("release manifest exceeds its byte limit")
        manifest_stream = archive.extractfile(manifest_member)
        if manifest_stream is None:
            raise GateError("release manifest cannot be read")
        manifest_bytes = manifest_stream.read(manifest_member.size + 1)
        if len(manifest_bytes) != manifest_member.size:
            raise GateError("release manifest was truncated")
        manifest = _validate_manifest(manifest_bytes, policy)
        entries = {entry["path"]: entry for entry in manifest["files"]}
        if set(names) != set(entries) | {"release-manifest.json"}:
            raise GateError("archive and release manifest file inventories differ")
        header_total = 0
        for member in members:
            if member.name == "release-manifest.json":
                continue
            entry = entries[member.name]
            if member.size != entry["bytes"] or member.size > maximum_file_bytes:
                raise GateError(f"archive member header does not match manifest: {member.name}")
            header_total += member.size
        if header_total > maximum_expanded_bytes:
            raise GateError("candidate archive headers exceed the expanded-byte limit")
        for member in members:
            if member.name == "release-manifest.json":
                content = manifest_bytes
                expected_mode = 0o644
            else:
                stream = archive.extractfile(member)
                if stream is None:
                    raise GateError(f"archive member cannot be read: {member.name}")
                entry = entries[member.name]
                content = stream.read(entry["bytes"] + 1)
                if (
                    len(content) != entry["bytes"]
                    or hashlib.sha256(content).hexdigest() != entry["sha256"]
                ):
                    raise GateError(f"archive member does not match manifest: {member.name}")
                expected_mode = entry["mode"]
            if stat.S_IMODE(member.mode) != expected_mode:
                raise GateError(f"archive member mode does not match manifest: {member.name}")
            relative = _safe_archive_name(member.name)
            destination = source_dir.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise GateError(f"archive extraction collision: {member.name}")
            with destination.open("xb") as output:
                output.write(content)
            os.chmod(destination, 0o500 if expected_mode == 0o700 else 0o400)

    for directory in sorted(
        (path for path in source_dir.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        os.chmod(directory, 0o500)
    os.chmod(source_dir, 0o500)
    identity = CandidateIdentity(
        kind=str(manifest["source_kind"]),
        archive_sha256=actual_archive_sha,
        tree_sha256=str(manifest["tree_sha256"]),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        git_head=str(manifest["git_head"]),
        git_dirty=bool(manifest["git_dirty"]),
        deleted_paths=tuple(str(item) for item in manifest["deleted_paths"]),
        file_count=len(manifest["files"]),
    )
    return identity, source_dir


def _private_state_root(path: Path) -> Path:
    path = path.absolute()
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise GateError("state root must be a real directory, not a link")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise GateError("state root must not be group/world accessible")
    runs = path / "runs"
    if runs.exists() and (runs.is_symlink() or not runs.is_dir()):
        raise GateError("state-root runs path is not an owned directory")
    runs.mkdir(mode=0o700, exist_ok=True)
    return path.resolve(strict=True)


def _new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"release-{stamp}-{secrets.token_hex(6)}"


class ReleaseGateController:
    def __init__(
        self,
        *,
        bundle: Path,
        expected_sha256: str,
        state_root: Path,
        policy_path: Path = DEFAULT_POLICY,
        executor_factory: Any | None = None,
    ) -> None:
        self.bundle = bundle
        self.expected_sha256 = expected_sha256
        self.state_root_argument = state_root
        self.policy_path = policy_path
        self.executor_factory = executor_factory or DockerGateExecutor
        self.run_dir: Path | None = None

    def run(self) -> Path:
        started_at = _utc_now()
        executor: GateExecutor | None = None
        cleanup: Mapping[str, Any] = {"complete": False, "resources": []}
        try:
            policy = Policy.load(self.policy_path)
            state_root = _private_state_root(self.state_root_argument)
            run_id = _new_run_id()
            run_dir = state_root / "runs" / run_id
            run_dir.mkdir(mode=0o700)
            self.run_dir = run_dir
            for name in ("reports", "candidate-output", "logs"):
                (run_dir / name).mkdir(mode=0o700)
            candidate, source_dir = seal_candidate_bundle(
                self.bundle, self.expected_sha256, run_dir, policy
            )
            bound_source = policy.raw.get("candidate_identity")
            if bound_source is not None and any(
                candidate.as_dict().get(key) != value for key, value in bound_source.items()
            ):
                raise GateError("candidate differs from exact branch policy binding")
            context = GateContext(
                run_id=run_id,
                run_dir=run_dir,
                source_dir=source_dir,
                reports_dir=run_dir / "reports",
                raw_reports_dir=run_dir / "candidate-output",
                logs_dir=run_dir / "logs",
                control_dir=run_dir / "control",
                policy=policy,
                candidate=candidate,
            )
            _atomic_json(
                run_dir / "run-state.json",
                {
                    "schema_version": "release-gate-state-v1",
                    "run_id": run_id,
                    "status": "RUNNING",
                    "started_at": started_at,
                    "source": candidate.as_dict(),
                    "policy": {"version": policy.version, "sha256": policy.sha256},
                },
            )
            executor = self.executor_factory()
            outcome = executor.execute(context)
            cleanup = executor.cleanup()
            receipt = self._build_receipt(
                context, outcome, cleanup, started_at=started_at, finished_at=_utc_now()
            )
            receipt_path = run_dir / "release-receipt.json"
            _atomic_json(receipt_path, receipt)
            verify_release_receipt(
                receipt_path,
                state_root=state_root,
                policy_path=policy.path,
                expected_source={
                    "archive_sha256": candidate.archive_sha256,
                    "tree_sha256": candidate.tree_sha256,
                    "manifest_sha256": candidate.manifest_sha256,
                },
            )
            executor = None
            _atomic_json(
                run_dir / "run-state.json",
                {
                    "schema_version": "release-gate-state-v1",
                    "run_id": run_id,
                    "status": "PASS",
                    "complete": True,
                    "receipt": "release-receipt.json",
                    "finished_at": _utc_now(),
                },
            )
            return receipt_path
        except BaseException as error:
            if executor is not None:
                try:
                    reject_artifacts = getattr(executor, "reject_artifacts", None)
                    if callable(reject_artifacts):
                        reject_artifacts()
                    cleanup = executor.cleanup()
                except BaseException as cleanup_error:
                    cleanup = {
                        "complete": False,
                        "resources": [],
                        "error": f"{type(cleanup_error).__name__}: {cleanup_error}",
                    }
            if self.run_dir is not None:
                (self.run_dir / "release-receipt.json").unlink(missing_ok=True)
                _atomic_json(
                    self.run_dir / "failure.json",
                    {
                        "schema_version": "release-gate-failure-v1",
                        "status": "FAIL",
                        "complete": False,
                        "started_at": started_at,
                        "finished_at": _utc_now(),
                        "error": f"{type(error).__name__}: {error}",
                        "cleanup": cleanup,
                    },
                )
            if isinstance(error, KeyboardInterrupt):
                raise GateError("release gate was interrupted") from error
            if isinstance(error, (GateError, ReceiptError)):
                raise
            raise GateError(f"release gate failed: {type(error).__name__}: {error}") from error

    @staticmethod
    def _build_receipt(
        context: GateContext,
        outcome: ExecutionOutcome,
        cleanup: Mapping[str, Any],
        *,
        started_at: str,
        finished_at: str,
    ) -> dict[str, Any]:
        stage_ids = tuple(str(stage.get("id", "")) for stage in outcome.stages)
        if stage_ids != context.policy.required_stage_ids:
            raise GateError("executor did not return the exact ordered required stage set")
        if any(
            stage.get("status") != "PASS" or stage.get("exit_code") != 0 for stage in outcome.stages
        ):
            raise GateError("executor returned an unsuccessful required stage")
        if outcome.inventory_sha256 != context.policy.inventory_sha256:
            raise GateError("executor expanded inventory does not match trusted policy")
        if outcome.explicit_not_performed != context.policy.explicit_not_performed:
            raise GateError("executor omissions do not match trusted policy")
        if cleanup.get("complete") is not True:
            raise GateError("disposable resource cleanup is incomplete")
        return {
            "schema_version": "release-gate-receipt-v1",
            "run_id": context.run_id,
            "status": "PASS",
            "complete": True,
            "started_at": started_at,
            "finished_at": finished_at,
            "policy": {
                "version": context.policy.version,
                "sha256": context.policy.sha256,
            },
            "source": context.candidate.as_dict(),
            "inventory_sha256": outcome.inventory_sha256,
            "stages": list(outcome.stages),
            "artifacts": dict(outcome.artifacts),
            "cleanup": dict(cleanup),
            "explicit_not_performed": list(outcome.explicit_not_performed),
            "authorization_scope": "technical readiness only; no deployment authorization",
        }


def _report_reference(path: Path, run_dir: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(run_dir).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _snapshot_candidate_report(source: Path, destination: Path) -> Path:
    maximum = 128 * 1024 * 1024
    copied = 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        raise GateError(f"candidate test report is missing or unsafe: {source.name}") from error
    try:
        source_stat = os.fstat(descriptor)
        if not stat.S_ISREG(source_stat.st_mode):
            raise GateError(f"candidate test report is not a regular file: {source.name}")
        if source_stat.st_size > maximum:
            raise GateError(f"candidate test report exceeds its byte limit: {source.name}")
        with (
            os.fdopen(descriptor, "rb", closefd=False) as incoming,
            destination.open("xb") as outgoing,
        ):
            for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                copied += len(chunk)
                if copied > maximum:
                    raise GateError(f"candidate test report exceeds its byte limit: {source.name}")
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    finally:
        os.close(descriptor)
    os.chmod(destination, 0o400)
    return destination


def _normalise_pytest_id(value: str) -> str:
    value = value.strip().replace("\\", "/")
    parts: list[str] = []
    start = 0
    bracket_depth = 0
    index = 0
    while index < len(value):
        if value[index] == "[":
            bracket_depth += 1
        elif value[index] == "]" and bracket_depth:
            bracket_depth -= 1
        elif value[index : index + 2] == "::" and bracket_depth == 0:
            parts.append(value[start:index])
            index += 2
            start = index
            continue
        index += 1
    parts.append(value[start:])
    module = parts[0]
    if module.endswith(".py"):
        module = module[:-3].replace("/", ".")
    if len(parts) <= 2:
        return "::".join([module, *parts[1:]])
    return f"{'.'.join([module, *parts[1:-1]])}::{parts[-1]}"


def _junit_counts(
    path: Path,
) -> tuple[dict[str, int], tuple[str, ...], tuple[str, ...]]:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise GateError(f"invalid JUnit report {path.name}: {error}") from error
    cases = list(root.findall(".//testcase"))
    case_ids = tuple(
        sorted(
            _normalise_pytest_id(
                f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
            )
            for case in cases
        )
    )
    if any(test_id.startswith("::") or test_id.endswith("::") for test_id in case_ids):
        raise GateError(f"JUnit report has an incomplete testcase identity: {path.name}")
    if len(set(case_ids)) != len(case_ids):
        raise GateError(f"JUnit report has duplicate testcase identities: {path.name}")
    counts = {
        "tests": len(cases),
        "failures": sum(case.find("failure") is not None for case in cases),
        "errors": sum(case.find("error") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
    }
    suites = [root] if root.tag == "testsuite" else list(root.findall("./testsuite"))
    declared = {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    if declared != counts:
        raise GateError(f"JUnit suite totals differ from testcase nodes: {path.name}")
    skipped = tuple(
        sorted(
            _normalise_pytest_id(
                f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
            )
            for case in cases
            if case.find("skipped") is not None
        )
    )
    return counts, skipped, case_ids


def _collection_ids(output: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            _normalise_pytest_id(line)
            for line in output.splitlines()
            if "::" in line and not line.lstrip().startswith(("=", "<"))
        )
    )


def _node_test_counts(output: str) -> tuple[dict[str, int], tuple[str, ...], str]:
    def metric(name: str) -> int:
        matches = re.findall(rf"^# {re.escape(name)} (\d+)\s*$", output, re.MULTILINE)
        if not matches:
            raise GateError(f"Node test output has no {name} total")
        return int(matches[-1])

    names = tuple(
        sorted(
            match.group(1).strip()
            for match in re.finditer(r"^ok\s+\d+\s+-\s+(.+?)\s*$", output, re.MULTILINE)
        )
    )
    counts = {
        "tests": metric("tests"),
        "failures": metric("fail"),
        "errors": metric("cancelled"),
        "skipped": metric("skipped"),
        "collected": len(names),
    }
    if counts["tests"] != len(names):
        raise GateError("Node test inventory count differs from its TAP collection")
    return counts, (), json_sha256(list(names))


class DockerGateExecutor:
    """Trusted host controller for the reviewed Docker topology."""

    def __init__(self) -> None:
        self.context: GateContext | None = None
        self.docker: tuple[str, ...] = ("docker",)
        self.docker_config_dir: Path | None = None
        self.docker_plugin: Path | None = None
        self.worker_uid: int | None = None
        self.worker_gid: int | None = None
        self.buildx_identity: Mapping[str, Any] = {}
        self.stages: list[dict[str, Any]] = []
        self.resources: list[dict[str, Any]] = []
        self.secrets: set[str] = set()
        self.pg_owner_password: str | None = None
        self.pg_id: str | None = None
        self.python_runner_id: str | None = None
        self.node_runner_id: str | None = None
        self.test_image_id: str | None = None
        self.acquisition_network_name: str | None = None
        self.acquisition_network_id: str | None = None
        self.node_test_network_name: str | None = None
        self.node_test_network_id: str | None = None
        self.artifacts: dict[str, Mapping[str, Any]] = {}
        self.accepted_artifact_resources: list[dict[str, Any]] = []

    @property
    def ctx(self) -> GateContext:
        if self.context is None:
            raise GateError("Docker executor has no active context")
        return self.context

    def _redact(self, data: bytes) -> bytes:
        for secret in self.secrets:
            data = data.replace(secret.encode(), b"<redacted>")
        return data

    def _run(
        self,
        command: Sequence[str],
        *,
        timeout: int,
        stdin: bytes | None = None,
        log_path: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        for name in tuple(environment):
            if name.startswith(("DOCKER_", "BUILDX_", "BUILDKIT_")):
                environment.pop(name)
        try:
            result = subprocess.run(
                list(command),
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            if log_path is not None:
                payload = self._redact((error.stdout or b"") + b"\nTIMEOUT\n")
                log_path.write_bytes(payload)
            raise GateError(f"command timed out after {timeout}s: {command[0]}") from error
        output = self._redact(result.stdout)
        if log_path is not None:
            log_path.write_bytes(output)
        completed = subprocess.CompletedProcess(command, result.returncode, output, None)
        if check and result.returncode != 0:
            raise GateError(f"command failed with exit code {result.returncode}: {command[0]}")
        return completed

    def _docker_capture(self, *arguments: str, timeout: int = 120) -> str:
        result = self._run([*self.docker, *arguments], timeout=timeout)
        return result.stdout.decode("utf-8", errors="replace").strip()

    def _worker_sandbox_options(self, *, test_size: str) -> list[str]:
        if self.worker_uid is None or self.worker_gid is None:
            raise GateError("candidate worker host identity is unavailable")
        owner = f"uid={self.worker_uid},gid={self.worker_gid},mode=0700"
        return [
            "--user",
            f"{self.worker_uid}:{self.worker_gid}",
            "--tmpfs",
            f"/test:rw,exec,nosuid,nodev,size={test_size},{owner}",
            "--tmpfs",
            f"/tmp:rw,nosuid,nodev,size=512m,{owner}",
        ]

    def _assert_worker_path_ownership(self) -> None:
        if self.worker_uid is None or self.worker_gid is None:
            raise GateError("candidate worker host identity is unavailable")
        paths = [self.ctx.source_dir, self.ctx.raw_reports_dir]
        paths.extend(self.ctx.source_dir.rglob("*"))
        for path in paths:
            metadata = path.lstat()
            if metadata.st_uid != self.worker_uid or metadata.st_gid != self.worker_gid:
                raise GateError(f"candidate worker path owner differs from controller: {path}")

    def _assert_worker_container(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        expected_user = f"{self.worker_uid}:{self.worker_gid}"
        actual_user = payload.get("Config", {}).get("User")
        tmpfs = payload.get("HostConfig", {}).get("Tmpfs") or {}
        if actual_user != expected_user or set(tmpfs) != {"/test", "/tmp"}:
            raise GateError("candidate worker user/tmpfs identity differs from controller policy")
        test_options = set(str(tmpfs["/test"]).split(","))
        tmp_options = set(str(tmpfs["/tmp"]).split(","))
        owner_options = {
            f"uid={self.worker_uid}",
            f"gid={self.worker_gid}",
        }
        valid_modes = {"mode=0700", "mode=700", "mode=448"}
        if not {"rw", "exec", "nosuid", "nodev", *owner_options}.issubset(
            test_options
        ) or not test_options.intersection(valid_modes):
            raise GateError("candidate /test tmpfs is not owned writable executable scratch")
        if (
            "noexec" in test_options
            or not {"rw", "nosuid", "nodev", *owner_options}.issubset(tmp_options)
            or not tmp_options.intersection(valid_modes)
        ):
            raise GateError("candidate /tmp tmpfs differs from isolated scratch policy")
        return {"user": actual_user, "tmpfs": tmpfs}

    def _probe_worker_scratch(self, container_id: str, role: str) -> Mapping[str, Any]:
        if role not in {"python", "node"}:
            raise GateError("unsupported candidate worker probe role")
        raw_name = f"{role}-worker-probe.txt"
        self._run(
            [
                *self.docker,
                "exec",
                container_id,
                "sh",
                "-eu",
                "-c",
                "umask 077; printf '#!/bin/sh\\nexit 0\\n' > /test/worker-probe; "
                "chmod 700 /test/worker-probe; /test/worker-probe; "
                f'printf \'{role} worker uid=%s gid=%s\\n\' "$(id -u)" "$(id -g)" '
                f"> /reports/{raw_name}",
            ],
            timeout=30,
        )
        trusted = _snapshot_candidate_report(
            self.ctx.raw_reports_dir / raw_name,
            self.ctx.reports_dir / raw_name,
        )
        expected = f"{role} worker uid={self.worker_uid} gid={self.worker_gid}\n"
        if trusted.read_text(encoding="utf-8") != expected:
            raise GateError(f"{role} worker identity probe differs from controller")
        return _report_reference(trusted, self.ctx.run_dir)

    def _configure_docker_client(self) -> None:
        configuration = self.ctx.policy.raw.get("docker_client")
        if not isinstance(configuration, dict):
            raise GateError("policy has no trusted Docker client configuration")
        if (
            configuration.get("binary") != "/usr/bin/docker"
            or configuration.get("host") != "unix:///var/run/docker.sock"
        ):
            raise GateError("policy Docker binary/endpoint is not the reviewed local engine")
        buildx = configuration.get("buildx")
        if not isinstance(buildx, dict):
            raise GateError("policy has no trusted buildx configuration")
        policy_dir = self.ctx.policy.path.parent
        config_relative = _safe_archive_name(str(buildx.get("config_relative_path", "")))
        plugin_relative = _safe_archive_name(str(buildx.get("plugin_relative_path", "")))
        config_dir = policy_dir.joinpath(*config_relative.parts)
        config_file = config_dir / "config.json"
        plugin = policy_dir.joinpath(*plugin_relative.parts)
        if plugin.parent != config_dir / "cli-plugins":
            raise GateError("trusted buildx plugin is outside its dedicated Docker config")
        for path in (config_dir, config_file, config_dir / "cli-plugins", plugin):
            if path.is_symlink():
                raise GateError("trusted Docker config/plugin must not contain symlinks")
        if (
            not config_file.is_file()
            or config_file.stat().st_size != 3
            or config_file.read_bytes() != b"{}\n"
        ):
            raise GateError("trusted Docker client config is not the reviewed empty config")
        if file_sha256(config_file) != buildx.get("config_sha256"):
            raise GateError("trusted Docker client config SHA-256 mismatch")
        if not plugin.is_file() or plugin.stat().st_size != buildx.get("bytes"):
            raise GateError("trusted buildx plugin is missing or has the wrong size")
        if file_sha256(plugin) != buildx.get("sha256"):
            raise GateError("trusted buildx plugin SHA-256 mismatch")
        if os.name != "nt" and plugin.stat().st_mode & 0o022:
            raise GateError("trusted buildx plugin must not be group/world writable")
        if os.name != "nt" and not os.access(plugin, os.X_OK):
            raise GateError("trusted buildx plugin is not executable")
        buildx_state = self.ctx.control_dir / "buildx-state"
        buildx_state.mkdir(mode=0o700)
        if buildx_state.is_symlink():
            raise GateError("per-run buildx state must not be a symlink")
        prefix = ("sudo", "-n") if os.name != "nt" and shutil.which("sudo") else ()
        self.docker = (
            *prefix,
            "/usr/bin/env",
            f"BUILDX_CONFIG={buildx_state}",
            "/usr/bin/docker",
            "--config",
            str(config_dir),
            "--host",
            str(configuration["host"]),
        )
        self.docker_config_dir = config_dir
        self.docker_plugin = plugin
        self._verify_docker_tool_immutability()
        version = self._docker_capture("buildx", "version")
        if version != buildx.get("version"):
            raise GateError("trusted buildx version differs from policy")
        platform = self._docker_capture("info", "--format", "{{.OSType}}/{{.Architecture}}")
        if platform != configuration.get("engine_platform"):
            raise GateError("Docker engine platform differs from buildx policy")
        builder = str(buildx.get("builder", ""))
        inspect = self._docker_capture("buildx", "inspect", builder)
        driver_match = re.search(r"^Driver:\s+(\S+)\s*$", inspect, re.MULTILINE)
        if driver_match is None or driver_match.group(1) != buildx.get("driver"):
            raise GateError("trusted buildx builder driver differs from policy")
        buildkit_match = re.search(r"^BuildKit version:\s+(\S+)\s*$", inspect, re.MULTILINE)
        if buildkit_match is None or buildkit_match.group(1) != buildx.get("buildkit_version"):
            raise GateError("trusted builder BuildKit version differs from policy")
        self.buildx_identity = {
            "binary": configuration["binary"],
            "endpoint": configuration["host"],
            "config": str(config_relative),
            "config_sha256": buildx["config_sha256"],
            "plugin": str(plugin_relative),
            "plugin_bytes": plugin.stat().st_size,
            "plugin_sha256": buildx["sha256"],
            "plugin_source_url": buildx["source_url"],
            "version": version,
            "binary_platform": buildx["binary_platform"],
            "engine_platform": platform,
            "builder": builder,
            "driver": driver_match.group(1),
            "buildkit": buildkit_match.group(1),
            "state": buildx_state.relative_to(self.ctx.run_dir).as_posix(),
        }

    def _verify_docker_tool_immutability(self) -> None:
        if self.docker_config_dir is None or self.docker_plugin is None:
            raise GateError("trusted Docker tool paths are unavailable")
        expected_files = {
            self.docker_config_dir / "config.json",
            self.docker_plugin,
        }
        actual_files: set[Path] = set()
        for path in self.docker_config_dir.rglob("*"):
            if path.is_symlink():
                raise GateError("immutable Docker tool bundle acquired a symlink")
            if path.is_file():
                actual_files.add(path)
        if actual_files != expected_files:
            raise GateError("immutable Docker tool bundle inventory changed")
        buildx = self.ctx.policy.raw["docker_client"]["buildx"]
        config_file = self.docker_config_dir / "config.json"
        if (
            config_file.read_bytes() != b"{}\n"
            or file_sha256(config_file) != buildx["config_sha256"]
            or self.docker_plugin.stat().st_size != buildx["bytes"]
            or file_sha256(self.docker_plugin) != buildx["sha256"]
        ):
            raise GateError("immutable Docker tool bundle content changed")

    def _stage(
        self,
        stage_id: str,
        command: Sequence[str],
        *,
        timeout: int,
        stdin: bytes | None = None,
        junit: Path | None = None,
        collection_command: Sequence[str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        if stage_id != self.ctx.policy.required_stage_ids[len(self.stages)]:
            raise GateError(f"executor stage order diverged at {stage_id}")
        started = _utc_now()
        reports: list[Mapping[str, Any]] = []
        collection_sha: str | None = None
        collection_count: int | None = None
        if collection_command is not None:
            collection_log = self.ctx.logs_dir / f"{stage_id}-collect.log"
            collection = self._run(
                collection_command,
                timeout=timeout,
                log_path=collection_log,
                check=False,
            )
            reports.append(_report_reference(collection_log, self.ctx.run_dir))
            if collection.returncode != 0:
                self.stages.append(
                    self._stage_payload(
                        stage_id,
                        started,
                        collection.returncode,
                        reports,
                        {},
                        (),
                        None,
                        command,
                    )
                )
                raise GateError(f"test collection failed for {stage_id}")
            ids = _collection_ids(collection.stdout.decode("utf-8", errors="replace"))
            if not ids:
                raise GateError(f"test collection was empty for {stage_id}")
            collection_sha = json_sha256(list(ids))
            collection_count = len(ids)
        log_path = self.ctx.logs_dir / f"{stage_id}.log"
        result = self._run(command, timeout=timeout, stdin=stdin, log_path=log_path, check=False)
        reports.append(_report_reference(log_path, self.ctx.run_dir))
        counts: dict[str, int] = {}
        skipped: tuple[str, ...] = ()
        if junit is not None:
            trusted_junit = _snapshot_candidate_report(junit, self.ctx.reports_dir / junit.name)
            counts, skipped, executed_ids = _junit_counts(trusted_junit)
            if collection_count is None or executed_ids != ids:
                raise GateError(f"executed and collected test identities differ for {stage_id}")
            counts["collected"] = collection_count
            reports.append(_report_reference(trusted_junit, self.ctx.run_dir))
        payload = self._stage_payload(
            stage_id,
            started,
            result.returncode,
            reports,
            counts,
            skipped,
            collection_sha,
            command,
        )
        self.stages.append(payload)
        if result.returncode != 0:
            raise GateError(f"required stage failed: {stage_id}")
        return result

    def _stage_payload(
        self,
        stage_id: str,
        started: str,
        return_code: int,
        reports: Sequence[Mapping[str, Any]],
        counts: Mapping[str, int],
        skipped: Sequence[str],
        collection_sha: str | None,
        command: Sequence[str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": stage_id,
            "status": "PASS" if return_code == 0 else "FAIL",
            "exit_code": return_code,
            "started_at": started,
            "finished_at": _utc_now(),
            "command": list(command),
            "counts": dict(counts),
            "skipped_test_ids": list(skipped),
            "reports": list(reports),
        }
        if collection_sha is not None:
            payload["collection_sha256"] = collection_sha
        return payload

    def _internal_stage(self, stage_id: str, payload: Mapping[str, Any]) -> None:
        if stage_id != self.ctx.policy.required_stage_ids[len(self.stages)]:
            raise GateError(f"executor stage order diverged at {stage_id}")
        report = self.ctx.reports_dir / f"{stage_id}.json"
        _atomic_json(report, payload)
        self.stages.append(
            {
                "id": stage_id,
                "status": "PASS",
                "exit_code": 0,
                "started_at": _utc_now(),
                "finished_at": _utc_now(),
                "command": ["trusted-controller", stage_id],
                "counts": {},
                "skipped_test_ids": [],
                "reports": [_report_reference(report, self.ctx.run_dir)],
            }
        )

    def _resource_name(self, suffix: str) -> str:
        compact = self.ctx.run_id.replace("release-", "rg-")
        return f"{compact}-{suffix}"[:120]

    def _image_policy(self, key: str) -> Mapping[str, Any]:
        runtime = self.ctx.policy.raw.get("runtime_images")
        if not isinstance(runtime, dict) or not isinstance(runtime.get(key), dict):
            raise GateError(f"policy has no runtime image: {key}")
        return runtime[key]

    def _assert_image(self, key: str) -> Mapping[str, Any]:
        image = self._image_policy(key)
        reference = str(image.get("reference", ""))
        expected_id = str(image.get("image_id", ""))
        try:
            raw = self._docker_capture("image", "inspect", reference)
        except GateError:
            self._docker_capture("pull", reference, timeout=900)
            raw = self._docker_capture("image", "inspect", reference)
        payload = json.loads(raw)[0]
        if payload.get("Id") != expected_id:
            raise GateError(f"runtime image identity mismatch: {key}")
        return payload

    def _register_resource(
        self,
        kind: str,
        name: str,
        identity: str,
        role: str,
        *,
        provisional_artifact: bool = False,
    ) -> None:
        if any(
            resource["kind"] == kind and resource["id"] == identity for resource in self.resources
        ):
            return
        self.resources.append(
            {
                "kind": kind,
                "name": name,
                "id": identity,
                "role": role,
                "identity_verified": False,
                "removed": False,
                "provisional_artifact": provisional_artifact,
            }
        )

    def _discover_resource(
        self,
        kind: str,
        name: str,
        role: str,
        *,
        provisional_artifact: bool = False,
    ) -> str | None:
        command = (
            [*self.docker, "image", "inspect", name]
            if kind == "image"
            else [*self.docker, "network", "inspect", name]
            if kind == "network"
            else [*self.docker, "inspect", name]
        )
        result = self._run(command, timeout=60, check=False)
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout)[0]
        labels = (
            payload.get("Labels") or {}
            if kind == "network"
            else payload.get("Config", {}).get("Labels") or {}
        )
        if labels.get(SESSION_LABEL) != self.ctx.run_id or labels.get(ROLE_LABEL) != role:
            raise GateError(f"Docker resource appeared without exact ownership labels: {name}")
        identity = str(payload["Id"])
        self._register_resource(
            kind,
            name,
            identity,
            role,
            provisional_artifact=provisional_artifact,
        )
        return identity

    def _create_network(self, suffix: str, role: str, *, internal: bool) -> tuple[str, str]:
        name = self._resource_name(suffix)
        command = [*self.docker, "network", "create"]
        if internal:
            command.append("--internal")
        command.extend(
            [
                "--label",
                f"{SESSION_LABEL}={self.ctx.run_id}",
                "--label",
                f"{ROLE_LABEL}={role}",
                name,
            ]
        )
        try:
            self._docker_capture(*command[len(self.docker) :])
        finally:
            identity = self._discover_resource("network", name, role)
        if identity is None:
            raise GateError(f"Docker network creation left no owned resource: {name}")
        return name, identity

    def _ensure_acquisition_network(self) -> tuple[str, str]:
        if self.acquisition_network_name is None or self.acquisition_network_id is None:
            self.acquisition_network_name, self.acquisition_network_id = self._create_network(
                "acqnet", "dependency-acquisition-network", internal=False
            )
        return self.acquisition_network_name, self.acquisition_network_id

    def _trusted_inventory(self) -> Mapping[str, Any]:
        expected = self.ctx.policy.raw["scope"]["expanded_inventory"]
        source = self.ctx.source_dir
        actual_web_tests = sorted(
            path.relative_to(source / "web").as_posix()
            for path in (source / "web" / "tests").rglob("*")
            if path.is_file() and re.search(r"\.test\.tsx?$", path.name)
        )
        actual_web_configs = sorted(
            path.name for path in (source / "web").glob("tsconfig.*-tests.json")
        )
        groups = expected.get("postgres_groups", [])
        mandatory_paths = sorted(str(path) for group in groups for path in group.get("paths", []))
        optional_paths = sorted(
            str(item["path"]) for item in expected.get("optional_integration", [])
        )
        actual_integration = sorted(
            path.relative_to(source).as_posix()
            for path in (source / "tests" / "integration").glob("test_*.py")
        )
        expected_integration = sorted(
            path
            for path in mandatory_paths + optional_paths
            if path.startswith("tests/integration/")
        )
        root_pg = sorted(
            path.relative_to(source).as_posix()
            for path in (source / "tests").glob("test_*.py")
            if ROOT_POSTGRES_PATTERN.search(path.read_text(encoding="utf-8"))
        )
        expected_root = sorted(
            path
            for path in mandatory_paths
            if path.startswith("tests/") and "/integration/" not in path
        )
        if actual_web_tests != expected.get("web_tests"):
            raise GateError("trusted web test inventory differs from policy")
        if actual_web_configs != expected.get("web_configs"):
            raise GateError("trusted web config inventory differs from policy")
        if actual_integration != expected_integration:
            raise GateError("trusted integration module inventory differs from policy")
        if root_pg != expected_root:
            raise GateError("trusted root PostgreSQL module inventory differs from policy")
        for path in mandatory_paths:
            if not (source / path).is_file():
                raise GateError(f"policy PostgreSQL module is missing: {path}")
        return expected

    def _prepare_runtime(self) -> None:
        docker_version = self._docker_capture("version", "--format", "{{.Server.Version}}")
        images = {key: self._assert_image(key).get("Id") for key in ("python", "node", "postgres")}
        conflicts: list[str] = []
        existing_containers = set(
            self._docker_capture("ps", "-a", "--format", "{{.Names}}").splitlines()
        )
        for suffix in ("pg", "python", "node", "api-smoke", "web-smoke"):
            name = self._resource_name(suffix)
            if name in existing_containers:
                conflicts.append(name)
        existing_networks = set(
            self._docker_capture("network", "ls", "--format", "{{.Name}}").splitlines()
        )
        for suffix in ("pgnet", "acqnet", "webtestnet"):
            name = self._resource_name(suffix)
            if name in existing_networks:
                conflicts.append(name)
        if conflicts:
            raise GateError(f"unowned Docker resource names already exist: {sorted(conflicts)}")
        self._internal_stage(
            "runtime-prerequisites",
            {
                "docker_server_version": docker_version,
                "runtime_image_ids": images,
                "docker_client": dict(self.buildx_identity),
                "candidate_worker_identity": {
                    "uid": self.worker_uid,
                    "gid": self.worker_gid,
                },
                "host_network_forbidden": True,
                "production_mounts_forbidden": True,
                "dependency_acquisition_exception": (
                    "Docker default build networking is used only for pinned dependency "
                    "layers/reviewed image builds; npm ci uses a dedicated bridge"
                ),
            },
        )

    def _build_python_runtime(self) -> None:
        image = self._image_policy("python")
        tag = self._resource_name("python-runtime")
        acquisition_network = "default"
        dockerfile = self.ctx.control_dir / "Dockerfile.python-runtime"
        uv_version = str(self.ctx.policy.raw.get("tool_versions", {}).get("uv", ""))
        dockerfile.write_text(
            f"""FROM {image["reference"]}
LABEL {SESSION_LABEL}={self.ctx.run_id} {ROLE_LABEL}=python-runtime
USER 0
RUN python -m pip install --timeout 300 --no-cache-dir uv=={uv_version}
COPY pyproject.toml uv.lock /opt/dependencies/
WORKDIR /opt/dependencies
RUN UV_HTTP_TIMEOUT=300 \\
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_CACHE_DIR=/opt/uv-cache UV_LINK_MODE=copy \\
    uv sync --frozen --extra dev --no-install-project
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH PYTHONPATH=/workspace/src:/workspace \\
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_CACHE_DIR=/test/uv-cache \\
    RUFF_CACHE_DIR=/test/ruff-cache MYPY_CACHE_DIR=/test/mypy-cache \\
    PYTHONPYCACHEPREFIX=/test/pycache TMPDIR=/test/tmp HOME=/test/home \\
    PYTHONDONTWRITEBYTECODE=1 UV_NO_SYNC=1
WORKDIR /workspace
ENTRYPOINT []
CMD ["sleep", "infinity"]
""",
            encoding="utf-8",
        )
        command = [
            *self.docker,
            "buildx",
            "build",
            "--builder",
            "default",
            "--load",
            "--progress=plain",
            "--pull=false",
            "--network",
            acquisition_network,
            "--label",
            f"{SESSION_LABEL}={self.ctx.run_id}",
            "--label",
            f"{ROLE_LABEL}=python-runtime",
            "--tag",
            tag,
            "--file",
            str(dockerfile),
            str(self.ctx.source_dir),
        ]
        try:
            self._stage(
                "python-runtime-build",
                command,
                timeout=int(self.ctx.policy.raw["limits"]["build_timeout_seconds"]),
            )
        finally:
            self._discover_resource("image", tag, "python-runtime")
        payload = json.loads(self._docker_capture("image", "inspect", tag))[0]
        self.test_image_id = str(payload["Id"])
        labels = payload.get("Config", {}).get("Labels") or {}
        if (
            labels.get(SESSION_LABEL) != self.ctx.run_id
            or labels.get(ROLE_LABEL) != "python-runtime"
        ):
            raise GateError("derived Python runtime image labels are invalid")
        self.stages[-1]["dependency_acquisition_network"] = acquisition_network

    def _start_postgres(self) -> None:
        pg_network, network_id = self._create_network("pgnet", "postgres-network", internal=True)
        owner_password = secrets.token_hex(32)
        self.secrets.add(owner_password)
        self.pg_owner_password = owner_password
        env_file = self.ctx.control_dir / "postgres.env"
        env_file.write_text(
            "POSTGRES_DB=postgres\nPOSTGRES_USER=procurement_owner\n"
            f"POSTGRES_PASSWORD={owner_password}\n",
            encoding="utf-8",
        )
        os.chmod(env_file, 0o600)
        pg_name = self._resource_name("pg")
        pg_reference = str(self._image_policy("postgres")["reference"])
        try:
            self.pg_id = self._docker_capture(
                "run",
                "--detach",
                "--pull",
                "never",
                "--name",
                pg_name,
                "--network",
                pg_network,
                "--memory",
                "1536m",
                "--cpus",
                "1",
                "--label",
                f"{SESSION_LABEL}={self.ctx.run_id}",
                "--label",
                f"{ROLE_LABEL}=postgres",
                "--env-file",
                str(env_file),
                pg_reference,
            )
        finally:
            discovered = self._discover_resource("container", pg_name, "postgres")
        env_file.unlink(missing_ok=True)
        if discovered is None or self.pg_id != discovered:
            raise GateError("disposable PostgreSQL identity could not be established")
        ready = False
        for _ in range(60):
            result = self._run(
                [*self.docker, "exec", self.pg_id, "pg_isready", "-U", "procurement_owner"],
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                ready = True
                break
            time.sleep(1)
        if not ready:
            raise GateError("disposable PostgreSQL did not become ready")
        inspect = json.loads(self._docker_capture("inspect", self.pg_id))[0]
        ports = inspect.get("NetworkSettings", {}).get("Ports") or {}
        if any(value for value in ports.values()):
            raise GateError("disposable PostgreSQL unexpectedly publishes a host port")
        self._internal_stage(
            "postgres-start",
            {
                "container_id": self.pg_id,
                "network_id": network_id,
                "published_ports": False,
                "network_internal": True,
            },
        )

    def _start_python_runner(self) -> None:
        if self.pg_id is None or self.test_image_id is None:
            raise GateError("Python runner prerequisites are incomplete")
        name = self._resource_name("python")
        try:
            self.python_runner_id = self._docker_capture(
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                f"container:{self.pg_id}",
                "--read-only",
                "--memory",
                "3g",
                "--cpus",
                "2.5",
                *self._worker_sandbox_options(test_size="1g"),
                "--volume",
                f"{self.ctx.source_dir}:/workspace:ro",
                "--volume",
                f"{self.ctx.raw_reports_dir}:/reports:rw",
                "--label",
                f"{SESSION_LABEL}={self.ctx.run_id}",
                "--label",
                f"{ROLE_LABEL}=python-runner",
                self.test_image_id,
            )
        finally:
            discovered = self._discover_resource("container", name, "python-runner")
        if discovered is None or self.python_runner_id != discovered:
            raise GateError("Python runner identity could not be established")
        self._run(
            [
                *self.docker,
                "exec",
                self.python_runner_id,
                "mkdir",
                "-p",
                "/test/tmp",
                "/test/home",
            ],
            timeout=30,
        )
        inspect = json.loads(self._docker_capture("inspect", self.python_runner_id))[0]
        sandbox = self._assert_worker_container(inspect)
        host_config = inspect.get("HostConfig", {})
        if host_config.get("NetworkMode") != f"container:{self.pg_id}":
            raise GateError("Python runner does not share the exact disposable PG namespace")
        mounts = inspect.get("Mounts", [])
        if any(mount.get("Destination") not in {"/workspace", "/reports"} for mount in mounts):
            raise GateError("Python runner received an unexpected host mount")
        versions = self._docker_capture(
            "exec",
            self.python_runner_id,
            "sh",
            "-c",
            "python --version 2>&1; uv --version; "
            "dpkg-query -W -f='${Package}=${Version}\\n' | LC_ALL=C sort",
        )
        probe_report = self._probe_worker_scratch(self.python_runner_id, "python")
        self._internal_stage(
            "python-runner-start",
            {
                "container_id": self.python_runner_id,
                "network_mode": f"container:{self.pg_id}",
                "source_read_only": True,
                "docker_socket_mounted": False,
                "production_environment_loaded": False,
                "sandbox": sandbox,
                "runtime_inventory": versions.splitlines(),
                "dependency_locks": {
                    "pyproject.toml": file_sha256(self.ctx.source_dir / "pyproject.toml"),
                    "uv.lock": file_sha256(self.ctx.source_dir / "uv.lock"),
                },
            },
        )
        self.stages[-1]["reports"].append(probe_report)

    def _python_command(self, *arguments: str) -> list[str]:
        if self.python_runner_id is None:
            raise GateError("Python runner is unavailable")
        timeout = int(self.ctx.policy.raw["limits"]["command_timeout_seconds"])
        return [
            *self.docker,
            "exec",
            self.python_runner_id,
            "timeout",
            "--signal=KILL",
            str(timeout),
            *arguments,
        ]

    def _python_quality(self) -> None:
        timeout = int(self.ctx.policy.raw["limits"]["command_timeout_seconds"]) + 30
        self._stage(
            "docs-navigation",
            self._python_command(
                "python", "scripts/check_docs.py",
                *(["--layout", "legacy-flat"] if self.ctx.policy.raw.get(
                    "documentation_layout"
                ) == "legacy-flat" else []),
            ),
            timeout=timeout,
        )
        scope = self._stage(
            "quality-scope",
            self._python_command("python", "scripts/check_quality_scope.py", "--check"),
            timeout=timeout,
        )
        inventory = self._trusted_inventory()
        inventory_report = self.ctx.reports_dir / "expanded-inventory.json"
        _atomic_json(inventory_report, inventory)
        self.stages[-1]["reports"].append(_report_reference(inventory_report, self.ctx.run_dir))
        scope_output = scope.stdout.decode("utf-8", errors="replace")
        groups = inventory["postgres_groups"]
        scope_marker = (
            f"PostgreSQL: {sum(len(group['paths']) for group in groups)} executable modules "
            f"in {len(groups)} fresh-DB groups"
        )
        if scope_marker not in scope_output:
            raise GateError("candidate quality-scope report does not confirm mandatory PG scope")
        self._stage(
            "lock-check",
            self._python_command("uv", "lock", "--check", "--offline"),
            timeout=timeout,
        )
        self._stage(
            "ruff",
            self._python_command("uv", "run", "--no-sync", "ruff", "check", "."),
            timeout=timeout,
        )
        self._stage(
            "mypy-domain",
            self._python_command("uv", "run", "--no-sync", "mypy", "src/procurement/domain"),
            timeout=timeout,
        )
        unit_xml = self.ctx.raw_reports_dir / "python-unit.xml"
        unit = [
            "uv",
            "run",
            "--no-sync",
            "pytest",
            "tests",
            "--ignore=tests/integration",
            "-q",
            "-rs",
            "--junitxml=/reports/python-unit.xml",
            "-o",
            "cache_dir=/test/pytest-unit",
        ]
        collect = [
            *unit[:4],
            "--collect-only",
            "tests",
            "--ignore=tests/integration",
        ]
        self._stage(
            "python-unit",
            self._python_command(*unit),
            timeout=timeout,
            junit=unit_xml,
            collection_command=self._python_command(*collect),
        )
        doctest_xml = self.ctx.raw_reports_dir / "domain-doctest.xml"
        doctest = [
            "uv",
            "run",
            "--no-sync",
            "python",
            "-m",
            "pytest",
            "--doctest-modules",
            "src/procurement/domain",
            "-q",
            "--junitxml=/reports/domain-doctest.xml",
            "-o",
            "cache_dir=/test/pytest-doctest",
        ]
        doctest_collect = [
            *doctest[:6],
            "--collect-only",
            "--doctest-modules",
            "src/procurement/domain",
        ]
        self._stage(
            "domain-doctest",
            self._python_command(*doctest),
            timeout=timeout,
            junit=doctest_xml,
            collection_command=self._python_command(*doctest_collect),
        )

    def _start_node_runner(self) -> None:
        node_network, network_id = self._ensure_acquisition_network()
        self.node_test_network_name, self.node_test_network_id = self._create_network(
            "webtestnet", "node-test-network", internal=True
        )
        name = self._resource_name("node")
        reference = str(self._image_policy("node")["reference"])
        try:
            self.node_runner_id = self._docker_capture(
                "run",
                "--detach",
                "--pull",
                "never",
                "--name",
                name,
                "--network",
                node_network,
                "--read-only",
                "--memory",
                "3g",
                "--cpus",
                "2.5",
                *self._worker_sandbox_options(test_size="2g"),
                "--env",
                "HOME=/test/home",
                "--env",
                "npm_config_cache=/test/npm-cache",
                "--volume",
                f"{self.ctx.source_dir}:/source:ro",
                "--volume",
                f"{self.ctx.raw_reports_dir}:/reports:rw",
                "--workdir",
                "/test",
                "--label",
                f"{SESSION_LABEL}={self.ctx.run_id}",
                "--label",
                f"{ROLE_LABEL}=node-runner",
                reference,
                "sleep",
                "infinity",
            )
        finally:
            discovered = self._discover_resource("container", name, "node-runner")
        if discovered is None or self.node_runner_id != discovered:
            raise GateError("Node runner identity could not be established")
        self._run(
            [
                *self.docker,
                "exec",
                self.node_runner_id,
                "mkdir",
                "-p",
                "/test/web",
                "/test/scripts",
                "/test/home",
                "/test/npm-cache",
            ],
            timeout=30,
        )
        inspect = json.loads(self._docker_capture("inspect", self.node_runner_id))[0]
        sandbox = self._assert_worker_container(inspect)
        if inspect.get("HostConfig", {}).get("NetworkMode") != node_network:
            raise GateError("Node runner is not attached to its dedicated network")
        versions = self._docker_capture(
            "exec",
            self.node_runner_id,
            "sh",
            "-c",
            "node --version; npm --version; "
            "dpkg-query -W -f='${Package}=${Version}\\n' | LC_ALL=C sort",
        )
        probe_report = self._probe_worker_scratch(self.node_runner_id, "node")
        self._internal_stage(
            "node-runner-start",
            {
                "container_id": self.node_runner_id,
                "network_id": network_id,
                "test_network_id": self.node_test_network_id,
                "source_read_only": True,
                "docker_socket_mounted": False,
                "production_environment_loaded": False,
                "initial_network_purpose": "dependency acquisition only",
                "sandbox": sandbox,
                "runtime_inventory": versions.splitlines(),
                "dependency_locks": {
                    "web/package.json": file_sha256(self.ctx.source_dir / "web" / "package.json"),
                    "web/package-lock.json": file_sha256(
                        self.ctx.source_dir / "web" / "package-lock.json"
                    ),
                },
            },
        )
        self.stages[-1]["reports"].append(probe_report)

    def _node_command(self, *arguments: str) -> list[str]:
        if self.node_runner_id is None:
            raise GateError("Node runner is unavailable")
        timeout = int(self.ctx.policy.raw["limits"]["command_timeout_seconds"])
        return [
            *self.docker,
            "exec",
            "--workdir",
            "/test/web",
            self.node_runner_id,
            "timeout",
            "--signal=KILL",
            str(timeout),
            *arguments,
        ]

    def _web_quality(self) -> None:
        timeout = int(self.ctx.policy.raw["limits"]["command_timeout_seconds"]) + 30
        self._stage(
            "web-install",
            self._node_command(
                "sh",
                "-eu",
                "-c",
                "cp -a /source/web/. /test/web/ && chmod -R u+rwX /test/web "
                "&& cp /source/scripts/run-web-tests.mjs /test/scripts/run-web-tests.mjs "
                "&& npm ci --ignore-scripts --no-audit --no-fund",
            ),
            timeout=timeout,
        )
        if self.node_test_network_name is None or self.node_runner_id is None:
            raise GateError("Node test network is unavailable")
        self._docker_capture(
            "network", "disconnect", self._resource_name("acqnet"), self.node_runner_id
        )
        self._docker_capture("network", "connect", self.node_test_network_name, self.node_runner_id)
        inspect = json.loads(self._docker_capture("inspect", self.node_runner_id))[0]
        attached = inspect.get("NetworkSettings", {}).get("Networks") or {}
        if set(attached) != {self.node_test_network_name}:
            raise GateError("Node runner retained a non-test network after acquisition")
        rebuild_log = self.ctx.logs_dir / "web-install-offline-rebuild.log"
        rebuild = self._run(
            self._node_command("npm", "rebuild", "--offline", "--no-audit", "--no-fund"),
            timeout=timeout,
            log_path=rebuild_log,
            check=False,
        )
        self.stages[-1]["reports"].append(_report_reference(rebuild_log, self.ctx.run_dir))
        self.stages[-1]["network_transition"] = {
            "acquisition_network_detached": True,
            "test_network": self.node_test_network_name,
            "test_network_internal": True,
            "offline_lifecycle_rebuild": True,
        }
        if rebuild.returncode != 0:
            self.stages[-1]["status"] = "FAIL"
            self.stages[-1]["exit_code"] = rebuild.returncode
            raise GateError("offline Node lifecycle rebuild failed")
        self._stage(
            "web-lint",
            self._node_command("npm", "run", "lint"),
            timeout=timeout,
        )
        result = self._stage(
            "web-tests",
            self._node_command("npm", "test"),
            timeout=timeout,
        )
        counts, skipped, collection_sha = _node_test_counts(
            result.stdout.decode("utf-8", errors="replace")
        )
        self.stages[-1]["counts"] = counts
        self.stages[-1]["skipped_test_ids"] = list(skipped)
        self.stages[-1]["collection_sha256"] = collection_sha
        self._stage(
            "web-build",
            self._node_command("npm", "run", "build"),
            timeout=int(self.ctx.policy.raw["limits"]["build_timeout_seconds"]),
        )

    def _recreate_database(self, database: str, app_password: str) -> None:
        if not re.fullmatch(r"procurement_[a-z0-9_]+", database):
            raise GateError(f"unsafe policy database name: {database!r}")
        if self.pg_id is None or self.pg_owner_password is None:
            raise GateError("PostgreSQL is unavailable")
        sql = f"""
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = '{database}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS \"{database}\";
DO $role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'procurement_app') THEN
    CREATE ROLE procurement_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END;
$role$;
ALTER ROLE procurement_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
 PASSWORD '{app_password}';
CREATE DATABASE \"{database}\" OWNER procurement_owner;
\\connect \"{database}"
GRANT CONNECT ON DATABASE \"{database}\" TO procurement_app;
GRANT USAGE ON SCHEMA public TO procurement_app;
""".encode()
        self._run(
            [
                *self.docker,
                "exec",
                "--interactive",
                self.pg_id,
                "psql",
                "--set=ON_ERROR_STOP=1",
                "--username=procurement_owner",
                "--dbname=postgres",
            ],
            timeout=120,
            stdin=sql,
        )

    def _write_pg_environment(self, database: str, app_password: str, group: str) -> None:
        if self.python_runner_id is None or self.pg_owner_password is None:
            raise GateError("Python/PostgreSQL environment is unavailable")
        self.secrets.add(app_password)
        fixtures = self.ctx.source_dir / "tests" / "fixtures" / "eis_release_baselines"
        values = {
            "DATABASE_ADMIN_URL": (
                "postgresql+psycopg://procurement_owner:"
                f"{self.pg_owner_password}@127.0.0.1:5432/{database}"
            ),
            "DATABASE_URL": (
                f"postgresql+psycopg://procurement_app:{app_password}@127.0.0.1:5432/{database}"
            ),
            "POSTGRES_EXPECTED_MAJOR": "16",
            "QUALITY_GATE_DISPOSABLE_POSTGRES": "1",
            "S206_BASELINE_ANALOGS_PATH": "/workspace/"
            + (fixtures / "s205_eis_analogs.py").relative_to(self.ctx.source_dir).as_posix(),
            "S208_BASELINE_ANALOGS_PATH": "/workspace/"
            + (fixtures / "s206_eis_analogs.py").relative_to(self.ctx.source_dir).as_posix(),
            "S209_BASELINE_ANALOGS_PATH": "/workspace/"
            + (fixtures / "s208_eis_analogs.py").relative_to(self.ctx.source_dir).as_posix(),
            "S209_BASELINE_HOLD_PATH": "/workspace/"
            + (fixtures / "s208_eis_notice_hold.py").relative_to(self.ctx.source_dir).as_posix(),
        }
        content = "".join(f"{key}={value}\n" for key, value in values.items()).encode()
        self._run(
            [
                *self.docker,
                "exec",
                "--interactive",
                self.python_runner_id,
                "sh",
                "-c",
                "umask 077; cat > /test/postgres.env",
            ],
            timeout=30,
            stdin=content,
        )
        if not SAFE_ID_RE.fullmatch(group):
            raise GateError("unsafe policy PostgreSQL group id")

    def _pg_shell_command(self, *arguments: str) -> list[str]:
        quoted = " ".join(_shell_quote(argument) for argument in arguments)
        return self._python_command(
            "sh",
            "-eu",
            "-c",
            f"set -a; . /test/postgres.env; set +a; exec {quoted}",
        )

    def _postgres_quality(self) -> None:
        groups = self.ctx.policy.raw["scope"]["expanded_inventory"]["postgres_groups"]
        timeout = int(self.ctx.policy.raw["limits"]["command_timeout_seconds"]) + 30
        for group in groups:
            group_id = str(group["group"])
            database = str(group["database"])
            paths = [str(path) for path in group["paths"]]
            app_password = secrets.token_hex(32)
            self._recreate_database(database, app_password)
            self._write_pg_environment(database, app_password, group_id)
            self._stage(
                f"pg-{group_id}-migrate",
                self._pg_shell_command("uv", "run", "--no-sync", "alembic", "upgrade", "head"),
                timeout=timeout,
            )
            junit = self.ctx.raw_reports_dir / f"postgres-{group_id}.xml"
            test_args = [
                "uv",
                "run",
                "--no-sync",
                "pytest",
                *paths,
                "--require-postgres",
                "-q",
                f"--junitxml=/reports/postgres-{group_id}.xml",
                "-o",
                f"cache_dir=/test/pytest-pg-{group_id}",
            ]
            collect_args = [
                "uv",
                "run",
                "--no-sync",
                "pytest",
                "--collect-only",
                *paths,
            ]
            self._stage(
                f"pg-{group_id}-tests",
                self._pg_shell_command(*test_args),
                timeout=timeout,
                junit=junit,
                collection_command=self._pg_shell_command(*collect_args),
            )
        if self.python_runner_id is not None:
            self._run(
                [*self.docker, "exec", self.python_runner_id, "rm", "-f", "/test/postgres.env"],
                timeout=30,
                check=False,
            )

    def _build_artifact(self, kind: str) -> None:
        if kind not in {"api", "web"}:
            raise GateError("unsupported artifact kind")
        base = self._image_policy("python" if kind == "api" else "node")
        recipes = self.ctx.policy.raw.get("build_recipes")
        if not isinstance(recipes, dict) or set(recipes) != {"api", "web"}:
            raise GateError("policy build recipe allowlist is incomplete")
        recipe = recipes.get(kind)
        if not isinstance(recipe, dict) or set(recipe) != {"path", "sha256"}:
            raise GateError(f"policy {kind} build recipe is malformed")
        if recipe["path"] != f"Dockerfile.{kind}":
            raise GateError(f"policy {kind} build recipe path is unexpected")
        dockerfile_path = self.ctx.source_dir / str(recipe["path"])
        if file_sha256(dockerfile_path) != recipe["sha256"]:
            raise GateError(f"Dockerfile.{kind} differs from the trusted recipe allowlist")
        dockerfile = dockerfile_path.read_text(encoding="utf-8")
        self._assert_dockerfile_network_policy(kind, dockerfile)
        match = re.search(r"^FROM\s+(\S+)\s*$", dockerfile, re.MULTILINE)
        if match is None or match.group(1) != base["reference"]:
            raise GateError(f"Dockerfile.{kind} does not use the policy-pinned base")
        tag = self._resource_name(f"accepted-{kind}")
        acquisition_network = "default"
        command = [
            *self.docker,
            "buildx",
            "build",
            "--builder",
            "default",
            "--load",
            "--progress=plain",
            "--pull=false",
            "--network",
            acquisition_network,
            "--label",
            f"{SESSION_LABEL}={self.ctx.run_id}",
            "--label",
            f"{ROLE_LABEL}=accepted-{kind}",
            "--tag",
            tag,
            "--file",
            str(dockerfile_path),
            str(self.ctx.source_dir),
        ]
        try:
            self._stage(
                f"build-{kind}",
                command,
                timeout=int(self.ctx.policy.raw["limits"]["build_timeout_seconds"]),
            )
        finally:
            self._discover_resource("image", tag, f"accepted-{kind}", provisional_artifact=True)
        payload = json.loads(self._docker_capture("image", "inspect", tag))[0]
        labels = payload.get("Config", {}).get("Labels") or {}
        if (
            labels.get(SESSION_LABEL) != self.ctx.run_id
            or labels.get(ROLE_LABEL) != f"accepted-{kind}"
        ):
            raise GateError(f"accepted {kind} image labels are invalid")
        locks = {
            path: file_sha256(self.ctx.source_dir / path)
            for path in (
                ("uv.lock", "pyproject.toml")
                if kind == "api"
                else ("web/package-lock.json", "web/package.json")
            )
        }
        self.artifacts[kind] = {
            "image_id": payload["Id"],
            "tag": tag,
            "source_tree_sha256": self.ctx.candidate.tree_sha256,
            "dockerfile_sha256": hashlib.sha256(dockerfile.encode()).hexdigest(),
            "base_image": base["reference"],
            "base_image_id": base["image_id"],
            "platform": {
                "os": payload.get("Os"),
                "architecture": payload.get("Architecture"),
            },
            "dependency_locks": locks,
            "build_command": command,
            "network_policy": "Docker default build dependency acquisition; no credentials",
        }

    @staticmethod
    def _assert_dockerfile_network_policy(kind: str, dockerfile: str) -> None:
        lines = [line.strip() for line in dockerfile.splitlines() if line.strip()]
        if kind == "web":
            required = (
                "RUN npm ci --ignore-scripts --no-audit --no-fund",
                "COPY web/ ./",
                "RUN --network=none npm run build",
            )
            positions = [lines.index(line) if line in lines else -1 for line in required]
            if positions != sorted(positions) or -1 in positions:
                raise GateError("Dockerfile.web does not separate acquisition and offline build")
            source_copy = positions[1]
        else:
            acquisition_prefix = (
                "RUN uv sync --frozen --no-dev --extra browser --no-install-project"
            )
            offline = (
                "RUN --network=none uv sync --frozen --no-dev --extra browser "
                "--offline --no-editable"
            )
            acquisition_positions = [
                index for index, line in enumerate(lines) if line.startswith(acquisition_prefix)
            ]
            if (
                len(acquisition_positions) != 1
                or offline not in lines
                or "COPY src ./src" not in lines
            ):
                raise GateError("Dockerfile.api does not separate acquisition and offline install")
            acquisition_position = acquisition_positions[0]
            if not lines[acquisition_position].endswith("\\") or lines[
                acquisition_position + 1
            ] != (
                "&& uv pip install --python /opt/venv/bin/python "
                "-r /opt/python-build-requirements.lock"
            ):
                raise GateError("Dockerfile.api acquisition command differs from reviewed form")
            source_copy = lines.index("COPY src ./src")
            if not (acquisition_position < source_copy < lines.index(offline)):
                raise GateError("Dockerfile.api dependency/source build order is unsafe")
        for line in lines[source_copy + 1 :]:
            if line.startswith("RUN ") and not line.startswith("RUN --network=none "):
                raise GateError(f"Dockerfile.{kind} executes candidate source with build network")

    def _smoke_artifact(self, kind: str) -> None:
        artifact = self.artifacts[kind]
        image_id = str(artifact["image_id"])
        name = self._resource_name(f"{kind}-smoke")
        if kind == "api":
            entrypoint, option, script = "python", "-c", _API_SMOKE
        else:
            entrypoint, option, script = "node", "-e", _WEB_SMOKE
        try:
            container_id = self._docker_capture(
                "create",
                "--name",
                name,
                "--network",
                "none",
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--label",
                f"{SESSION_LABEL}={self.ctx.run_id}",
                "--label",
                f"{ROLE_LABEL}={kind}-smoke",
                "--entrypoint",
                entrypoint,
                image_id,
                option,
                script,
            )
        finally:
            discovered = self._discover_resource("container", name, f"{kind}-smoke")
        if discovered is None or container_id != discovered:
            raise GateError(f"accepted {kind} smoke container identity is unavailable")
        result = self._stage(
            f"smoke-{kind}",
            [*self.docker, "start", "--attach", container_id],
            timeout=90,
        )
        inspect = json.loads(self._docker_capture("inspect", container_id))[0]
        if (
            inspect.get("Image") != image_id
            or inspect.get("HostConfig", {}).get("NetworkMode") != "none"
            or inspect.get("State", {}).get("ExitCode") != 0
            or result.returncode != 0
        ):
            raise GateError(f"accepted {kind} image failed its network-none smoke")

    def execute(self, context: GateContext) -> ExecutionOutcome:
        self.context = context
        if not hasattr(os, "getuid") or not hasattr(os, "getgid"):
            raise GateError("release gate Docker execution requires a POSIX host identity")
        self.worker_uid = os.getuid()
        self.worker_gid = os.getgid()
        self._assert_worker_path_ownership()
        self._configure_docker_client()
        self._prepare_runtime()
        self._build_python_runtime()
        self._start_postgres()
        self._start_python_runner()
        self._python_quality()
        sequential = self.ctx.policy.raw.get("postgres_before_web", False)
        if sequential:
            self._postgres_quality()
            # Keep inspected identities for normal cleanup, release worker RAM before Node/build.
            self._docker_capture("stop", "--time", "10", str(self.python_runner_id))
            self._docker_capture("stop", "--time", "10", str(self.pg_id))
        self._start_node_runner()
        self._web_quality()
        if sequential:
            self._docker_capture("stop", "--time", "10", str(self.node_runner_id))
        else:
            self._postgres_quality()
        self._build_artifact("api")
        self._build_artifact("web")
        self.artifacts["worker"] = {
            **self.artifacts["api"],
            "role": "worker uses the exact accepted API image",
        }
        self._smoke_artifact("api")
        self._smoke_artifact("web")
        self._verify_docker_tool_immutability()
        tool_report = self.ctx.reports_dir / "docker-tool-final.json"
        _atomic_json(
            tool_report,
            {**self.buildx_identity, "immutable_tool_inventory_verified_after": True},
        )
        self.stages[-1]["reports"].append(_report_reference(tool_report, self.ctx.run_dir))
        if tuple(stage["id"] for stage in self.stages) != context.policy.required_stage_ids:
            raise GateError("Docker executor did not complete the exact policy stage order")
        outcome = ExecutionOutcome(
            stages=tuple(self.stages),
            artifacts=self.artifacts,
            inventory_sha256=context.policy.inventory_sha256,
            explicit_not_performed=context.policy.explicit_not_performed,
        )
        self.accepted_artifact_resources = [
            resource for resource in self.resources if resource["provisional_artifact"]
        ]
        self.resources = [
            resource for resource in self.resources if not resource["provisional_artifact"]
        ]
        return outcome

    def reject_artifacts(self) -> None:
        """Return not-yet-accepted images to guarded cleanup after receipt rejection."""

        self.resources.extend(self.accepted_artifact_resources)
        self.accepted_artifact_resources = []

    def _inspect_resource(self, resource: Mapping[str, Any]) -> Mapping[str, Any] | None:
        kind = resource["kind"]
        command = (
            [*self.docker, "image", "inspect", str(resource["id"])]
            if kind == "image"
            else [*self.docker, "network", "inspect", str(resource["id"])]
            if kind == "network"
            else [*self.docker, "inspect", str(resource["id"])]
        )
        result = self._run(command, timeout=60, check=False)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)[0]

    def cleanup(self) -> Mapping[str, Any]:
        for resource in reversed(self.resources):
            if resource["removed"]:
                continue
            try:
                payload = self._inspect_resource(resource)
                if payload is None:
                    resource["identity_verified"] = False
                    continue
                labels = (
                    payload.get("Config", {}).get("Labels") or {}
                    if resource["kind"] != "network"
                    else payload.get("Labels") or {}
                )
                identity = payload.get("Id")
                if (
                    identity != resource["id"]
                    or labels.get(SESSION_LABEL) != self.ctx.run_id
                    or labels.get(ROLE_LABEL) != resource["role"]
                ):
                    resource["identity_verified"] = False
                    continue
                resource["identity_verified"] = True
                if resource["kind"] == "container":
                    command = [*self.docker, "rm", "--force", "--volumes", str(resource["id"])]
                elif resource["kind"] == "network":
                    command = [*self.docker, "network", "rm", str(resource["id"])]
                else:
                    command = [*self.docker, "image", "rm", str(resource["id"])]
                removed = self._run(command, timeout=120, check=False)
                resource["removed"] = removed.returncode == 0
            except BaseException as error:
                resource["cleanup_error"] = f"{type(error).__name__}: {error}"
        complete = all(
            resource.get("identity_verified") is True and resource.get("removed") is True
            for resource in self.resources
        )
        return {"complete": complete, "resources": self.resources}


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


_API_SMOKE = """import os
os.environ['EIS_PILOT_TOKEN'] = 'release-gate-' + 'a' * 48
os.environ['EIS_PILOT_COMPANY'] = 'release-gate-test-only'
assert 'DATABASE_URL' not in os.environ
from fastapi.testclient import TestClient
from procurement.api.discovery_runtime import create_discovery_app
with TestClient(create_discovery_app()) as client:
    assert client.get('/health').status_code == 200
    assert client.get('/v1/cases').status_code == 404
    assert client.get('/v1/tender-discovery/runs').status_code == 401
print('API_RELEASE_GATE_SMOKE_PASS')
"""

_WEB_SMOKE = """const fs = require('fs');
const {spawn} = require('child_process');
const http = require('http');
if (!fs.readFileSync('/app/.next/BUILD_ID', 'utf8').trim()) throw Error('BUILD_ID_MISSING');
const proc = spawn('npm',['run','start','--','--hostname','127.0.0.1','--port','3000'],
    {cwd:'/app',stdio:'ignore'});
const limit = Date.now() + 25000;
async function test() {
  while (Date.now() < limit) {
    const status = await new Promise(resolve => {
      const request = http.get('http://127.0.0.1:3000/tender-discovery', response => {
        response.resume(); resolve(response.statusCode);
      });
      request.setTimeout(1000, () => request.destroy());
      request.on('error', () => resolve(0));
    });
    if (status === 200) {proc.kill(); console.log('WEB_RELEASE_GATE_SMOKE_PASS'); return;}
    await new Promise(resolve => setTimeout(resolve, 300));
  }
  proc.kill(); throw Error('WEB_RELEASE_GATE_START_FAILED');
}
test().catch(error => {console.error(error.message); process.exitCode=1;});
"""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        receipt = ReleaseGateController(
            bundle=arguments.source_bundle,
            expected_sha256=arguments.expected_sha256,
            state_root=arguments.state_root,
            policy_path=arguments.policy,
        ).run()
    except (GateError, ReceiptError, OSError) as error:
        print(f"RELEASE_GATE_FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS", "receipt": str(receipt)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
