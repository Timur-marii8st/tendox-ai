"""Synthetic acceptance for the offline, evidence-bound search benchmark v2."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from procurement.sources.eis_search_benchmark_v2 import (
    BenchmarkCase,
    BenchmarkLabel,
    BenchmarkMethod,
    BenchmarkSuite,
    CorpusConsistency,
    CorpusManifest,
    CorpusPartition,
    CorpusRecord,
    EvidenceRef,
    ExactResultId,
    FilterSpec,
    LabelSet,
    Observation,
    ObservationSet,
    PackageManifest,
    PlannedAttempt,
    PublicationInterval,
    SearchScope,
    calculate_report,
    canonical_digest,
    digest_bytes,
    load_package,
    ordered_digest,
)

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
TENANT = "synthetic-tenant"
CASE_ID = "synthetic-paper"


def identity(number: str = "0123456789012345678", *, version: int = 1, sha: str = "a" * 64):
    return ExactResultId(
        law="44", purchase_number=number, version_number=version, source_xml_sha256=sha
    )


def write_json(root: Path, name: str, value: object, locator: str = "/") -> EvidenceRef:
    path = root / name
    payload = (
        json.dumps(
            value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode()
        + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return EvidenceRef(
        path=path.relative_to(root).as_posix(),
        sha256=digest_bytes(payload),
        locator=locator,
        max_bytes=max(1, len(payload)),
    )


def default_scope(*, unsupported: bool = False, continuation: bool = False) -> SearchScope:
    return SearchScope(
        version="eis-search-scope-v2",
        law="44",
        endpoint="/v1/tender-discovery/eis-index",
        measurement_boundary="HTTP_READ_ONLY_ENDPOINT",
        boundary_notes="Read-only endpoint; excludes UI, queueing, ingestion and public EIS.",
        search_scope="NOT_EXPIRED_OR_UNKNOWN",
        region_mode="UNBOUNDED",
        region_codes=(),
        region_source="No HTTP region filter.",
        publication_interval=PublicationInterval(mode="UNBOUNDED"),
        clock=NOW,
        deadline_mode="NOT_EXPIRED_OR_UNKNOWN",
        filters=(FilterSpec(name="region", value="77", application="UNSUPPORTED"),)
        if unsupported
        else (FilterSpec(name="search_scope", value="NOT_EXPIRED_OR_UNKNOWN", application="HTTP"),),
        page_size=100,
        continuation_policy="UNTIL_END_OR_PAGE_BUDGET" if continuation else "FIRST_PAGE_ONLY",
    )


def plan(repeats: int) -> tuple[PlannedAttempt, ...]:
    return tuple(
        PlannedAttempt(
            attempt_id=f"attempt-{repeat}",
            repeat=repeat,
            kind="FIRST_PAGE",
            page_index=1,
        )
        for repeat in range(1, repeats + 1)
    )


def observation_spec(
    repeat: int,
    outcome: str = "SUCCEEDED",
    duration: str = "1",
    results: tuple[ExactResultId, ...] = (),
    **extra: object,
) -> dict[str, object]:
    return {
        "attempt_id": f"attempt-{repeat}",
        "repeat": repeat,
        "kind": "FIRST_PAGE",
        "page_index": 1,
        "outcome": outcome,
        "duration": duration,
        "results": results,
        **extra,
    }


def build_package(
    root: Path,
    *,
    plans: tuple[PlannedAttempt, ...] | None = None,
    observation_specs: tuple[dict[str, object], ...] = (),
    records: tuple[ExactResultId, ...] = (),
    label_specs: tuple[dict[str, object], ...] = (),
    unsupported: bool = False,
    bad_response_locator: bool = False,
    row_cap: int = 100,
    dataset_kind: str = "SYNTHETIC",
    review_binding_overrides: dict[str, object] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    plans = plans or plan(max((int(item["repeat"]) for item in observation_specs), default=1))
    repeats = max(item.repeat for item in plans)
    scope = default_scope(
        unsupported=unsupported,
        continuation=any(item.kind == "CONTINUATION" for item in plans),
    )
    intent = "Synthetic paper supply intent"
    case = BenchmarkCase(
        case_id=CASE_ID,
        order=1,
        kind="UNSUPPORTED" if unsupported else "MEASURED",
        query="бумага",
        intent=intent,
        intent_sha256=digest_bytes(intent.encode()),
        relevance_criterion="Exact saved-version evidence reviewed against the synthetic intent.",
        scope=scope,
        scope_sha256=canonical_digest(scope),
        repeats=repeats,
        timeout_ms=Decimal("30000"),
        warmup_count=0,
        page_budget=max((item.page_index or 1 for item in plans), default=1),
        attempts=plans,
    )
    suite = BenchmarkSuite(
        version="eis-search-suite-v2", tenant=TENANT, suite_id="synthetic-suite", cases=(case,)
    )
    suite_ref = write_json(root, "suite.json", suite)
    method = BenchmarkMethod(
        version="eis-search-method-v2",
        method_id="synthetic-method",
        dataset_kind=dataset_kind,
        instrument_author="instrument-author",
        max_artifact_bytes=4 * 1024 * 1024,
        max_observations=1000,
        max_labels=1000,
        target_all_outcome_p95_ms=Decimal("5000"),
        target_precision_at_10=Decimal("0.90"),
        target_known_reference_recall=Decimal("0.95"),
    )
    method_ref = write_json(root, "method.json", method)
    proof = {
        "tenant": TENANT,
        "capture_id": "synthetic-capture",
        "captured_at": NOW.isoformat(),
        "complete": True,
        "partial": False,
        "repeatable_read": True,
        "tenant_rls_bound": True,
        "single_clock": True,
    }
    proof_ref = write_json(
        root,
        "proof.json",
        {"version": "eis-search-consistency-proof-v2", "proof": proof},
        "/proof",
    )
    corpus_records = tuple(
        sorted(
            (
                CorpusRecord(
                    identity=item,
                    ingested_at=NOW - timedelta(minutes=1),
                    source_identity_sha256="b" * 64,
                    eligible_case_ids=(CASE_ID,),
                )
                for item in records
            ),
            key=lambda item: (
                item.identity.law,
                item.identity.purchase_number,
                item.identity.version_number,
                item.identity.source_xml_sha256,
            ),
        )
    )
    rows44 = tuple(item for item in corpus_records if item.identity.law == "44")
    rows223 = tuple(item for item in corpus_records if item.identity.law == "223")
    corpus = CorpusManifest(
        version="eis-search-corpus-v2",
        tenant=TENANT,
        capture_id="synthetic-capture",
        captured_at=NOW,
        selection="Synthetic complete exact-version manifest.",
        tables_and_fields=("synthetic.identity",),
        schema_revision="synthetic-head",
        database_runtime="synthetic-postgresql",
        source_release_sha256="c" * 64,
        lock_sha256="d" * 64,
        consistency=CorpusConsistency(
            mode="IMMUTABLE_COPY",
            complete=True,
            partial=False,
            repeatable_read=True,
            tenant_rls_bound=True,
            single_clock=True,
            proof=proof_ref,
        ),
        partitions=(
            CorpusPartition(
                law="44",
                row_count=len(rows44),
                row_cap=row_cap,
                ordered_records_sha256=ordered_digest(rows44),
            ),
            CorpusPartition(
                law="223",
                row_count=len(rows223),
                row_cap=100,
                ordered_records_sha256=ordered_digest(rows223),
            ),
        ),
        records=corpus_records,
    )
    corpus_ref = write_json(root, "corpus.json", corpus)
    observations: list[Observation] = []
    for index, spec in enumerate(observation_specs):
        outcome = str(spec["outcome"])
        result_items = tuple(spec.get("results", ()))
        evidence = None
        response_bytes = 0
        if outcome == "SUCCEEDED":
            evidence_results = tuple(spec.get("evidence_results", result_items))
            response_ref = write_json(
                root,
                f"responses/{index}.json",
                {
                    "version": "eis-search-response-evidence-v2",
                    "results": [item.model_dump(mode="json") for item in evidence_results],
                },
                "/missing" if bad_response_locator else "/results",
            )
            evidence = response_ref
            response_bytes = (root / response_ref.path).stat().st_size
        kind = str(spec.get("kind", "FIRST_PAGE"))
        page_index = spec.get("page_index", 1)
        observations.append(
            Observation(
                attempt_id=str(spec["attempt_id"]),
                tenant=str(spec.get("tenant", TENANT)),
                case_id=CASE_ID,
                repeat=int(spec["repeat"]),
                kind=kind,
                page_index=page_index,
                suite_sha256=str(spec.get("suite_sha256", suite_ref.sha256)),
                corpus_sha256=str(spec.get("corpus_sha256", corpus_ref.sha256)),
                method_sha256=str(spec.get("method_sha256", method_ref.sha256)),
                scope_sha256=str(spec.get("scope_sha256", case.scope_sha256)),
                started_at=NOW + timedelta(seconds=index),
                ended_at=NOW + timedelta(seconds=index, milliseconds=1),
                duration_ms=Decimal(str(spec["duration"])),
                outcome=outcome,
                error_code="SYNTHETIC_TIMEOUT" if outcome == "TIMEOUT" else None,
                response_evidence=evidence,
                response_bytes=response_bytes,
                results=result_items,
                input_cursor_sha256=spec.get("input_cursor_sha256"),
                output_cursor_sha256=spec.get("output_cursor_sha256"),
                page_snapshot_sha256=spec.get(
                    "page_snapshot_sha256",
                    "e" * 64 if outcome == "SUCCEEDED" and kind != "COMPLETE_TRAVERSAL" else None,
                ),
                snapshot_at=spec.get(
                    "snapshot_at",
                    NOW if outcome == "SUCCEEDED" and kind != "COMPLETE_TRAVERSAL" else None,
                ),
                traversal_complete=kind == "COMPLETE_TRAVERSAL" and outcome == "SUCCEEDED",
            )
        )
    observations_ref = write_json(
        root,
        "observations.json",
        ObservationSet(
            version="eis-search-observations-v2",
            tenant=TENANT,
            observations=tuple(observations),
        ),
    )
    labels: list[BenchmarkLabel] = []
    for index, spec in enumerate(label_specs):
        item = spec["identity"]
        assert isinstance(item, ExactResultId)
        verdict = str(spec.get("verdict", "RELEVANT"))
        author = str(spec.get("label_author", "label-author"))
        reviewer = str(spec.get("reviewer", "independent-reviewer"))
        evidence_ref = write_json(
            root,
            f"labels/evidence-{index}.json",
            {
                "version": "eis-search-label-source-evidence-v2",
                "identity": item.model_dump(mode="json"),
            },
            "/identity",
        )
        review = {
            "tenant": TENANT,
            "case_id": CASE_ID,
            "reviewer": reviewer,
            "label_author": author,
            "identity": item.model_dump(mode="json"),
            "intent_sha256": case.intent_sha256,
            "scope_sha256": case.scope_sha256,
            "verdict": verdict,
            "membership": spec.get("membership", "IN_SCOPE_PRESENT_EXACT"),
        }
        review.update(review_binding_overrides or {})
        review_ref = write_json(
            root,
            f"labels/review-{index}.json",
            {"version": "eis-search-label-review-evidence-v2", "review": review},
            "/review",
        )
        labels.append(
            BenchmarkLabel(
                tenant=TENANT,
                case_id=CASE_ID,
                intent_sha256=case.intent_sha256,
                scope_sha256=case.scope_sha256,
                identity=item,
                verdict=verdict,
                membership=spec.get("membership", "IN_SCOPE_PRESENT_EXACT"),
                review_status=spec.get("review_status", "REVIEWED"),
                label_author=author,
                reviewer=reviewer,
                method="Synthetic exact-version review protocol.",
                reviewed_at=NOW,
                reason="Synthetic evidence for deterministic calculator acceptance.",
                evidence=evidence_ref,
                review_evidence=review_ref,
            )
        )
    labels_ref = write_json(
        root,
        "labels.json",
        LabelSet(version="eis-search-labels-v2", tenant=TENANT, labels=tuple(labels)),
    )
    manifest = PackageManifest(
        version="eis-search-package-v2",
        tenant=TENANT,
        package_id="synthetic-package",
        created_at=NOW,
        suite=suite_ref,
        corpus=corpus_ref,
        observations=observations_ref,
        labels=labels_ref,
        method=method_ref,
    )
    write_json(root, "package.json", manifest)
    return root / "package.json"


def test_all_outcome_p95_includes_two_timeouts_after_nineteen_fast_successes(tmp_path):
    specs = tuple(observation_spec(index, "SUCCEEDED", "1") for index in range(1, 20)) + tuple(
        observation_spec(index, "TIMEOUT", "30000") for index in range(20, 22)
    )
    package = load_package(tmp_path, build_package(tmp_path, observation_specs=specs))
    latency = calculate_report(package).cases[0].first_page_latency
    assert latency.planned_count == latency.completed_count == 21
    assert latency.not_attempted_count == 0
    assert latency.all_outcome_p50_ms == Decimal("1")
    assert latency.all_outcome_p95_ms == Decimal("30000")
    assert latency.success_only_p95_ms == Decimal("1")
    assert latency.outcome_counts == {"SUCCEEDED": 19, "TIMEOUT": 2}


def test_all_error_latency_is_measured_but_missing_attempt_blocks_status(tmp_path):
    specs = (observation_spec(1, "TIMEOUT", "30000"), observation_spec(2, "TIMEOUT", "30000"))
    all_error = tmp_path / "all-error"
    report = calculate_report(
        load_package(all_error, build_package(all_error, observation_specs=specs))
    )
    latency = report.cases[0].first_page_latency
    assert latency.all_outcome_p95_ms == Decimal("30000") and latency.error_rate == Decimal(1)
    missing_plans = plan(3)
    missing = calculate_report(
        load_package(
            tmp_path / "missing",
            build_package(tmp_path / "missing", plans=missing_plans, observation_specs=specs),
        )
    )
    assert missing.cases[0].first_page_latency.not_attempted_count == 1
    assert missing.cases[0].status == "UNKNOWN"


def test_empty_positive_is_zero_and_absent_reference_is_coverage_loss(tmp_path):
    absent = identity("0123456789012345679")
    package_path = build_package(
        tmp_path,
        observation_specs=(observation_spec(1),),
        label_specs=({"identity": absent, "membership": "ABSENT_FROM_CORPUS"},),
    )
    quality = calculate_report(load_package(tmp_path, package_path)).cases[0].repeats[0]
    assert quality.precision_at_10 == Decimal(0) and quality.precision_status == "MEASURED"
    assert quality.absent_from_corpus_count == 1
    assert quality.eligible_reference_count == 0
    assert quality.known_reference_recall_at_10 is None
    assert quality.recall_at_10_status == "ZERO_DENOMINATOR"


def test_empty_without_positive_has_zero_denominator(tmp_path):
    quality = (
        calculate_report(
            load_package(
                tmp_path, build_package(tmp_path, observation_specs=(observation_spec(1),))
            )
        )
        .cases[0]
        .repeats[0]
    )
    assert quality.precision_at_10 is None
    assert quality.precision_status == quality.recall_at_10_status == "ZERO_DENOMINATOR"


def test_present_exact_not_retrieved_is_retrieval_miss_not_coverage_loss(tmp_path):
    present = identity()
    absent = identity("0123456789012345679")
    package_path = build_package(
        tmp_path,
        observation_specs=(observation_spec(1),),
        records=(present,),
        label_specs=(
            {"identity": present, "membership": "IN_SCOPE_PRESENT_EXACT"},
            {"identity": absent, "membership": "ABSENT_FROM_CORPUS"},
        ),
    )
    quality = calculate_report(load_package(tmp_path, package_path)).cases[0].repeats[0]
    assert quality.eligible_reference_count == 1
    assert quality.known_reference_recall_at_10 == Decimal(0)
    assert quality.retrieval_miss_at_10_count == 1
    assert quality.absent_from_corpus_count == 1


def test_partial_label_and_wrong_exact_version_keep_precision_unknown(tmp_path):
    returned = identity()
    stale = identity(version=2, sha="f" * 64)
    package_path = build_package(
        tmp_path,
        observation_specs=(observation_spec(1, results=(returned,)),),
        records=(returned,),
        label_specs=(
            {
                "identity": returned,
                "membership": "IN_SCOPE_PRESENT_EXACT",
                "review_status": "PROVISIONAL",
            },
            {"identity": stale, "membership": "VERSION_CONFLICT"},
        ),
    )
    quality = calculate_report(load_package(tmp_path, package_path)).cases[0].repeats[0]
    assert quality.precision_at_10 is None and quality.precision_status == "UNKNOWN"
    assert quality.known_reference_recall_at_10 is None
    assert quality.version_conflict_count == 1


def test_conflicting_reviewed_verdicts_remain_unknown(tmp_path):
    item = identity()
    package = build_package(
        tmp_path,
        observation_specs=(observation_spec(1, results=(item,)),),
        records=(item,),
        label_specs=(
            {"identity": item, "verdict": "RELEVANT"},
            {"identity": item, "verdict": "IRRELEVANT"},
        ),
    )
    quality = calculate_report(load_package(tmp_path, package)).cases[0].repeats[0]
    assert quality.precision_at_10 is None
    assert quality.recall_at_10_status == "UNKNOWN"
    assert any(reason.startswith("CONFLICTING_REVIEWED_LABEL") for reason in quality.status_reasons)


def test_self_review_and_tampered_or_missing_evidence_are_rejected(tmp_path):
    item = identity()
    self_review = tmp_path / "self"
    package = build_package(
        self_review,
        observation_specs=(observation_spec(1, results=(item,)),),
        records=(item,),
        label_specs=({"identity": item, "reviewer": "instrument-author"},),
    )
    with pytest.raises(ValueError, match="LABEL_SELF_REVIEW"):
        calculate_report(load_package(self_review, package))
    tampered = tmp_path / "tampered"
    package = build_package(tampered, observation_specs=(observation_spec(1),))
    (tampered / "responses/0.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="EVIDENCE_SHA_MISMATCH"):
        load_package(tampered, package)
    locator = tmp_path / "locator"
    package = build_package(
        locator, observation_specs=(observation_spec(1),), bad_response_locator=True
    )
    with pytest.raises(ValueError, match="EVIDENCE_LOCATOR_MISSING"):
        load_package(locator, package)


def test_path_partial_cap_and_exact_binding_fail_closed(tmp_path):
    with pytest.raises(ValidationError):
        EvidenceRef(path="../escape.json", sha256="a" * 64, locator="/", max_bytes=1)
    proof = EvidenceRef(path="proof.json", sha256="a" * 64, locator="/", max_bytes=1)
    with pytest.raises(ValidationError):
        CorpusConsistency.model_validate(
            {
                "mode": "IMMUTABLE_COPY",
                "complete": True,
                "partial": True,
                "repeatable_read": True,
                "tenant_rls_bound": True,
                "single_clock": True,
                "proof": proof.model_dump(),
            }
        )
    with pytest.raises(ValueError, match="CORPUS_ROW_COUNT_INVALID"):
        build_package(
            tmp_path / "cap",
            records=(identity(), identity("0123456789012345679")),
            row_cap=1,
        )
    wrong_binding = tmp_path / "binding"
    package = build_package(
        wrong_binding,
        observation_specs=(observation_spec(1, scope_sha256="9" * 64),),
    )
    with pytest.raises(ValueError, match="OBSERVATION_BINDING_MISMATCH"):
        calculate_report(load_package(wrong_binding, package))
    wrong_identity = tmp_path / "identity"
    returned = identity()
    package = build_package(
        wrong_identity,
        observation_specs=(
            observation_spec(
                1,
                results=(returned,),
                evidence_results=(identity(version=2, sha="f" * 64),),
            ),
        ),
    )
    with pytest.raises(ValueError, match="OBSERVATION_EXACT_IDENTITY_MISMATCH"):
        load_package(wrong_identity, package)


def test_oversized_package_manifest_is_rejected_before_read_bytes(tmp_path, monkeypatch):
    manifest = tmp_path / "package.json"
    manifest.write_bytes(b"{" + b" " * (1024 * 1024))
    read_bytes_calls: list[Path] = []

    def unexpected_read_bytes(path: Path) -> bytes:
        read_bytes_calls.append(path)
        raise AssertionError("unbounded read_bytes must not run")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read_bytes)
    with pytest.raises(ValueError, match="EVIDENCE_SIZE_LIMIT"):
        load_package(tmp_path, manifest)
    assert read_bytes_calls == []


def test_success_snapshot_must_match_scope_and_corpus_clock(tmp_path):
    package = build_package(
        tmp_path,
        observation_specs=(observation_spec(1, snapshot_at=NOW + timedelta(days=7)),),
    )
    with pytest.raises(ValueError, match="OBSERVATION_SNAPSHOT_CLOCK_MISMATCH"):
        calculate_report(load_package(tmp_path, package))


@pytest.mark.parametrize(
    ("second_input", "second_output", "expected_reason"),
    (
        ("2" * 64, None, "CURSOR_CHAIN_MISMATCH"),
        ("1" * 64, "3" * 64, "TERMINAL_CURSOR_PRESENT"),
    ),
)
def test_disconnected_or_nonterminal_cursor_blocks_complete_recall(
    tmp_path, second_input, second_output, expected_reason
):
    item = identity()
    plans = (
        PlannedAttempt(attempt_id="p1", repeat=1, kind="FIRST_PAGE", page_index=1),
        PlannedAttempt(attempt_id="p2", repeat=1, kind="CONTINUATION", page_index=2),
        PlannedAttempt(attempt_id="full", repeat=1, kind="COMPLETE_TRAVERSAL"),
    )
    specs = (
        observation_spec(
            1,
            results=(item,),
            attempt_id="p1",
            output_cursor_sha256="1" * 64,
        ),
        observation_spec(
            1,
            attempt_id="p2",
            kind="CONTINUATION",
            page_index=2,
            input_cursor_sha256=second_input,
            output_cursor_sha256=second_output,
        ),
        observation_spec(
            1,
            results=(item,),
            attempt_id="full",
            kind="COMPLETE_TRAVERSAL",
            page_index=None,
        ),
    )
    package = build_package(
        tmp_path,
        plans=plans,
        observation_specs=specs,
        records=(item,),
        label_specs=({"identity": item},),
    )
    quality = calculate_report(load_package(tmp_path, package)).cases[0].repeats[0]
    assert quality.known_reference_recall_at_10 == Decimal(1)
    assert quality.known_reference_recall_complete is None
    assert quality.recall_complete_status == "INCOMPLETE"
    assert expected_reason in quality.status_reasons


def test_exact_cursor_chain_allows_complete_recall(tmp_path):
    item = identity()
    plans = (
        PlannedAttempt(attempt_id="p1", repeat=1, kind="FIRST_PAGE", page_index=1),
        PlannedAttempt(attempt_id="p2", repeat=1, kind="CONTINUATION", page_index=2),
        PlannedAttempt(attempt_id="full", repeat=1, kind="COMPLETE_TRAVERSAL"),
    )
    specs = (
        observation_spec(
            1,
            results=(item,),
            attempt_id="p1",
            output_cursor_sha256="1" * 64,
        ),
        observation_spec(
            1,
            attempt_id="p2",
            kind="CONTINUATION",
            page_index=2,
            input_cursor_sha256="1" * 64,
        ),
        observation_spec(
            1,
            results=(item,),
            attempt_id="full",
            kind="COMPLETE_TRAVERSAL",
            page_index=None,
        ),
    )
    package = build_package(
        tmp_path,
        plans=plans,
        observation_specs=specs,
        records=(item,),
        label_specs=({"identity": item},),
    )
    quality = calculate_report(load_package(tmp_path, package)).cases[0].repeats[0]
    assert quality.known_reference_recall_complete == Decimal(1)
    assert quality.recall_complete_status == "MEASURED"
    assert quality.status_reasons == ()


@pytest.mark.parametrize("continuation_outcome", (None, "PAGE_EXPIRED"))
def test_asserted_traversal_requires_every_planned_successful_page(tmp_path, continuation_outcome):
    item = identity()
    plans = (
        PlannedAttempt(attempt_id="p1", repeat=1, kind="FIRST_PAGE", page_index=1),
        PlannedAttempt(attempt_id="p2", repeat=1, kind="CONTINUATION", page_index=2),
        PlannedAttempt(attempt_id="full", repeat=1, kind="COMPLETE_TRAVERSAL"),
    )
    specs = [observation_spec(1, results=(item,), attempt_id="p1")]
    if continuation_outcome is not None:
        specs.append(
            observation_spec(
                1,
                outcome=continuation_outcome,
                attempt_id="p2",
                kind="CONTINUATION",
                page_index=2,
            )
        )
    specs.append(
        observation_spec(
            1,
            results=(item,),
            attempt_id="full",
            kind="COMPLETE_TRAVERSAL",
            page_index=None,
        )
    )
    package = build_package(
        tmp_path,
        plans=plans,
        observation_specs=tuple(specs),
        records=(item,),
        label_specs=({"identity": item},),
    )
    quality = calculate_report(load_package(tmp_path, package)).cases[0].repeats[0]
    assert quality.known_reference_recall_at_10 == Decimal(1)
    assert quality.known_reference_recall_complete is None
    assert quality.recall_complete_status == "INCOMPLETE"
    assert "PLANNED_PAGE_INCOMPLETE" in quality.status_reasons


def test_eligible_exact_label_cannot_be_reclassified_out_of_scope(tmp_path):
    item = identity()
    package = build_package(
        tmp_path,
        observation_specs=(observation_spec(1),),
        records=(item,),
        label_specs=({"identity": item, "membership": "OUT_OF_SCOPE"},),
    )
    with pytest.raises(ValueError, match="LABEL_MEMBERSHIP_MISMATCH"):
        calculate_report(load_package(tmp_path, package))


def test_eligible_exact_membership_unknown_keeps_recall_unknown(tmp_path):
    item = identity()
    package = build_package(
        tmp_path,
        observation_specs=(observation_spec(1, results=(item,)),),
        records=(item,),
        label_specs=({"identity": item, "membership": "MEMBERSHIP_UNKNOWN"},),
    )
    quality = calculate_report(load_package(tmp_path, package)).cases[0].repeats[0]
    assert quality.known_reference_recall_at_10 is None
    assert quality.recall_at_10_status == "UNKNOWN"
    assert quality.membership_unknown_count == 1
    assert "REFERENCE_MEMBERSHIP_UNRESOLVED" in quality.status_reasons


def test_conflicting_reviewed_membership_keeps_reference_and_nulls_recall(tmp_path):
    first = identity()
    missed = identity("0123456789012345679", sha="b" * 64)
    package = build_package(
        tmp_path,
        observation_specs=(observation_spec(1, results=(first,)),),
        records=(first, missed),
        label_specs=(
            {"identity": first},
            {"identity": missed},
            {"identity": missed, "membership": "MEMBERSHIP_UNKNOWN"},
        ),
    )
    quality = calculate_report(load_package(tmp_path, package)).cases[0].repeats[0]
    assert quality.eligible_reference_count == 2
    assert quality.retrieved_reference_at_10_count == 1
    assert quality.known_reference_recall_at_10 is None
    assert quality.recall_at_10_status == "UNKNOWN"
    assert quality.retrieval_miss_at_10_count == 1
    assert "CONFLICTING_MEMBERSHIP_CLASS" in quality.status_reasons
    assert "REFERENCE_MEMBERSHIP_UNRESOLVED" in quality.status_reasons


def test_failed_first_page_has_unknown_recall_and_null_miss_count(tmp_path):
    item = identity()
    package = build_package(
        tmp_path,
        observation_specs=(observation_spec(1, outcome="TIMEOUT", duration="30000"),),
        records=(item,),
        label_specs=({"identity": item},),
    )
    quality = calculate_report(load_package(tmp_path, package)).cases[0].repeats[0]
    assert quality.known_reference_recall_at_10 is None
    assert quality.recall_at_10_status == "UNKNOWN"
    assert quality.retrieval_miss_at_10_count is None


def test_real_frozen_is_unknown_without_trusted_m2b_authority(tmp_path):
    item = identity()
    package = build_package(
        tmp_path,
        observation_specs=(observation_spec(1, results=(item,)),),
        records=(item,),
        label_specs=({"identity": item},),
        dataset_kind="REAL_FROZEN",
    )
    report = calculate_report(load_package(tmp_path, package))
    assert report.cases[0].status == "MEASURED"
    assert report.acceptance_status == "UNKNOWN"
    assert report.prerequisites["trusted_m2b_capture_proof_validated"] is False
    assert report.prerequisites["trusted_m2b_review_provenance_validated"] is False
    assert "REAL_CAPTURE_AUTHORITY_NOT_VALIDATED_IN_M2A" in report.status_reasons


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("tenant", "another-tenant"),
        ("case_id", "another-case"),
        ("membership", "OUT_OF_SCOPE"),
    ),
)
def test_review_evidence_binds_tenant_case_and_membership(tmp_path, key, value):
    item = identity()
    package = build_package(
        tmp_path,
        observation_specs=(observation_spec(1),),
        records=(item,),
        label_specs=({"identity": item},),
        review_binding_overrides={key: value},
    )
    with pytest.raises(ValueError, match="LABEL_REVIEW_PROOF_MISMATCH"):
        load_package(tmp_path, package)


def test_continuation_duplicate_and_fingerprint_drift_block_complete_recall(tmp_path):
    item = identity()
    plans = (
        PlannedAttempt(attempt_id="p1", repeat=1, kind="FIRST_PAGE", page_index=1),
        PlannedAttempt(attempt_id="p2", repeat=1, kind="CONTINUATION", page_index=2),
        PlannedAttempt(attempt_id="full", repeat=1, kind="COMPLETE_TRAVERSAL"),
    )
    specs = (
        observation_spec(1, results=(item,), attempt_id="p1"),
        observation_spec(
            1,
            results=(item,),
            attempt_id="p2",
            kind="CONTINUATION",
            page_index=2,
            input_cursor_sha256="1" * 64,
            page_snapshot_sha256="f" * 64,
        ),
        observation_spec(
            1,
            results=(item, item),
            attempt_id="full",
            kind="COMPLETE_TRAVERSAL",
            page_index=None,
        ),
    )
    package = build_package(
        tmp_path,
        plans=plans,
        observation_specs=specs,
        records=(item,),
        label_specs=({"identity": item},),
    )
    quality = calculate_report(load_package(tmp_path, package)).cases[0].repeats[0]
    assert quality.known_reference_recall_complete is None
    assert quality.recall_complete_status == "INCOMPLETE"
    assert "PAGE_RESULT_DUPLICATE" in quality.status_reasons
    assert "PAGE_FINGERPRINT_DRIFT" in quality.status_reasons


def test_expired_cursor_and_missing_traversal_cannot_be_complete(tmp_path):
    plans = (
        PlannedAttempt(attempt_id="p1", repeat=1, kind="FIRST_PAGE", page_index=1),
        PlannedAttempt(attempt_id="p2", repeat=1, kind="CONTINUATION", page_index=2),
        PlannedAttempt(attempt_id="full", repeat=1, kind="COMPLETE_TRAVERSAL"),
    )
    specs = (
        observation_spec(1, attempt_id="p1"),
        observation_spec(
            1,
            outcome="PAGE_EXPIRED",
            duration="900000",
            attempt_id="p2",
            kind="CONTINUATION",
            page_index=2,
        ),
    )
    package = build_package(tmp_path, plans=plans, observation_specs=specs)
    case = calculate_report(load_package(tmp_path, package)).cases[0]
    assert case.status == "UNKNOWN"
    assert "NON_SUCCESS_OUTCOME" in case.reasons
    assert "TRAVERSAL_INCOMPLETE" in case.reasons
    assert case.traversal_latency.not_attempted_count == 1


def test_unsupported_filter_records_no_fake_http_duration(tmp_path):
    unsupported_plan = (
        PlannedAttempt(
            attempt_id="attempt-1",
            repeat=1,
            kind="FIRST_PAGE",
            page_index=1,
            http_request_expected=False,
        ),
    )
    package = build_package(tmp_path, plans=unsupported_plan, unsupported=True)
    case = calculate_report(load_package(tmp_path, package)).cases[0]
    assert case.first_page_latency.planned_count == 1
    assert case.first_page_latency.attempted_count == 0
    assert case.first_page_latency.not_attempted_count == 1
    assert case.first_page_latency.all_outcome_p95_ms is None
    assert case.status == "UNKNOWN" and "UNSUPPORTED_FILTER" in case.reasons


def test_cli_replay_is_deterministic_offline_and_template_covers_contract(tmp_path):
    item = identity()
    evidence = tmp_path / "данные"
    package = build_package(
        evidence,
        observation_specs=(observation_spec(1, results=(item,)),),
        records=(item,),
        label_specs=({"identity": item},),
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "eis-search-benchmark-v2.py"
    outputs = []
    for name in ("отчёт-a", "отчёт-b"):
        output = tmp_path / name
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script),
                "--evidence-root",
                str(evidence),
                "--package",
                str(package),
                "--output",
                str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            },
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        outputs.append(
            tuple(
                (output / file).read_bytes()
                for file in ("report.json", "report.md", "labels-template.json")
            )
        )
    assert outputs[0] == outputs[1]
    report = json.loads(outputs[0][0])
    assert report["acceptance_status"] == "SYNTHETIC_ONLY"
    suite_path = Path(__file__).resolve().parents[1] / "scripts/benchmarks/eis-query-suite.v2.json"
    suite = BenchmarkSuite.model_validate_json(suite_path.read_bytes())
    assert {case.scope.law for case in suite.cases} == {"44", "223"}
    assert {case.scope.search_scope for case in suite.cases if case.scope.law == "44"} == {
        "ALL_CACHED",
        "NOT_EXPIRED_OR_UNKNOWN",
    }
    assert any(case.scope.continuation_policy == "UNTIL_END_OR_PAGE_BUDGET" for case in suite.cases)
    assert any(case.kind == "UNSUPPORTED" for case in suite.cases)
    assert any(case.kind == "INVALID_QUERY" for case in suite.cases)
    (evidence / "responses/0.json").write_text('{"results": []}\n', encoding="utf-8")
    rejected = subprocess.run(
        [
            sys.executable,
            "-B",
            str(script),
            "--evidence-root",
            str(evidence),
            "--package",
            str(package),
            "--output",
            str(tmp_path / "rejected"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        },
    )
    assert rejected.returncode == 2
    assert rejected.stderr == "benchmark v2 rejected: ValueError\n"
    assert not (tmp_path / "rejected").exists()
