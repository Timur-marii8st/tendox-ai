"""Typed release-gate receipts and fail-closed verification.

The verifier trusts a reviewed policy and a controller-owned state root.  A JSON
document supplied by a candidate is never a release receipt merely because it
contains ``"status": "PASS"``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

RECEIPT_SCHEMA = "release-gate-receipt-v1"
POLICY_SCHEMA = "release-gate-policy-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{15,95}$")


class ReceiptError(RuntimeError):
    """A receipt or its trusted evidence failed validation."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ReceiptError(f"{label} must be an object")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReceiptError(f"{label} must be a non-empty string")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReceiptError(f"{label} must be a non-negative integer")
    return value


def _safe_relative(value: object, label: str) -> PurePosixPath:
    text = _string(value, label)
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or text != path.as_posix()
        or ".." in path.parts
        or "." in path.parts
        or "\\" in text
        or ":" in path.parts[0]
    ):
        raise ReceiptError(f"{label} is not a safe relative path")
    return path


def _assert_no_symlink(path: Path, boundary: Path) -> None:
    current = path
    boundary = boundary.absolute()
    while True:
        if current.is_symlink():
            raise ReceiptError(f"symlink is forbidden in trusted receipt path: {current}")
        if current.absolute() == boundary:
            return
        if current.parent == current:
            raise ReceiptError("receipt path escapes the trusted state root")
        current = current.parent


@dataclass(frozen=True)
class Policy:
    path: Path
    raw: Mapping[str, Any]
    version: str
    sha256: str
    required_stage_ids: tuple[str, ...]
    stage_expectations: Mapping[str, Mapping[str, Any]]
    inventory_sha256: str
    supported_candidate_kinds: tuple[str, ...]
    explicit_not_performed: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> Policy:
        path = path.resolve(strict=True)
        try:
            raw_object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ReceiptError(f"policy is unreadable: {error}") from error
        raw = _mapping(raw_object, "policy")
        if raw.get("schema_version") != POLICY_SCHEMA:
            raise ReceiptError("unsupported release-gate policy schema")
        version = _string(raw.get("policy_version"), "policy_version")
        kinds_value = raw.get("supported_candidate_kinds")
        if not isinstance(kinds_value, list) or not kinds_value:
            raise ReceiptError("supported_candidate_kinds must be a non-empty list")
        kinds = tuple(_string(item, "candidate kind") for item in kinds_value)
        if len(set(kinds)) != len(kinds):
            raise ReceiptError("candidate kinds must be unique")
        stages_value = raw.get("required_stages")
        if not isinstance(stages_value, list) or not stages_value:
            raise ReceiptError("required_stages must be a non-empty list")
        stage_ids: list[str] = []
        expectations: dict[str, Mapping[str, Any]] = {}
        for index, item in enumerate(stages_value):
            stage = _mapping(item, f"required_stages[{index}]")
            stage_id = _string(stage.get("id"), f"required_stages[{index}].id")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,95}", stage_id):
                raise ReceiptError(f"invalid required stage id: {stage_id!r}")
            stage_ids.append(stage_id)
            expectation = stage.get("expect", {})
            expectations[stage_id] = _mapping(expectation, f"{stage_id}.expect")
        if len(set(stage_ids)) != len(stage_ids):
            raise ReceiptError("required stage ids must be unique")
        scope = _mapping(raw.get("scope"), "scope")
        inventory = _mapping(scope.get("expanded_inventory"), "expanded_inventory")
        declared_inventory_hash = _string(
            scope.get("expanded_inventory_sha256"), "expanded_inventory_sha256"
        )
        if not SHA256_RE.fullmatch(declared_inventory_hash):
            raise ReceiptError("expanded inventory SHA-256 is malformed")
        if json_sha256(inventory) != declared_inventory_hash:
            raise ReceiptError("expanded inventory hash does not match policy content")
        omissions = raw.get("explicit_not_performed")
        if not isinstance(omissions, list):
            raise ReceiptError("explicit_not_performed must be a list")
        explicit = tuple(_string(item, "explicit omission") for item in omissions)
        if len(set(explicit)) != len(explicit):
            raise ReceiptError("explicit omissions must be unique")
        return cls(
            path=path,
            raw=raw,
            version=version,
            sha256=json_sha256(raw),
            required_stage_ids=tuple(stage_ids),
            stage_expectations=expectations,
            inventory_sha256=declared_inventory_hash,
            supported_candidate_kinds=kinds,
            explicit_not_performed=explicit,
        )


