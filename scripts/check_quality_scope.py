"""Inventory quality tests and run PostgreSQL groups only on disposable local databases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

OPTIONAL_INTEGRATION = {
    "test_paddle_ocr.py": "optional PaddleOCR runtime and model assets",
}
BASELINE_FIXTURES = {
    "S206_BASELINE_ANALOGS_PATH": (
        "s205_eis_analogs.py",
        9615,
        "b94a0c850223006787457bad239f7bb77fa0ae2dd06e584f179839f4810be84b",
    ),
    "S208_BASELINE_ANALOGS_PATH": (
        "s206_eis_analogs.py",
        9884,
        "12e41b09bf4c415549aaef265543d615b4f614d8a901f7bd707c36ebc52fc0b5",
    ),
    "S209_BASELINE_ANALOGS_PATH": (
        "s208_eis_analogs.py",
        11025,
        "3b43638c735e443423d923a0fbb48a6f4cad56906c7448edb3fb46e7bd64b619",
    ),
    "S209_BASELINE_HOLD_PATH": (
        "s208_eis_notice_hold.py",
        14631,
        "b044241cc52de3cc742d13f597060cb76d0268072e78879b0680d6d80e6cf570",
    ),
}
DEFAULT_DATABASE = "procurement_eis_test_20261005_s209"
SPECIAL_DATABASES = {
    "test_eis_223_wide_window_pg.py": "procurement_eis_test_20261004_s176",
    "test_eis_characteristic_pair_pg.py": "procurement_eis_test_20261005_s209",
    "test_eis_notice_projection_pg.py": "procurement_eis_test_20261004_s180",
    "test_eis_notice_variants_pg.py": "procurement_eis_test_20261004_s178",
}
MANUFACTURER_PREFIXES = ("test_manufacturer_",)
DOWNGRADE_PATTERN = re.compile(r"\bcommand\.downgrade\s*\(")
DOWNGRADE_MODULES = {
    "test_eis_223_catalog_checks_pg.py",
    "test_eis_223_events_pg.py",
    "test_eis_223_general_pg.py",
    "test_eis_223_index_pg.py",
    "test_eis_223_lot_events_pg.py",
    "test_eis_223_regions_pg.py",
    "test_eis_223_regular_kesmbo_pg.py",
    "test_eis_223_zpesmbo_pg.py",
    "test_eis_223_position_projection_pg.py",
    "test_eis_223_wide_window_pg.py",
    "test_eis_notice_projection_pg.py",
    "test_eis_notice_variants_pg.py",
}
ROOT_POSTGRES_PATTERN = re.compile(
    r"os\.getenv\([\"']DATABASE_URL[\"']|storage\s*=\s*storage_fixture"
)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class PostgresGroup:
    name: str
    database: str
    paths: tuple[str, ...]
    isolated: bool


@dataclass(frozen=True)
class Inventory:
    web_tests: tuple[str, ...]
    web_configs: tuple[str, ...]
    postgres_groups: tuple[PostgresGroup, ...]
    optional_integration: tuple[tuple[str, str], ...]


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _web_inventory(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    web = root / "web"
    tests = tuple(
        sorted(
            _relative(path, web)
            for path in (web / "tests").rglob("*")
            if path.is_file() and re.search(r"\.test\.tsx?$", path.name)
        )
    )
    configs = tuple(sorted(path.name for path in web.glob("tsconfig.*-tests.json")))
    if not tests or not configs:
        raise ValueError("web tests and test TypeScript configs must both be present")

    owners: dict[str, list[str]] = {path: [] for path in tests}
    build_root = (web / "build").resolve()
    out_dirs: dict[Path, str] = {}
    for config_name in configs:
        config_path = web / config_name
        config = json.loads(config_path.read_text(encoding="utf-8"))
        includes = config.get("include", [])
        selected = [path for path in includes if re.search(r"\.test\.tsx?$", path)]
        if not selected:
            raise ValueError(f"{config_name} includes no test source")
        for included in includes:
            if not (web / included).is_file():
                raise ValueError(f"{config_name} references missing file {included}")
        for selected_path in selected:
            if selected_path not in owners:
                raise ValueError(f"{config_name} includes untracked test {selected_path}")
            owners[selected_path].append(config_name)
        out_dir = config.get("compilerOptions", {}).get("outDir")
        if not out_dir:
            raise ValueError(f"{config_name} has no compilerOptions.outDir")
        resolved_out_dir = (web / out_dir).resolve()
        if resolved_out_dir == build_root or not resolved_out_dir.is_relative_to(build_root):
            raise ValueError(f"{config_name} outDir must be a strict descendant of web/build")
        overlap = next(
            (
                existing
                for existing in out_dirs
                if resolved_out_dir == existing
                or resolved_out_dir.is_relative_to(existing)
                or existing.is_relative_to(resolved_out_dir)
            ),
            None,
        )
        if overlap is not None:
            raise ValueError(
                f"{config_name} outDir overlaps {out_dirs[overlap]}: {out_dir}"
            )
        out_dirs[resolved_out_dir] = config_name

    errors = [f"{path}: {assigned}" for path, assigned in owners.items() if len(assigned) != 1]
    if errors:
        raise ValueError("web tests must belong to exactly one config: " + "; ".join(errors))
    return tests, configs


def _shared_group_name(filename: str) -> str:
    if filename.startswith(MANUFACTURER_PREFIXES):
        return "manufacturer"
    if filename in {"test_eis_characteristic_pair_pg.py", "test_supplier_captcha_pg.py"}:
        return "eis-characteristic-pair"
    if filename.startswith("test_eis_"):
        suffix = filename.removeprefix("test_eis_")
        return "eis-a-m" if suffix[0].lower() <= "m" else "eis-n-z"
    return "foundation"


def _postgres_inventory(
    root: Path,
) -> tuple[tuple[PostgresGroup, ...], tuple[tuple[str, str], ...]]:
    integration = root / "tests" / "integration"
    integration_files = sorted(integration.glob("test_*.py"))
    root_postgres_files = sorted(
        path
        for path in (root / "tests").glob("test_*.py")
        if ROOT_POSTGRES_PATTERN.search(path.read_text(encoding="utf-8"))
    )
    files = [*integration_files, *root_postgres_files]
    names = {path.name for path in integration_files}
    stale_exclusions = set(OPTIONAL_INTEGRATION) - names
    if stale_exclusions:
        raise ValueError(f"stale optional integration entries: {sorted(stale_exclusions)}")
    stale_downgrades = DOWNGRADE_MODULES - names
    if stale_downgrades:
        raise ValueError(f"stale downgrade module entries: {sorted(stale_downgrades)}")

    grouped: dict[tuple[str, str, bool], list[str]] = {}
    optional = []
    for path in files:
        relative_path = _relative(path, root)
        if path.name in OPTIONAL_INTEGRATION:
            optional.append((relative_path, OPTIONAL_INTEGRATION[path.name]))
            continue
        source = path.read_text(encoding="utf-8")
        if path in root_postgres_files:
            key = ("root-postgres", DEFAULT_DATABASE, False)
        elif path.name in DOWNGRADE_MODULES or DOWNGRADE_PATTERN.search(source):
            group_name = "migration-" + path.stem.removeprefix("test_").replace("_", "-")
            database = SPECIAL_DATABASES.get(path.name, DEFAULT_DATABASE)
            key = (group_name, database, True)
        else:
            group_name = _shared_group_name(path.name)
            database = (
                "procurement_manufacturer_test"
                if group_name == "manufacturer"
                else SPECIAL_DATABASES.get(path.name, DEFAULT_DATABASE)
            )
            key = (group_name, database, False)
        grouped.setdefault(key, []).append(relative_path)

    groups = tuple(
        PostgresGroup(name, database, tuple(paths), isolated)
        for (name, database, isolated), paths in sorted(grouped.items())
    )
    covered = {path for group in groups for path in group.paths}
    excluded = {path for path, _ in optional}
    expected = {_relative(path, root) for path in files}
    if covered & excluded or covered | excluded != expected:
        raise ValueError("PostgreSQL inventory has missing or duplicate module assignments")
    if any(group.isolated and len(group.paths) != 1 for group in groups):
        raise ValueError("every downgrade module must have its own fresh database job")
    return groups, tuple(optional)


def build_inventory(root: Path) -> Inventory:
    _baseline_environment(root)
    web_tests, web_configs = _web_inventory(root)
    postgres_groups, optional = _postgres_inventory(root)
    return Inventory(web_tests, web_configs, postgres_groups, optional)


def _baseline_environment(root: Path) -> dict[str, str]:
    fixture_root = root / "tests" / "fixtures" / "eis_release_baselines"
    manifest_path = fixture_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"historical baseline manifest is unavailable: {error}") from error
    if manifest.get("schemaVersion") != 1 or manifest.get("sourceKind") != (
        "OWN_RELEASE_CODE_REGRESSION_ORACLE"
    ):
        raise ValueError("historical baseline manifest identity is invalid")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("historical baseline manifest files must be a list")
    by_filename = {
        entry.get("filename"): entry for entry in entries if isinstance(entry, dict)
    }
    expected_filenames = {spec[0] for spec in BASELINE_FIXTURES.values()}
    if len(by_filename) != len(entries) or set(by_filename) != expected_filenames:
        raise ValueError("historical baseline manifest file inventory is invalid")

    environment: dict[str, str] = {}
    for variable, (filename, expected_bytes, expected_sha256) in BASELINE_FIXTURES.items():
        entry = by_filename[filename]
        if (
            entry.get("bytes") != expected_bytes
            or entry.get("sha256") != expected_sha256
            or entry.get("testBindings") != [variable]
        ):
            raise ValueError(f"historical baseline manifest entry is invalid: {filename}")
        path = fixture_root / filename
        try:
            content = path.read_bytes()
        except OSError as error:
            raise ValueError(f"historical baseline fixture is unavailable: {filename}") from error
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if len(content) != expected_bytes or actual_sha256 != expected_sha256:
            raise ValueError(f"historical baseline fixture hash mismatch: {filename}")
        environment[variable] = str(path.resolve())
    return environment


def _database_from_url(value: str, variable: str) -> tuple[str, int | None, str]:
    normalized = value.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    database = unquote(parsed.path.lstrip("/"))
    host = parsed.hostname or ""
    if (
        parsed.scheme != "postgresql"
        or not database
        or host not in LOCAL_HOSTS
        or parsed.query
        or parsed.fragment
        or parsed.params
    ):
        raise ValueError(
            f"{variable} must be a local PostgreSQL URL with an explicit database "
            "and no query overrides"
        )
    return host, parsed.port, database


def assert_disposable_database(group: PostgresGroup) -> None:
    if os.environ.get("QUALITY_GATE_DISPOSABLE_POSTGRES") != "1":
        raise ValueError("QUALITY_GATE_DISPOSABLE_POSTGRES=1 is required")
    targets = {
        _database_from_url(os.environ.get(variable, ""), variable)
        for variable in ("DATABASE_URL", "DATABASE_ADMIN_URL")
    }
    databases = {target[2] for target in targets}
    if len(targets) != 1 or databases != {group.database}:
        raise ValueError(
            f"group {group.name} requires both URLs to target the same local endpoint and "
            f"disposable database {group.database!r}; got {sorted(map(repr, targets))!r}"
        )


def _matrix(inventory: Inventory) -> dict[str, list[dict[str, object]]]:
    return {
        "include": [
            {
                "group": group.name,
                "database": group.database,
                "isolated": group.isolated,
            }
            for group in inventory.postgres_groups
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--postgres-matrix", action="store_true")
    mode.add_argument("--run-postgres-group")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    inventory = build_inventory(root)

    if args.postgres_matrix:
        print(json.dumps(_matrix(inventory), separators=(",", ":")))
        return 0
    if args.check:
        executed = sum(len(group.paths) for group in inventory.postgres_groups)
        isolated = sum(group.isolated for group in inventory.postgres_groups)
        print(f"Web: {len(inventory.web_tests)} tests in {len(inventory.web_configs)} configs")
        print(
            f"PostgreSQL: {executed} executable modules in "
            f"{len(inventory.postgres_groups)} fresh-DB groups ({isolated} downgrade-isolated)"
        )
        for path, reason in inventory.optional_integration:
            print(f"NOT_PERFORMED: {path} ({reason})")
        print("NOT_PERFORMED: browser/E2E suite (no configured browser test suite)")
        return 0

    group = next(
        (item for item in inventory.postgres_groups if item.name == args.run_postgres_group),
        None,
    )
    if group is None:
        parser.error(f"unknown PostgreSQL group {args.run_postgres_group!r}")
    assert_disposable_database(group)
    print(f"Running PostgreSQL group {group.name}: {', '.join(group.paths)}", flush=True)
    environment = os.environ.copy()
    environment.update(_baseline_environment(root))
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *group.paths, "--require-postgres", "-q", "-rs"],
        cwd=root,
        env=environment,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
