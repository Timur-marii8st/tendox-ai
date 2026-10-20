"""Bounded queue step; failures cannot reveal raw transport exception secrets."""

from datetime import datetime

import pytest

from procurement.sources import eis_223_document_worker as worker
from procurement.sources.eis_223_documents import Notice223DocumentRef

REF = Notice223DocumentRef(
    purchase_number="32600000001", version_number=2, notice_xml_sha256="a" * 64
)


@pytest.fixture
def calls(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "resource_gate", lambda *a, **k: None)
    monkeypatch.setattr(worker, "next_document223", lambda *a: (REF, "A" * 32))
    monkeypatch.setattr(worker, "collect_document223", lambda *a, **k: calls.append("collect"))
    monkeypatch.setattr(worker, "record_document223_attempt", lambda *a, **k: calls.append(a[4:6]))
    return calls


@pytest.mark.parametrize("reason", ["DATABASE_BUDGET_REACHED", "DISK_RESERVE_REACHED"])
def test_resource_guard_stops_before_queue_or_download(monkeypatch, calls, reason):
    monkeypatch.setattr(worker, "resource_gate", lambda *a, **k: reason)
    monkeypatch.setattr(worker, "next_document223", lambda *a: pytest.fail("unexpected queue"))
    result = worker.run_document223_step(object(), "tenant-a", actor_id="worker")
    assert result.status == "BLOCKED" and result.attempted == 0 and not calls


def test_completed_or_deferred_queue_never_calls_collector(monkeypatch, calls):
    monkeypatch.setattr(worker, "next_document223", lambda *a: None)
    assert worker.run_document223_step(object(), "tenant-a", actor_id="worker").attempted == 0
    assert not calls


def test_success_runs_exactly_one_file_and_leaves_eligibility_unknown(calls):
    result = worker.run_document223_step(object(), "tenant-a", actor_id="worker")
    assert (
        result.status == "PROCESSED" and result.attempted == 1 and result.eligibility == "UNKNOWN"
    )
    assert calls == ["collect", ("RECEIVED", None)]


@pytest.mark.parametrize(
    "error,expected",
    [
        ("ROBOTS_CRAWL_DELAY", "ROBOTS_CRAWL_DELAY"),
        ("secret=token-and-password", "DOCUMENT_223_UNAVAILABLE"),
    ],
)
def test_failure_code_is_safe_and_journaled(monkeypatch, calls, error, expected):
    def fail(*a, **k):
        raise ValueError(error)

    monkeypatch.setattr(worker, "collect_document223", fail)
    result = worker.run_document223_step(object(), "tenant-a", actor_id="worker")
    assert result.reason == expected and result.status == "BLOCKED"
    assert calls == [("FAILED", expected)] and "password" not in result.model_dump_json()


def test_naive_clock_stops_before_resource_guard(monkeypatch):
    monkeypatch.setattr(worker, "resource_gate", lambda *a, **k: pytest.fail("unexpected DB"))
    with pytest.raises(ValueError, match="DOCUMENT_WORKER_INPUT_INVALID"):
        worker.run_document223_step(
            object(), "tenant-a", actor_id="worker", now=datetime(2026, 10, 2)
        )
