"""Pinned four-module VPS rollout; never packages the local development tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

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

# A bounded FULL_SOURCE adapter for the reviewed production223 release. Legacy
# overlay entrypoints below still refuse unconditionally. Updating these pins
# requires a new reviewed trusted diff and exact activation approval.
FULL_BASE = STATE / "production223-compat-20261009-v1"
FULL_RUN = "release-20261008-222648-27c4a2414d9e"
FULL_STAGE = STATE / "full-source-production223-v2"
FULL_WORKER_BUDGET = {"mem_limit": "3g", "cpus": 3.0}
FULL_WORKER_BUDGET_BEFORE = {"mem_limit": "2g", "cpus": 2.0}
FULL_SOURCE_ID = {
    "archive_sha256": "c6415267a4ec5340ef8be68266aea792d4b24a282874961347e4e0b03831102e",
    "tree_sha256": "e573c9fcd98b341f49e1cab08da50a687ecf8263ed71c8e38207428ebb8b3b73",
    "manifest_sha256": "d27ff331e5cd1c4280f899b769a195a9ac88170239b611bc1cd35e6277bc13d0",
}
FULL_RECEIPT_SHA = "11dd4ff15906cb574c0a622c0299ea63d4566d5df6206a4bc032d08f00ab6526"
FULL_POLICY_SHA = "c6f470570cc0ba39f0c328e3429bdb29b0cf392bfa91395f0b8ffd2fe73d0a82"
FULL_VERIFIER_SHA = "31c7bc8c4e27e431dedb8652fe6df5f2fc145455b6ca25070517fe0350117605"
FULL_ACTIVE_COMPOSE = STATE / "discovery-pagination-20261007/compose-release-v9.yml"
FULL_SCHEMA_BEFORE = "20261006_08"
FULL_SCHEMA_AFTER = "20261008_01"
FULL_TRUSTED_GUARDS = {
    "server-supplier-browser-rollout.py": (
        "1558b34e7cce71ded5736f4cc687c5feb1765c871dba84d03d0c6a90c76e3077"
    ),
    "server-supplier-captcha-rollout.py": (
        "50c1b5a1b21973acbcd91d3e3f4e8dbcb95d266b1030e1e24e46ae703a2d446a"
    ),
}


def full_run(*args: str, timeout: int = 120) -> bytes:
    """Finite host phase; terminate its process group on timeout."""
    process = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except BaseException:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, args, output=output)
    return output


def full_docker(*args: str, timeout: int = 120) -> bytes:
    return full_run(
        "sudo",
        "-n",
        "/usr/bin/docker",
        "--host",
        "unix:///var/run/docker.sock",
        *args,
        timeout=timeout,
    )


def full_write(path: Path, raw: bytes, mode: int = 0o600) -> None:
    """Private unpredictable temp, containment and symlink rejection."""
    if not any(path.is_relative_to(root) for root in (HOST, FULL_STAGE)):
        raise RuntimeError("FULL_SOURCE_WRITE_OUTSIDE_SCOPE")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise RuntimeError("FULL_SOURCE_WRITE_SYMLINK")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".full-source-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def full_read(path: Path) -> bytes:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise RuntimeError("FULL_SOURCE_SYMLINK")
    if not path.is_file() or path.stat().st_size > 25 * 1024 * 1024:
        raise RuntimeError("FULL_SOURCE_FILE_INVALID")
    return path.read_bytes()


def full_receipt():
    """Load only the pinned trusted verifier, never candidate-provided Python."""
    provider = FULL_BASE / "provider"
    verifier = provider / "release_gate_receipt.py"
    policy = provider / "release_gate_policy.json"
    receipt = FULL_BASE / "gate-state/runs" / FULL_RUN / "release-receipt.json"
    for path, expected in (
        (verifier, FULL_VERIFIER_SHA),
        (policy, FULL_POLICY_SHA),
        (receipt, FULL_RECEIPT_SHA),
    ):
        if sha(full_read(path)) != expected:
            raise RuntimeError("FULL_SOURCE_TRUSTED_IDENTITY_CHANGED")
    raw = full_read(verifier)
    if sha(raw) != FULL_VERIFIER_SHA:
        raise RuntimeError("FULL_SOURCE_TRUSTED_IDENTITY_CHANGED")
    module = ModuleType("full_source_trusted_receipt")
    module.__file__ = str(verifier)
    sys.modules[module.__name__] = module
    exec(compile(raw, str(verifier), "exec"), module.__dict__)
    return module.verify_release_receipt(
        receipt,
        state_root=FULL_BASE / "gate-state",
        policy_path=policy,
        expected_source=FULL_SOURCE_ID,
    )


def full_containers(require_running: bool = True) -> dict:
    identities = {}
    for service in ("api", "web", "db"):
        value = json.loads(full_docker("inspect", "vibe-seller-" + service + "-1"))[0]
        if not value["State"]["Running"] and (require_running or service == "db"):
            raise RuntimeError("FULL_SOURCE_SERVICE_NOT_RUNNING:" + service)
        identities[service] = {"id": value["Id"], "image": value["Image"]}
    return identities


def full_schema() -> str:
    return (
        full_docker(
            "exec",
            "vibe-seller-db-1",
            "psql",
            "-U",
            "procurement_owner",
            "-d",
            "procurement",
            "-Atqc",
            "SELECT version_num FROM alembic_version",
        )
        .decode()
        .strip()
    )


def full_resources() -> dict:
    available = next(
        int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemAvailable:")
    )
    disk = shutil.disk_usage(STATE).free
    if available < 5 * 1024**3 or disk < 40 * 1024**3 or (os.cpu_count() or 0) < 4:
        raise RuntimeError("FULL_SOURCE_SERVER_RESERVE_INSUFFICIENT")
    return {"available_memory_bytes": available, "free_disk_bytes": disk}


def full_host_scope(source: Path) -> dict:
    """Bind runtime code and existing host executables; no broad checkout copy."""
    manifest = json.loads(full_read(source / "release-manifest.json"))
    operations = {}
    for entry in manifest["files"]:
        name = entry["path"]
        application = name.startswith(("src/procurement/", "migrations/"))
        executable = (
            name.startswith("scripts/server-")
            and name.endswith((".sh", ".py"))
            and Path(name).name not in FULL_TRUSTED_GUARDS
            and (HOST / name).is_file()
        )
        if not (application or executable):
            continue
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise RuntimeError("FULL_SOURCE_PATH_INVALID")
        raw = full_read(source / name)
        if sha(raw) != entry["sha256"]:
            raise RuntimeError("FULL_SOURCE_SEALED_FILE_CHANGED")
        target = HOST / name
        if target.exists():
            before = sha(full_read(target))
            mode = target.stat().st_mode & 0o777
        else:
            before, mode = None, 0o644
        operations[name] = {"before": before, "after": entry["sha256"], "mode": mode}
    # Extra host Python would otherwise run outside the accepted effective tree.
    for prefix in ("src/procurement", "migrations"):
        if any(
            p.relative_to(HOST).as_posix() not in operations
            for p in (HOST / prefix).rglob("*.py")
            if "__pycache__" not in p.parts
        ):
            raise RuntimeError("FULL_SOURCE_UNACCEPTED_HOST_CODE")
    for p in (HOST / "scripts").glob("server-*"):
        if (
            p.suffix in {".py", ".sh"}
            and p.name not in FULL_TRUSTED_GUARDS
            and p.relative_to(HOST).as_posix() not in operations
        ):
            raise RuntimeError("FULL_SOURCE_UNACCEPTED_HOST_EXECUTABLE:" + p.name)
    return operations


def full_guards(require_active: bool = False) -> dict:
    bindings = {}
    for name, before in FULL_TRUSTED_GUARDS.items():
        after = (
            sha(full_read(Path(__file__)))
            if name == "server-supplier-browser-rollout.py"
            else before
        )
        installed = sha(full_read(HOST / "scripts" / name))
        if installed not in ({after} if require_active else {before, after}):
            raise RuntimeError("FULL_SOURCE_TRUSTED_GUARD_CHANGED_OR_NOT_ACTIVATED:" + name)
        bindings[name] = {"before": before, "after": after}
    return bindings


def full_compose(raw: bytes, images: dict, worker_budget: dict | None = None) -> bytes:
    """Rewrite exact images and the separately approved worker budget only."""
    import re

    text = raw.decode()
    for service in ("api", "web", "worker"):
        block = re.search(rf"(?ms)^  {service}:\n(?:(?!^  [\w-]+:).)*", text)
        if block is None or len(re.findall(r"(?m)^    image:", block[0])) > 1:
            raise RuntimeError("FULL_SOURCE_COMPOSE_IMAGE_AMBIGUOUS:" + service)
        expression = rf"(?m)(^  {service}:\n(?:(?!^  \w).|\n)*?^    image: )[^\n]+"
        image = images[service]
        text, count = re.subn(expression, lambda m, image=image: m[1] + image, text)
        if count == 0 and service == "worker":
            text, count = re.subn(r"(?m)^  worker:\n", f"  worker:\n    image: {image}\n", text)
        if count != 1:
            raise RuntimeError("FULL_SOURCE_COMPOSE_IMAGE_AMBIGUOUS:" + service)
    if worker_budget is not None:
        block = re.search(r"(?ms)^  worker:\n(?:(?!^  [\w-]+:).)*", text)
        if block is None or worker_budget != FULL_WORKER_BUDGET:
            raise RuntimeError("FULL_SOURCE_WORKER_BUDGET_INVALID")
        updated = block[0]
        for key, value in worker_budget.items():
            updated, count = re.subn(rf"(?m)^    {key}: [^\n]+", f"    {key}: {value}", updated)
            if count != 1:
                raise RuntimeError("FULL_SOURCE_WORKER_BUDGET_AMBIGUOUS:" + key)
        text = text[: block.start()] + updated + text[block.end() :]
    return text.encode()


def full_configuration(overlay: Path | None = None) -> dict:
    from urllib.parse import urlsplit

    command = (
        "compose",
        "--profile",
        "*",
        "-p",
        "vibe-seller",
        "-f",
        str(HOST / "docker-compose.server.yml"),
        "-f",
        str(FULL_ACTIVE_COMPOSE),
    )
    if overlay is not None:
        command += ("-f", str(overlay))
    raw = full_docker(*command, "config", "--format", "json")
    config = json.loads(raw)
    worker = config["services"]["worker"]
    url = urlsplit(worker.get("environment", {}).get("DATABASE_ADMIN_URL", ""))
    if (url.username, url.hostname, url.path) != ("procurement_owner", "db", "/procurement"):
        raise RuntimeError("FULL_SOURCE_ADMIN_MIGRATION_ROLE_UNCONFIRMED")
    for name in ("api", "web", "worker"):
        for mount in config["services"][name].get("volumes", []):
            if mount.get("type") == "bind":
                raise RuntimeError("FULL_SOURCE_UNACCEPTED_RUNTIME_BIND:" + name)
    images = {name: config["services"][name].get("image") for name in ("api", "web", "worker")}
    for name in ("api", "web", "worker"):
        config["services"][name].pop("image", None)
        config["services"][name].pop("pull_policy", None)
    runtime_contract = sha(json.dumps(config, sort_keys=True).encode())
    worker_memory, worker_cpus = worker.get("mem_limit"), worker.get("cpus")
    worker.pop("mem_limit", None)
    worker.pop("cpus", None)
    return {
        "sha256": sha(raw),
        "worker_admin_role": url.username,
        "runtime_contract_sha256": runtime_contract,
        "non_worker_budget_contract_sha256": sha(json.dumps(config, sort_keys=True).encode()),
        "images": images,
        "worker_memory_limit": worker_memory,
        "worker_cpus": worker_cpus,
    }


def full_plan() -> dict:
    receipt = full_receipt()
    images = {name: value.image_id for name, value in receipt.artifacts.items()}
    for image in images.values():
        if full_docker("image", "inspect", "--format", "{{.Id}}", image).decode().strip() != image:
            raise RuntimeError("FULL_SOURCE_ARTIFACT_UNAVAILABLE")
    if full_schema() != FULL_SCHEMA_BEFORE:
        raise RuntimeError("FULL_SOURCE_SCHEMA_CONFLICT")
    source = receipt.path.parent / "source"
    compose = full_read(HOST / "docker-compose.server.yml")
    updated = full_compose(compose, images, FULL_WORKER_BUDGET)
    before_containers = full_containers()
    before_worker = (
        full_docker("image", "inspect", "--format", "{{.Id}}", "vibe-seller-worker")
        .decode()
        .strip()
    )
    old_images = {name: before_containers[name]["image"] for name in ("api", "web")}
    old_images["worker"] = before_worker
    overlay = full_overlay(images, FULL_WORKER_BUDGET)
    configuration = full_configuration()
    if (
        configuration["worker_memory_limit"] != str(2 * 1024**3)
        or configuration["worker_cpus"] != 2
    ):
        raise RuntimeError("FULL_SOURCE_WORKER_BASELINE_CHANGED")
    return {
        "schema": "production223-full-source-install-v2",
        "worker_budget_after": FULL_WORKER_BUDGET,
        "adapter_sha256": sha(full_read(Path(__file__))),
        "company_id": "local-eis-supplier",
        "source": FULL_SOURCE_ID,
        "receipt_sha256": FULL_RECEIPT_SHA,
        "images": images,
        "before_containers": before_containers,
        "before_worker_image": before_worker,
        "trusted_guards": full_guards(),
        "effective_configuration": configuration,
        "host_files": full_host_scope(source),
        "compose_before": sha(compose),
        "compose_after": sha(updated),
        "active_compose_sha256": sha(full_read(FULL_ACTIVE_COMPOSE)),
        "overlay_sha256": sha(overlay),
        "rollback_overlay_sha256": sha(full_overlay(old_images, FULL_WORKER_BUDGET_BEFORE)),
        "rollback_compose_sha256": sha(full_compose(compose, old_images)),
        "schema_before": FULL_SCHEMA_BEFORE,
        "schema_after": FULL_SCHEMA_AFTER,
        "rollback": (
            "Restore host files/config and old immutable images; "
            "preserve widened DB CHECK/history; never delete >4-archive rows"
        ),
        "backup_script_sha256": sha(full_read(HOST / "scripts/server-backup.sh")),
    }


def prepare_full_source() -> None:
    plan = full_plan()
    resources = full_resources()
    if FULL_STAGE.exists():
        if any(
            (FULL_STAGE / name).exists()
            for name in ("backup", "installation.json", "migration.json")
        ):
            raise RuntimeError("FULL_SOURCE_STAGE_ALREADY_ATTEMPTED")
        if (FULL_STAGE / "plan.json").exists():
            previous = full_read(FULL_STAGE / "plan.json")
            full_write(FULL_STAGE / ("plan-prior-" + sha(previous) + ".json"), previous)
    else:
        FULL_STAGE.mkdir(mode=0o700)
    raw = (json.dumps(plan, sort_keys=True, indent=2) + "\n").encode()
    full_write(FULL_STAGE / "plan.json", raw)
    overlay_path = FULL_STAGE / "compose.yml"
    full_write(overlay_path, full_overlay(plan["images"], plan["worker_budget_after"]))
    effective = full_configuration(overlay_path)
    full_check_install_configuration(plan, effective)
    print(
        json.dumps(
            {
                "status": "PREPARED_NOT_APPROVED",
                "plan_sha256": sha(raw),
                "stage": str(FULL_STAGE),
                "resources": resources,
            }
        )
    )


def preflight_full_source(expected_plan_sha256: str) -> dict:
    raw = full_read(FULL_STAGE / "plan.json")
    if sha(raw) != expected_plan_sha256:
        raise RuntimeError("FULL_SOURCE_EXACT_PLAN_MISMATCH")
    plan = json.loads(raw)
    if plan != full_plan():
        raise RuntimeError("FULL_SOURCE_INSTALLED_OR_PAYLOAD_CHANGED")
    return plan


def full_overlay(images: dict, worker_budget: dict | None = None) -> bytes:
    raw = (
        "services:\n"
        + "".join(
            f"  {name}:\n    image: {images[name]}\n    pull_policy: never\n"
            for name in ("api", "web", "worker")
        )
    ).encode()
    if worker_budget is not None:
        if worker_budget not in (FULL_WORKER_BUDGET, FULL_WORKER_BUDGET_BEFORE):
            raise RuntimeError("FULL_SOURCE_WORKER_BUDGET_INVALID")
        raw += (
            f"    mem_limit: {worker_budget['mem_limit']}\n    cpus: {worker_budget['cpus']}\n"
        ).encode()
    return raw


def full_check_install_configuration(plan: dict, effective: dict) -> None:
    if (
        plan["worker_budget_after"] != FULL_WORKER_BUDGET
        or effective["images"] != plan["images"]
        or effective["worker_memory_limit"] != str(3 * 1024**3)
        or effective["worker_cpus"] != 3
        or effective["non_worker_budget_contract_sha256"]
        != plan["effective_configuration"]["non_worker_budget_contract_sha256"]
    ):
        raise RuntimeError("FULL_SOURCE_RUNTIME_CONTRACT_CHANGED")


def full_command(overlay: Path) -> tuple[str, ...]:
    return (
        "compose",
        "-p",
        "vibe-seller",
        "-f",
        str(HOST / "docker-compose.server.yml"),
        "-f",
        str(FULL_ACTIVE_COMPOSE),
        "-f",
        str(overlay),
    )


def full_health() -> None:
    full_docker(
        "exec",
        "vibe-seller-api-1",
        "python",
        "-c",
        "import time,urllib.request; deadline=time.monotonic()+40; "
        'exec("while True:\\n try:\\n  '
        "urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5); break"
        "\\n except Exception:\\n  if time.monotonic()>deadline: raise"
        '\\n  time.sleep(1)")',
        timeout=65,
    )
    full_docker(
        "exec",
        "vibe-seller-web-1",
        "node",
        "-e",
        "fetch('http://127.0.0.1:3000/tender-discovery', {signal:AbortSignal.timeout(20000)})"
        ".then(r=>{if(r.status!==200)process.exit(1)}).catch(()=>process.exit(1))",
        timeout=30,
    )


def full_migrate(command: tuple[str, ...], image: str) -> None:
    name = "vibe-seller-production223-migration"
    label = "com.syurai.production223-plan"
    plan_sha = sha(full_read(FULL_STAGE / "plan.json"))
    existing = full_docker("ps", "-aq", "--filter", "name=^/" + name + "$").decode().strip()
    if existing:
        raise RuntimeError("FULL_SOURCE_MIGRATION_CONTAINER_ALREADY_EXISTS")
    try:
        output = (
            full_docker(
                *command,
                "run",
                "-d",
                "-T",
                "--no-deps",
                "--pull",
                "never",
                "--name",
                name,
                "-l",
                label + "=" + plan_sha,
                "-e",
                "PGOPTIONS=-c lock_timeout=30000 -c statement_timeout=120000",
                "worker",
                "alembic",
                "upgrade",
                FULL_SCHEMA_AFTER,
            )
            .decode()
            .splitlines()
        )
        ids = [
            line.strip()
            for line in output
            if len(line.strip()) == 64 and all(c in "0123456789abcdef" for c in line.strip())
        ]
        if len(ids) != 1:
            raise RuntimeError("FULL_SOURCE_MIGRATION_CONTAINER_ID_INVALID")
        container = ids[0]
        identity = json.loads(full_docker("inspect", container))[0]
        if identity["Image"] != image or identity["Config"]["Labels"].get(label) != plan_sha:
            raise RuntimeError("FULL_SOURCE_MIGRATION_IMAGE_MISMATCH")
        full_write(
            FULL_STAGE / "migration.json",
            json.dumps(
                {"container_id": container, "image": image, "started_at_unix": time.time()}
            ).encode(),
        )
        exit_code = full_docker("wait", container, timeout=150).decode().strip()
        if exit_code != "0":
            full_write(FULL_STAGE / "migration.log", full_docker("logs", container))
            raise RuntimeError("FULL_SOURCE_MIGRATION_FAILED")
    except subprocess.CalledProcessError as error:
        full_write(FULL_STAGE / "migration-launch.log", error.output or b"")
        raise
    finally:
        found = (
            full_docker("ps", "-aq", "--no-trunc", "--filter", "name=^/" + name + "$")
            .decode()
            .strip()
        )
        if found:
            identity = json.loads(full_docker("inspect", found))[0]
            if identity["Image"] != image or identity["Config"]["Labels"].get(label) != plan_sha:
                raise RuntimeError("FULL_SOURCE_MIGRATION_CLEANUP_IDENTITY_CHANGED")
            full_docker("rm", "-f", found, timeout=30)


def full_restore(plan: dict, changed: list[str]) -> None:
    backup = FULL_STAGE / "backup"
    originals = {}
    for name, operation in plan["host_files"].items():
        target = HOST / name
        current = sha(full_read(target)) if target.exists() else None
        if current not in {operation["before"], operation["after"]}:
            raise RuntimeError("FULL_SOURCE_ROLLBACK_HOST_CHANGED:" + name)
        if name in changed and operation["before"] is not None:
            raw = full_read(backup / name)
            if sha(raw) != operation["before"]:
                raise RuntimeError("FULL_SOURCE_ROLLBACK_BACKUP_CHANGED")
            originals[name] = raw
    original = full_read(backup / "compose.yml")
    if sha(original) != plan["compose_before"]:
        raise RuntimeError("FULL_SOURCE_ROLLBACK_COMPOSE_BACKUP_CHANGED")
    if sha(full_read(HOST / "docker-compose.server.yml")) not in {
        plan["compose_before"],
        plan["compose_after"],
        plan["rollback_compose_sha256"],
    }:
        raise RuntimeError("FULL_SOURCE_ROLLBACK_COMPOSE_CHANGED")
    if sha(full_read(FULL_ACTIVE_COMPOSE)) != plan["active_compose_sha256"]:
        raise RuntimeError("FULL_SOURCE_ROLLBACK_ACTIVE_COMPOSE_CHANGED")
    old_images = {
        service: plan["before_containers"][service]["image"] for service in ("api", "web")
    }
    old_images["worker"] = plan["before_worker_image"]
    inverse = full_overlay(old_images, FULL_WORKER_BUDGET_BEFORE)
    restored_compose = full_compose(original, old_images)
    if (
        sha(inverse) != plan["rollback_overlay_sha256"]
        or sha(restored_compose) != plan["rollback_compose_sha256"]
    ):
        raise RuntimeError("FULL_SOURCE_ROLLBACK_PAYLOAD_CHANGED")
    full_write(FULL_STAGE / "compose-rollback.yml", inverse)
    effective = full_configuration(FULL_STAGE / "compose-rollback.yml")
    if (
        effective["images"] != old_images
        or effective["runtime_contract_sha256"]
        != plan["effective_configuration"]["runtime_contract_sha256"]
    ):
        raise RuntimeError("FULL_SOURCE_ROLLBACK_RUNTIME_CONTRACT_CHANGED")
    for name in reversed(changed):
        operation = plan["host_files"][name]
        target = HOST / name
        if operation["before"] is None:
            if target.is_symlink():
                raise RuntimeError("FULL_SOURCE_ROLLBACK_SYMLINK")
            target.unlink(missing_ok=True)
        else:
            full_write(target, originals[name], operation["mode"])
    full_write(HOST / "docker-compose.server.yml", restored_compose)
    full_docker(
        *full_command(FULL_STAGE / "compose-rollback.yml"),
        "up",
        "-d",
        "--no-build",
        "--pull",
        "never",
        "--no-deps",
        "api",
        "web",
        timeout=120,
    )
    identities = full_containers()
    for service in ("api", "web"):
        if identities[service]["image"] != old_images[service]:
            raise RuntimeError("FULL_SOURCE_ROLLBACK_IMAGE_MISMATCH")
    if identities["db"] != plan["before_containers"]["db"]:
        raise RuntimeError("FULL_SOURCE_ROLLBACK_DATABASE_IDENTITY_CHANGED")
    for name in changed:
        path = HOST / name
        actual = sha(full_read(path)) if path.exists() else None
        if actual != plan["host_files"][name]["before"]:
            raise RuntimeError("FULL_SOURCE_ROLLBACK_HOST_PARITY_MISMATCH")
    full_health()


def install_full_source(expected_plan_sha256: str, approval_reference: str) -> None:
    """Separate exact human approval is required for this pinned plan."""
    if not approval_reference or len(approval_reference) > 500:
        raise RuntimeError("FULL_SOURCE_EXACT_APPROVAL_REFERENCE_REQUIRED")
    preflight_full_source(expected_plan_sha256)
    result = {
        "status": "ATTEMPT_STARTED",
        "plan_sha256": expected_plan_sha256,
        "approval_reference": approval_reference,
        "actor": "operator",
        "started_at_unix": time.time(),
        "database_downgraded": False,
    }
    changed: list[str] = []
    production_write_started = False
    try:
        with deployment_lease():
            plan = preflight_full_source(expected_plan_sha256)
            full_guards(require_active=True)
            result["resources_before"] = full_resources()
            backup = FULL_STAGE / "backup"
            if backup.exists():
                raise RuntimeError("FULL_SOURCE_INSTALL_ALREADY_ATTEMPTED")
            full_write(FULL_STAGE / "installation.json", json.dumps(result, indent=2).encode())
            # Existing verified private pg_dump; not another EIS capture/restore.
            full_run("bash", str(HOST / "scripts/server-backup.sh"), timeout=900)
            backup.mkdir(mode=0o700)
            compose_path = HOST / "docker-compose.server.yml"
            compose = full_read(compose_path)
            full_write(backup / "compose.yml", compose)
            for name, operation in plan["host_files"].items():
                if operation["before"] is not None:
                    full_write(backup / name, full_read(HOST / name))
            source = FULL_BASE / "gate-state/runs" / FULL_RUN / "source"
            overlay_path = FULL_STAGE / "compose.yml"
            full_write(overlay_path, full_overlay(plan["images"], plan["worker_budget_after"]))
            command = full_command(overlay_path)
            full_docker(*command, "config", "--quiet")
            effective = full_configuration(overlay_path)
            full_check_install_configuration(plan, effective)
            # Hashes, receipt and installed state checked under lease after backup.
            preflight_full_source(expected_plan_sha256)
            try:
                production_write_started = True
                full_migrate(command, plan["images"]["worker"])
                if full_schema() != FULL_SCHEMA_AFTER:
                    raise RuntimeError("FULL_SOURCE_MIGRATION_NOT_INSTALLED")
                definition = full_docker(
                    "exec",
                    "vibe-seller-db-1",
                    "psql",
                    "-U",
                    "procurement_owner",
                    "-d",
                    "procurement",
                    "-Atqc",
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='eis_223_windows'::regclass AND conname='ck_eis_223_counts'",
                ).decode()
                if "archive_count <= 8" not in definition or "record_count >= 1" not in definition:
                    raise RuntimeError("FULL_SOURCE_DATABASE_CONSTRAINT_UNCONFIRMED")
                for name, operation in plan["host_files"].items():
                    if operation["before"] == operation["after"]:
                        continue
                    raw = full_read(source / name)
                    if sha(raw) != operation["after"]:
                        raise RuntimeError("FULL_SOURCE_SEALED_FILE_CHANGED")
                    changed.append(name)
                    full_write(HOST / name, raw, operation["mode"])
                full_write(
                    compose_path, full_compose(compose, plan["images"], plan["worker_budget_after"])
                )
                full_docker(
                    *command,
                    "up",
                    "-d",
                    "--no-build",
                    "--pull",
                    "never",
                    "--no-deps",
                    "api",
                    "web",
                    timeout=120,
                )
                identities = full_containers()
                for service in ("api", "web"):
                    if identities[service]["image"] != plan["images"][service]:
                        raise RuntimeError("FULL_SOURCE_INSTALLED_IMAGE_MISMATCH")
                if identities["db"] != plan["before_containers"]["db"]:
                    raise RuntimeError("FULL_SOURCE_DATABASE_IDENTITY_CHANGED")
                for name, operation in plan["host_files"].items():
                    if sha(full_read(HOST / name)) != operation["after"]:
                        raise RuntimeError("FULL_SOURCE_HOST_PARITY_MISMATCH")
                full_health()
                result.update(
                    status="INSTALLED_PENDING_LEASE_CLEANUP",
                    containers=identities,
                    schema=full_schema(),
                )
            except BaseException:
                try:
                    full_restore(plan, changed)
                    result["rollback"] = "VERIFIED_IMAGES_HOST_HEALTH; DB_CHECK_PRESERVED"
                except BaseException as recovery:
                    result["rollback"] = "UNKNOWN"
                    result["rollback_error_type"] = type(recovery).__name__
                raise
        result["status"] = "INSTALLED"
        result["lease_cleanup"] = "PASS"
    except BaseException as error:
        result["status"] = (
            "FAILED"
            if result["status"] != "INSTALLED_PENDING_LEASE_CLEANUP"
            else "INSTALLED_CLEANUP_FAILED"
        )
        result["error_type"] = type(error).__name__
        if isinstance(error, RuntimeError):
            result["reason"] = str(error)
        result["production_write_started"] = production_write_started
        raise
    finally:
        result["finished_at_unix"] = time.time()
        full_write(FULL_STAGE / "installation.json", (json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps(result))


def rollback_full_source(expected_plan_sha256: str, approval_reference: str) -> None:
    if not approval_reference or len(approval_reference) > 500:
        raise RuntimeError("FULL_SOURCE_EXACT_APPROVAL_REFERENCE_REQUIRED")
    raw = full_read(FULL_STAGE / "plan.json")
    if sha(raw) != expected_plan_sha256:
        raise RuntimeError("FULL_SOURCE_EXACT_PLAN_MISMATCH")
    plan = json.loads(raw)
    if plan["adapter_sha256"] != sha(full_read(Path(__file__))):
        raise RuntimeError("FULL_SOURCE_ADAPTER_CHANGED")
    result = {
        "status": "ROLLBACK_ATTEMPT",
        "plan_sha256": expected_plan_sha256,
        "approval_reference": approval_reference,
        "actor": "operator",
        "started_at_unix": time.time(),
        "database_downgraded": False,
    }
    try:
        with deployment_lease(request_priority=False):
            full_receipt()
            full_guards(require_active=True)
            identities = full_containers(require_running=False)
            if identities["db"] != plan["before_containers"]["db"]:
                raise RuntimeError("FULL_SOURCE_ROLLBACK_DATABASE_IDENTITY_CHANGED")
            for name in ("api", "web"):
                if identities[name]["image"] not in {
                    plan["images"][name],
                    plan["before_containers"][name]["image"],
                }:
                    raise RuntimeError("FULL_SOURCE_ROLLBACK_INSTALLED_IMAGES_CHANGED")
            full_write(FULL_STAGE / "rollback.json", json.dumps(result, indent=2).encode())
            changed = [
                name for name, op in plan["host_files"].items() if op["before"] != op["after"]
            ]
            full_restore(plan, changed)
            result["status"] = "ROLLED_BACK_PENDING_LEASE_CLEANUP"
        result["status"] = "ROLLED_BACK_DB_HISTORY_PRESERVED"
        result["lease_cleanup"] = "PASS"
    except BaseException as error:
        result["status"] = "ROLLBACK_FAILED_OR_CLEANUP_UNKNOWN"
        result["error_type"] = type(error).__name__
        if isinstance(error, RuntimeError):
            result["reason"] = str(error)
        raise
    finally:
        result["finished_at_unix"] = time.time()
        full_write(FULL_STAGE / "rollback.json", json.dumps(result, indent=2).encode())
    print(json.dumps(result))


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
def deployment_lease(request_priority: bool = True):
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
            if name == "eis-priority.lock" and request_priority:
                result = (
                    full_docker(
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
        try:
            if marker_owned:
                full_docker(
                    "exec",
                    "vibe-seller-api-1",
                    "python",
                    "-c",
                    "from pathlib import Path; "
                    "Path('/var/lib/eis-browser/eis-priority.request').unlink(missing_ok=True)",
                    timeout=30,
                )
        finally:
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
    parser.add_argument(
        "mode",
        choices=(
            "prepare",
            "install",
            "enable-init",
            "full-source-prepare",
            "full-source-preflight",
            "full-source-install",
            "full-source-rollback",
        ),
    )
    parser.add_argument("stage", type=Path, nargs="?")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--approval-reference")
    args = parser.parse_args()
    if args.mode.startswith("full-source-"):
        if args.stage is not None:
            parser.error("full source uses the pinned stage only")
        if args.mode == "full-source-prepare":
            prepare_full_source()
        elif args.mode == "full-source-preflight":
            preflight_full_source(args.expected_plan_sha256 or "")
            print(json.dumps({"status": "PREFLIGHT_PASS_NOT_APPROVED"}))
        elif args.mode == "full-source-install":
            install_full_source(args.expected_plan_sha256 or "", args.approval_reference or "")
        else:
            rollback_full_source(args.expected_plan_sha256 or "", args.approval_reference or "")
    else:
        if args.stage is None:
            parser.error("legacy stage required")
        resolved = args.stage.resolve()
        if resolved.parent != STATE / "supplier-browser-rollout":
            parser.error("stage must be inside the dedicated rollout directory")
        {"prepare": prepare, "install": install, "enable-init": enable_init}[args.mode](resolved)
