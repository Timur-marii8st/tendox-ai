from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "scripts" / "release_gate_policy.json"


def test_branch_policy_refuses_other_source_before_executor(tmp_path: Path) -> None:
    bundle, digest = _archive(tmp_path)
    raw = json.loads(POLICY.read_text(encoding="utf-8"))
    raw["candidate_identity"] = {
        "archive_sha256": "0" * 64,
        "tree_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
    }
    policy = tmp_path / "branch-policy.json"
    policy.write_text(json.dumps(raw), encoding="utf-8")

    def forbidden_executor():
        pytest.fail("wrong branch source must be refused before any worker starts")

    with pytest.raises(GateError, match="exact branch policy binding"):
        ReleaseGateController(
            bundle=bundle, expected_sha256=digest, state_root=tmp_path / "state",
            policy_path=policy, executor_factory=forbidden_executor,
        ).run()
    assert not list((tmp_path / "state").rglob("release-receipt.json"))


def test_branch_policy_requires_all_three_source_identities(tmp_path: Path) -> None:
    raw = json.loads(POLICY.read_text(encoding="utf-8"))
    raw["candidate_identity"] = {"archive_sha256": "0" * 64}
    path = tmp_path / "bad-policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ReceiptError, match="exact three"):
        Policy.load(path)


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_RECEIPT = _load("release_gate_receipt", ROOT / "scripts" / "release_gate_receipt.py")
_RUNNER = _load("release_gate_runner", ROOT / "scripts" / "run_release_gate.py")
Policy = _RECEIPT.Policy
ReceiptError = _RECEIPT.ReceiptError
json_sha256 = _RECEIPT.json_sha256
verify_release_receipt = _RECEIPT.verify_release_receipt
ExecutionOutcome = _RUNNER.ExecutionOutcome
GateContext = _RUNNER.GateContext
GateError = _RUNNER.GateError
ReleaseGateController = _RUNNER.ReleaseGateController
parse_args = _RUNNER.parse_args


