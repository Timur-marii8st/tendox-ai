"""Pinned four-module VPS rollout; never packages the local development tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

HOST = Path("/home/syurai/vibe-seller")
STATE = Path("/home/syurai/vibe-seller-state")
FILES = (
    "sources/supplier_serp.py",
    "sources/supplier_serp_browser.py",
    "storage/eis_supplier_serp.py",
    "api/eis_supplier_serp_runner.py",
)
IMAGE = "vibe-seller-api:supplier-headed-20261006"
BASE_TAG = "vibe-seller-api:supplier-base-20261006"


def run(*args: str) -> bytes:
    return subprocess.check_output(args, stderr=subprocess.STDOUT)


def docker(*args: str) -> bytes:
    return run("sudo", "-n", "docker", *args)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic(path: Path, raw: bytes) -> None:
    temporary = path.with_name(path.name + ".supplier-rollout-tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def patch_once(raw: bytes, old: str, new: str) -> bytes:
    if raw.count(old.encode()) != 1:
        raise RuntimeError("PINNED_PATCH_FRAGMENT_CONFLICT")
    return raw.replace(old.encode(), new.encode())


def prepare(stage: Path) -> None:
    stage.mkdir(mode=0o700)
    (stage / "backup").mkdir(mode=0o700)
    originals = {}
    for name in FILES:
        target = HOST / "src/procurement" / name
        if name.endswith("supplier_serp_browser.py") and not target.exists():
            originals[name] = None
            continue
        installed = docker("exec", "vibe-seller-api-1", "cat", "/app/src/procurement/" + name)
        raw = target.read_bytes()
        if installed != raw:
            raise RuntimeError("HOST_INSTALLED_HASH_CONFLICT:" + name)
        originals[name] = sha(raw)
        backup = stage / "backup" / name
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(raw)
    compose = (HOST / "docker-compose.server.yml").read_bytes()
    (stage / "backup/compose.yml").write_bytes(compose)
    storage = (stage / "backup/storage/eis_supplier_serp.py").read_bytes()
    if b"**browser_transport_provenance()," not in storage:
        storage = patch_once(
            storage,
            "    observe_supplier_serp,",
            "    observe_supplier_serp,\n    browser_transport_provenance,",
        )
        storage = patch_once(
            storage,
            "observe_supplier_serp(query, cooldowns=cooldowns)",
            "observe_supplier_serp(query, cooldowns=cooldowns, company_id=company)",
        )
        storage = patch_once(
            storage,
            '"policy_version": POLICY,',
            '"policy_version": POLICY,\n            **browser_transport_provenance(),',
        )
    elif storage.count(b"company_id=company)") != 1:
        raise RuntimeError("INSTALLED_STORAGE_PATCH_CONFLICT")
    source_dir = stage / "src/procurement"
    (source_dir / "storage").mkdir(parents=True)
    (source_dir / "storage/eis_supplier_serp.py").write_bytes(storage)
    for name in FILES:
        if name.startswith("storage/"):
            continue
        destination = source_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(stage.parent / "payload" / name, destination)
    image_id = docker("inspect", "--format", "{{.Image}}", "vibe-seller-api-1").decode().strip()
    docker("tag", image_id, BASE_TAG)
    (stage / "Dockerfile").write_text(f"FROM {BASE_TAG}\nCOPY src/ /app/src/\n")
    manifest = {
        "base_image": image_id,
        "base_sha256": originals,
        "compose_sha256": sha(compose),
        "installed_sha256": {name: sha((source_dir / name).read_bytes()) for name in FILES},
        "image": IMAGE,
        "chrome_path": docker(
            "exec",
            "vibe-seller-api-1",
            "python",
            "-c",
            "from playwright.sync_api import sync_playwright; "
            "p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()",
        )
        .decode()
        .strip(),
        "xvfb_path": "/usr/bin/Xvfb",
    }
    docker("build", "--pull=false", "--tag", IMAGE, str(stage))
    manifest["built_image_id"] = (
        docker("image", "inspect", "--format", "{{.Id}}", IMAGE).decode().strip()
    )
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))
    docker("run", "--rm", "--entrypoint", manifest["chrome_path"], IMAGE, "--version")
    docker("run", "--rm", "--entrypoint", "test", IMAGE, "-x", manifest["xvfb_path"])
    docker(
        "run",
        "--rm",
        "--entrypoint",
        "python",
        IMAGE,
        "-c",
        "from procurement.sources.supplier_serp import observe_supplier_serp; "
        "from procurement.sources.supplier_serp_browser import capture_headed_serp; "
        "from procurement.storage.eis_supplier_serp import prepare_supplier_serp; "
        "from procurement.api.eis_supplier_serp_runner import _environment; "
        "print('IMPORT_PASS')",
    )
    print(json.dumps({"status": "PREPARED", **manifest}))


@contextmanager
def deployment_lease():
    import fcntl

    locks = []
    marker_owned = False
    try:
        for name in (
            "backend-deploy.lock",
            "web-deploy.lock",
            "eis-priority.lock",
            "eis-import.lock",
        ):
            handle = (STATE / name).open("a+b")
            locks.append(handle)
            deadline = time.monotonic() + (180 if name == "eis-import.lock" else 45)
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("ROLLOUT_BUSY:" + name) from None
                    time.sleep(0.5)
            if name == "eis-priority.lock":
                result = (
                    docker(
                        "exec",
                        "vibe-seller-api-1",
                        "python",
                        "-c",
                        "from pathlib import Path; "
                        "p=Path('/var/lib/eis-browser/eis-priority.request'); "
                        "exists=p.exists(); p.touch() if not exists else None; "
                        "print('EXISTS' if exists else 'CREATED')",
                    )
                    .decode()
                    .strip()
                )
                marker_owned = result == "CREATED"
        yield
    finally:
        if marker_owned:
            docker(
                "exec",
                "vibe-seller-api-1",
                "python",
                "-c",
                "from pathlib import Path; "
                "Path('/var/lib/eis-browser/eis-priority.request').unlink(missing_ok=True)",
            )
        for handle in reversed(locks):
            handle.close()


def require_quality_adapter(source_kind: str) -> None:
    """ADR-0107: legacy payloads cannot inherit a full-snapshot quality receipt."""
    raise RuntimeError(f"QUALITY_GATE_ADAPTER_UNAVAILABLE: {source_kind}")


def install(stage: Path) -> None:
    require_quality_adapter("INSTALLED_BASE_OVERLAY")
    with deployment_lease():
        install_locked(stage)


def install_locked(stage: Path) -> None:
    require_quality_adapter("INSTALLED_BASE_OVERLAY")
    manifest = json.loads((stage / "manifest.json").read_text())
    if (
        docker("image", "inspect", "--format", "{{.Id}}", IMAGE).decode().strip()
        != manifest["built_image_id"]
    ):
        raise RuntimeError("STAGED_IMAGE_CHANGED")
    if (
        docker("inspect", "--format", "{{.Image}}", "vibe-seller-api-1").decode().strip()
        != manifest["base_image"]
    ):
        raise RuntimeError("BASE_IMAGE_CHANGED")
    for name, digest in manifest["base_sha256"].items():
        target = HOST / "src/procurement" / name
        if digest is None:
            if target.exists():
                raise RuntimeError("NEW_FILE_CONFLICT")
        elif sha(target.read_bytes()) != digest:
            raise RuntimeError("BASE_FILE_CHANGED")
    compose_path = HOST / "docker-compose.server.yml"
    original_compose = compose_path.read_bytes()
    if sha(original_compose) != manifest["compose_sha256"]:
        raise RuntimeError("COMPOSE_CHANGED")
    if f"  api:\n    image: {IMAGE}\n".encode() in original_compose:
        compose = original_compose
    else:
        compose = patch_once(original_compose, "  api:\n", f"  api:\n    image: {IMAGE}\n")
        compose = patch_once(
            compose,
            "      EIS_DISCOVERY_DB: /var/lib/eis-browser/discovery/eis-discovery.sqlite3\n",
            "      EIS_DISCOVERY_DB: /var/lib/eis-browser/discovery/eis-discovery.sqlite3\n"
            "      SUPPLIER_SERP_BROWSER_STATE_DIR: /var/lib/eis-browser/supplier-serp\n"
            f"      SUPPLIER_SERP_CHROME_PATH: {manifest['chrome_path']}\n"
            f"      SUPPLIER_SERP_XVFB_PATH: {manifest['xvfb_path']}\n",
        )
    command = ("compose", "-p", "vibe-seller", "-f", str(compose_path))
    try:
        for name, digest in manifest["installed_sha256"].items():
            raw = (stage / "src/procurement" / name).read_bytes()
            if sha(raw) != digest:
                raise RuntimeError("STAGED_FILE_CHANGED")
            atomic(HOST / "src/procurement" / name, raw)
        atomic(compose_path, compose)
        docker(*command, "config", "--quiet")
        docker(*command, "up", "-d", "--no-build", "--no-deps", "api")
        docker(
            "exec",
            "vibe-seller-api-1",
            "python",
            "-c",
            "from procurement.sources.supplier_serp_browser import capture_headed_serp; "
            "from procurement.storage.eis_supplier_serp import prepare_supplier_serp; "
            "print('INSTALLED_IMPORT_PASS')",
        )
        for name, digest in manifest["installed_sha256"].items():
            if (
                sha(docker("exec", "vibe-seller-api-1", "cat", "/app/src/procurement/" + name))
                != digest
            ):
                raise RuntimeError("INSTALLED_HASH_CONFLICT")
        print(json.dumps({"status": "INSTALLED", "manifest": str(stage / "manifest.json")}))
    except BaseException:
        for name, digest in manifest["base_sha256"].items():
            target = HOST / "src/procurement" / name
            if digest is None:
                target.unlink(missing_ok=True)
            else:
                atomic(target, (stage / "backup" / name).read_bytes())
        atomic(compose_path, original_compose)
        docker("tag", manifest["base_image"], IMAGE)
        docker(*command, "up", "-d", "--no-build", "--no-deps", "api")
        raise


def enable_init(stage: Path) -> None:
    require_quality_adapter("CONFIG_CHANGE")
    with deployment_lease():
        manifest = json.loads((stage / "manifest.json").read_text())
        image_id = docker("inspect", "--format", "{{.Image}}", "vibe-seller-api-1").decode().strip()
        if image_id != manifest["built_image_id"]:
            raise RuntimeError("INSTALLED_IMAGE_CHANGED")
        path = HOST / "docker-compose.server.yml"
        original = path.read_bytes()
        expected = f"  api:\n    image: {IMAGE}\n"
        updated = patch_once(original, expected, expected + "    init: true\n")
        (stage / "backup/compose-before-init.yml").write_bytes(original)
        command = ("compose", "-p", "vibe-seller", "-f", str(path))
        try:
            atomic(path, updated)
            docker(*command, "config", "--quiet")
            docker(*command, "up", "-d", "--no-build", "--no-deps", "api")
            if (
                docker("inspect", "--format", "{{.HostConfig.Init}}", "vibe-seller-api-1")
                .decode()
                .strip()
                != "true"
            ):
                raise RuntimeError("INIT_NOT_ACTIVE")
            evidence = {
                "status": "INIT_ACTIVE",
                "image_id": image_id,
                "compose_sha256": sha(updated),
            }
            (stage / "init-acceptance.json").write_text(json.dumps(evidence, indent=2))
            print(json.dumps(evidence))
        except BaseException:
            atomic(path, original)
            docker(*command, "up", "-d", "--no-build", "--no-deps", "api")
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "install", "enable-init"))
    parser.add_argument("stage", type=Path)
    args = parser.parse_args()
    resolved = args.stage.resolve()
    if resolved.parent != STATE / "supplier-browser-rollout":
        parser.error("stage must be inside the dedicated rollout directory")
    {"prepare": prepare, "install": install, "enable-init": enable_init}[args.mode](resolved)