@dataclass(frozen=True)
class StageReceipt:
    stage_id: str
    status: str
    exit_code: int
    counts: Mapping[str, int]
    skipped_test_ids: tuple[str, ...]
    reports: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ArtifactReceipt:
    kind: str
    image_id: str
    source_tree_sha256: str
    base_image: str


@dataclass(frozen=True)
class ReleaseReceipt:
    path: Path
    run_id: str
    source: Mapping[str, Any]
    stages: tuple[StageReceipt, ...]
    artifacts: Mapping[str, ArtifactReceipt]
    raw: Mapping[str, Any]


def _validate_stage(
    raw: Mapping[str, Any], policy: Policy, run_dir: Path, state_root: Path
) -> StageReceipt:
    stage_id = _string(raw.get("id"), "stage.id")
    if stage_id not in policy.stage_expectations:
        raise ReceiptError(f"unexpected stage: {stage_id}")
    status = _string(raw.get("status"), f"{stage_id}.status")
    exit_code = _integer(raw.get("exit_code"), f"{stage_id}.exit_code")
    if status != "PASS" or exit_code != 0:
        raise ReceiptError(f"stage is not a successful terminal result: {stage_id}")
    counts_raw = _mapping(raw.get("counts", {}), f"{stage_id}.counts")
    counts = {
        str(key): _integer(value, f"{stage_id}.counts.{key}") for key, value in counts_raw.items()
    }
    skipped_raw = raw.get("skipped_test_ids", [])
    if not isinstance(skipped_raw, list):
        raise ReceiptError(f"{stage_id}.skipped_test_ids must be a list")
    skipped = tuple(_string(item, f"{stage_id}.skip") for item in skipped_raw)
    if len(set(skipped)) != len(skipped):
        raise ReceiptError(f"{stage_id} has duplicate skipped test ids")

    expected = policy.stage_expectations[stage_id]
    for key in ("tests", "failures", "errors", "skipped"):
        if key in expected and counts.get(key) != _integer(
            expected[key], f"{stage_id}.expect.{key}"
        ):
            raise ReceiptError(f"{stage_id} has unexpected {key} count")
    if "min_tests" in expected and counts.get("tests", -1) < _integer(
        expected["min_tests"], f"{stage_id}.expect.min_tests"
    ):
        raise ReceiptError(f"{stage_id} collected fewer tests than policy permits")
    actual_collection = raw.get("collection_sha256")
    if ("tests" in expected or "min_tests" in expected) and (
        not isinstance(actual_collection, str)
        or not SHA256_RE.fullmatch(actual_collection)
        or counts.get("collected") != counts.get("tests")
    ):
        raise ReceiptError(f"{stage_id} has no exact expanded collection identity")
    expected_collection = expected.get("collection_sha256")
    if expected_collection is not None and (
        not isinstance(expected_collection, str)
        or not SHA256_RE.fullmatch(expected_collection)
        or actual_collection != expected_collection
    ):
        raise ReceiptError(f"{stage_id} collection identity differs from policy")
    allowed_skips_raw = expected.get("allowed_skip_ids", [])
    if not isinstance(allowed_skips_raw, list):
        raise ReceiptError(f"{stage_id}.allowed_skip_ids must be a list")
    allowed_skips = tuple(sorted(_string(item, "allowed skip id") for item in allowed_skips_raw))
    if tuple(sorted(skipped)) != allowed_skips:
        raise ReceiptError(f"{stage_id} has an unexpected skip inventory")

    reports_raw = raw.get("reports")
    if not isinstance(reports_raw, list) or not reports_raw:
        raise ReceiptError(f"{stage_id} must bind at least one report")
    reports: list[Mapping[str, Any]] = []
    for index, report_value in enumerate(reports_raw):
        report = _mapping(report_value, f"{stage_id}.reports[{index}]")
        relative = _safe_relative(report.get("path"), "report.path")
        if relative.parts[0] not in {"logs", "reports"}:
            raise ReceiptError("stage reports must live under logs/ or reports/")
        expected_sha = _string(report.get("sha256"), "report.sha256")
        if not SHA256_RE.fullmatch(expected_sha):
            raise ReceiptError("report SHA-256 is malformed")
        expected_bytes = _integer(report.get("bytes"), "report.bytes")
        report_path = run_dir.joinpath(*relative.parts)
        _assert_no_symlink(report_path, state_root)
        try:
            stat = report_path.stat()
        except OSError as error:
            raise ReceiptError(f"bound report is unavailable: {relative}") from error
        if not report_path.is_file() or stat.st_size != expected_bytes:
            raise ReceiptError(f"bound report size mismatch: {relative}")
        if file_sha256(report_path) != expected_sha:
            raise ReceiptError(f"bound report hash mismatch: {relative}")
        reports.append(report)
    return StageReceipt(stage_id, status, exit_code, counts, skipped, tuple(reports))


