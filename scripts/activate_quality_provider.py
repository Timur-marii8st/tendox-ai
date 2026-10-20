"""Preflight or install one exact approved local quality-provider payload.

This installer only writes trusted controller/build-tool files and the two legacy refusal
adapters. It never runs Docker, changes application configuration, or deploys a
candidate. Supplying a plan hash binds bytes; it does not grant human approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

HOST = Path("/home/syurai/vibe-seller")
PROVIDER = Path("/home/syurai/vibe-seller-state/quality-provider")
CONTROLLER_FILES = frozenset(
    {"run_release_gate.py", "release_gate_receipt.py", "release_gate_policy.json"}
)
GUARD_FILES = frozenset(
    {"server-supplier-browser-rollout.py", "server-supplier-captcha-rollout.py"}
)
SCHEMA = "quality-provider-activation-v1"
TOOL_FILES = frozenset({"docker-config/config.json", "docker-config/cli-plugins/docker-buildx"})
BUILDX_SHA256 = "982ca20490b45ed1ec8d99795974d3d874a358f75938c9c237305010e6b7e548"
BUILDX_BYTES = 65806498
TOOL_IDENTITY = {
    "docker-config/config.json": {"sha256": hashlib.sha256(b"{}\n").hexdigest(), "bytes": 3},
    "docker-config/cli-plugins/docker-buildx": {"sha256": BUILDX_SHA256, "bytes": BUILDX_BYTES},
}
TOOL_PROVENANCE = {
    "version": "v0.37.2",
    "platform": "linux/amd64",
    "source_url": "https://github.com/docker/buildx/releases/download/v0.37.2/buildx-v0.37.2.linux-amd64",
    "sha256": BUILDX_SHA256,
    "bytes": BUILDX_BYTES,
    "config_path": "docker-config/config.json",
    "plugin_path": "docker-config/cli-plugins/docker-buildx",
    "docker_endpoint": "unix:///var/run/docker.sock",
    "builder": "default",
    "driver": "docker",
}


class ActivationError(RuntimeError):
    """The exact activation payload cannot be safely applied."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def safe_path(path: Path) -> Path:
    """Reject links in the entire path, including existing parents."""
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ActivationError(f"ACTIVATION_SYMLINK: {path}")
    return path


def read_regular(path: Path, maximum_bytes: int = 16 * 1024 * 1024) -> bytes:
    safe_path(path)
    if not path.is_file() or path.stat().st_size > maximum_bytes:
        raise ActivationError(f"ACTIVATION_NOT_REGULAR_BOUNDED_FILE: {path}")
    return path.read_bytes()


def read_tool(root: Path, name: str) -> bytes:
    if name not in TOOL_FILES:
        raise ActivationError("ACTIVATION_TOOL_SCOPE_MISMATCH")
    raw = read_regular(root / name, TOOL_IDENTITY[name]["bytes"])
    if len(raw) != TOOL_IDENTITY[name]["bytes"] or digest(raw) != TOOL_IDENTITY[name]["sha256"]:
        raise ActivationError("ACTIVATION_TOOL_IDENTITY_MISMATCH: " + name)
    return raw


def bundle_manifest(plan: dict[str, Any]) -> dict[str, Any]:
    return {"controller": plan["controller"], "tools": plan["tools"],
            "tool_provenance": plan["tool_provenance"]}


def verify_release(release: Path, plan: dict[str, Any]) -> None:
    expected = CONTROLLER_FILES | TOOL_FILES | {"bundle.json"}
    actual = {path.relative_to(release).as_posix() for path in release.rglob("*") if path.is_file()}
    if actual != expected or any(path.is_symlink() for path in release.rglob("*")):
        raise ActivationError("ACTIVATION_EXISTING_RELEASE_SCOPE_MISMATCH")
    for name, sha256 in plan["controller"].items():
        if digest(read_regular(release / name)) != sha256:
            raise ActivationError("ACTIVATION_EXISTING_RELEASE_HASH_MISMATCH")
    for name in TOOL_FILES:
        read_tool(release, name)
    if read_regular(release / "bundle.json") != canonical(bundle_manifest(plan)):
        raise ActivationError("ACTIVATION_EXISTING_RELEASE_MANIFEST_MISMATCH")


