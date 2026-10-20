"""Gap diagnostics never imply source completeness or authorize broad retries."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from procurement.storage.eis_gap_status import (
    EisGapReasonGroup,
    EisGapSample,
    EisGapStatus,
    GapCategory,
    gap_category,
    read_eis_gap_status,
)

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("outcome", "code", "category"),
    (
        (None, None, "UNATTEMPTED"),
        ("NO_DATA", "SOURCE_TRANSPORT_FAILED", "NO_DATA"),
        ("FAILED", "SOURCE_TRANSPORT_FAILED", "SOURCE_RETRY"),
        ("FAILED", "SOURCE_WSDL_UNAVAILABLE", "SOURCE_RETRY"),
        ("SERVICE_ERROR", None, "SOURCE_RETRY"),
        ("PREPARING", None, "SOURCE_RETRY"),
        ("FAILED", "SOURCE_TRANSPORT_FAILED_OTHER", "UNKNOWN"),
        ("FAILED", "SOURCE_FAILURE", "UNKNOWN"),
        ("FAILED", "ATTACHMENT_REFERENCE_INVALID", "PARSER_REVIEW"),
        ("FAILED", "ATTACHMENT_COUNT_LIMIT", "PARSER_REVIEW"),
        ("FAILED", "MEMBER_UNSUPPORTED", "PARSER_REVIEW"),
        ("FAILED", "CHARACTERISTIC_RANGE_STRUCTURE_UNSUPPORTED", "PARSER_REVIEW"),
        ("FAILED", "CHARACTERISTIC_RANGE_STRUCTURE_UNSUPPORTED_OTHER", "UNKNOWN"),
        ("FAILED", "ARCHIVE_WINDOW_EXPANSION_LIMIT", "RESOURCE_REVIEW"),
        ("FAILED", "NOTICE_VERSION_CONFLICT", "VARIANT_REVIEW"),
        ("FAILED", "PREPARED_REQUEST_MISMATCH", "SOURCE_CONTRACT_REVIEW"),
        ("SYNCED", None, "UNKNOWN"),
    ),
)
def test_exact_latest_state_category(outcome, code, category):
    assert gap_category(outcome, code) == category


def report(**changes) -> EisGapStatus:
    return EisGapStatus.model_validate(
        {
            "company_id": "tenant-a",
            "checked_at": NOW,
            "status": "OBSERVED",
            "planned_targets": 2,
            "completed_targets": 1,
            "pending_targets": 1,
            "unattempted_targets": 1,
            "no_data_targets": 0,
            "historical_source_retry_due": 0,
            "transport_only_targets": 0,
            "invalid_source_coordinates": 0,
            "candidate_region_codes": 1,
            "oldest_source_day": "2026-09-17",
            "newest_source_day": "2026-09-17",
            "groups": (
                EisGapReasonGroup(
                    category=GapCategory.UNATTEMPTED,
                    outcome=None,
                    reason_code=None,
                    targets=1,
                    oldest_source_day="2026-09-17",
                    newest_source_day="2026-09-17",
                    oldest_attempt_at=None,
                    newest_attempt_at=None,
                ),
            ),
            "samples": (
                EisGapSample(
                    window_key="getDocsIP/PRIZ/77/2026-09-17+03:00",
                    planned_at=NOW,
                    source_day="2026-09-17",
                    outcome=None,
                    reason_code=None,
                    attempted_at=None,
                    attempt_id=None,
                    source_response_sha256=None,
                    historical_source_retry_due=False,
                ),
            ),
            "sample_limit": 20,
            "samples_truncated": False,
            **changes,
        }
    )


def test_queue_observation_and_invalid_coordinates_never_become_full_coverage():
    observed = report()
    assert observed.coverage == observed.freshness == "UNKNOWN"
    assert observed.source_requests == observed.database_writes == 0
    unknown = report(status="UNKNOWN", invalid_source_coordinates=1)
    assert unknown.coverage == "UNKNOWN"
    with pytest.raises(ValidationError):
        report(coverage="PASS")


@pytest.mark.parametrize(
    "changes",
    (
        {"completed_targets": 2},
        {"groups": ()},
        {"samples": ()},
        {"unattempted_targets": 0},
        {"no_data_targets": 1},
        {"samples_truncated": True},
        {"historical_source_retry_due": 2},
        {"transport_only_targets": 2},
        {"invalid_source_coordinates": 1},
        {"checked_at": NOW.replace(tzinfo=None)},
    ),
)
def test_inconsistent_totals_or_naive_timestamp_rejected(changes):
    with pytest.raises(ValidationError):
        report(**changes)


@pytest.mark.parametrize(
    ("company", "now", "limit"),
    ((" ", NOW, 20), ("a", NOW.replace(tzinfo=None), 20), ("a", NOW, 0), ("a", NOW, 101)),
)
def test_invalid_request_fails_before_database_access(company, now, limit):
    with pytest.raises(ValueError, match="GAP_STATUS_REQUEST_INVALID"):
        read_eis_gap_status(object(), company, now=now, sample_limit=limit)


def test_cli_gap_status_needs_no_source_token_and_disposes_engine(monkeypatch, capsys):
    from procurement import eis_corpus_cli as cli

    disposed = []
    engine = SimpleNamespace(dispose=lambda: disposed.append(True))
    monkeypatch.setenv("DATABASE_URL", "unused-test-url")
    monkeypatch.delenv("EIS_GETDOCS_IP_TOKEN", raising=False)
    monkeypatch.setattr(cli, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(cli, "PostgresStorage", lambda e: object())
    monkeypatch.setattr(cli, "read_eis_gap_status", lambda *a, **kw: report())
    assert cli.main(["gap-status", "--company-id", "tenant-a", "--actor-id", "observer"]) == 0
    assert '"coverage":"UNKNOWN"' in capsys.readouterr().out
    assert disposed == [True]