def _archive(
    tmp_path: Path,
    *,
    extra: bool = False,
    link: bool = False,
    traversal: bool = False,
    header_mismatch: bool = False,
) -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = b"sealed release candidate\n"
    files = [
        {
            "path": "README.md",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "mode": 0o644,
        }
    ]
    manifest = {
        "format_version": 1,
        "source_kind": "WORKTREE_SNAPSHOT",
        "git_head": "1" * 40,
        "git_dirty": True,
        "tree_sha256": json_sha256(files),
        "files": files,
        "deleted_paths": [],
        "excluded_count": 0,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    output = tmp_path / "candidate.tar.gz"
    with (
        output.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        archived_payload = payload + (b"unexpected expansion" if header_mismatch else b"")
        info = tarfile.TarInfo("README.md")
        info.size, info.mode, info.mtime = len(archived_payload), 0o644, 0
        archive.addfile(info, io.BytesIO(archived_payload))
        if extra:
            unlisted = b"print('unlisted')\n"
            info = tarfile.TarInfo("scripts/unlisted.py")
            info.size, info.mode, info.mtime = len(unlisted), 0o644, 0
            archive.addfile(info, io.BytesIO(unlisted))
        if link:
            info = tarfile.TarInfo("unsafe-link")
            info.type = tarfile.SYMTYPE
            info.linkname = "README.md"
            info.mode, info.mtime = 0o777, 0
            archive.addfile(info)
        if traversal:
            unsafe = b"escape\n"
            info = tarfile.TarInfo("../escape")
            info.size, info.mode, info.mtime = len(unsafe), 0o644, 0
            archive.addfile(info, io.BytesIO(unsafe))
        info = tarfile.TarInfo("release-manifest.json")
        info.size, info.mode, info.mtime = len(manifest_bytes), 0o644, 0
        archive.addfile(info, io.BytesIO(manifest_bytes))
    return output, hashlib.sha256(output.read_bytes()).hexdigest()


class FakeExecutor:
    mode = "pass"

    def __init__(self) -> None:
        self.context: GateContext | None = None

    def execute(self, context: GateContext) -> ExecutionOutcome:
        self.context = context
        if self.mode == "interrupt":
            raise KeyboardInterrupt
        stages: list[dict[str, Any]] = []
        for stage_id in context.policy.required_stage_ids:
            expected = context.policy.stage_expectations[stage_id]
            counts: dict[str, int] = {}
            for key in ("tests", "failures", "errors", "skipped"):
                if key in expected:
                    counts[key] = int(expected[key])
            if "min_tests" in expected:
                counts["tests"] = int(expected["min_tests"])
            if "tests" in counts:
                counts["collected"] = counts["tests"]
            skipped = list(expected.get("allowed_skip_ids", []))
            report = context.logs_dir / f"{stage_id}.log"
            report.write_text(f"{stage_id} PASS\n", encoding="utf-8")
            stage: dict[str, Any] = {
                "id": stage_id,
                "status": "PASS",
                "exit_code": 0,
                "started_at": "2026-10-07T00:00:00+00:00",
                "finished_at": "2026-10-07T00:00:01+00:00",
                "command": ["fake", stage_id],
                "counts": counts,
                "skipped_test_ids": skipped,
                "reports": [
                    {
                        "path": report.relative_to(context.run_dir).as_posix(),
                        "bytes": report.stat().st_size,
                        "sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
                    }
                ],
            }
            if "collection_sha256" in expected:
                stage["collection_sha256"] = expected["collection_sha256"]
            elif "tests" in expected or "min_tests" in expected:
                stage["collection_sha256"] = hashlib.sha256(stage_id.encode()).hexdigest()
            stages.append(stage)
        if self.mode == "missing-stage":
            stages.pop(-2)
        if self.mode == "unexpected-skip":
            unit = next(stage for stage in stages if stage["id"] == "python-unit")
            unit["counts"]["skipped"] += 1
            unit["skipped_test_ids"].append("tests.fake::unexpected")
        image_a = "sha256:" + "a" * 64
        image_b = "sha256:" + "b" * 64
        python_runtime = context.policy.raw["runtime_images"]["python"]
        node_runtime = context.policy.raw["runtime_images"]["node"]
        recipes = context.policy.raw["build_recipes"]
        artifacts = {
            "api": {
                "image_id": image_a,
                "source_tree_sha256": context.candidate.tree_sha256,
                "base_image": python_runtime["reference"],
                "base_image_id": python_runtime["image_id"],
                "dockerfile_sha256": recipes["api"]["sha256"],
            },
            "web": {
                "image_id": image_b,
                "source_tree_sha256": context.candidate.tree_sha256,
                "base_image": node_runtime["reference"],
                "base_image_id": node_runtime["image_id"],
                "dockerfile_sha256": recipes["web"]["sha256"],
            },
            "worker": {
                "image_id": image_a if self.mode != "worker-mismatch" else image_b,
                "source_tree_sha256": context.candidate.tree_sha256,
                "base_image": python_runtime["reference"],
                "base_image_id": python_runtime["image_id"],
                "dockerfile_sha256": recipes["api"]["sha256"],
            },
        }
        return ExecutionOutcome(
            tuple(stages),
            artifacts,
            context.policy.inventory_sha256,
            context.policy.explicit_not_performed,
        )

    def cleanup(self) -> dict[str, Any]:
        return {
            "complete": self.mode != "cleanup-failure",
            "resources": [
                {
                    "kind": "container",
                    "name": "fake",
                    "id": "f" * 64,
                    "role": "fake",
                    "identity_verified": True,
                    "removed": self.mode != "cleanup-failure",
                }
            ],
        }


def _run(tmp_path: Path, mode: str = "pass") -> tuple[Path, Path]:
    bundle, digest = _archive(tmp_path)
    state = tmp_path / "state"
    factory = type("ConfiguredFake", (FakeExecutor,), {"mode": mode})
    receipt = ReleaseGateController(
        bundle=bundle,
        expected_sha256=digest,
        state_root=state,
        policy_path=POLICY,
        executor_factory=factory,
    ).run()
    return receipt, state


def _source_identity(receipt: Path) -> dict[str, str]:
    source = json.loads(receipt.read_text(encoding="utf-8"))["source"]
    return {key: source[key] for key in ("archive_sha256", "tree_sha256", "manifest_sha256")}


def test_complete_candidate_emits_verifiable_identity_bound_receipt(tmp_path: Path) -> None:
    receipt, state = _run(tmp_path)
    parsed = verify_release_receipt(
        receipt,
        state_root=state,
        policy_path=POLICY,
        expected_source=_source_identity(receipt),
        expected_images={
            "api": "sha256:" + "a" * 64,
            "web": "sha256:" + "b" * 64,
            "worker": "sha256:" + "a" * 64,
        },
    )
    assert parsed.raw["status"] == "PASS"
    assert parsed.raw["complete"] is True


@pytest.mark.parametrize("mode", ["missing-stage", "unexpected-skip", "cleanup-failure"])
def test_incomplete_stage_skip_or_cleanup_never_emits_pass(tmp_path: Path, mode: str) -> None:
    with pytest.raises((GateError, ReceiptError)):
        _run(tmp_path, mode)
    run = next((tmp_path / "state" / "runs").iterdir())
    assert not (run / "release-receipt.json").exists()
    assert json.loads((run / "failure.json").read_text())["complete"] is False


def test_interruption_never_reuses_partial_run_as_success(tmp_path: Path) -> None:
    with pytest.raises(GateError, match="interrupted"):
        _run(tmp_path, "interrupt")
    first = next((tmp_path / "state" / "runs").iterdir())
    assert not (first / "release-receipt.json").exists()
    receipt, _ = _run(tmp_path / "retry")
    assert receipt.parent != first


def test_tampered_or_fabricated_receipt_is_rejected(tmp_path: Path) -> None:
    receipt, state = _run(tmp_path)
    run = receipt.parent
    bound_log = next((run / "logs").glob("*.log"))
    bound_log.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ReceiptError, match=r"hash mismatch|size mismatch"):
        verify_release_receipt(
            receipt,
            state_root=state,
            policy_path=POLICY,
            expected_source=_source_identity(receipt),
        )


def test_sealed_source_byte_change_invalidates_receipt(tmp_path: Path) -> None:
    receipt, state = _run(tmp_path)
    source_file = receipt.parent / "source" / "README.md"
    os.chmod(source_file, 0o600)
    source_file.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ReceiptError, match="sealed source file changed"):
        verify_release_receipt(
            receipt,
            state_root=state,
            policy_path=POLICY,
            expected_source=_source_identity(receipt),
        )
    fabricated = state / "fabricated.json"
    fabricated.write_text(receipt.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ReceiptError, match="canonical trusted run path"):
        verify_release_receipt(
            fabricated,
            state_root=state,
            policy_path=POLICY,
            expected_source=_source_identity(receipt),
        )


