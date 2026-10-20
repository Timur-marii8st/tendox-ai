"""Synthetic negative boundaries for truthful search measurements."""

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from procurement.sources.eis_search_benchmark import (
    BenchmarkItem,
    BenchmarkLabel,
    BenchmarkObservation,
    EvidenceRef,
    latency_summary,
    quality_summary,
    source_age_seconds,
    source_overlap,
)

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _observation(numbers=("0000000000000000001",), **kwargs):
    return BenchmarkObservation(
        company_id="tenant-a",
        run_id="synthetic",
        query_id="paper",
        query="бумага",
        source="LOCAL_INDEX",
        observed_at=NOW,
        status="SUCCEEDED",
        duration_ms="20",
        evidence=EvidenceRef(path="response.json", sha256="a" * 64, locator="matched"),
        raw_numbers=numbers,
        items=tuple(
            BenchmarkItem(
                purchase_number=number,
                title="Бумага",
                source_sha256="b" * 64,
                application_status="UNKNOWN",
            )
            for number in numbers
        ),
        **kwargs,
    )


def _label(number="0000000000000000001", **kwargs):
    return BenchmarkLabel(
        company_id="tenant-a",
        query_id="paper",
        purchase_number=number,
        source_sha256="b" * 64,
        verdict="RELEVANT",
        review_status="REVIEWED",
        reviewer="synthetic-reviewer",
        reason="Synthetic title evidence",
        evidence=EvidenceRef(path="response.json", sha256="a" * 64, locator="matched[0]"),
        **kwargs,
    )


def test_unjudged_results_and_provisional_labels_do_not_become_precision_pass():
    result = quality_summary(_observation(), ())
    assert result.precision_at_k is None and result.quality_status == "UNKNOWN"
    assert result.precision_lower_bound == Decimal("0")
    assert result.precision_upper_bound == Decimal("1")
    provisional = _label().model_copy(update={"review_status": "PROVISIONAL"})
    assert quality_summary(_observation(), (provisional,)).precision_at_k is None


def test_duplicates_unknowns_and_stale_versions_never_inflate_precision_or_recall():
    first, second = "0000000000000000001", "0000000000000000002"
    observation = _observation((first, first, second))
    labels = (_label(), _label(second).model_copy(update={"source_sha256": "c" * 64}))
    result = quality_summary(observation, labels)
    assert result.unique_returned_count == 2 and result.duplicate_count == 1
    assert result.judged_count == 1 and result.unjudged_count == 1
    assert result.precision_at_k is None
    assert result.precision_lower_bound == Decimal("0.5")
    assert result.known_reference_recall_at_k is None
    assert result.full_corpus_recall is None


def test_complete_judgements_only_prove_quality_of_that_returned_slice():
    first, second = "0000000000000000001", "0000000000000000002"
    labels = (_label(), _label(second).model_copy(update={"verdict": "IRRELEVANT"}))
    result = quality_summary(_observation((first, second)), labels)
    assert result.precision_at_k == Decimal("0.5")
    assert result.quality_status == "MEASURED_SLICE"
    assert result.full_corpus_recall is None


def test_missing_provenance_or_conflicting_duplicate_version_stays_unknown():
    without_evidence = _observation().model_copy(update={"evidence": None})
    assert quality_summary(without_evidence, (_label(),)).precision_at_k is None
    first = _observation().items[0]
    conflicting = _observation().model_copy(
        update={"items": (first, first.model_copy(update={"source_sha256": "c" * 64}))}
    )
    quality = quality_summary(conflicting, (_label(),))
    assert quality.precision_at_k is None
    assert quality.known_reference_recall_at_k is None


def test_label_tenant_or_conflicting_evidence_is_rejected():
    with pytest.raises(ValueError, match="LABEL_TENANT_MISMATCH"):
        quality_summary(_observation(), (_label().model_copy(update={"company_id": "tenant-b"}),))
    with pytest.raises(ValueError, match="LABEL_CONFLICT"):
        quality_summary(
            _observation(), (_label(), _label().model_copy(update={"verdict": "IRRELEVANT"}))
        )


