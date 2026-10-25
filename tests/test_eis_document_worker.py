"""Worker source holds precede cached analysis and survive receipt races."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from procurement.sources import eis_document_worker as worker

NOW = datetime(2026, 10, 4, tzinfo=UTC)
HOLD = "NOTICE_VARIANT_REVIEW_REQUIRED"


def row(number="0373100047426001450"):
    return dict(
        purchase_number=number, version_number=1, notice_xml_sha256="a" * 64, created_at=NOW
    )


class Storage:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.statements = []

    @contextmanager
    def transaction(self, *args, **kwargs):
        yield self

    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: next(self.pages)))


@pytest.fixture
def deps(monkeypatch):
    gate = SimpleNamespace(blocked_reasons=())
    document = SimpleNamespace(
        filename="document.pdf",
        reference_status="PASS",
        fetch_status="RECEIVED",
        reasons=("ANALYSIS_NOT_AVAILABLE",),
        content_uid="doc",
        source_url="https://example.invalid/doc",
        observed_at=None,
    )
    report = SimpleNamespace(
        version_status="CURRENT_KNOWN_VERSION",
        documents=[document],
        read_gate=gate,
        analyzer_version="test",
    )
    mocks = {}
    for name, result in [
        ("resource_gate", None),
        ("assert_notice_source_usable", None),
        ("get_document_status", report),
        ("document_read_gate", gate),
        ("reanalyze_received_document", True),
        ("record_document_outcome", None),
    ]:
        mocks[name] = Mock(return_value=result)
        monkeypatch.setattr(worker, name, mocks[name])
    return SimpleNamespace(**mocks, document=document, report=report)


def run(storage, **kwargs):
    return worker.run_document_step(storage, "tenant", actor_id="worker", now=NOW, **kwargs)


def test_held_cached_job_audited_without_analysis_and_other_job_advances(deps):
    storage = Storage([[row()], [row("0373100047426001451")]])
    result = run(storage)
    assert result["status"] == "REANALYZED"
    assert result["purchase_number"] == "0373100047426001451"
    deps.document_read_gate.assert_called_once()
    deps.reanalyze_received_document.assert_called_once()
    sql = str(storage.statements[1])
    assert "NOT (" in sql and "eis_notice_variants" in sql and "LIMIT" in sql


def test_archived_cached_analysis_preserves_deadline_behavior(deps):
    deps.report.read_gate.blocked_reasons = ("DEADLINE_EXPIRED",)
    assert run(Storage([[], [row()]]))["status"] == "REANALYZED"
    deps.assert_notice_source_usable.assert_called_once()
    deps.document_read_gate.assert_not_called()


@pytest.mark.parametrize(
    "stage", ["assert_notice_source_usable", "get_document_status", "reanalyze_received_document"]
)
def test_hold_arriving_before_cached_analysis_skips_safely(deps, stage):
    getattr(deps, stage).side_effect = ValueError(HOLD)
    result = run(Storage([[], [row()], []]))
    assert result["status"] == "IDLE"
    assert result["skip_reasons"] == {HOLD: 1}
    deps.record_document_outcome.assert_not_called()
    deps.document_read_gate.assert_called_once()
    if stage == "assert_notice_source_usable":
        deps.get_document_status.assert_not_called()


def test_status_read_hold_after_successful_assert_advances_to_other_job(deps):
    deps.get_document_status.side_effect = [ValueError(HOLD), deps.report]
    download = Mock()
    result = run(Storage([[], [row(), row("0373100047426001451")]]), downloader=download)
    assert result["status"] == "REANALYZED"
    assert result["purchase_number"] == "0373100047426001451"
    assert deps.assert_notice_source_usable.call_count == 2
    deps.document_read_gate.assert_called_once()
    assert deps.document_read_gate.call_args.args[2].purchase_number == row()["purchase_number"]
    deps.reanalyze_received_document.assert_called_once()
    assert (
        deps.reanalyze_received_document.call_args.args[2].purchase_number
        == result["purchase_number"]
    )
    download.assert_not_called()
    deps.record_document_outcome.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["SOURCE_BUSY", "DOCUMENT_BYTES_RESOURCE_LIMIT", "DOCUMENT_CONTENT_CONFLICT"]
)
def test_hold_before_failure_record_is_blocked_without_unhandled_error(deps, failure):
    deps.document.fetch_status = "PENDING"
    deps.document.reasons = ()
    if failure == "SOURCE_BUSY":
        download = Mock(side_effect=worker.EisPublicError(failure))
        deps.record_document_outcome.side_effect = ValueError(HOLD)
        expected_calls = 1
    else:
        download = Mock(return_value=b"document")
        deps.record_document_outcome.side_effect = [ValueError(failure), ValueError(HOLD)]
        expected_calls = 2
    result = run(Storage([[], [row()]]), downloader=download)
    assert result == {"status": "BLOCKED", "reason": HOLD, "attempted": 1}
    assert deps.record_document_outcome.call_count == expected_calls
    assert deps.record_document_outcome.call_args.kwargs["failure_code"] == failure
    assert deps.document_read_gate.call_count == 2  # Initial gate and late-hold audit.
    deps.reanalyze_received_document.assert_not_called()


def test_late_receipt_hold_never_retries_as_failed(deps):
    deps.document.fetch_status = "PENDING"
    deps.document.reasons = ()
    deps.record_document_outcome.side_effect = ValueError(HOLD)
    download = Mock(return_value=b"document")
    result = run(Storage([[], [row()]]), downloader=download)
    assert result["status"] == "BLOCKED" and result["reason"] == HOLD
    assert result["attempted"] == 1
    deps.record_document_outcome.assert_called_once()
    assert "failure_code" not in deps.record_document_outcome.call_args.kwargs


def test_probe_held_cached_does_not_audit_or_analyze(deps):
    result = run(Storage([[row()], []]), probe_only=True)
    assert result["attempted"] == 0 and result["skip_reasons"] == {HOLD: 1}
    deps.document_read_gate.assert_not_called()
    deps.reanalyze_received_document.assert_not_called()


@pytest.mark.parametrize("probe", [False, True])
def test_slash_label_blocks_before_download_and_probe_has_no_writes(deps, probe):
    deps.document.filename = "Часть 1/2.pdf"
    deps.document.fetch_status = "PENDING"
    deps.document.reasons = ()
    download = Mock(side_effect=AssertionError("unsafe name must not be downloaded"))
    result = run(Storage([[], [row()]]), downloader=download, probe_only=probe)
    assert result == {
        "status": "BLOCKED",
        "reason": "ATTACHMENT_FILENAME_REQUIRES_REVIEW",
        "attempted": 0,
    }
    download.assert_not_called()
    deps.reanalyze_received_document.assert_not_called()
    if probe:
        deps.record_document_outcome.assert_not_called()
        deps.document_read_gate.assert_not_called()
    else:
        deps.record_document_outcome.assert_called_once()
        assert deps.record_document_outcome.call_args.kwargs["failure_code"] == result["reason"]


def test_filename_review_failure_respects_late_source_hold(deps):
    deps.document.filename = "Часть 1/2.pdf"
    deps.document.fetch_status = "PENDING"
    deps.document.reasons = ()
    deps.record_document_outcome.side_effect = ValueError(HOLD)
    download = Mock()
    result = run(Storage([[], [row()]]), downloader=download)
    assert result == {"status": "BLOCKED", "reason": HOLD, "attempted": 0}
    download.assert_not_called()


@pytest.mark.parametrize("probe", [False, True])
def test_ambiguous_attachment_never_downloads(deps, probe):
    deps.document.reference_status = "UNKNOWN"
    deps.document.fetch_status = "PENDING"
    deps.document.reasons = ()
    download = Mock(side_effect=AssertionError("ambiguous reference"))
    result = run(Storage([[], [row()]]), downloader=download, probe_only=probe)
    assert result == {
        "status": "BLOCKED",
        "reason": "ATTACHMENT_REFERENCE_REQUIRES_REVIEW",
        "attempted": 0,
    }
    download.assert_not_called()
    deps.reanalyze_received_document.assert_not_called()
    if probe:
        deps.record_document_outcome.assert_not_called()
    else:
        assert deps.record_document_outcome.call_args.kwargs["failure_code"] == result["reason"]
