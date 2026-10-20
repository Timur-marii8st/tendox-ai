"""A provider install must bind the approved bytes and recover partial changes."""

from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def activation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path, str]:
    spec = spec_from_file_location(
        "activation_under_test", ROOT / "scripts/activate_quality_provider.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HOST", tmp_path / "host")
    monkeypatch.setattr(module, "PROVIDER", tmp_path / "provider")
    (module.HOST / "scripts").mkdir(parents=True)
    package = tmp_path / "package"
    (package / "controller").mkdir(parents=True)
    (package / "guards").mkdir()
    tools = {}
    for name in module.TOOL_FILES:
        raw = b"synthetic pinned buildx" if name.endswith("docker-buildx") else b"{}\n"
        path = package / "tools" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        tools[name] = {"sha256": module.digest(raw), "bytes": len(raw)}
    monkeypatch.setattr(module, "TOOL_IDENTITY", tools)
    controller = {}
    for name in module.CONTROLLER_FILES:
        raw = ("synthetic controller: " + name).encode()
        (package / "controller" / name).write_bytes(raw)
        controller[name] = module.digest(raw)
    guards = {}
    for name in module.GUARD_FILES:
        before = ("synthetic previous: " + name).encode()
        after = ("synthetic refusal: " + name).encode()
        (module.HOST / "scripts" / name).write_bytes(before)
        (package / "guards" / name).write_bytes(after)
        guards[name] = {
            "before_sha256": module.digest(before), "after_sha256": module.digest(after)
        }
    plan = {
        "schema": module.SCHEMA, "provider_root": str(module.PROVIDER),
        "host_root": str(module.HOST), "runtime_changes": [],
        "controller": controller, "guards": guards,
        "tools": tools,
        "tool_provenance": module.TOOL_PROVENANCE,
        "bundle_id": module.digest(module.canonical({
            "controller": controller, "tools": tools, "tool_provenance": module.TOOL_PROVENANCE
        })),
        "previous_current_sha256": None,
    }
    raw = module.canonical(plan)
    (package / "plan.json").write_bytes(raw)
    return module, package, module.digest(raw)


def test_preflight_does_not_create_provider_or_touch_operational_files(activation: Any) -> None:
    module, package, plan_sha = activation
    before = {path: path.read_bytes() for path in (module.HOST / "scripts").iterdir()}
    module.preflight(package, plan_sha)
    assert not module.PROVIDER.exists()
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("mutation", ["controller", "installed_guard", "plan_sha", "runtime"])
def test_changed_or_out_of_scope_activation_refuses_before_writes(
    activation: Any, mutation: str
) -> None:
    module, package, plan_sha = activation
    if mutation == "controller":
        (package / "controller/run_release_gate.py").write_bytes(b"tampered controller")
    elif mutation == "installed_guard":
        name = next(iter(module.GUARD_FILES))
        (module.HOST / "scripts" / name).write_bytes(b"concurrent operational change")
    elif mutation == "plan_sha":
        plan_sha = "0" * 64
    else:
        plan = json.loads((package / "plan.json").read_bytes())
        plan["runtime_changes"] = ["recreate API"]
        raw = module.canonical(plan)
        (package / "plan.json").write_bytes(raw)
        plan_sha = module.digest(raw)
    with pytest.raises(module.ActivationError):
        module.activate(package, plan_sha)
    assert not module.PROVIDER.exists()


def test_installed_provider_does_not_claim_quality_acceptance(activation: Any) -> None:
    module, package, plan_sha = activation
    report = module.activate(package, plan_sha)
    assert report["status"] == "INSTALLED; WORKFLOW_ACCEPTANCE_PENDING"
    assert report["runtime_changes"] == []
    assert not (module.PROVIDER / "activation.lock").exists()
    pointer = json.loads((module.PROVIDER / "current.json").read_bytes())
    assert pointer["activation_plan_sha256"] == plan_sha
    for name in module.CONTROLLER_FILES:
        assert (module.PROVIDER / "releases" / pointer["bundle_id"] / name).read_bytes() == (
            package / "controller" / name
        ).read_bytes()
    for name in module.GUARD_FILES:
        installed = (module.HOST / "scripts" / name).read_bytes()
        assert installed == (package / "guards" / name).read_bytes()
    for name in module.TOOL_FILES:
        installed = module.PROVIDER / "releases" / pointer["bundle_id"] / name
        assert installed.read_bytes() == (package / "tools" / name).read_bytes()


@pytest.mark.parametrize("mutation", ["missing", "hash", "out-of-scope"])
def test_bad_build_tool_refuses_before_any_writes(activation: Any, mutation: str) -> None:
    module, package, plan_sha = activation
    plugin = package / "tools/docker-config/cli-plugins/docker-buildx"
    if mutation == "missing":
        plugin.unlink()
    elif mutation == "hash":
        plugin.write_bytes(b"wrong tool bytes")
    else:
        plan = json.loads((package / "plan.json").read_bytes())
        plan["tools"]["../foreign-plugin"] = {"bytes": 1, "sha256": "0" * 64}
        raw = module.canonical(plan)
        (package / "plan.json").write_bytes(raw)
        plan_sha = module.digest(raw)
    with pytest.raises(module.ActivationError):
        module.activate(package, plan_sha)
    assert not module.PROVIDER.exists()