def test_old_policy_source_or_artifact_identity_is_rejected(tmp_path: Path) -> None:
    receipt, state = _run(tmp_path)
    with pytest.raises(ReceiptError, match="source identity mismatch"):
        verify_release_receipt(
            receipt,
            state_root=state,
            policy_path=POLICY,
            expected_source={**_source_identity(receipt), "tree_sha256": "0" * 64},
        )
    with pytest.raises(ReceiptError, match="artifact identity mismatch"):
        verify_release_receipt(
            receipt,
            state_root=state,
            policy_path=POLICY,
            expected_source=_source_identity(receipt),
            expected_images={
                "api": "sha256:" + "0" * 64,
                "web": "sha256:" + "b" * 64,
                "worker": "sha256:" + "a" * 64,
            },
        )
    old_policy = tmp_path / "old-policy.json"
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    policy["policy_version"] = "older-weaker-policy"
    old_policy.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ReceiptError, match="different or weaker policy"):
        verify_release_receipt(
            receipt,
            state_root=state,
            policy_path=old_policy,
            expected_source=_source_identity(receipt),
        )


@pytest.mark.parametrize("kind", ["extra", "link", "traversal"])
def test_unmanifested_or_link_archive_is_rejected_before_execution(
    tmp_path: Path, kind: str
) -> None:
    bundle, digest = _archive(
        tmp_path,
        extra=kind == "extra",
        link=kind == "link",
        traversal=kind == "traversal",
    )
    called = False

    def factory() -> FakeExecutor:
        nonlocal called
        called = True
        return FakeExecutor()

    with pytest.raises(GateError, match="archive"):
        ReleaseGateController(
            bundle=bundle,
            expected_sha256=digest,
            state_root=tmp_path / "state",
            policy_path=POLICY,
            executor_factory=factory,
        ).run()
    assert called is False


