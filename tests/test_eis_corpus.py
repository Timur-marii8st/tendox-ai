"""Large scope planning must stay bounded and must not certify source completeness."""

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from procurement import eis_corpus_cli
from procurement.sources import eis_corpus
from procurement.sources.eis_corpus import EisCorpusScope, parse_date_window
from procurement.sources.eis_feed_sync import EisRejectedWindowError, EisSyncError

NOW = datetime(2026, 9, 28, tzinfo=UTC)


def scope() -> EisCorpusScope:
    return EisCorpusScope(
        ("50", "77"),
        ("epNotificationEF2020", "epNotificationCancel"),
        date(2026, 9, 1),
        date(2026, 9, 27),
    )


def test_lazy_scope_batches_are_unique_complete_and_newest_first() -> None:
    selected = scope()
    selected.validate(NOW)
    batches = list(selected.batches())
    assert all(1 <= len(batch) <= 31 for batch in batches)
    keys = [selection.window_key for batch in batches for selection in batch]
    assert len(set(keys)) == len(keys) == selected.expected_windows == 108
    assert batches[0][0].day == date(2026, 9, 27)
    assert batches[-1][-1].day == date(2026, 9, 1)
    assert selected.source_completeness == "UNKNOWN"
    assert (
        len(selected.sha256) == 64 and selected.sha256 != replace(selected, regions=("50",)).sha256
    )


@pytest.mark.parametrize("regions", [(), ("00",), ("100",), ("1",), ("50", "50")])
def test_invalid_region_space_is_rejected(regions: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="CORPUS_SCOPE_INVALID"):
        replace(scope(), regions=regions).validate(NOW)


def test_source_flags_unknown_type_and_live_day_cannot_be_upgraded() -> None:
    for selected in (
        replace(scope(), source_completeness="PASS"),
        replace(scope(), document_types=("invented",)),
        replace(scope(), first_day=date(2020, 1, 1)),
    ):
        with pytest.raises(ValueError, match="CORPUS_SCOPE_INVALID"):
            selected.validate(NOW)
    with pytest.raises(ValueError, match="CORPUS_DATE_NOT_COMPLETED"):
        replace(scope(), last_day=date(2026, 9, 28)).validate(NOW)


def test_parse_window_preserves_type_region_and_offset() -> None:
    key = "getDocsIP/PRIZ/01/2026-09-27+03:00/epNotificationCancelFailure"
    assert parse_date_window(key).window_key == key
    competition = "getDocsIP/PRIZ/50/2026-09-27+03:00/epNotificationEOK2020"
    assert parse_date_window(competition).document_type == "epNotificationEOK2020"
    assert (
        parse_date_window("getDocsIP/PRIZ/77/2026-09-27+03:00").document_type
        == "epNotificationEF2020"
    )
    with pytest.raises(ValueError, match="CORPUS_WINDOW_INVALID"):
        parse_date_window("getDocsIP/PRIZ/77/2026-09-27/10+03:00")


class Journal:
    storage = object()
    company_id = "tenant-a"
    actor_id = "corpus-worker"

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str | None]] = []

    def record(
        self,
        key: str,
        status: str,
        *,
        reason_code: str | None = None,
        source_response_sha256: str | None = None,
        variant_intake=None,
    ) -> None:
        self.records.append((key, status, reason_code or source_response_sha256))


KEYS = (
    "getDocsIP/PRIZ/50/2026-09-27+03:00",
    "getDocsIP/PRIZ/77/2026-09-27+03:00/epNotificationEOK2020",
)


