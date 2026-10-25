"""Known recent reconciliation must reach the worker before cold-history SQL."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def module():
    spec = importlib.util.spec_from_file_location(
        "probe223", Path(__file__).parents[1] / "scripts/server-eis-223-refresh.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz or UTC)

    m.datetime = Clock
    return m


@pytest.mark.parametrize("urgent", [False, True])
def test_recent_or_current_known_demand_never_enters_cold_history(monkeypatch, urgent):
    m = module()
    engine = Mock()
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setattr(m, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(m, "PostgresStorage", lambda *a: object())
    monkeypatch.setattr(
        m,
        "read_region_coverage",
        lambda *a, **k: SimpleNamespace(
            catalog_sha256="a" * 64, wave_id="wave", end_day=NOW.date()
        ),
    )
    monkeypatch.setattr(m, "catalog_refresh_due", lambda *a: urgent)
    monkeypatch.setattr(m, "regional_due_windows", lambda *a, **k: ())
    recent = (
        Mock(side_effect=AssertionError("urgent needs no recovery query"))
        if urgent
        else Mock(return_value=True)
    )
    monkeypatch.setattr(m, "recent_reconciliation_due", recent)
    cold = Mock(side_effect=AssertionError("known recent demand must not scan history"))
    monkeypatch.setattr(m, "recovery_windows", cold)
    monkeypatch.setattr(m, "joint_mandatory_status", cold)
    result = m.probe()
    assert result["status"] == "READY" and result["source_requests"] == 0
    assert result["recent_reconciliation_due"] is (not urgent)
    cold.assert_not_called()
    engine.dispose.assert_called_once()


def test_recent_probe_refuses_naive_time():
    with pytest.raises(ValueError, match="PROBE_TIMEZONE_MISSING"):
        module().recent_reconciliation_due(object(), NOW.replace(tzinfo=None))


def test_probe_sql_failure_does_not_turn_into_idle(monkeypatch):
    m = module()
    engine = Mock()
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setattr(m, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(m, "PostgresStorage", lambda *a: object())
    monkeypatch.setattr(
        m,
        "read_region_coverage",
        lambda *a, **k: SimpleNamespace(
            catalog_sha256="a" * 64, wave_id="wave", end_day=NOW.date()
        ),
    )
    monkeypatch.setattr(m, "catalog_refresh_due", lambda *a: False)
    monkeypatch.setattr(m, "regional_due_windows", lambda *a, **k: ())
    monkeypatch.setattr(
        m, "recent_reconciliation_due", Mock(side_effect=RuntimeError("SQL_UNAVAILABLE"))
    )
    with pytest.raises(RuntimeError, match="SQL_UNAVAILABLE"):
        m.probe()
    engine.dispose.assert_called_once()