def test_archive_hash_and_unowned_state_root_are_rejected(tmp_path: Path) -> None:
    bundle, _ = _archive(tmp_path)
    with pytest.raises(GateError, match="SHA-256 mismatch"):
        ReleaseGateController(
            bundle=bundle,
            expected_sha256="0" * 64,
            state_root=tmp_path / "state",
            policy_path=POLICY,
            executor_factory=FakeExecutor,
        ).run()
    unowned = tmp_path / "not-a-directory"
    unowned.write_text("occupied", encoding="utf-8")
    with pytest.raises(GateError, match="real directory"):
        ReleaseGateController(
            bundle=bundle,
            expected_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
            state_root=unowned,
            policy_path=POLICY,
            executor_factory=FakeExecutor,
        ).run()


def test_archive_header_size_is_rejected_before_member_read(tmp_path: Path) -> None:
    bundle, digest = _archive(tmp_path, header_mismatch=True)
    with pytest.raises(GateError, match="header does not match manifest"):
        ReleaseGateController(
            bundle=bundle,
            expected_sha256=digest,
            state_root=tmp_path / "state",
            policy_path=POLICY,
            executor_factory=FakeExecutor,
        ).run()


def test_junit_nodes_must_match_declared_totals_and_collected_identities(
    tmp_path: Path,
) -> None:
    forged = tmp_path / "forged.xml"
    forged.write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0">'
        '<testcase classname="tests.test_demo" name="test_one" />'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    with pytest.raises(GateError, match="totals differ"):
        _RUNNER._junit_counts(forged)
    duplicate = tmp_path / "duplicate.xml"
    duplicate.write_text(
        '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0">'
        '<testcase classname="tests.test_demo" name="test_one[A]" />'
        '<testcase classname="tests.test_demo" name="test_one[A]" />'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    with pytest.raises(GateError, match="duplicate testcase identities"):
        _RUNNER._junit_counts(duplicate)

    valid = tmp_path / "valid.xml"
    valid.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="tests.test_demo" name="test_one" />'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    counts, skipped, executed = _RUNNER._junit_counts(valid)
    assert counts == {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}
    assert skipped == ()
    assert executed == ("tests.test_demo::test_one",)
    assert _RUNNER._collection_ids("tests/test_demo.py::test_two\n") != executed
    assert _RUNNER._collection_ids(
        "tests/test_demo.py::TestGroup::test_param[value::with-colons]\n"
    ) == ("tests.test_demo.TestGroup::test_param[value::with-colons]",)
    assert _RUNNER._collection_ids(
        "src/procurement/domain/economics.py::procurement.domain.economics.money\n"
    ) == ("src.procurement.domain.economics::procurement.domain.economics.money",)
    snapshot = _RUNNER._snapshot_candidate_report(valid, tmp_path / "trusted.xml")
    valid.write_text("candidate changed its raw output", encoding="utf-8")
    assert _RUNNER._junit_counts(snapshot)[0]["tests"] == 1
    symlink = tmp_path / "candidate-link.xml"
    try:
        symlink.symlink_to(snapshot)
    except OSError:
        pass
    else:
        with pytest.raises(GateError, match="missing or unsafe"):
            _RUNNER._snapshot_candidate_report(symlink, tmp_path / "linked-copy.xml")
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "candidate-report.fifo"
        os.mkfifo(fifo)
        with pytest.raises(GateError, match="not a regular file"):
            _RUNNER._snapshot_candidate_report(fifo, tmp_path / "fifo-copy.xml")


def test_interrupted_network_creation_is_discovered_and_guardedly_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = Policy.load(POLICY)
    run_dir = tmp_path / "run"
    for name in ("source", "reports", "candidate-output", "logs", "control"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    context = GateContext(
        run_id="release-20261007-000000-abcdef123456",
        run_dir=run_dir,
        source_dir=run_dir / "source",
        reports_dir=run_dir / "reports",
        raw_reports_dir=run_dir / "candidate-output",
        logs_dir=run_dir / "logs",
        control_dir=run_dir / "control",
        policy=policy,
        candidate=_RUNNER.CandidateIdentity(
            "WORKTREE_SNAPSHOT", "0" * 64, "1" * 64, "2" * 64, "3" * 40, False, (), 1
        ),
    )
    executor = _RUNNER.DockerGateExecutor()
    executor.context = context
    network_name = executor._resource_name("acqnet")
    network_id = "a" * 64
    inspect_payload = json.dumps(
        [
            {
                "Id": network_id,
                "Labels": {
                    _RUNNER.SESSION_LABEL: context.run_id,
                    _RUNNER.ROLE_LABEL: "dependency-acquisition-network",
                },
            }
        ]
    ).encode()
    removed: list[str] = []

    def fake_run(
        command: list[str] | tuple[str, ...], **_: Any
    ) -> subprocess.CompletedProcess[bytes]:
        words = list(command)
        if words[-3:-1] == ["network", "rm"]:
            removed.append(words[-1])
            return subprocess.CompletedProcess(words, 0, b"", None)
        if "inspect" in words:
            return subprocess.CompletedProcess(words, 0, inspect_payload, None)
        return subprocess.CompletedProcess(words, 1, b"interrupted", None)

    def interrupted_capture(*_: str, **__: Any) -> str:
        raise GateError("simulated create interruption")

    monkeypatch.setattr(executor, "_run", fake_run)
    monkeypatch.setattr(executor, "_docker_capture", interrupted_capture)
    with pytest.raises(GateError, match="simulated"):
        executor._create_network("acqnet", "dependency-acquisition-network", internal=False)
    assert executor.resources[0]["name"] == network_name
    assert executor.cleanup()["complete"] is True
    assert removed == [network_id]


def test_node_dependency_acquisition_is_detached_before_candidate_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (ROOT / "scripts" / "run_release_gate.py").read_text(encoding="utf-8")
    assert "PYTHONPATH=/workspace/src:/workspace" in source
    assert "npm ci --ignore-scripts" in source
    assert '"network", "disconnect"' in source
    assert '"npm", "rebuild", "--offline"' in source
    assert "cp /source/scripts/run-web-tests.mjs" in source
    assert "npm_config_cache=/test/npm-cache" in source
    sandbox_executor = _RUNNER.DockerGateExecutor()
    sandbox_executor.worker_uid = 1001
    sandbox_executor.worker_gid = 1002
    sandbox = sandbox_executor._worker_sandbox_options(test_size="1g")
    assert sandbox[:2] == ["--user", "1001:1002"]
    assert "/test:rw,exec,nosuid,nodev,size=1g,uid=1001,gid=1002,mode=0700" in sandbox
    assert "/tmp:rw,nosuid,nodev,size=512m,uid=1001,gid=1002,mode=0700" in sandbox
    inspect_payload = {
        "Config": {"User": "1001:1002"},
        "HostConfig": {
            "Tmpfs": {
                "/test": "rw,exec,nosuid,nodev,size=1g,uid=1001,gid=1002,mode=0700",
                "/tmp": "rw,nosuid,nodev,size=512m,uid=1001,gid=1002,mode=0700",
            }
        },
    }
    assert sandbox_executor._assert_worker_container(inspect_payload)["user"] == "1001:1002"
    inspect_payload["Config"]["User"] = "0:0"
    with pytest.raises(GateError, match="user/tmpfs identity"):
        sandbox_executor._assert_worker_container(inspect_payload)
    for kind in ("api", "web"):
        _RUNNER.DockerGateExecutor._assert_dockerfile_network_policy(
            kind, (ROOT / f"Dockerfile.{kind}").read_text(encoding="utf-8")
        )
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for directory in ("reports", "candidate-output", "logs", "control"):
        (tmp_path / directory).mkdir()
    for kind in ("api", "web"):
        text = (ROOT / f"Dockerfile.{kind}").read_text(encoding="utf-8")
        if kind == "api":
            text = text.replace(
                "COPY src ./src", "COPY scripts /tmp/candidate\nRUN true\nCOPY src ./src"
            )
        (source_dir / f"Dockerfile.{kind}").write_text(text, encoding="utf-8")
    context = GateContext(
        run_id="release-20261007-000000-fedcba654321",
        run_dir=tmp_path,
        source_dir=source_dir,
        reports_dir=tmp_path / "reports",
        raw_reports_dir=tmp_path / "candidate-output",
        logs_dir=tmp_path / "logs",
        control_dir=tmp_path / "control",
        policy=Policy.load(POLICY),
        candidate=_RUNNER.CandidateIdentity(
            "WORKTREE_SNAPSHOT", "0" * 64, "1" * 64, "2" * 64, "3" * 40, False, (), 1
        ),
    )
    executor = _RUNNER.DockerGateExecutor()
    executor.context = context
    docker_called = False

    def unexpected_stage(*_: Any, **__: Any) -> None:
        nonlocal docker_called
        docker_called = True

    monkeypatch.setattr(executor, "_stage", unexpected_stage)
    with pytest.raises(GateError, match="trusted recipe allowlist"):
        executor._build_artifact("api")
    assert docker_called is False

    tool_policy_raw = json.loads(POLICY.read_text(encoding="utf-8"))
    docker_config = tmp_path / "docker-config"
    plugin = docker_config / "cli-plugins" / "docker-buildx"
    plugin.parent.mkdir(parents=True)
    plugin.write_bytes(b"reviewed-buildx-test-double")
    os.chmod(plugin, 0o700)
    (docker_config / "config.json").write_bytes(b"{}\n")
    buildx = tool_policy_raw["docker_client"]["buildx"]
    buildx["bytes"] = plugin.stat().st_size
    buildx["sha256"] = hashlib.sha256(plugin.read_bytes()).hexdigest()
    tool_policy_path = tmp_path / "tool-policy.json"
    tool_policy_path.write_text(json.dumps(tool_policy_raw), encoding="utf-8")
    tool_context = _RUNNER.GateContext(
        **{**context.__dict__, "policy": Policy.load(tool_policy_path)}
    )
    tool_executor = _RUNNER.DockerGateExecutor()
    tool_executor.context = tool_context

    def buildx_capture(*arguments: str, **_: Any) -> str:
        if arguments == ("buildx", "version"):
            return str(buildx["version"])
        if arguments == ("info", "--format", "{{.OSType}}/{{.Architecture}}"):
            return "linux/x86_64"
        if arguments == ("buildx", "inspect", "default"):
            return "Name: default\nDriver: docker\nBuildKit version: v0.26.2\n"
        raise AssertionError(arguments)

    monkeypatch.setattr(tool_executor, "_docker_capture", buildx_capture)
    tool_executor._configure_docker_client()
    assert "/usr/bin/docker" in tool_executor.docker
    assert "unix:///var/run/docker.sock" in tool_executor.docker
    env_index = tool_executor.docker.index("/usr/bin/env")
    docker_index = tool_executor.docker.index("/usr/bin/docker")
    assert env_index < docker_index
    assert tool_executor.docker[env_index + 1] == (
        f"BUILDX_CONFIG={tmp_path / 'control' / 'buildx-state'}"
    )
    tool_executor._verify_docker_tool_immutability()
    (docker_config / "unexpected-state").write_text("forbidden", encoding="utf-8")
    with pytest.raises(GateError, match="inventory changed"):
        tool_executor._verify_docker_tool_immutability()
    (docker_config / "unexpected-state").unlink()
    (tmp_path / "control" / "buildx-state").rmdir()
    plugin.write_bytes(b"tampered-buildx")
    rejected = _RUNNER.DockerGateExecutor()
    rejected.context = tool_context
    with pytest.raises(GateError, match=r"size|SHA-256"):
        rejected._configure_docker_client()


def test_worker_image_must_equal_accepted_api_image(tmp_path: Path) -> None:
    with pytest.raises(ReceiptError, match="worker artifact"):
        _run(tmp_path, "worker-mismatch")
    run = next((tmp_path / "state" / "runs").iterdir())
    assert not (run / "release-receipt.json").exists()


@pytest.mark.parametrize("forbidden", ["--skip", "--database-url", "--accept-existing-pass"])
def test_cli_has_no_scope_weakening_or_external_database_option(forbidden: str) -> None:
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--source-bundle",
                "candidate.tar.gz",
                "--expected-sha256",
                "0" * 64,
                "--state-root",
                "state",
                forbidden,
                "value",
            ]
        )