def test_interrupted_tool_staging_cannot_publish_pointer(
    activation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, package, plan_sha = activation
    atomic = module.atomic_write

    def interrupted(path: Path, raw: bytes, mode: int) -> None:
        atomic(path, raw, mode)
        if path.name == "docker-buildx":
            raise OSError("synthetic tool interruption")

    monkeypatch.setattr(module, "atomic_write", interrupted)
    with pytest.raises(OSError, match="tool interruption"):
        module.activate(package, plan_sha)
    assert not (module.PROVIDER / "current.json").exists()
    plan = json.loads((package / "plan.json").read_bytes())
    assert not (module.PROVIDER / "releases" / plan["bundle_id"]).exists()


def test_tool_symlink_refuses_before_writes(
    activation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, package, plan_sha = activation
    plugin = package / "tools/docker-config/cli-plugins/docker-buildx"
    is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == plugin or is_symlink(path))
    with pytest.raises(module.ActivationError, match="SYMLINK"):
        module.activate(package, plan_sha)
    assert not module.PROVIDER.exists()


def test_failure_after_guard_replacement_restores_originals(
    activation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, package, plan_sha = activation
    originals = {path: path.read_bytes() for path in (module.HOST / "scripts").iterdir()}
    atomic = module.atomic_write
    writes = 0

    def fail_after_second_guard(path: Path, raw: bytes, mode: int) -> None:
        nonlocal writes
        atomic(path, raw, mode)
        if path.parent == module.HOST / "scripts" and b"synthetic refusal" in raw:
            writes += 1
            if writes == 2:
                raise OSError("synthetic failure after replacing second guard")

    monkeypatch.setattr(module, "atomic_write", fail_after_second_guard)
    with pytest.raises(OSError, match="synthetic failure"):
        module.activate(package, plan_sha)
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    assert not (module.PROVIDER / "current.json").exists()
    assert not (module.PROVIDER / "activation.lock").exists()
    records = list((module.PROVIDER / "activations").glob("*/failure.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_bytes())["status"] == "FAIL"


def test_occupied_activation_lock_is_preserved(activation: Any) -> None:
    module, package, plan_sha = activation
    module.PROVIDER.mkdir(mode=0o700)
    lock = module.PROVIDER / "activation.lock"
    lock.write_bytes(b"another owner")
    with pytest.raises(module.ActivationError, match="LOCK_OCCUPIED"):
        module.activate(package, plan_sha)
    assert lock.read_bytes() == b"another owner"
    assert not (module.PROVIDER / "current.json").exists()


def test_interrupted_controller_staging_can_retry_without_replacing_partial_bundle(
    activation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, package, plan_sha = activation
    plan = json.loads((package / "plan.json").read_bytes())
    atomic = module.atomic_write
    failed_once = False

    def fail_once_after_staged_controller(path: Path, raw: bytes, mode: int) -> None:
        nonlocal failed_once
        atomic(path, raw, mode)
        if not failed_once and path.name in module.CONTROLLER_FILES:
            failed_once = True
            raise OSError("synthetic interrupted controller staging")

    monkeypatch.setattr(module, "atomic_write", fail_once_after_staged_controller)
    with pytest.raises(OSError, match="interrupted controller"):
        module.activate(package, plan_sha)
    assert not (module.PROVIDER / "releases" / plan["bundle_id"]).exists()
    assert not (module.PROVIDER / "current.json").exists()
    assert len(list((module.PROVIDER / "releases").glob(".staging-*"))) == 1
    assert module.activate(package, plan_sha)["status"] == "INSTALLED; WORKFLOW_ACCEPTANCE_PENDING"


def test_missing_guard_during_recovery_does_not_prevent_other_restore_or_record(
    activation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, package, plan_sha = activation
    paths = sorted((module.HOST / "scripts").iterdir())
    originals = {path: path.read_bytes() for path in paths}
    atomic = module.atomic_write

    def remove_one_guard_before_pointer(path: Path, raw: bytes, mode: int) -> None:
        if path == module.PROVIDER / "current.json":
            paths[0].unlink()
            raise OSError("synthetic concurrent guard removal")
        atomic(path, raw, mode)

    monkeypatch.setattr(module, "atomic_write", remove_one_guard_before_pointer)
    with pytest.raises(module.ActivationError, match="RECOVERY_INCOMPLETE") as caught:
        module.activate(package, plan_sha)
    assert isinstance(caught.value.__cause__, OSError)
    assert not paths[0].exists()
    assert paths[1].read_bytes() == originals[paths[1]]
    records = list((module.PROVIDER / "activations").glob("*/failure.json"))
    assert len(records) == 1
    report = json.loads(records[0].read_bytes())
    assert report["error_type"] == "OSError"
    assert report["recovery_refusals"]


def test_missing_lock_during_failure_does_not_mask_original_error(
    activation: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, package, plan_sha = activation
    atomic = module.atomic_write

    def remove_lock_before_result(path: Path, raw: bytes, mode: int) -> None:
        if path.name == "result.json":
            (module.PROVIDER / "activation.lock").unlink()
            raise OSError("synthetic original activation failure")
        atomic(path, raw, mode)

    monkeypatch.setattr(module, "atomic_write", remove_lock_before_result)
    with pytest.raises(OSError, match="original activation failure"):
        module.activate(package, plan_sha)
    assert not (module.PROVIDER / "current.json").exists()
    assert len(list((module.PROVIDER / "activations").glob("*/failure.json"))) == 1
    assert len(list((module.PROVIDER / "activations").glob("*/cleanup-failure.json"))) == 1