def test_failed_timeouts_remain_visible_and_are_not_fast_successes():
    successful = _observation()
    timeout = successful.model_copy(update={"status": "FAILED", "duration_ms": Decimal("30000")})
    result = latency_summary((successful, timeout))
    assert result.success_count == 1 and result.failure_count == 1
    assert result.success_p95_ms == Decimal("20")
    assert result.failure_max_ms == Decimal("30000")
    assert latency_summary((timeout,)).success_p50_ms is None


def test_watermark_age_does_not_invent_timezone_or_freshness():
    assert source_age_seconds(NOW - timedelta(hours=2), NOW) == 7200
    assert source_age_seconds(NOW + timedelta(seconds=1), NOW) is None
    assert source_age_seconds(NOW.replace(tzinfo=None), NOW) is None
    assert source_age_seconds(None, NOW) is None
    with pytest.raises(ValidationError):
        BenchmarkObservation.model_validate(
            {
                **_observation().model_dump(),
                "observed_at": NOW.replace(tzinfo=None),
            }
        )


def test_cross_source_overlap_is_not_full_recall_or_comparable_scope():
    result = source_overlap(
        _observation(("0000000000000000001", "0000000000000000002")),
        _observation(("0000000000000000001",)),
    )
    assert result.shared_count == 1 and result.reference_unique_count == 2
    assert result.reference_id_overlap_fraction == Decimal("0.5")
    assert result.full_corpus_recall is None and result.scope_comparability == "UNKNOWN"
    with pytest.raises(ValueError, match="OBSERVATION_SCOPE_MISMATCH"):
        source_overlap(_observation(), _observation().model_copy(update={"company_id": "tenant-b"}))


def _runner():
    path = Path(__file__).resolve().parents[1] / "scripts" / "server-eis-query-benchmark.py"
    spec = importlib.util.spec_from_file_location("benchmark_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_timeout_circuit_stops_after_first_call_and_never_persists_secret(monkeypatch, tmp_path):
    runner = _runner()
    suite = tmp_path / "suite.json"
    suite.write_text(
        json.dumps(
            {
                "version": "eis-query-v1",
                "queries": [
                    {"id": f"q{n}", "query": "paper", "intent": "Synthetic paper query"}
                    for n in range(20)
                ],
            }
        )
    )
    calls = []

    def timeout(request):
        calls.append(request.url)
        raise httpx.ReadTimeout("SECRET upstream body", request=request)

    original = httpx.Client
    monkeypatch.setattr(
        runner.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(timeout),
            **kwargs,
        ),
    )
    monkeypatch.setattr(runner, "_token", lambda path: "synthetic-token")
    runner.run(suite, tmp_path / "runs", "http://api:8000", tmp_path / "absent.env", 3, False)
    assert len(calls) == 1
    report = next((tmp_path / "runs").rglob("report.json"))
    result = json.loads(report.read_text())
    assert result["local_latency"]["success_count"] == 0
    assert result["local_latency"]["failure_count"] == 1
    assert "SECRET" not in report.read_text() and "synthetic-token" not in report.read_text()


def test_evidence_path_escape_and_modified_bytes_are_rejected(tmp_path):
    runner = _runner()
    child = tmp_path / "run"
    child.mkdir()
    evidence_file = child / "response.json"
    evidence_file.write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="BENCHMARK_EVIDENCE_MISMATCH"):
        runner._verify_evidence(
            child, EvidenceRef(path="response.json", sha256="a" * 64, locator="row")
        )
    with pytest.raises(ValueError, match="BENCHMARK_EVIDENCE_MISMATCH"):
        runner._verify_evidence(
            child, EvidenceRef(path="../response.json", sha256="a" * 64, locator="row")
        )