def test_verifier_refuses_other_exact_branch_even_with_updated_policy_reference(
    tmp_path: Path,
) -> None:
    receipt, state = _run(tmp_path)
    raw = json.loads(POLICY.read_text(encoding="utf-8"))
    raw["candidate_identity"] = {**_source_identity(receipt), "archive_sha256": "0" * 64}
    policy_path = tmp_path / "other-branch.json"
    policy_path.write_text(json.dumps(raw), encoding="utf-8")
    policy = Policy.load(policy_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["policy"] = {"version": policy.version, "sha256": policy.sha256}
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReceiptError, match="exact branch policy binding"):
        verify_release_receipt(
            receipt, state_root=state, policy_path=policy_path,
            expected_source=_source_identity(receipt),
        )


@pytest.mark.parametrize("stop_fails", [False, True])
def test_sequential_workers_release_ram_before_node_or_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_fails: bool,
) -> None:
    executor = _RUNNER.DockerGateExecutor()
    events: list[str] = []
    monkeypatch.setattr(_RUNNER.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(_RUNNER.os, "getgid", lambda: 1000, raising=False)
    for method in (
        "_assert_worker_path_ownership", "_configure_docker_client", "_prepare_runtime",
        "_build_python_runtime", "_start_postgres", "_start_python_runner",
        "_python_quality",
    ):
        monkeypatch.setattr(executor, method, lambda: None)
    monkeypatch.setattr(executor, "_postgres_quality", lambda: events.append("postgres"))
    executor.python_runner_id = "python-id"
    executor.pg_id = "pg-id"

    def stop(*args: str, **kwargs: Any) -> str:
        assert args[:3] == ("stop", "--time", "10")
        events.append(args[3])
        if stop_fails:
            raise GateError("stop refused")
        return ""

    def start_node() -> None:
        events.append("node")
        raise GateError("test boundary reached")

    monkeypatch.setattr(executor, "_docker_capture", stop)
    monkeypatch.setattr(executor, "_start_node_runner", start_node)
    context = SimpleNamespace(policy=SimpleNamespace(raw={"postgres_before_web": True}))
    with pytest.raises(GateError, match="stop refused" if stop_fails else "test boundary"):
        executor.execute(context)
    assert events == (
        ["postgres", "python-id"] if stop_fails
        else ["postgres", "python-id", "pg-id", "node"]
    )


def test_dependency_transport_timeout_preserves_lock_and_overall_build_cap(tmp_path, monkeypatch):
    executor = _RUNNER.DockerGateExecutor()
    executor.context = SimpleNamespace(
        run_id="release-test",
        control_dir=tmp_path,
        source_dir=tmp_path,
        policy=SimpleNamespace(
            raw={"tool_versions": {"uv": "0.9.12"}, "limits": {"build_timeout_seconds": 1800}}
        ),
    )
    monkeypatch.setattr(executor, "_image_policy", lambda kind: {"reference": "python:pinned"})
    monkeypatch.setattr(executor, "_resource_name", lambda role: "test-python-runtime")
    monkeypatch.setattr(executor, "_discover_resource", lambda *args: None)

    def boundary(stage, command, *, timeout):
        assert stage == "python-runtime-build" and timeout == 1800
        raise GateError("test boundary: no Docker invoked")

    monkeypatch.setattr(executor, "_stage", boundary)
    with pytest.raises(GateError, match="test boundary"):
        executor._build_python_runtime()
    recipe = (tmp_path / "Dockerfile.python-runtime").read_text()
    assert "pip install --timeout 300 --no-cache-dir uv==0.9.12" in recipe
    assert "UV_HTTP_TIMEOUT=300" in recipe
    assert "COPY pyproject.toml uv.lock" in recipe
    assert "uv sync --frozen --extra dev --no-install-project" in recipe
    assert "UV_NO_SYNC=1" in recipe