def _verify_sealed_source(run_dir: Path, source: Mapping[str, Any], state_root: Path) -> None:
    archive = run_dir / "control" / "candidate.tar.gz"
    manifest_path = run_dir / "source" / "release-manifest.json"
    for path in (archive, manifest_path):
        _assert_no_symlink(path, state_root)
        if not path.is_file():
            raise ReceiptError(f"sealed candidate input is missing: {path.name}")
    if file_sha256(archive) != source.get("archive_sha256"):
        raise ReceiptError("sealed candidate archive changed after acceptance")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != source.get("manifest_sha256"):
        raise ReceiptError("sealed release manifest changed after acceptance")
    try:
        manifest_value = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise ReceiptError(f"sealed release manifest is invalid: {error}") from error
    manifest = _mapping(manifest_value, "sealed manifest")
    files = manifest.get("files")
    if not isinstance(files, list) or json_sha256(files) != source.get("tree_sha256"):
        raise ReceiptError("sealed source tree identity differs from receipt")
    expected: dict[str, Mapping[str, Any]] = {}
    for value in files:
        entry = _mapping(value, "sealed manifest file")
        relative = _safe_relative(entry.get("path"), "sealed manifest file path")
        name = relative.as_posix()
        if name in expected:
            raise ReceiptError("sealed manifest contains duplicate files")
        expected[name] = entry
    source_dir = run_dir / "source"
    actual: dict[str, Path] = {}
    for path in source_dir.rglob("*"):
        if path.is_symlink():
            raise ReceiptError("sealed source contains a symlink")
        if path.is_file() and path != manifest_path:
            actual[path.relative_to(source_dir).as_posix()] = path
    if set(actual) != set(expected):
        raise ReceiptError("sealed source file inventory changed after acceptance")
    for name, path in actual.items():
        entry = expected[name]
        size = entry.get("bytes")
        sha256 = entry.get("sha256")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or path.stat().st_size != size
            or not isinstance(sha256, str)
            or file_sha256(path) != sha256
        ):
            raise ReceiptError(f"sealed source file changed after acceptance: {name}")