def _ungated(monkeypatch: pytest.MonkeyPatch, keys: tuple[str, ...] = KEYS) -> None:
    monkeypatch.setattr(eis_corpus, "eligible_windows", lambda *_args, **_kwargs: keys)
    monkeypatch.setattr(eis_corpus, "resource_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(eis_corpus, "priority_requested", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(eis_corpus.asyncio, "sleep", AsyncMock())


def test_one_transport_instance_is_reused_across_two_atomic_windows(monkeypatch) -> None:
    _ungated(monkeypatch)
    shared = object()
    seen: list[tuple[str, object]] = []

    async def sync(_storage, _company, _actor, selection, _token, transport):
        seen.append((selection.window_key, transport))
        return SimpleNamespace(
            status="SYNCED",
            source_response_sha256="a" * 64,
            new_versions=1,
            new_events=0,
        )

    monkeypatch.setattr(eis_corpus, "sync_eis_window", sync)
    journal = Journal()
    result = asyncio.run(eis_corpus.run_corpus(journal, "secret", now=NOW, transport=shared))

    assert seen == [(KEYS[0], shared), (KEYS[1], shared)]
    assert result["attempted"] == result["synced"] == 2
    assert [record[1] for record in journal.records] == ["SYNCED", "SYNCED"]


def test_shared_transport_failure_stops_before_the_next_window(monkeypatch) -> None:
    _ungated(monkeypatch)
    sync = AsyncMock(side_effect=EisSyncError("SOURCE_TRANSPORT_FAILED"))
    monkeypatch.setattr(eis_corpus, "sync_eis_window", sync)
    journal = Journal()

    result = asyncio.run(eis_corpus.run_corpus(journal, "secret", now=NOW, transport=object()))

    assert sync.await_count == 1
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_TRANSPORT_FAILED"
    assert result["attempted"] == 1
    assert journal.records == [(KEYS[0], "FAILED", "SOURCE_TRANSPORT_FAILED")]


def test_rejected_window_reports_retention_failure_and_continues_without_admission(monkeypatch):
    _ungated(monkeypatch)
    sync = AsyncMock(
        side_effect=[
            EisRejectedWindowError("DUPLICATE_NOTICE_VERSION", "a" * 64, None, "FAILED"),
            SimpleNamespace(
                status="NO_DATA", source_response_sha256="b" * 64, new_versions=0, new_events=0
            ),
        ]
    )
    monkeypatch.setattr(eis_corpus, "sync_eis_window", sync)
    journal = Journal()
    journal.record = Mock()
    result = asyncio.run(
        eis_corpus.run_corpus(journal, "synthetic-secret", now=NOW, transport=object())
    )
    assert result["attempted"] == 2 and result["synced"] == result["new_versions"] == 0
    assert result["coverage"] == "UNKNOWN"
    assert result["rejected_windows"] == [
        {
            "window_key": KEYS[0],
            "reason": "DUPLICATE_NOTICE_VERSION",
            "source_response_sha256": "a" * 64,
            "retention_status": "UNAVAILABLE",
            "retention_reason": "RETENTION_UNAVAILABLE",
            "manifest_sha256": None,
            "audit_status": "FAILED",
            "conflict_diagnosis": {
                "status": "UNAVAILABLE",
                "coverage": "UNKNOWN",
                "audit_status": "NOT_REQUIRED",
            },
            "variant_intake": {
                "status": "NOT_ATTEMPTED",
                "coverage": "UNKNOWN",
                "stage": "PREREQUISITES",
                "reason": "PREREQUISITES_MISSING",
                "ledger_receipt_id": None,
                "ledger_audit_event_id": None,
                "projection": None,
            },
        }
    ]
    journal.record.assert_any_call(
        KEYS[0],
        "FAILED",
        reason_code="DUPLICATE_NOTICE_VERSION",
        source_response_sha256="a" * 64,
        variant_intake=None,
    )
    assert "synthetic-secret" not in str(result)


@pytest.mark.parametrize("replayed", [False, True])
def test_partial_projection_is_separate_from_completed_windows(monkeypatch, replayed):
    from procurement.sources.eis_variant_intake import EisVariantIntakeReport
    from procurement.storage.eis_notice_projection import EisNoticeProjectionReport

    _ungated(monkeypatch, KEYS[:1])
    projection = EisNoticeProjectionReport(
        batch_id="batch",
        receipt_id="receipt",
        archive_count=1,
        occurrence_count=3,
        pair_count=2,
        projected_count=1,
        replayed_count=0,
        held_count=1,
        replayed=replayed,
        audit_event_id="audit",
    )
    intake = EisVariantIntakeReport(
        status="PARTIAL",
        stage="COMPLETE",
        reason=None,
        ledger_receipt_id="receipt",
        ledger_audit_event_id="ledger-audit",
        projection=projection,
    )
    error = EisRejectedWindowError(
        "DUPLICATE_NOTICE_VERSION", "a" * 64, None, "RECORDED", variant_intake=intake
    )
    monkeypatch.setattr(eis_corpus, "sync_eis_window", AsyncMock(side_effect=error))
    journal = Journal()
    result = asyncio.run(eis_corpus.run_corpus(journal, "secret", now=NOW, transport=object()))
    assert result["partial_windows"] == 1 and result["synced"] == result["skipped"] == 0
    assert result["new_versions"] == (0 if replayed else 1)
    assert result["held_pairs"] == 1
    assert result["replayed_projection_batches"] == int(replayed)
    assert journal.records == [(KEYS[0], "FAILED", "DUPLICATE_NOTICE_VERSION")]
    assert result["coverage"] == "UNKNOWN"


def test_failed_automatic_intake_stops_corpus_with_original_source_reason(monkeypatch):
    from procurement.sources.eis_variant_intake import EisVariantIntakeReport

    _ungated(monkeypatch)
    intake = EisVariantIntakeReport(status="FAILED", stage="LEDGER", reason="DATABASE_FAILED")
    error = EisRejectedWindowError(
        "NOTICE_VERSION_CONFLICT", "a" * 64, None, "RECORDED", variant_intake=intake
    )
    sync = AsyncMock(side_effect=error)
    monkeypatch.setattr(eis_corpus, "sync_eis_window", sync)
    journal = Journal()
    result = asyncio.run(eis_corpus.run_corpus(journal, "secret", now=NOW, transport=object()))
    assert sync.await_count == 1 and result["status"] == "BLOCKED"
    assert result["reason"] == "DATABASE_FAILED" and result["partial_windows"] == 0
    assert journal.records[0][2] == "NOTICE_VERSION_CONFLICT"


@pytest.mark.parametrize("gate", ["priority", "resource"])
def test_pre_window_gates_do_not_call_the_source(monkeypatch, gate: str) -> None:
    monkeypatch.setattr(eis_corpus, "eligible_windows", lambda *_args, **_kwargs: KEYS)
    monkeypatch.setattr(
        eis_corpus,
        "priority_requested",
        lambda *_args, **_kwargs: gate == "priority",
    )
    resource = Mock(return_value="DATABASE_BUDGET_REACHED" if gate == "resource" else None)
    monkeypatch.setattr(eis_corpus, "resource_gate", resource)
    sync = AsyncMock()
    monkeypatch.setattr(eis_corpus, "sync_eis_window", sync)

    result = asyncio.run(eis_corpus.run_corpus(Journal(), "secret", now=NOW, transport=object()))

    sync.assert_not_awaited()
    assert result["attempted"] == 0
    assert result["reason"] == (
        "PRIORITY_REFRESH_REQUESTED" if gate == "priority" else "DATABASE_BUDGET_REACHED"
    )
    assert resource.call_count == (0 if gate == "priority" else 1)


def test_regional_request_before_first_window_prevents_source_and_journal(monkeypatch) -> None:
    monkeypatch.setattr(eis_corpus, "eligible_windows", lambda *_args, **_kwargs: KEYS)
    marker = object()
    monkeypatch.setattr(
        eis_corpus,
        "priority_requested",
        lambda path, **_kwargs: path is marker,
    )
    resource = Mock()
    monkeypatch.setattr(eis_corpus, "resource_gate", resource)
    sync = AsyncMock()
    monkeypatch.setattr(eis_corpus, "sync_eis_window", sync)
    journal = Journal()

    result = asyncio.run(
        eis_corpus.run_corpus(
            journal,
            "secret",
            now=NOW,
            priority_request=None,
            regional_request=marker,  # type: ignore[arg-type]
            transport=object(),
        )
    )

    assert result["reason"] == "REGIONAL_REFRESH_REQUESTED"
    assert result["attempted"] == 0 and journal.records == []
    sync.assert_not_awaited()
    resource.assert_not_called()


def test_regional_request_arriving_during_window_preserves_commit_and_stops_next(
    monkeypatch,
) -> None:
    monkeypatch.setattr(eis_corpus, "eligible_windows", lambda *_args, **_kwargs: KEYS)
    monkeypatch.setattr(eis_corpus, "resource_gate", lambda *_args, **_kwargs: None)
    checks = 0

    def requested(path, **_kwargs):
        nonlocal checks
        if path == "regional":
            checks += 1
            return checks > 1
        return False

    monkeypatch.setattr(eis_corpus, "priority_requested", requested)
    monkeypatch.setattr(eis_corpus.asyncio, "sleep", AsyncMock())
    sync = AsyncMock(
        return_value=SimpleNamespace(
            status="SYNCED",
            source_response_sha256="a" * 64,
            new_versions=1,
            new_events=0,
        )
    )
    monkeypatch.setattr(eis_corpus, "sync_eis_window", sync)
    journal = Journal()

    result = asyncio.run(
        eis_corpus.run_corpus(
            journal,
            "secret",
            now=NOW,
            regional_request="regional",  # type: ignore[arg-type]
            transport=object(),
        )
    )

    assert sync.await_count == 1 and result["attempted"] == result["synced"] == 1
    assert journal.records == [(KEYS[0], "SYNCED", "a" * 64)]
    assert result["reason"] == "REGIONAL_REFRESH_REQUESTED"


def test_request_marker_accepts_only_present_recent_nonfuture_file(tmp_path) -> None:
    marker = tmp_path / "regional.request"
    marker.write_text("")
    epoch = NOW.timestamp()
    os.utime(marker, (epoch - 600, epoch - 600))
    assert eis_corpus.priority_requested(marker, now=NOW)
    os.utime(marker, (epoch - 601, epoch - 601))
    assert not eis_corpus.priority_requested(marker, now=NOW)
    os.utime(marker, (epoch + 1, epoch + 1))
    assert not eis_corpus.priority_requested(marker, now=NOW)
    assert not eis_corpus.priority_requested(tmp_path / "missing", now=NOW)


def test_corpus_pass_closes_shared_transport_when_runner_fails(monkeypatch) -> None:
    shared = object()
    lifecycle: list[str] = []

    @asynccontextmanager
    async def session():
        lifecycle.append("entered")
        try:
            yield shared
        finally:
            lifecycle.append("closed")

    runner = AsyncMock(side_effect=RuntimeError("synthetic"))
    regional = eis_corpus.Path("/synthetic/eis-223-refresh.request")
    monkeypatch.setattr(eis_corpus_cli, "eis_browser_transport", session)
    monkeypatch.setattr(eis_corpus_cli, "run_corpus", runner)

    with pytest.raises(RuntimeError, match="synthetic"):
        asyncio.run(
            eis_corpus_cli._corpus_pass(
                Journal(),
                "secret",
                now=NOW,
                max_windows=2,
                max_database_bytes=100,
                min_free_bytes=10,
                priority_request=None,
                regional_request=regional,
            )
        )

    assert lifecycle == ["entered", "closed"]
    assert runner.await_args.kwargs["transport"] is shared
    assert runner.await_args.kwargs["regional_request"] == regional


def test_historical_retry_shared_sql_contract_is_latest_first_and_safe_date():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from procurement.storage.eis_sync_journal import latest_eis_attempts

    latest = latest_eis_attempts("tenant-test")
    statement = select(latest.c.window_key).where(
        eis_corpus.historical_source_retry_clause(latest, NOW)
    )
    compiled = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "DISTINCT ON (eis_sync_attempts.window_key)" in compiled
    assert "eis_sync_attempts.attempted_at DESC, eis_sync_attempts.attempt_id DESC" in compiled
    assert "eis_sync_attempts.company_id = 'tenant-test'" in compiled
    assert "CASE WHEN pg_input_is_valid" in compiled
    assert "SOURCE_TRANSPORT_FAILED" in compiled and "SOURCE_WSDL_UNAVAILABLE" in compiled
    assert "SERVICE_ERROR" in compiled and "PREPARING" in compiled
    assert "NO_DATA" not in compiled and "NOTICE_VERSION_CONFLICT" not in compiled


@pytest.mark.parametrize("new_count,other_count", [(36, 24), (6, 4), (1, 9), (9, 1), (1, 1)])
def test_daily_interleaving_preserves_selected_set_lane_order_and_old_anchor(
    new_count, other_count
):
    fresh = tuple(f"new-{i}" for i in range(new_count))
    other = tuple(f"old-{i}" for i in range(other_count))
    original = [other[0], fresh[0], *other[1:], *fresh[1:]]
    selected = eis_corpus._interleave_daily_first_attempts(original, fresh)
    assert selected[:2] == (other[0], fresh[0])
    assert len(selected) == len(set(selected)) == len(original)
    assert set(selected) == set(original)
    assert tuple(k for k in selected if k in fresh) == fresh
    assert tuple(k for k in selected if k in other) == other
    if new_count >= 4 and other_count >= 2:
        # A pass interrupted after six windows has four fresh first attempts,
        # while preserving the old anchor and another nonfresh eligible window.
        assert selected[:6] == (other[0], *fresh[:4], other[1])


def test_daily_interleaving_does_not_slow_an_already_fresh_prefix_without_retries():
    fresh = tuple(f"new-{i}" for i in range(36))
    original = ["old-anchor", *fresh, *(f"old-{i}" for i in range(23))]
    assert eis_corpus._interleave_daily_first_attempts(original, fresh) == tuple(original)
    assert all(k in fresh for k in original[1:37])
