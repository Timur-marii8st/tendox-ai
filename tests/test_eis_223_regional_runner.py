"""National batch admission, local failure fairness and renewed resource gates."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from procurement.sources.eis_223_sync import Eis223RefreshTarget
from procurement.storage.eis_223_regions import Eis223RegionalCoverage
from test_eis_223_sync import runner as runner_fixture


@pytest.fixture
def runner():
    return runner_fixture.__wrapped__()


@pytest.mark.parametrize(
    "case",
    ["missing_catalog", "local_failure", "disk_after_first", "priority_before", "priority_during"],
)
def test_regional_batch_guards_and_target_local_failure(monkeypatch, runner, case):
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.scalar.return_value = 1
    monkeypatch.setenv("EIS_223_REGIONAL_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setenv("EIS_GETDOCS_IP_TOKEN", "synthetic-test-token")
    monkeypatch.setattr(runner, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(runner, "PostgresStorage", lambda *a: object())

    async def catalog(_):
        return {"status": "NOT_DUE", "source_requests": 0}

    monkeypatch.setattr(runner, "refresh_catalog", catalog)
    calls = []
    monkeypatch.setattr(
        runner,
        "priority_requested",
        lambda *a, **k: case == "priority_before" or (case == "priority_during" and bool(calls)),
    )
    quality = MagicMock(return_value={"source_requests": 0})
    monkeypatch.setattr(runner, "quality_report", quality)

    def disk(_):
        return SimpleNamespace(
            free=0 if case == "disk_after_first" and calls else runner.MIN_FREE_BYTES + 1
        )

    monkeypatch.setattr(runner.shutil, "disk_usage", disk)
    monkeypatch.setattr(
        runner, "ensure_region_wave", lambda *a, **k: None if case == "missing_catalog" else "wave"
    )
    targets = tuple(
        Eis223RefreshTarget(date(2026, 10, 3), "purchaseNoticeAESMBO", r) for r in ("77", "78")
    )
    monkeypatch.setattr(runner, "regional_due_windows", lambda *a, **k: targets)
    monkeypatch.setattr(
        runner,
        "read_region_coverage",
        lambda *a, **k: Eis223RegionalCoverage(
            company_id="local-eis-supplier", checked_at=datetime.now(UTC)
        ),
    )

    @asynccontextmanager
    async def session():
        assert case != "missing_catalog"

        class Inner:
            async def post(self, xml):
                return 200, b"synthetic"

        yield Inner()

    async def fetch(*args, region, **kwargs):
        calls.append(region)
        await args[3].post(b"synthetic")
        if case == "local_failure" and len(calls) == 1:
            raise ValueError("ARCHIVE_SET_MISMATCH")
        return SimpleNamespace(status="NO_DATA", response_sha256="a" * 64)

    records = []
    monkeypatch.setattr(runner, "eis_browser_transport", session)
    monkeypatch.setattr(runner, "fetch_notice223_day", fetch)
    monkeypatch.setattr(runner, "record_attempt", lambda *a, **k: records.append(a[3]))
    result = asyncio.run(runner.run())
    if case == "missing_catalog":
        assert not calls and result["reason"] == "OFFICIAL_REGION_CATALOG_MISSING"
    elif case == "local_failure":
        assert calls == ["77", "78"] and records == ["FAILED", "NO_DATA"]
        assert result["source_posts"] == 2 and "deferred_windows" not in result
    elif case == "disk_after_first":
        assert calls == ["77"] and records == ["NO_DATA"]
        assert result["stop_reason"] == "DISK_RESERVE_REACHED"
    else:
        assert calls == ["77"] and records == ["NO_DATA"]
        assert result["attempted"] == 1 and result["source_posts"] == 1
        assert result["stop_reason"] == "PRIORITY_REFRESH_REQUESTED"
        assert result["quality"] == {"reason": "DEFERRED_FOR_PRIORITY", "source_requests": 0}
        quality.assert_not_called()
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("case", ["not_due", "fetched", "failed"])
def test_catalog_hook_does_not_fetch_until_due_and_records_safe_outcome(monkeypatch, runner, case):
    from procurement.storage.eis_223_catalog_checks import CatalogCheck

    now = datetime.now(UTC)
    calls = []
    monkeypatch.setattr(runner, "catalog_refresh_due", lambda *a: case != "not_due")

    async def fetch():
        calls.append("fetch")
        return SimpleNamespace(
            body=b"synthetic" if case == "fetched" else b"",
            observed_at=now,
            reason=None if case == "fetched" else "HTTP_REJECTED",
            http_status=200 if case == "fetched" else 503,
            source_requests=1,
        )

    def record(storage, company, body, **kwargs):
        calls.append("record")
        assert body == (b"synthetic" if case == "fetched" else None)
        assert kwargs["http_status"] == (200 if case == "fetched" else 503)
        return CatalogCheck(
            company_id=company,
            attempt_id="test",
            checked_at=now,
            status="ACCEPTED" if case == "fetched" else "FAILED",
            catalog_sha256="a" * 64 if case == "fetched" else None,
            response_sha256="a" * 64 if case == "fetched" else None,
            http_status=kwargs["http_status"],
            reason=kwargs["reason"],
        )

    monkeypatch.setattr(runner, "fetch_region_selector", fetch)
    monkeypatch.setattr(runner, "record_catalog_check", record)
    result = asyncio.run(runner.refresh_catalog(object()))
    assert calls == ([] if case == "not_due" else ["fetch", "record"])
    assert result["source_requests"] == (0 if case == "not_due" else 1)


@pytest.mark.parametrize(
    "case",
    ["idle", "catalog", "new_wave", "calendar", "targets", "failed", "catalog_only", "no_catalog"],
)
def test_readonly_dispatch_probe_announces_only_meaningful_work(monkeypatch, runner, case):
    engine = MagicMock()
    created = []

    def create(*args, **kwargs):
        created.append(kwargs)
        return engine

    monkeypatch.setenv("DATABASE_URL", "synthetic")
    monkeypatch.setattr(runner, "create_engine", create)
    monkeypatch.setattr(runner, "PostgresStorage", lambda *a: object())
    monkeypatch.setattr(runner, "catalog_refresh_due", lambda *a: case == "catalog")
    monkeypatch.setattr(runner, "accepted_catalog_present", lambda *a: case != "no_catalog")

    def due(*a, limit, **k):
        assert 2 <= limit <= 32
        return [object()] if case == "targets" else []

    monkeypatch.setattr(runner, "regional_due_windows", due)

    def coverage(*a, **k):
        if case == "failed":
            raise ValueError("synthetic-probe-failure")
        return Eis223RegionalCoverage(
            company_id="local-eis-supplier",
            checked_at=datetime.now(UTC),
            catalog_sha256=None if case in {"catalog_only", "no_catalog"} else "a" * 64,
            wave_id=None if case in {"new_wave", "catalog_only", "no_catalog"} else "wave",
            first_sweep_finished=case == "calendar",
            end_day=date(2020, 1, 1),
        )

    monkeypatch.setattr(runner, "read_region_coverage", coverage)
    forbidden = MagicMock(side_effect=AssertionError("probe must not mutate or access source"))
    for name in (
        "ensure_region_wave",
        "record_attempt",
        "refresh_catalog",
        "eis_browser_transport",
    ):
        monkeypatch.setattr(runner, name, forbidden)
    if case == "failed":
        with pytest.raises(ValueError, match="synthetic-probe-failure"):
            runner.probe()
    else:
        result = runner.probe()
        assert result["status"] == ("IDLE" if case in {"idle", "no_catalog"} else "READY")
        assert result["source_requests"] == 0 and result["coverage"] == "UNKNOWN"
    assert "default_transaction_read_only=on" in created[0]["connect_args"]["options"]
    forbidden.assert_not_called()
    engine.dispose.assert_called_once()


def test_quality_rechecks_priority_after_last_window_or_catalog_work(monkeypatch, runner):
    priority = False
    quality = MagicMock(return_value={"reason": "COMPLETED", "source_requests": 0})
    monkeypatch.setattr(runner, "priority_requested", lambda *a, **k: priority)
    monkeypatch.setattr(runner, "quality_report", quality)
    assert runner.optional_quality(object(), regional=True)["reason"] == "COMPLETED"
    priority = True
    assert runner.optional_quality(object(), regional=True)["reason"] == "DEFERRED_FOR_PRIORITY"
    assert quality.call_count == 1
    assert runner.optional_quality(object(), regional=False)["reason"] == "COMPLETED"