def verify_release_receipt(
    receipt_path: Path,
    *,
    state_root: Path,
    policy_path: Path,
    expected_source: Mapping[str, str],
    expected_images: Mapping[str, str] | None = None,
) -> ReleaseReceipt:
    """Verify one controller-owned PASS receipt and every bound local report."""

    state_root_argument = state_root.absolute()
    if state_root_argument.is_symlink():
        raise ReceiptError("trusted state root must not be a symlink")
    state_root = state_root_argument.resolve(strict=True)
    receipt_path = receipt_path.absolute()
    _assert_no_symlink(receipt_path, state_root)
    try:
        raw_object = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReceiptError(f"receipt is unreadable: {error}") from error
    raw = _mapping(raw_object, "receipt")
    if raw.get("schema_version") != RECEIPT_SCHEMA:
        raise ReceiptError("unsupported release-gate receipt schema")
    run_id = _string(raw.get("run_id"), "run_id")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ReceiptError("receipt run id is invalid")
    run_dir = state_root / "runs" / run_id
    expected_receipt_path = run_dir / "release-receipt.json"
    if receipt_path.resolve(strict=True) != expected_receipt_path.resolve(strict=True):
        raise ReceiptError("receipt is outside its canonical trusted run path")

    policy = Policy.load(policy_path)
    policy_ref = _mapping(raw.get("policy"), "receipt.policy")
    if policy_ref.get("version") != policy.version or policy_ref.get("sha256") != policy.sha256:
        raise ReceiptError("receipt was produced by a different or weaker policy")
    if raw.get("status") != "PASS" or raw.get("complete") is not True:
        raise ReceiptError("receipt is not a complete PASS")
    if raw.get("inventory_sha256") != policy.inventory_sha256:
        raise ReceiptError("receipt expanded inventory does not match policy")
    omissions = raw.get("explicit_not_performed")
    if omissions != list(policy.explicit_not_performed):
        raise ReceiptError("receipt explicit omissions do not match policy")

    source = _mapping(raw.get("source"), "source")
    source_kind = _string(source.get("kind"), "source.kind")
    if source_kind not in policy.supported_candidate_kinds:
        raise ReceiptError("receipt candidate kind is unsupported")
    for field in ("archive_sha256", "tree_sha256", "manifest_sha256"):
        if not SHA256_RE.fullmatch(_string(source.get(field), f"source.{field}")):
            raise ReceiptError(f"source {field} is malformed")
    required_source_identity = {"archive_sha256", "tree_sha256", "manifest_sha256"}
    if set(expected_source) != required_source_identity:
        raise ReceiptError("expected source must contain the exact three content identities")
    for key, value in expected_source.items():
        if source.get(key) != value:
            raise ReceiptError(f"receipt source identity mismatch: {key}")
    _verify_sealed_source(run_dir, source, state_root)

    stages_raw = raw.get("stages")
    if not isinstance(stages_raw, list):
        raise ReceiptError("receipt stages must be a list")
    stages = tuple(
        _validate_stage(_mapping(item, "stage"), policy, run_dir, state_root) for item in stages_raw
    )
    actual_stage_ids = tuple(stage.stage_id for stage in stages)
    if actual_stage_ids != policy.required_stage_ids:
        raise ReceiptError("receipt does not contain the exact ordered required stage set")

    artifacts_raw = _mapping(raw.get("artifacts"), "artifacts")
    if set(artifacts_raw) != {"api", "web", "worker"}:
        raise ReceiptError("receipt must bind exactly api, web and worker artifacts")
    artifacts: dict[str, ArtifactReceipt] = {}
    runtime_images = _mapping(policy.raw.get("runtime_images"), "runtime_images")
    build_recipes = _mapping(policy.raw.get("build_recipes"), "build_recipes")
    for kind, value in artifacts_raw.items():
        artifact = _mapping(value, f"artifacts.{kind}")
        image_id = _string(artifact.get("image_id"), f"artifacts.{kind}.image_id")
        if not IMAGE_ID_RE.fullmatch(image_id):
            raise ReceiptError(f"artifact image id is malformed: {kind}")
        tree_sha = _string(
            artifact.get("source_tree_sha256"), f"artifacts.{kind}.source_tree_sha256"
        )
        if tree_sha != source.get("tree_sha256"):
            raise ReceiptError(f"artifact is not bound to receipt source: {kind}")
        base_image = _string(artifact.get("base_image"), f"artifacts.{kind}.base_image")
        runtime_key = "node" if kind == "web" else "python"
        expected_runtime = _mapping(
            runtime_images.get(runtime_key), f"runtime_images.{runtime_key}"
        )
        if base_image != expected_runtime.get("reference") or artifact.get(
            "base_image_id"
        ) != expected_runtime.get("image_id"):
            raise ReceiptError(f"artifact base image differs from policy: {kind}")
        recipe_key = "api" if kind == "worker" else kind
        recipe = _mapping(build_recipes.get(recipe_key), f"build_recipes.{recipe_key}")
        if artifact.get("dockerfile_sha256") != recipe.get("sha256"):
            raise ReceiptError(f"artifact build recipe differs from policy: {kind}")
        artifacts[kind] = ArtifactReceipt(kind, image_id, tree_sha, base_image)
    if artifacts["worker"].image_id != artifacts["api"].image_id:
        raise ReceiptError("worker artifact must be the exact accepted API image")
    if expected_images is not None:
        if set(expected_images) != {"api", "web", "worker"}:
            raise ReceiptError("expected images must identify api, web and worker")
        for kind, image_id in expected_images.items():
            if kind not in artifacts or artifacts[kind].image_id != image_id:
                raise ReceiptError(f"receipt artifact identity mismatch: {kind}")

    cleanup = _mapping(raw.get("cleanup"), "cleanup")
    if cleanup.get("complete") is not True:
        raise ReceiptError("disposable resource cleanup is incomplete")
    resources = cleanup.get("resources")
    if not isinstance(resources, list):
        raise ReceiptError("cleanup.resources must be a list")
    for item in resources:
        resource = _mapping(item, "cleanup resource")
        if resource.get("removed") is not True or resource.get("identity_verified") is not True:
            raise ReceiptError("cleanup contains an unverified or retained disposable resource")

    return ReleaseReceipt(receipt_path, run_id, source, stages, artifacts, raw)
