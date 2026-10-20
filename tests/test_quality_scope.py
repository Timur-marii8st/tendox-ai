from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "quality_scope_under_test", ROOT / "scripts" / "check_quality_scope.py"
)
assert SPEC is not None and SPEC.loader is not None
QUALITY_SCOPE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = QUALITY_SCOPE
SPEC.loader.exec_module(QUALITY_SCOPE)
OPTIONAL_INTEGRATION = QUALITY_SCOPE.OPTIONAL_INTEGRATION
BASELINE_FIXTURES = QUALITY_SCOPE.BASELINE_FIXTURES
DOWNGRADE_MODULES = QUALITY_SCOPE.DOWNGRADE_MODULES
baseline_environment = QUALITY_SCOPE._baseline_environment
assert_disposable_database = QUALITY_SCOPE.assert_disposable_database
build_inventory = QUALITY_SCOPE.build_inventory


def test_repository_quality_inventory_is_complete_and_downgrades_are_isolated() -> None:
    inventory = build_inventory(ROOT)
    actual_web = {
        path.relative_to(ROOT / "web").as_posix()
        for path in (ROOT / "web" / "tests").rglob("*")
        if path.is_file() and path.name.endswith((".test.ts", ".test.tsx"))
    }
    assert set(inventory.web_tests) == actual_web

    actual_postgres = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests" / "integration").glob("test_*.py")
    }
    actual_postgres.update(
        {
            f"tests/{name}"
            for name in (
                "test_eis_mixed_number_archive.py",
                "test_eis_no_data_evidence.py",
                "test_eis_no_data_public_check.py",
                "test_eis_no_data_report.py",
                "test_eis_no_data_store_report.py",
                "test_eis_public_candidate_recovery.py",
                "test_eis_requirement_review_postgres.py",
            )
        }
    )
    executable = {path for group in inventory.postgres_groups for path in group.paths}
    optional = {path for path, _ in inventory.optional_integration}
    assert executable.isdisjoint(optional)
    assert executable | optional == actual_postgres
    assert {Path(path).name for path in optional} == set(OPTIONAL_INTEGRATION)
    assert {Path(path).name for path in executable} >= {
        "test_eis_analog_holds_pg.py",
        "test_eis_analog_prefilter_pg.py",
        "test_eis_analog_resolution_scope_pg.py",
    }
    assert {Path(path).name for path in optional} == {"test_paddle_ocr.py"}
    assert all(len(group.paths) == 1 for group in inventory.postgres_groups if group.isolated)
    assert {
        Path(group.paths[0]).name for group in inventory.postgres_groups if group.isolated
    } == DOWNGRADE_MODULES
    characteristic_group = next(
        group for group in inventory.postgres_groups if group.name == "eis-characteristic-pair"
    )
    assert characteristic_group.database == "procurement_eis_test_20261005_s209"
    assert {Path(path).name for path in characteristic_group.paths} == {
        "test_eis_characteristic_pair_pg.py",
        "test_supplier_captcha_pg.py",
    }


def test_historical_baseline_manifest_and_bytes_are_pinned(tmp_path) -> None:
    fixture_dir = tmp_path / "tests" / "fixtures" / "eis_release_baselines"
    fixture_dir.parent.mkdir(parents=True)
    shutil.copytree(ROOT / "tests" / "fixtures" / "eis_release_baselines", fixture_dir)

    environment = baseline_environment(tmp_path)
    assert set(environment) == set(BASELINE_FIXTURES)
    for variable, path_value in environment.items():
        filename, expected_bytes, expected_sha256 = BASELINE_FIXTURES[variable]
        path = Path(path_value)
        assert path.name == filename
        assert path.stat().st_size == expected_bytes
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256

    tampered = fixture_dir / "s205_eis_analogs.py"
    # copytree preserves the sealed source's read-only mode. Mutate only this copy.
    tampered.chmod(tampered.stat().st_mode | 0o200)
    tampered.write_bytes(tampered.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="fixture hash mismatch"):
        baseline_environment(tmp_path)


def test_postgres_runner_refuses_unmarked_or_wrong_database(monkeypatch) -> None:
    inventory = build_inventory(ROOT)
    group = inventory.postgres_groups[0]
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://app@127.0.0.1/production"
    )
    monkeypatch.setenv(
        "DATABASE_ADMIN_URL", "postgresql+psycopg://owner@127.0.0.1/production"
    )
    with pytest.raises(ValueError, match="QUALITY_GATE_DISPOSABLE_POSTGRES"):
        assert_disposable_database(group)
    monkeypatch.setenv("QUALITY_GATE_DISPOSABLE_POSTGRES", "1")
    with pytest.raises(ValueError, match="requires both URLs"):
        assert_disposable_database(group)


def test_postgres_runner_rejects_dsn_query_overrides(monkeypatch) -> None:
    inventory = build_inventory(ROOT)
    group = next(item for item in inventory.postgres_groups if item.name == "foundation")
    safe = f"postgresql+psycopg://user@127.0.0.1:5432/{group.database}"
    monkeypatch.setenv("QUALITY_GATE_DISPOSABLE_POSTGRES", "1")
    monkeypatch.setenv("DATABASE_ADMIN_URL", safe)
    monkeypatch.setenv("DATABASE_URL", safe)
    assert_disposable_database(group)
    monkeypatch.setenv("DATABASE_URL", safe + "?host=remote.example&dbname=production")
    with pytest.raises(ValueError, match="no query overrides"):
        assert_disposable_database(group)


def test_web_inventory_rejects_output_outside_build_before_runner_delete(tmp_path) -> None:
    web = tmp_path / "web"
    tests = web / "tests"
    tests.mkdir(parents=True)
    (tests / "example.test.ts").write_text("export {};", encoding="utf-8")
    (web / "tsconfig.escape-tests.json").write_text(
        json.dumps(
            {
                "compilerOptions": {"outDir": "../outside"},
                "include": ["tests/example.test.ts"],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "tests" / "integration").mkdir(parents=True)
    shutil.copytree(
        ROOT / "tests" / "fixtures" / "eis_release_baselines",
        tmp_path / "tests" / "fixtures" / "eis_release_baselines",
    )
    with pytest.raises(ValueError, match="strict descendant of web/build"):
        build_inventory(tmp_path)