def atomic_write(path: Path, raw: bytes, mode: int) -> None:
    safe_path(path)
    fd, temporary = tempfile.mkstemp(prefix=".quality-activation-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def preflight(package: Path, expected_plan_sha256: str) -> dict[str, Any]:
    """Validate all bytes and installed preconditions without creating anything."""
    plan_raw = read_regular(package / "plan.json")
    if digest(plan_raw) != expected_plan_sha256:
        raise ActivationError("ACTIVATION_PLAN_HASH_MISMATCH")
    plan = json.loads(plan_raw)
    if (
        plan.get("schema") != SCHEMA
        or plan.get("provider_root") != str(PROVIDER)
        or plan.get("host_root") != str(HOST)
        or plan.get("runtime_changes") != []
        or set(plan.get("controller", {})) != CONTROLLER_FILES
        or set(plan.get("guards", {})) != GUARD_FILES
        or plan.get("tools") != TOOL_IDENTITY
        or plan.get("tool_provenance") != TOOL_PROVENANCE
    ):
        raise ActivationError("ACTIVATION_PLAN_SCOPE_MISMATCH")
    safe_path(PROVIDER)
    if os.name == "posix" and PROVIDER.exists() and PROVIDER.stat().st_mode & 0o022:
        raise ActivationError("ACTIVATION_PROVIDER_WRITABLE_BY_OTHERS")
    controller = plan["controller"]
    if plan.get("bundle_id") != digest(canonical(bundle_manifest(plan))):
        raise ActivationError("ACTIVATION_BUNDLE_ID_MISMATCH")
    for name, sha256 in controller.items():
        if digest(read_regular(package / "controller" / name)) != sha256:
            raise ActivationError("ACTIVATION_CONTROLLER_HASH_MISMATCH: " + name)
    for name in TOOL_FILES:
        read_tool(package / "tools", name)
    for name, hashes in plan["guards"].items():
        if set(hashes) != {"before_sha256", "after_sha256"}:
            raise ActivationError("ACTIVATION_GUARD_SCHEMA_MISMATCH")
        if digest(read_regular(package / "guards" / name)) != hashes["after_sha256"]:
            raise ActivationError("ACTIVATION_GUARD_HASH_MISMATCH: " + name)
        if digest(read_regular(HOST / "scripts" / name)) != hashes["before_sha256"]:
            raise ActivationError("ACTIVATION_INSTALLED_GUARD_CHANGED: " + name)
    current = safe_path(PROVIDER / "current.json")
    current_sha = digest(read_regular(current)) if current.exists() else None
    if current_sha != plan.get("previous_current_sha256"):
        raise ActivationError("ACTIVATION_PREVIOUS_PROVIDER_CHANGED")
    return plan


def activate(package: Path, expected_plan_sha256: str) -> dict[str, Any]:
    """Apply an approved payload with a mutation lock and guarded recovery."""
    plan = preflight(package, expected_plan_sha256)
    os.umask(0o077)
    PROVIDER.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock = PROVIDER / "activation.lock"
    marker = secrets.token_hex(24).encode()
    safe_path(lock)
    try:
        with lock.open("xb") as stream:
            stream.write(marker)
    except FileExistsError as error:
        raise ActivationError("ACTIVATION_LOCK_OCCUPIED; inspect before recovery") from error
    backups: dict[Path, tuple[bytes, int]] = {}
    applied: dict[Path, str] = {}
    current = PROVIDER / "current.json"
    previous_current: bytes | None = None
    pointer_raw: bytes | None = None
    record_dir: Path | None = None
    try:
        # Recheck under the lock, before any operational file replacement.
        plan = preflight(package, expected_plan_sha256)
        if current.exists():
            previous_current = read_regular(current)
        records = safe_path(PROVIDER / "activations")
        records.mkdir(mode=0o700, exist_ok=True)
        record_dir = records / (expected_plan_sha256[:16] + "-" + secrets.token_hex(6))
        record_dir.mkdir(mode=0o700)
        atomic_write(record_dir / "plan.json", read_regular(package / "plan.json"), 0o600)
        for name in GUARD_FILES:
            target = HOST / "scripts" / name
            raw = read_regular(target)
            mode = stat.S_IMODE(target.stat().st_mode)
            backups[target] = raw, mode
            atomic_write(record_dir / (name + ".before"), raw, 0o600)
        releases = safe_path(PROVIDER / "releases")
        releases.mkdir(mode=0o700, exist_ok=True)
        release = safe_path(releases / plan["bundle_id"])
        if release.exists():
            verify_release(release, plan)
        else:
            staging = releases / (".staging-" + plan["bundle_id"][:16] + "-" + secrets.token_hex(6))
            staging.mkdir(mode=0o700, exist_ok=False)
            for name, sha256 in plan["controller"].items():
                raw = read_regular(package / "controller" / name)
                if digest(raw) != sha256:
                    raise ActivationError("ACTIVATION_CONTROLLER_CHANGED_UNDER_LOCK")
                atomic_write(staging / name, raw, 0o444)
            for name in sorted(TOOL_FILES):
                target = staging / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                atomic_write(target, read_tool(package / "tools", name),
                             0o555 if name.endswith("docker-buildx") else 0o444)
            atomic_write(staging / "bundle.json", canonical(bundle_manifest(plan)), 0o444)
            verify_release(staging, plan)
            if release.exists():
                raise ActivationError("ACTIVATION_RELEASE_APPEARED; publication refused")
            staging.rename(release)
        for name in GUARD_FILES:
            target = HOST / "scripts" / name
            if digest(read_regular(target)) != plan["guards"][name]["before_sha256"]:
                raise ActivationError("ACTIVATION_GUARD_CHANGED_UNDER_LOCK: " + name)
            raw = read_regular(package / "guards" / name)
            if digest(raw) != plan["guards"][name]["after_sha256"]:
                raise ActivationError("ACTIVATION_GUARD_PAYLOAD_CHANGED_UNDER_LOCK")
            applied[target] = digest(raw)
            atomic_write(target, raw, backups[target][1])
        pointer_raw = canonical({
            "schema": SCHEMA,
            "bundle_id": plan["bundle_id"],
            "controller": plan["controller"],
            "tools": plan["tools"],
            "tool_provenance": plan["tool_provenance"],
            "activation_plan_sha256": expected_plan_sha256,
        })
        atomic_write(current, pointer_raw, 0o600)
        report = {
            "schema": SCHEMA, "status": "INSTALLED; WORKFLOW_ACCEPTANCE_PENDING",
            "plan_sha256": expected_plan_sha256, "bundle_id": plan["bundle_id"],
            "operational_paths": [str(path) for path in sorted(applied)],
            "runtime_changes": [], "record_dir": str(record_dir),
        }
        atomic_write(record_dir / "result.json", canonical(report), 0o600)
        return report
    except BaseException as error:
        recovery: list[str] = []
        if pointer_raw is not None:
            try:
                if not current.exists() and previous_current is None:
                    pass
                elif digest(read_regular(current)) == digest(pointer_raw):
                    if previous_current is None:
                        current.unlink()
                    else:
                        atomic_write(current, previous_current, 0o600)
                else:
                    recovery.append("CURRENT_POINTER_CHANGED; rollback refused")
            except Exception as recovery_error:
                recovery.append("CURRENT_POINTER_RECOVERY: " + type(recovery_error).__name__)
        for target, written_sha in reversed(list(applied.items())):
            try:
                actual_sha = digest(read_regular(target))
                raw, mode = backups[target]
                if actual_sha == digest(raw):
                    continue
                if actual_sha != written_sha:
                    recovery.append(str(target) + ": changed; rollback refused")
                    continue
                atomic_write(target, raw, mode)
            except Exception as recovery_error:
                recovery.append(str(target) + ": " + type(recovery_error).__name__)
        if record_dir is not None:
            try:
                atomic_write(record_dir / "failure.json", canonical({
                    "status": "FAIL", "error_type": type(error).__name__,
                    "recovery_refusals": recovery, "runtime_changes": [],
                }), 0o600)
            except Exception as record_error:
                recovery.append("FAILURE_RECORD: " + type(record_error).__name__)
        if recovery:
            message = "ACTIVATION_RECOVERY_INCOMPLETE: " + "; ".join(recovery)
            raise ActivationError(message) from error
        raise
    finally:
        primary_error = sys.exc_info()[0]
        try:
            if read_regular(lock) != marker:
                raise ActivationError("ACTIVATION_LOCK_CHANGED; removal refused")
            lock.unlink()
        except Exception as lock_error:
            record = {"status": "FAIL", "lock_cleanup_error": type(lock_error).__name__}
            if record_dir is not None:
                with suppress(Exception):
                    atomic_write(record_dir / "cleanup-failure.json", canonical(record), 0o600)
            if primary_error is None:
                raise ActivationError("ACTIVATION_LOCK_CLEANUP_FAILED") from lock_error
            print(json.dumps(record), file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--activate", action="store_true",
                        help="Apply only after separate exact-payload human approval")
    args = parser.parse_args()
    if args.activate:
        result = activate(args.package, args.expected_plan_sha256)
    else:
        plan = preflight(args.package, args.expected_plan_sha256)
        result = {"status": "PREFLIGHT_PASS; NOT_ACTIVATED", "bundle_id": plan["bundle_id"]}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
