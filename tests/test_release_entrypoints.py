"""Legacy mutators must refuse before touching an unaccepted deployment payload."""

from __future__ import annotations

import json
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class ForbiddenStage:
    def __truediv__(self, name: str) -> Path:
        raise AssertionError(f"unaccepted stage accessed: {name}")


@pytest.mark.parametrize(
    ("filename", "entrypoint", "source_kind"),
    [
        ("server-supplier-browser-rollout.py", "install", "INSTALLED_BASE_OVERLAY"),
        ("server-supplier-browser-rollout.py", "install_locked", "INSTALLED_BASE_OVERLAY"),
        ("server-supplier-browser-rollout.py", "enable_init", "CONFIG_CHANGE"),
        ("server-supplier-captcha-rollout.py", "install", "INSTALLED_BASE_OVERLAY"),
    ],
)
def test_legacy_mutator_refuses_before_any_payload_or_runtime_access(
    filename: str, entrypoint: str, source_kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = spec_from_file_location("legacy_rollout_under_test", ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("runtime, lease or source access before quality admission")

    for name in ("docker", "run", "atomic", "write", "deployment_lease", "spec_from_file_location"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, forbidden)
    with pytest.raises(RuntimeError, match=f"QUALITY_GATE_ADAPTER_UNAVAILABLE: {source_kind}"):
        getattr(module, entrypoint)(ForbiddenStage())


@pytest.fixture
def full_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = spec_from_file_location(
        "full_rollout_test", ROOT / "scripts/server-supplier-browser-rollout.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, value in (
        ("HOST", tmp_path / "host"),
        ("STATE", tmp_path / "state"),
        ("FULL_STAGE", tmp_path / "state/stage"),
        ("FULL_BASE", tmp_path / "state/provider"),
    ):
        monkeypatch.setattr(module, name, value)
        value.mkdir(parents=True, exist_ok=True)
    return module


def test_full_source_compose_preserves_environment_limits_and_adds_worker_image(full_adapter):
    raw = (
        b"services:\n  api:\n    image: api:old\n    mem_limit: 1g\n"
        b"    environment:\n      TOKEN: private\n  web:\n    image: web:old\n"
        b"    mem_limit: 768m\n  worker:\n    build:\n      context: .\n"
        b"    mem_limit: 2g\n    cpus: 2\n"
    )
    images = {"api": "sha256:a", "web": "sha256:b", "worker": "sha256:a"}
    changed = full_adapter.full_compose(raw, images)
    assert changed == raw.replace(b"api:old", b"sha256:a").replace(b"web:old", b"sha256:b").replace(
        b"  worker:\n", b"  worker:\n    image: sha256:a\n"
    )


def test_full_source_rejects_ambiguous_image_before_rewrite(full_adapter):
    with pytest.raises(RuntimeError, match="COMPOSE_IMAGE_AMBIGUOUS"):
        full_adapter.full_compose(
            b"services:\n  api:\n    image: a\n    image: b\n", {"api": "new"}
        )


def test_full_source_secure_writer_does_not_use_legacy_predictable_temp(full_adapter):
    path = full_adapter.HOST / "runtime.py"
    predictable = path.with_name(path.name + ".supplier-rollout-tmp")
    predictable.write_bytes(b"must remain unchanged")
    full_adapter.full_write(path, b"accepted bytes")
    assert path.read_bytes() == b"accepted bytes"
    assert predictable.read_bytes() == b"must remain unchanged"
    assert not list(path.parent.glob(".full-source-*"))
    with pytest.raises(RuntimeError, match="WRITE_OUTSIDE_SCOPE"):
        full_adapter.full_write(full_adapter.HOST.parent / "outside", b"forbidden")


def test_full_source_verifier_executes_hash_verified_bytes_without_pyc(full_adapter, monkeypatch):
    provider = full_adapter.FULL_BASE / "provider"
    provider.mkdir()
    raw = b"def verify_release_receipt(*args, **kwargs):\n    return kwargs['expected_source']\n"
    verifier = provider / "release_gate_receipt.py"
    verifier.write_bytes(raw)
    (provider / "release_gate_receipt.pyc").write_bytes(b"untrusted compiled bytes")
    (provider / "release_gate_policy.json").write_bytes(b"policy")
    receipt = (
        full_adapter.FULL_BASE / "gate-state/runs" / full_adapter.FULL_RUN / "release-receipt.json"
    )
    receipt.parent.mkdir(parents=True)
    receipt.write_bytes(b"receipt")
    for name, value in (
        ("FULL_VERIFIER_SHA", raw),
        ("FULL_POLICY_SHA", b"policy"),
        ("FULL_RECEIPT_SHA", b"receipt"),
    ):
        monkeypatch.setattr(full_adapter, name, full_adapter.sha(value))
    assert full_adapter.full_receipt() == full_adapter.FULL_SOURCE_ID
    verifier.write_bytes(b"raise AssertionError('must not execute')")
    with pytest.raises(RuntimeError, match="TRUSTED_IDENTITY_CHANGED"):
        full_adapter.full_receipt()


def test_full_source_tampered_plan_refuses_before_lease_or_host_access(full_adapter, monkeypatch):
    (full_adapter.FULL_STAGE / "plan.json").write_bytes(b"{}")
    calls = []
    monkeypatch.setattr(full_adapter, "deployment_lease", lambda: calls.append("lease"))
    with pytest.raises(RuntimeError, match="EXACT_PLAN_MISMATCH"):
        full_adapter.install_full_source("incorrect", "test exact approval")
    assert calls == []


def test_full_source_host_inventory_refuses_unaccepted_executable(full_adapter):
    source = full_adapter.STATE / "source"
    source.mkdir()
    (source / "release-manifest.json").write_text('{"files": []}')
    scripts = full_adapter.HOST / "scripts"
    scripts.mkdir()
    (scripts / "server-unaccepted.py").write_bytes(b"unaccepted")
    with pytest.raises(RuntimeError, match="UNACCEPTED_HOST_EXECUTABLE"):
        full_adapter.full_host_scope(source)


def _installation_fixture(module, monkeypatch):
    compose = (
        b"services:\n  api:\n    image: a\n  web:\n    image: b\n"
        b"  worker:\n    image: w\n    mem_limit: 2g\n    cpus: 2.0\n"
    )
    (module.HOST / "docker-compose.server.yml").write_bytes(compose)
    source = module.FULL_BASE / "gate-state/runs" / module.FULL_RUN / "source"
    source.mkdir(parents=True)
    name = "src/procurement/changed.py"
    (source / name).parent.mkdir(parents=True)
    (source / name).write_bytes(b"new")
    (module.HOST / name).parent.mkdir(parents=True)
    (module.HOST / name).write_bytes(b"old")
    before = {
        "api": {"id": "a1", "image": "a"},
        "web": {"id": "w1", "image": "b"},
        "db": {"id": "d1", "image": "db"},
    }
    plan = {
        "host_files": {
            name: {"before": module.sha(b"old"), "after": module.sha(b"new"), "mode": 0o600}
        },
        "images": {"api": "new-a", "web": "new-w", "worker": "new-a"},
        "worker_budget_after": module.FULL_WORKER_BUDGET,
        "before_containers": before,
        "before_worker_image": "w",
        "compose_before": module.sha(compose),
        "compose_after": module.sha(
            module.full_compose(
                compose,
                {"api": "new-a", "web": "new-w", "worker": "new-a"},
                module.FULL_WORKER_BUDGET,
            )
        ),
        "active_compose_sha256": module.sha(b"active"),
    }
    module.FULL_ACTIVE_COMPOSE = module.STATE / "active.yml"
    module.FULL_ACTIVE_COMPOSE.write_bytes(b"active")
    monkeypatch.setattr(module, "preflight_full_source", lambda _: plan)
    monkeypatch.setattr(module, "full_resources", lambda: {})
    monkeypatch.setattr(module, "full_guards", lambda **kwargs: {})
    monkeypatch.setattr(module, "full_schema", lambda: module.FULL_SCHEMA_AFTER)

    @contextmanager
    def lease():
        yield

    monkeypatch.setattr(module, "deployment_lease", lease)
    monkeypatch.setattr(module, "full_run", lambda *args, **kwargs: b"backup")
    plan["effective_configuration"] = {
        "runtime_contract_sha256": "same",
        "non_worker_budget_contract_sha256": "same",
    }
    old_images = {"api": "a", "web": "b", "worker": "w"}
    plan["rollback_compose_sha256"] = module.sha(module.full_compose(compose, old_images))
    plan["rollback_overlay_sha256"] = module.sha(
        module.full_overlay(old_images, module.FULL_WORKER_BUDGET_BEFORE)
    )
    monkeypatch.setattr(
        module,
        "full_configuration",
        lambda *args: {
            "images": (
                old_images if args and args[0].name == "compose-rollback.yml" else plan["images"]
            ),
            "runtime_contract_sha256": "same",
            "non_worker_budget_contract_sha256": "same",
            "worker_memory_limit": str(3 * 1024**3),
            "worker_cpus": 3,
        },
    )
    return plan, name


def test_full_source_backup_failure_records_terminal_audit_without_production_write(
    full_adapter, monkeypatch
):
    _, name = _installation_fixture(full_adapter, monkeypatch)

    def failure(*args, **kwargs):
        raise RuntimeError("BACKUP_FAILURE")

    monkeypatch.setattr(full_adapter, "full_run", failure)
    with pytest.raises(RuntimeError, match="BACKUP_FAILURE"):
        full_adapter.install_full_source("exact-plan", "approved test")
    result = json.loads((full_adapter.FULL_STAGE / "installation.json").read_text())
    assert result["status"] == "FAILED" and not result["production_write_started"]
    assert (full_adapter.HOST / name).read_bytes() == b"old"


def test_full_source_health_failure_restores_exact_images_and_host_bytes(full_adapter, monkeypatch):
    plan, name = _installation_fixture(full_adapter, monkeypatch)
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "exec":
            return b"CHECK (archive_count <= 8 AND record_count >= 1)"
        return b""

    monkeypatch.setattr(full_adapter, "full_docker", docker)
    monkeypatch.setattr(full_adapter, "full_migrate", lambda *args: None)
    new = {k: dict(v) for k, v in plan["before_containers"].items()}
    new["api"]["image"], new["web"]["image"] = "new-a", "new-w"
    identities = iter((new, plan["before_containers"]))
    monkeypatch.setattr(full_adapter, "full_containers", lambda: next(identities))
    health = iter((False, True))

    def check_health():
        if not next(health):
            raise RuntimeError("HEALTH_FAILURE")

    monkeypatch.setattr(full_adapter, "full_health", check_health)
    with pytest.raises(RuntimeError, match="HEALTH_FAILURE"):
        full_adapter.install_full_source("exact-plan", "approved test")
    result = json.loads((full_adapter.FULL_STAGE / "installation.json").read_text())
    assert result["rollback"].startswith("VERIFIED_IMAGES_HOST_HEALTH")
    assert result["database_downgraded"] is False
    assert (full_adapter.HOST / name).read_bytes() == b"old"
    inverse = (full_adapter.FULL_STAGE / "compose-rollback.yml").read_text()
    assert "image: a\n" in inverse and "image: b\n" in inverse and "image: w\n" in inverse
    assert all("build" not in args and "tag" not in args for args in calls)


def test_full_source_migration_uses_admin_worker_bounded_wait_and_cleans_timeout(
    full_adapter, monkeypatch
):
    import subprocess

    (full_adapter.FULL_STAGE / "plan.json").write_bytes(b"{}")
    container = "a" * 64
    identity = [
        {
            "Image": "accepted",
            "Config": {"Labels": {"com.syurai.production223-plan": full_adapter.sha(b"{}")}},
        }
    ]
    calls = []
    ps = iter((b"", container.encode()))

    def docker(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "ps":
            return next(ps)
        if "run" in args:
            return b"compose warning\n" + container.encode() + b"\n"
        if args[0] == "inspect":
            return json.dumps(identity).encode()
        if args[0] == "wait":
            raise subprocess.TimeoutExpired("wait", 150)
        return b""

    monkeypatch.setattr(full_adapter, "full_docker", docker)
    with pytest.raises(subprocess.TimeoutExpired):
        full_adapter.full_migrate(("compose",), "accepted")
    invocation = next(args for args, _ in calls if "run" in args)
    assert "worker" in invocation and "--no-build" not in invocation and "never" in invocation
    assert "PGOPTIONS=-c lock_timeout=30000 -c statement_timeout=120000" in invocation
    assert (("rm", "-f", container), {"timeout": 30}) in calls


def test_full_source_health_probe_contains_valid_python(full_adapter, monkeypatch):
    import ast

    calls = []
    monkeypatch.setattr(
        full_adapter, "full_docker", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    full_adapter.full_health()
    ast.parse(calls[0][0][-1])
    assert calls[0][1]["timeout"] == 65 and calls[1][1]["timeout"] == 30


def test_full_source_runtime_configuration_rejects_app_role_for_migration(
    full_adapter, monkeypatch
):
    config = {
        "services": {
            "api": {},
            "web": {},
            "worker": {
                "environment": {
                    "DATABASE_ADMIN_URL": "postgresql://procurement_app:synthetic@db/procurement"
                }
            },
        }
    }
    monkeypatch.setattr(full_adapter, "full_docker", lambda *args: json.dumps(config).encode())
    with pytest.raises(RuntimeError, match="ADMIN_MIGRATION_ROLE_UNCONFIRMED"):
        full_adapter.full_configuration()
    config["services"]["worker"]["environment"]["DATABASE_ADMIN_URL"] = (
        "postgresql://procurement_owner:synthetic@db/procurement"
    )
    config["services"]["worker"].update(mem_limit="2147483648", cpus=2)
    before = full_adapter.full_configuration()
    for service in config["services"].values():
        service.update(image="sha256:new", pull_policy="never")
    after = full_adapter.full_configuration()
    assert before["runtime_contract_sha256"] == after["runtime_contract_sha256"]
    config["services"]["worker"]["cpus"] = 4
    assert (
        full_adapter.full_configuration()["runtime_contract_sha256"]
        != after["runtime_contract_sha256"]
    )


def test_deployment_lease_closes_all_handles_when_marker_cleanup_fails(full_adapter, monkeypatch):
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "fcntl",
        SimpleNamespace(
            LOCK_EX=1,
            LOCK_NB=2,
            flock=lambda *args: None,
        ),
    )
    handles = []
    original = type(full_adapter.STATE).open

    def open_path(path, *args, **kwargs):
        handle = original(path, *args, **kwargs)
        if path.suffix == ".lock":
            handles.append(handle)
        return handle

    monkeypatch.setattr(type(full_adapter.STATE), "open", open_path)
    outputs = iter((b"CREATED", RuntimeError("MARKER_CLEANUP_FAILED")))

    def docker(*args, **kwargs):
        value = next(outputs)
        if isinstance(value, RuntimeError):
            raise value
        return value

    monkeypatch.setattr(full_adapter, "full_docker", docker)
    with (
        pytest.raises(RuntimeError, match="MARKER_CLEANUP_FAILED"),
        full_adapter.deployment_lease(),
    ):
        assert len(handles) == 4
    assert all(handle.closed for handle in handles)


def test_unaccepted_rollout_name_cannot_bypass_host_inventory(full_adapter):
    source = full_adapter.STATE / "source"
    source.mkdir()
    (source / "release-manifest.json").write_text('{"files": []}')
    scripts = full_adapter.HOST / "scripts"
    scripts.mkdir()
    (scripts / "server-unaccepted-rollout.py").write_bytes(b"unaccepted")
    with pytest.raises(RuntimeError, match="UNACCEPTED_HOST_EXECUTABLE"):
        full_adapter.full_host_scope(source)


def test_rollback_rechecks_receipt_under_lease_and_keeps_terminal_failure_audit(
    full_adapter, monkeypatch
):
    plan, _ = _installation_fixture(full_adapter, monkeypatch)
    plan["adapter_sha256"] = full_adapter.sha(full_adapter.full_read(Path(full_adapter.__file__)))
    raw = json.dumps(plan).encode()
    (full_adapter.FULL_STAGE / "plan.json").write_bytes(raw)
    calls = []

    @contextmanager
    def lease(**kwargs):
        calls.append("lease_enter")
        try:
            yield
        finally:
            calls.append("lease_exit")

    def receipt():
        calls.append("receipt")
        raise RuntimeError("RECEIPT_INVALIDATED")

    monkeypatch.setattr(full_adapter, "deployment_lease", lease)
    monkeypatch.setattr(full_adapter, "full_receipt", receipt)
    with pytest.raises(RuntimeError, match="RECEIPT_INVALIDATED"):
        full_adapter.rollback_full_source(full_adapter.sha(raw), "approved rollback")
    assert calls == ["lease_enter", "receipt", "lease_exit"]
    result = json.loads((full_adapter.FULL_STAGE / "rollback.json").read_text())
    assert result["status"] == "ROLLBACK_FAILED_OR_CLEANUP_UNKNOWN"
    assert result["database_downgraded"] is False


def test_full_source_rollback_can_retry_its_exact_inverse_after_compose_failure(
    full_adapter, monkeypatch
):
    plan, name = _installation_fixture(full_adapter, monkeypatch)
    backup = full_adapter.FULL_STAGE / "backup"
    (backup / name).parent.mkdir(parents=True)
    (backup / name).write_bytes(b"old")
    original = (full_adapter.HOST / "docker-compose.server.yml").read_bytes()
    (backup / "compose.yml").write_bytes(original)
    (full_adapter.HOST / name).write_bytes(b"new")
    full_adapter.full_write(
        full_adapter.HOST / "docker-compose.server.yml",
        full_adapter.full_compose(original, plan["images"], plan["worker_budget_after"]),
    )
    up = iter((False, True))

    def docker(*args, **kwargs):
        if "up" in args and not next(up):
            raise RuntimeError("FIRST_ROLLBACK_COMPOSE_FAILURE")
        return b""

    monkeypatch.setattr(full_adapter, "full_docker", docker)
    monkeypatch.setattr(full_adapter, "full_containers", lambda: plan["before_containers"])
    monkeypatch.setattr(full_adapter, "full_health", lambda: None)
    with pytest.raises(RuntimeError, match="FIRST_ROLLBACK_COMPOSE_FAILURE"):
        full_adapter.full_restore(plan, [name])
    assert (
        full_adapter.sha((full_adapter.HOST / "docker-compose.server.yml").read_bytes())
        == plan["rollback_compose_sha256"]
    )
    full_adapter.full_restore(plan, [name])
    assert (full_adapter.HOST / name).read_bytes() == b"old"


def test_rollback_refuses_environment_drift_before_restoring_host_code(full_adapter, monkeypatch):
    plan, name = _installation_fixture(full_adapter, monkeypatch)
    backup = full_adapter.FULL_STAGE / "backup"
    (backup / name).parent.mkdir(parents=True)
    (backup / name).write_bytes(b"old")
    (backup / "compose.yml").write_bytes(
        (full_adapter.HOST / "docker-compose.server.yml").read_bytes()
    )
    (full_adapter.HOST / name).write_bytes(b"new")
    monkeypatch.setattr(
        full_adapter,
        "full_configuration",
        lambda *args: {
            "images": {"api": "a", "web": "b", "worker": "w"},
            "runtime_contract_sha256": "changed-env",
        },
    )
    with pytest.raises(RuntimeError, match="ROLLBACK_RUNTIME_CONTRACT_CHANGED"):
        full_adapter.full_restore(plan, [name])
    assert (full_adapter.HOST / name).read_bytes() == b"new"


def test_rollback_inspection_allows_stopped_app_but_requires_running_database(
    full_adapter, monkeypatch
):
    database_running = True

    def docker(*args, **kwargs):
        service = args[1].removeprefix("vibe-seller-").removesuffix("-1")
        return json.dumps(
            [
                {
                    "Id": service,
                    "Image": service,
                    "State": {"Running": database_running if service == "db" else False},
                }
            ]
        ).encode()

    monkeypatch.setattr(full_adapter, "full_docker", docker)
    assert set(full_adapter.full_containers(require_running=False)) == {"api", "web", "db"}
    with pytest.raises(RuntimeError, match="SERVICE_NOT_RUNNING:api"):
        full_adapter.full_containers()
    database_running = False
    with pytest.raises(RuntimeError, match="SERVICE_NOT_RUNNING:db"):
        full_adapter.full_containers(require_running=False)


def test_full_source_approved_budget_changes_worker_only_and_inverse_preserves_original(
    full_adapter,
):
    raw = (
        b"services:\n  api:\n    image: a\n    mem_limit: 1g\n"
        b"  web:\n    image: b\n    mem_limit: 768m\n"
        b"  worker:\n    image: c\n    mem_limit: 2g\n    cpus: 2.0\n"
    )
    images = {"api": "a", "web": "b", "worker": "c"}
    assert full_adapter.full_compose(raw, images, full_adapter.FULL_WORKER_BUDGET) == raw.replace(
        b"mem_limit: 2g", b"mem_limit: 3g"
    ).replace(b"cpus: 2.0", b"cpus: 3.0")
    assert full_adapter.full_compose(raw, images) == raw
    with pytest.raises(RuntimeError, match="WORKER_BUDGET_INVALID"):
        full_adapter.full_compose(raw, images, {"mem_limit": "4g", "cpus": 4})
    with pytest.raises(RuntimeError, match="WORKER_BUDGET_AMBIGUOUS"):
        full_adapter.full_compose(
            raw.replace(b"    cpus: 2.0\n", b""), images, full_adapter.FULL_WORKER_BUDGET
        )


def test_full_source_only_exact_worker_budget_allows_configuration_delta(full_adapter, monkeypatch):
    config = {
        "services": {
            "api": {"environment": {"TOKEN": "synthetic"}},
            "web": {},
            "worker": {
                "mem_limit": "2147483648",
                "cpus": 2,
                "environment": {
                    "DATABASE_ADMIN_URL": "postgresql://procurement_owner:synthetic@db/procurement"
                },
            },
        }
    }
    monkeypatch.setattr(full_adapter, "full_docker", lambda *args: json.dumps(config).encode())
    before = full_adapter.full_configuration()
    images = {"api": "a", "web": "b", "worker": "c"}
    for name, image in images.items():
        config["services"][name]["image"] = image
    config["services"]["worker"].update(mem_limit=str(3 * 1024**3), cpus=3)
    plan = {
        "images": images,
        "worker_budget_after": full_adapter.FULL_WORKER_BUDGET,
        "effective_configuration": before,
    }
    full_adapter.full_check_install_configuration(plan, full_adapter.full_configuration())
    config["services"]["api"]["environment"]["TOKEN"] = "drift"
    with pytest.raises(RuntimeError, match="RUNTIME_CONTRACT_CHANGED"):
        full_adapter.full_check_install_configuration(plan, full_adapter.full_configuration())
    config["services"]["api"]["environment"]["TOKEN"] = "synthetic"
    config["services"]["worker"]["cpus"] = 4
    with pytest.raises(RuntimeError, match="RUNTIME_CONTRACT_CHANGED"):
        full_adapter.full_check_install_configuration(plan, full_adapter.full_configuration())


def test_full_source_migration_launch_refusal_preserves_diagnostics(full_adapter, monkeypatch):
    import subprocess

    (full_adapter.FULL_STAGE / "plan.json").write_bytes(b"{}")
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if "run" in args:
            raise subprocess.CalledProcessError(1, args, output=b"compose launch refusal")
        return b""

    monkeypatch.setattr(full_adapter, "full_docker", docker)
    with pytest.raises(subprocess.CalledProcessError):
        full_adapter.full_migrate(("compose",), "accepted")
    assert (
        full_adapter.FULL_STAGE / "migration-launch.log"
    ).read_bytes() == b"compose launch refusal"
    assert calls[-1][0] == "ps"


def test_full_source_budget_requires_memory_and_cpu_reserve(full_adapter, monkeypatch):
    from types import SimpleNamespace

    values = {"available": 6 * 1024**3, "cpus": 4}
    original = Path.read_text
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, *args, **kwargs: (
            f"MemAvailable: {values['available'] // 1024} kB\n"
            if path.as_posix() == "/proc/meminfo"
            else original(path, *args, **kwargs)
        ),
    )
    monkeypatch.setattr(full_adapter.os, "cpu_count", lambda: values["cpus"])
    monkeypatch.setattr(
        full_adapter.shutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 1024**3)
    )
    assert full_adapter.full_resources()["available_memory_bytes"] == values["available"]
    values["available"] = 4 * 1024**3
    with pytest.raises(RuntimeError, match="RESERVE_INSUFFICIENT"):
        full_adapter.full_resources()
    values.update(available=6 * 1024**3, cpus=3)
    with pytest.raises(RuntimeError, match="RESERVE_INSUFFICIENT"):
        full_adapter.full_resources()


def test_full_source_inverse_overlay_restores_worker_budget_before_host_rewrite(full_adapter):
    images = {"api": "a", "web": "b", "worker": "c"}
    inverse = full_adapter.full_overlay(images, full_adapter.FULL_WORKER_BUDGET_BEFORE)
    assert inverse.endswith(b"    mem_limit: 2g\n    cpus: 2.0\n")
    assert b"mem_limit: 3g" not in inverse
    with pytest.raises(RuntimeError, match="WORKER_BUDGET_INVALID"):
        full_adapter.full_overlay(images, {"mem_limit": "4g", "cpus": 4})
