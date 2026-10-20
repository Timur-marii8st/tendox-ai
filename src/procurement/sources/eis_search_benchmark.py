"""Evidence-bound measurements; no measurement implies procurement admission."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class BenchmarkModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceRef(BenchmarkModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    locator: str = Field(min_length=1)


class BenchmarkQuery(BenchmarkModel):
    id: str = Field(pattern=r"^[a-z0-9-]{1,60}$")
    query: str = Field(min_length=1, max_length=120)
    intent: str = Field(min_length=1)
    public_pages: tuple[int, ...] = ()


class BenchmarkSuite(BenchmarkModel):
    version: Literal["eis-query-v1"]
    queries: tuple[BenchmarkQuery, ...] = Field(min_length=20, max_length=30)


class BenchmarkItem(BenchmarkModel):
    purchase_number: str = Field(pattern=r"^(?:[0-9]{11}|[0-9]{19,23})$")
    title: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    application_status: Literal["FAIL", "UNKNOWN"]


class BenchmarkObservation(BenchmarkModel):
    company_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    query_id: str
    query: str
    effective_query_keys: tuple[str, ...] | None = None
    source: Literal["LOCAL_INDEX", "EIS_PUBLIC"]
    observed_at: AwareDatetime
    status: Literal["SUCCEEDED", "FAILED", "RATE_LIMITED", "BLOCKED", "COOLDOWN"]
    duration_ms: Decimal = Field(ge=0)
    wait_ms: Decimal = Field(default=Decimal(0), ge=0)
    http_status: int | None = None
    error_code: str | None = None
    request_url: str | None = None
    evidence: EvidenceRef | None = None
    response_bytes: int = Field(default=0, ge=0)
    raw_numbers: tuple[str, ...] = ()
    items: tuple[BenchmarkItem, ...] = ()
    scanned_count: int | None = None
    unidentified_count: int | None = None
    unparsed_count: int = 0
    page_number: int | None = None
    indexed_current_notices: int | None = None
    evaluated_candidate_notices: int | None = None
    matched_count: int | None = None
    source_watermark_age_seconds: int | None = None
    ingestion_watermark_age_seconds: int | None = None
    search_elapsed_ms: int | None = None
    source_freshness: Literal["UNKNOWN"] = "UNKNOWN"
    corpus_coverage: Literal["UNKNOWN"] = "UNKNOWN"


class BenchmarkLabel(BenchmarkModel):
    company_id: str
    query_id: str
    purchase_number: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    verdict: Literal["RELEVANT", "IRRELEVANT", "UNKNOWN"]
    review_status: Literal["PROVISIONAL", "REVIEWED"] = "PROVISIONAL"
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence: EvidenceRef


class LatencySummary(BenchmarkModel):
    sample_count: int
    success_count: int
    failure_count: int
    success_p50_ms: Decimal | None
    success_p95_ms: Decimal | None
    failure_max_ms: Decimal | None
    successful_response_bytes: int
    percentile_method: Literal["NEAREST_RANK"] = "NEAREST_RANK"
    includes_upstream_wait: Literal[False] = False


def latency_summary(observations: Sequence[BenchmarkObservation]) -> LatencySummary:
    successes = sorted(item.duration_ms for item in observations if item.status == "SUCCEEDED")
    failures = [item.duration_ms for item in observations if item.status != "SUCCEEDED"]

    def percentile(value: int) -> Decimal | None:
        if not successes:
            return None
        index = (len(successes) * value + 99) // 100 - 1
        return successes[index]

    return LatencySummary(
        sample_count=len(observations),
        success_count=len(successes),
        failure_count=len(failures),
        success_p50_ms=percentile(50),
        success_p95_ms=percentile(95),
        failure_max_ms=max(failures) if failures else None,
        successful_response_bytes=sum(
            item.response_bytes for item in observations if item.status == "SUCCEEDED"
        ),
    )


class QualitySummary(BenchmarkModel):
    k: int
    unique_returned_count: int
    duplicate_count: int
    judged_count: int
    unjudged_count: int
    relevant_count: int
    irrelevant_count: int
    precision_at_k: Decimal | None
    precision_lower_bound: Decimal | None
    precision_upper_bound: Decimal | None
    known_reference_count: int
    known_reference_recall_at_k: Decimal | None
    quality_status: Literal["UNKNOWN", "MEASURED_SLICE"]
    full_corpus_recall: None = None


def quality_summary(
    observation: BenchmarkObservation,
    labels: Sequence[BenchmarkLabel],
    *,
    k: int = 10,
) -> QualitySummary:
    if not 1 <= k <= 100:
        raise ValueError("QUALITY_K_INVALID")
    selected: dict[tuple[str, str], BenchmarkLabel] = {}
    for label in labels:
        if label.company_id != observation.company_id:
            raise ValueError("LABEL_TENANT_MISMATCH")
        if label.query_id != observation.query_id or label.review_status != "REVIEWED":
            continue
        key = label.purchase_number, label.source_sha256
        if key in selected and selected[key].verdict != label.verdict:
            raise ValueError("LABEL_CONFLICT")
        selected[key] = label
    # Duplicate result rows are never counted as additional correct answers.
    unique = {item.purchase_number: item for item in reversed(observation.items)}
    conflicting_ids = {
        number
        for number in unique
        if len({item.source_sha256 for item in observation.items if item.purchase_number == number})
        > 1
    }
    # Preserve the first occurrence's ranking, not the reversed insertion order.
    ranked_ids = list(dict.fromkeys(item.purchase_number for item in observation.items))[:k]
    top = [unique[number] for number in ranked_ids]
    verdicts = [
        selected.get((item.purchase_number, item.source_sha256))
        if item.purchase_number not in conflicting_ids and observation.evidence
        else None
        for item in top
    ]
    relevant = sum(label is not None and label.verdict == "RELEVANT" for label in verdicts)
    irrelevant = sum(label is not None and label.verdict == "IRRELEVANT" for label in verdicts)
    unjudged = len(top) - relevant - irrelevant
    positive_labels = [label for label in selected.values() if label.verdict == "RELEVANT"]
    reference_numbers = {label.purchase_number for label in positive_labels}
    stale = any(
        label.purchase_number in unique
        and unique[label.purchase_number].source_sha256 != label.source_sha256
        for label in positive_labels
    )
    recall = (
        Decimal(len(reference_numbers & set(ranked_ids))) / len(reference_numbers)
        if reference_numbers
        and not stale
        and not conflicting_ids
        and observation.evidence
        and observation.status == "SUCCEEDED"
        else None
    )
    measured = observation.status == "SUCCEEDED" and bool(top) and not unjudged
    return QualitySummary(
        k=k,
        unique_returned_count=len(unique),
        duplicate_count=len(observation.items) - len(unique),
        judged_count=relevant + irrelevant,
        unjudged_count=unjudged,
        relevant_count=relevant,
        irrelevant_count=irrelevant,
        precision_at_k=Decimal(relevant) / len(top) if measured else None,
        precision_lower_bound=Decimal(relevant) / len(top) if top else None,
        precision_upper_bound=Decimal(relevant + unjudged) / len(top) if top else None,
        known_reference_count=len(reference_numbers),
        known_reference_recall_at_k=recall,
        quality_status="MEASURED_SLICE" if measured else "UNKNOWN",
    )


def source_age_seconds(value: datetime | None, observed_at: datetime) -> int | None:
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return None
    if observed_at.tzinfo is None or observed_at.utcoffset() is None or value > observed_at:
        return None
    return int((observed_at - value).total_seconds())


class SourceOverlap(BenchmarkModel):
    reference_unique_count: int
    compared_unique_count: int
    shared_count: int
    reference_id_overlap_fraction: Decimal | None
    scope_comparability: Literal["UNKNOWN"] = "UNKNOWN"
    full_corpus_recall: None = None


class ReferenceCorpusEntry(BenchmarkModel):
    purchase_number: str
    version_number: int
    document_type: str
    title: str
    xml_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_member: str
    published_at: AwareDatetime | None
    deadline: AwareDatetime | None


class ReferenceMembership(BenchmarkModel):
    company_id: str
    run_id: str
    observed_at: AwareDatetime
    requested_numbers: tuple[str, ...]
    entries: tuple[ReferenceCorpusEntry, ...]
    scope: Literal["TENANT_CURRENT_KNOWN_VERSIONS"] = "TENANT_CURRENT_KNOWN_VERSIONS"
    corpus_coverage: Literal["UNKNOWN"] = "UNKNOWN"


def source_overlap(
    reference: BenchmarkObservation, compared: BenchmarkObservation
) -> SourceOverlap:
    if (reference.company_id, reference.query_id, reference.query) != (
        compared.company_id,
        compared.query_id,
        compared.query,
    ):
        raise ValueError("OBSERVATION_SCOPE_MISMATCH")
    ref_ids, compared_ids = set(reference.raw_numbers), set(compared.raw_numbers)
    successful = reference.status == compared.status == "SUCCEEDED"
    return SourceOverlap(
        reference_unique_count=len(ref_ids),
        compared_unique_count=len(compared_ids),
        shared_count=len(ref_ids & compared_ids),
        reference_id_overlap_fraction=Decimal(len(ref_ids & compared_ids)) / len(ref_ids)
        if ref_ids and successful
        else None,
    )
