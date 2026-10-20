"""Obsolete attachment-cap recovery stays bounded and never invents completion."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import OperationalError

from procurement.sources import eis_attachment_recovery as subject
from procurement.sources.eis_feed_sync import EisHourSyncResult, EisSyncError

NOW = datetime(2026, 10, 5, tzinfo=UTC)
TOKEN = "11111111-1111-4111-8111-111111111111"
KEY = "getDocsIP/PRIZ/50/2026-09-25+03:00"


def candidate(key=KEY, attempt="original"):
    return subject.AttachmentRecoveryCandidate(
        window_key=key,
        original_attempt_id=attempt,
        original_attempted_at=NOW - timedelta(hours=25),
        original_source_response_sha256="a" * 64,
    )


@pytest.fixture
def setup(monkeypatch):
    journal = SimpleNamespace(
        storage=object(),
        company_id="tenant",
        actor_id="worker",
        record=Mock(return_value="new-attempt"),
    )
    plan = subject.AttachmentRecoveryPlan(
        company_id="tenant",
        checked_at=NOW,
        eligible_count=2,
        candidates=(
            candidate(),
            candidate("getDocsIP/PRIZ/77/2026-10-02/12+03:00/epNotificationEOK2020", "other"),
        ),
    )
    mocks = {}
    for name, result in [
        ("read_attachment_recovery_plan", plan),
        ("resource_gate", None),
        ("_recheck", None),
        ("_checkpoint", True),
    ]:
        mocks[name] = Mock(return_value=result)
        monkeypatch.setattr(subject, name, mocks[name])
    sync = AsyncMock(
        return_value=EisHourSyncResult(
            KEY, "SYNCED", new_versions=2, source_response_sha256="b" * 64
        )
    )
    monkeypatch.setattr(subject, "sync_eis_window", sync)
    monkeypatch.setattr(subject.asyncio, "sleep", AsyncMock())
    return journal, sync, mocks


def run(journal, **kwargs):
    return asyncio.run(
        subject.run_attachment_recovery(journal, TOKEN, now=NOW, transport=object(), **kwargs)
    )


@pytest.mark.parametrize(
    "key", [KEY, "getDocsIP/PRIZ/77/2026-10-02/12+03:00/epNotificationEOK2020"]
)
def test_date_and_hour_exact_round_trip(key):
    assert subject.parse_attachment_recovery_window(key).window_key == key


@pytest.mark.parametrize(
    "key",
    [
        KEY.replace("+03", "+04"),
        KEY.replace("09-25", "99-99"),
        KEY.replace("+03", "/24+03"),
        KEY.replace("/50/", "/00/"),
        KEY + "/unknown",
    ],
)
def test_invalid_source_coordinates_are_rejected(key):
    with pytest.raises(ValueError, match="ATTACHMENT_RECOVERY_WINDOW_INVALID"):
        subject.parse_attachment_recovery_window(key)


def test_config_rejected_before_plan_source_or_journal(setup):
    journal, sync, mocks = setup
    with pytest.raises(ValueError, match="ATTACHMENT_RECOVERY_CONFIG_INVALID"):
        asyncio.run(subject.run_attachment_recovery(journal, "secret", now=NOW, transport=object()))
    mocks["read_attachment_recovery_plan"].assert_not_called()
    sync.assert_not_called()
    journal.record.assert_not_called()


@pytest.mark.parametrize("reason", ["SOURCE_CANDIDATE_CHANGED", "SOURCE_CANDIDATE_COMPLETED"])
def test_changed_candidate_stops_without_attempt(setup, reason):
    journal, sync, mocks = setup
    mocks["_recheck"].return_value = reason
    report = run(journal)
    assert report.status == "BLOCKED" and report.reason == reason and report.attempted == 0
    assert report.outcomes[0].outcome == "NOT_ATTEMPTED"
    assert report.outcomes[0].new_attempt_id is None
    sync.assert_not_called()
    journal.record.assert_not_called()


@pytest.mark.parametrize("checkpoint", [True, False])
def test_skipped_requires_actual_checkpoint(setup, checkpoint):
    journal, sync, mocks = setup
    sync.return_value = EisHourSyncResult(KEY, "SKIPPED")
    mocks["_checkpoint"].return_value = checkpoint
    report = run(journal)
    assert report.outcomes[0].canonical_checkpoint is checkpoint
    assert report.outcomes[0].outcome == ("SKIPPED" if checkpoint else "FAILED")
    if not checkpoint:
        assert report.reason == "CANONICAL_CHECKPOINT_MISSING" and sync.call_count == 1


@pytest.mark.parametrize("status", ["NO_DATA", "PREPARING", "SERVICE_ERROR"])
def test_incomplete_outcomes_never_claim_checkpoint(setup, status):
    journal, sync, mocks = setup
    sync.return_value = EisHourSyncResult(KEY, status, source_response_sha256="b" * 64)
    report = run(journal)
    assert not any(item.canonical_checkpoint for item in report.outcomes)
    mocks["_checkpoint"].assert_not_called()
    assert report.coverage == "UNKNOWN"
    if status == "SERVICE_ERROR":
        assert report.reason == "SOURCE_SERVICE_ERROR" and sync.call_count == 1


def test_source_failure_preserves_original_evidence_and_stops(setup):
    journal, sync, _ = setup
    sync.side_effect = EisSyncError("SOURCE_TRANSPORT_FAILED")
    report = run(journal)
    assert report.attempted == 1 and report.reason == "SOURCE_TRANSPORT_FAILED"
    assert report.outcomes[0].candidate.original_attempt_id == "original"
    assert report.outcomes[0].new_attempt_id == "new-attempt"
    journal.record.assert_called_once_with(
        KEY,
        "FAILED",
        reason_code="SOURCE_TRANSPORT_FAILED",
        source_response_sha256=None,
        variant_intake=None,
    )


def test_failed_journal_stops_without_fabricated_attempt_id(setup):
    journal, sync, _ = setup
    journal.record.side_effect = OperationalError("secret SQL", {}, RuntimeError("secret DSN"))
    report = run(journal)
    assert report.reason == "DATABASE_FAILED" and report.attempted == 1
    assert report.outcomes[0].new_attempt_id is None
    assert "secret" not in report.model_dump_json()
    assert sync.call_count == 1


def test_time_budget_stops_next_operation_without_journal_timeout(setup, monkeypatch):
    journal, sync, _ = setup
    # A private clock namespace leaves the asyncio clock untouched.
    monkeypatch.setattr(subject, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 0, 601])))
    report = run(journal)
    assert report.reason == "RECOVERY_TIME_BUDGET_REACHED" and report.attempted == 1
    assert report.outcomes[-1].outcome == "NOT_ATTEMPTED"
    assert sync.call_count == journal.record.call_count == 1


@pytest.mark.parametrize("partial_status", ["PARTIAL", "FAILED"])
def test_variant_intake_remains_failed_without_canonical_checkpoint(setup, partial_status):
    from procurement.sources.eis_feed_sync import EisRejectedWindowError
    from procurement.sources.eis_variant_intake import EisVariantIntakeReport
    from procurement.storage.eis_notice_projection import EisNoticeProjectionReport

    journal, sync, mocks = setup
    if partial_status == "PARTIAL":
        intake = EisVariantIntakeReport(
            status="PARTIAL",
            stage="COMPLETE",
            reason=None,
            ledger_receipt_id="receipt",
            ledger_audit_event_id="ledger-audit",
            projection=EisNoticeProjectionReport(
                batch_id="batch",
                receipt_id="receipt",
                archive_count=1,
                occurrence_count=3,
                pair_count=2,
                projected_count=1,
                replayed_count=0,
                held_count=1,
                replayed=False,
                audit_event_id="projection-audit",
            ),
        )
    else:
        intake = EisVariantIntakeReport(
            status="FAILED",
            stage="PROJECTION",
            reason="DATABASE_FAILED",
            ledger_receipt_id="receipt",
            ledger_audit_event_id="ledger-audit",
        )
    sync.side_effect = EisRejectedWindowError(
        "NOTICE_VERSION_CONFLICT", "b" * 64, None, "RECORDED", variant_intake=intake
    )
    report = run(journal)
    assert all(
        item.outcome == "FAILED" and not item.canonical_checkpoint for item in report.outcomes
    )
    assert report.outcomes[0].variant_intake == intake
    assert report.outcomes[0].source_response_sha256 == "b" * 64
    assert report.outcomes[0].new_versions == (1 if partial_status == "PARTIAL" else 0)
    mocks["_checkpoint"].assert_not_called()
    if partial_status == "FAILED":
        assert report.reason == "DATABASE_FAILED" and report.attempted == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome": "FAILED", "reason": None},
        {"outcome": "NO_DATA", "source_response_sha256": None},
        {"outcome": "SYNCED", "canonical_checkpoint": True, "source_response_sha256": None},
        {"outcome": "FAILED", "reason": "SOURCE_FAILURE", "canonical_checkpoint": True},
    ],
)
def test_outcome_model_rejects_missing_or_false_evidence(changes):
    with pytest.raises(ValueError):
        subject.AttachmentRecoveryOutcome(candidate=candidate(), **changes)


def test_run_model_rejects_duplicate_and_unplanned_outcomes(setup):
    journal, _, _ = setup
    report = run(journal)
    for outcomes in (
        (report.outcomes[0], report.outcomes[0]),
        (report.outcomes[1], report.outcomes[0]),
    ):
        payload = report.model_dump()
        payload["outcomes"] = [item.model_dump() for item in outcomes]
        with pytest.raises(ValueError, match="ATTACHMENT_RECOVERY_RUN_INVALID"):
            subject.AttachmentRecoveryRunReport.model_validate(payload)
