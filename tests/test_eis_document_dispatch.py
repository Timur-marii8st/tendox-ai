"""No source or database writes during the operational ready probe."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from procurement import eis_document_dispatch_cli as dispatch


@pytest.mark.parametrize(
    "preferred,ready44,ready223,expected",
    [
        ("44", True, True, "44"),
        ("223", True, True, "223"),
        ("44", False, True, "223"),
        ("223", True, False, "44"),
        ("223", False, False, None),
    ],
)
def test_choose_due_family_without_idle_slots(monkeypatch, preferred, ready44, ready223, expected):
    monkeypatch.setattr(dispatch, "resource_gate", lambda *a, **k: None)

    def probe44(*args, **kwargs):
        assert kwargs["probe_only"] is True
        return {"status": "READY" if ready44 else "IDLE"}

    monkeypatch.setattr(dispatch, "run_document_step", probe44)
    monkeypatch.setattr(
        dispatch, "next_document223", lambda *a: (SimpleNamespace(), "uid") if ready223 else None
    )
    report = dispatch.probe_dispatch(None, "tenant-a", preferred_law=preferred)
    assert report.law == expected
    assert report.status == ("READY" if expected else "IDLE")
    assert report.checked_at.utcoffset() is not None


def test_resource_stop_precedes_any_queue_probe(monkeypatch):
    monkeypatch.setattr(dispatch, "resource_gate", lambda *a, **k: "DATABASE_BUDGET_REACHED")

    def forbidden(*args, **kwargs):
        raise AssertionError("No queue processing after resource stop")

    monkeypatch.setattr(dispatch, "run_document_step", forbidden)
    monkeypatch.setattr(dispatch, "next_document223", forbidden)
    report = dispatch.probe_dispatch(None, "tenant-a", preferred_law="44")
    assert report.status == "BLOCKED" and report.law is None


@pytest.mark.parametrize(
    "company,law,now",
    [
        ("", "44", datetime.now(UTC)),
        ("a", "444", datetime.now(UTC)),
        ("a", "223", datetime(2026, 10, 2)),
    ],
)
def test_invalid_operational_inputs_rejected(company, law, now):
    with pytest.raises(ValueError, match="DOCUMENT_DISPATCH_INPUT_INVALID"):
        dispatch.probe_dispatch(None, company, preferred_law=law, now=now)
