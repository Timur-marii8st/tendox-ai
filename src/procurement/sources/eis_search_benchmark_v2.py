"""Strict offline metrics for an evidence-bound saved-search benchmark package."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CaseId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")]
PurchaseNumber = Annotated[str, StringConstraints(pattern=r"^(?:[0-9]{11}|[0-9]{19,23})$")]
Law = Literal["44", "223"]
AttemptKind = Literal["FIRST_PAGE", "CONTINUATION", "COMPLETE_TRAVERSAL"]
Outcome = Literal[
    "SUCCEEDED",
    "ERROR",
    "TIMEOUT",
    "INVALID_RESPONSE",
    "PAGE_CHANGED",
    "PAGE_EXPIRED",
    "UNSUPPORTED",
]
Membership = Literal[
    "IN_SCOPE_PRESENT_EXACT",
    "ABSENT_FROM_CORPUS",
    "OUT_OF_SCOPE",
    "VERSION_CONFLICT",
    "MEMBERSHIP_UNKNOWN",
]

CALCULATOR_VERSION = "eis-search-calculator-v2"
CANONICAL_JSON = "UTF-8 JSON, sorted keys, compact separators, ensure_ascii=false"


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FiniteDecimalModel(StrictModel):
    @field_validator("*", mode="before")
    @classmethod
    def reject_non_finite_floats(cls, value: object) -> object:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("NON_FINITE_NUMBER")
        return value


class EvidenceRef(StrictModel):
    path: str = Field(min_length=1, max_length=240)
    sha256: Sha256
    locator: str = Field(min_length=1, max_length=500)
    max_bytes: int = Field(ge=1, le=16 * 1024 * 1024)

    @field_validator("path")
    @classmethod
    def relative_posix_path(cls, value: str) -> str:
        parsed = PurePosixPath(value)
        if parsed.is_absolute() or ".." in parsed.parts or "\\" in value:
            raise ValueError("EVIDENCE_PATH_INVALID")
        return value

    @field_validator("locator")
    @classmethod
    def json_pointer(cls, value: str) -> str:
        if value != "/" and not value.startswith("/"):
            raise ValueError("EVIDENCE_LOCATOR_INVALID")
        return value


class FilterSpec(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,60}$")
    value: str = Field(min_length=1, max_length=200)
    application: Literal["HTTP", "STORAGE", "UNSUPPORTED"]


class PublicationInterval(StrictModel):
    mode: Literal["UNBOUNDED", "BOUNDED"]
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    bounds: Literal["[]", "[)"] | None = None

    @model_validator(mode="after")
    def coherent(self) -> PublicationInterval:
        if self.mode == "UNBOUNDED" and any(
            value is not None for value in (self.start, self.end, self.bounds)
        ):
            raise ValueError("UNBOUNDED_INTERVAL_HAS_BOUNDS")
        if self.mode == "BOUNDED" and (
            self.start is None or self.end is None or self.bounds is None or self.start > self.end
        ):
            raise ValueError("BOUNDED_INTERVAL_INVALID")
        return self


class SearchScope(StrictModel):
    version: Literal["eis-search-scope-v2"]
    law: Law
    endpoint: Literal[
        "/v1/tender-discovery/eis-index",
        "/v1/tender-discovery/eis-223-index",
    ]
    measurement_boundary: Literal["HTTP_READ_ONLY_ENDPOINT", "SQL_STORAGE"]
    boundary_notes: str = Field(min_length=1)
    search_scope: Literal["ALL_CACHED", "NOT_EXPIRED_OR_UNKNOWN"]
    region_mode: Literal["UNBOUNDED", "EXPLICIT"]
    region_codes: tuple[str, ...] = ()
    region_source: str = Field(min_length=1)
    publication_interval: PublicationInterval
    clock: AwareDatetime
    deadline_mode: Literal["ALL_CACHED", "NOT_EXPIRED_OR_UNKNOWN", "ACTIVE_ONLY_UNSUPPORTED"]
    filters: tuple[FilterSpec, ...]
    order_version: Literal[1] = 1
    page_size: int = Field(ge=1, le=100)
    continuation_policy: Literal["FIRST_PAGE_ONLY", "UNTIL_END_OR_PAGE_BUDGET"]

    @model_validator(mode="after")
    def interface_is_real(self) -> SearchScope:
        expected = (
            "/v1/tender-discovery/eis-index"
            if self.law == "44"
            else "/v1/tender-discovery/eis-223-index"
        )
        if self.endpoint != expected:
            raise ValueError("SCOPE_ENDPOINT_LAW_MISMATCH")
        if self.law == "223" and self.search_scope != "ALL_CACHED":
            raise ValueError("SCOPE_223_MODE_UNSUPPORTED")
        if self.region_mode == "UNBOUNDED" and self.region_codes:
            raise ValueError("SCOPE_REGION_INVALID")
        if self.region_mode == "EXPLICIT" and not self.region_codes:
            raise ValueError("SCOPE_REGION_INVALID")
        if len(set(self.region_codes)) != len(self.region_codes):
            raise ValueError("SCOPE_REGION_DUPLICATE")
        if len({item.name for item in self.filters}) != len(self.filters):
            raise ValueError("SCOPE_FILTER_DUPLICATE")
        http_supported = {"search_scope"} if self.law == "44" else set()
        storage_supported = {"require_documents", "exclude_failed"} if self.law == "44" else set()
        unsupported = {
            "region",
            "price",
            "ktru",
            "okpd2",
            "publication_date",
            "active_only",
        }
        for item in self.filters:
            if item.application == "HTTP" and item.name not in http_supported:
                raise ValueError("SCOPE_HTTP_FILTER_UNSUPPORTED")
            if item.application == "STORAGE" and (
                self.measurement_boundary != "SQL_STORAGE" or item.name not in storage_supported
            ):
                raise ValueError("SCOPE_STORAGE_FILTER_UNSUPPORTED")
            if (
                item.application == "UNSUPPORTED"
                and item.name not in unsupported | storage_supported
            ):
                raise ValueError("SCOPE_UNSUPPORTED_FILTER_UNKNOWN")
        return self


class PlannedAttempt(StrictModel):
    attempt_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    repeat: int = Field(ge=1, le=100)
    kind: AttemptKind
    page_index: int | None = Field(default=None, ge=1, le=100)
    http_request_expected: bool = True

    @model_validator(mode="after")
    def page_matches_kind(self) -> PlannedAttempt:
        if self.kind == "COMPLETE_TRAVERSAL" and self.page_index is not None:
            raise ValueError("TRAVERSAL_PAGE_INDEX_INVALID")
        if self.kind != "COMPLETE_TRAVERSAL" and self.page_index is None:
            raise ValueError("PAGE_INDEX_REQUIRED")
        return self


class BenchmarkCase(FiniteDecimalModel):
    case_id: CaseId
    order: int = Field(ge=1)
    kind: Literal["MEASURED", "UNSUPPORTED", "INVALID_QUERY"]
    query: str = Field(min_length=1, max_length=120)
    intent: str = Field(min_length=1)
    intent_sha256: Sha256
    relevance_criterion: str = Field(min_length=1)
    scope: SearchScope
    scope_sha256: Sha256
    repeats: int = Field(ge=1, le=100)
    timeout_ms: Decimal = Field(gt=0, le=Decimal("120000"))
    warmup_count: int = Field(ge=0, le=20)
    page_budget: int = Field(ge=1, le=100)
    attempts: tuple[PlannedAttempt, ...] = Field(min_length=1, max_length=2000)

    @field_validator("timeout_ms")
    @classmethod
    def finite_timeout(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("NON_FINITE_DURATION")
        return value

    @model_validator(mode="after")
    def hashes_and_plan(self) -> BenchmarkCase:
        if self.intent_sha256 != digest_bytes(self.intent.encode("utf-8")):
            raise ValueError("INTENT_SHA_MISMATCH")
        if self.scope_sha256 != canonical_digest(self.scope):
            raise ValueError("SCOPE_SHA_MISMATCH")
        ids = [item.attempt_id for item in self.attempts]
        if len(set(ids)) != len(ids):
            raise ValueError("ATTEMPT_ID_DUPLICATE")
        if {item.repeat for item in self.attempts} != set(range(1, self.repeats + 1)):
            raise ValueError("ATTEMPT_REPEAT_PLAN_INCOMPLETE")
        if any((item.page_index or 0) > self.page_budget for item in self.attempts):
            raise ValueError("ATTEMPT_PAGE_BUDGET_EXCEEDED")
        for repeat in range(1, self.repeats + 1):
            kinds = {item.kind for item in self.attempts if item.repeat == repeat}
            required = (
                {"FIRST_PAGE"}
                if self.scope.continuation_policy == "FIRST_PAGE_ONLY"
                else {"FIRST_PAGE", "CONTINUATION", "COMPLETE_TRAVERSAL"}
            )
            if kinds != required:
                raise ValueError("ATTEMPT_CONTINUATION_PLAN_INVALID")
        unsupported = any(item.application == "UNSUPPORTED" for item in self.scope.filters)
        if unsupported != (self.kind == "UNSUPPORTED"):
            raise ValueError("UNSUPPORTED_CASE_MISMATCH")
        if any(item.http_request_expected == unsupported for item in self.attempts):
            raise ValueError("ATTEMPT_HTTP_EXPECTATION_INVALID")
        return self


class BenchmarkSuite(StrictModel):
    version: Literal["eis-search-suite-v2"]
    tenant: str = Field(min_length=1)
    suite_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    cases: tuple[BenchmarkCase, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_cases(self) -> BenchmarkSuite:
        ids = [case.case_id for case in self.cases]
        orders = [case.order for case in self.cases]
        if len(set(ids)) != len(ids) or len(set(orders)) != len(orders):
            raise ValueError("SUITE_CASE_DUPLICATE")
        if orders != sorted(orders):
            raise ValueError("SUITE_ORDER_INVALID")
        attempt_ids = [attempt.attempt_id for case in self.cases for attempt in case.attempts]
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("SUITE_ATTEMPT_ID_DUPLICATE")
        return self


class ExactResultId(StrictModel):
    law: Law
    purchase_number: PurchaseNumber
    version_number: int = Field(ge=1)
    source_xml_sha256: Sha256

    @model_validator(mode="after")
    def number_matches_law(self) -> ExactResultId:
        if self.law == "223" and len(self.purchase_number) != 11:
            raise ValueError("PURCHASE_NUMBER_LAW_MISMATCH")
        if self.law == "44" and not 19 <= len(self.purchase_number) <= 23:
            raise ValueError("PURCHASE_NUMBER_LAW_MISMATCH")
        return self


class CorpusRecord(StrictModel):
    identity: ExactResultId
    ingested_at: AwareDatetime
    source_identity_sha256: Sha256
    eligible_case_ids: tuple[CaseId, ...]


class CorpusPartition(StrictModel):
    law: Law
    row_count: int = Field(ge=0)
    row_cap: int = Field(ge=1)
    ordered_records_sha256: Sha256


class CorpusConsistency(StrictModel):
    mode: Literal["IMMUTABLE_COPY", "EXPORTED_POSTGRES_SNAPSHOT"]
    complete: Literal[True]
    partial: Literal[False]
    repeatable_read: Literal[True]
    tenant_rls_bound: Literal[True]
    single_clock: Literal[True]
    proof: EvidenceRef


class CorpusManifest(StrictModel):
    version: Literal["eis-search-corpus-v2"]
    tenant: str = Field(min_length=1)
    capture_id: str = Field(min_length=1)
    captured_at: AwareDatetime
    selection: str = Field(min_length=1)
    tables_and_fields: tuple[str, ...] = Field(min_length=1)
    schema_revision: str = Field(min_length=1)
    database_runtime: str = Field(min_length=1)
    source_release_sha256: Sha256
    lock_sha256: Sha256
    consistency: CorpusConsistency
    partitions: tuple[CorpusPartition, ...] = Field(min_length=2, max_length=2)
    records: tuple[CorpusRecord, ...]

    @model_validator(mode="after")
    def validate_ordered_records(self) -> CorpusManifest:
        if {item.law for item in self.partitions} != {"44", "223"}:
            raise ValueError("CORPUS_PARTITIONS_INCOMPLETE")
        identities = [identity_key(item.identity) for item in self.records]
        if identities != sorted(identities) or len(set(identities)) != len(identities):
            raise ValueError("CORPUS_RECORD_ORDER_INVALID")
        if any(item.ingested_at > self.captured_at for item in self.records):
            raise ValueError("CORPUS_RECORD_AFTER_CAPTURE")
        for partition in self.partitions:
            records = [item for item in self.records if item.identity.law == partition.law]
            if partition.row_count != len(records) or partition.row_count > partition.row_cap:
                raise ValueError("CORPUS_ROW_COUNT_INVALID")
            if partition.ordered_records_sha256 != ordered_digest(records):
                raise ValueError("CORPUS_RECORD_SHA_MISMATCH")
        return self


class Observation(FiniteDecimalModel):
    attempt_id: str
    tenant: str
    case_id: CaseId
    repeat: int = Field(ge=1)
    kind: AttemptKind
    page_index: int | None = Field(default=None, ge=1)
    suite_sha256: Sha256
    corpus_sha256: Sha256
    method_sha256: Sha256
    scope_sha256: Sha256
    started_at: AwareDatetime
    ended_at: AwareDatetime
    duration_ms: Decimal = Field(ge=0)
    outcome: Outcome
    http_status: int | None = Field(default=None, ge=100, le=599)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,80}$")
    response_evidence: EvidenceRef | None = None
    response_bytes: int = Field(default=0, ge=0)
    results: tuple[ExactResultId, ...] = ()
    input_cursor_sha256: Sha256 | None = None
    output_cursor_sha256: Sha256 | None = None
    page_snapshot_sha256: Sha256 | None = None
    snapshot_at: AwareDatetime | None = None
    traversal_complete: bool = False

    @field_validator("duration_ms")
    @classmethod
    def finite_duration(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("NON_FINITE_DURATION")
        return value

    @model_validator(mode="after")
    def terminal_shape(self) -> Observation:
        if self.ended_at < self.started_at:
            raise ValueError("OBSERVATION_TIME_INVALID")
        if self.kind == "COMPLETE_TRAVERSAL":
            if self.page_index is not None:
                raise ValueError("TRAVERSAL_PAGE_INDEX_INVALID")
        elif self.page_index is None:
            raise ValueError("PAGE_INDEX_REQUIRED")
        if self.outcome == "SUCCEEDED":
            if self.response_evidence is None:
                raise ValueError("SUCCESS_EVIDENCE_REQUIRED")
            if self.kind != "COMPLETE_TRAVERSAL" and (
                self.page_snapshot_sha256 is None or self.snapshot_at is None
            ):
                raise ValueError("SUCCESS_PAGE_SNAPSHOT_REQUIRED")
            if self.kind == "CONTINUATION" and self.input_cursor_sha256 is None:
                raise ValueError("CONTINUATION_CURSOR_REQUIRED")
            if self.kind == "COMPLETE_TRAVERSAL" and not self.traversal_complete:
                raise ValueError("TRAVERSAL_COMPLETION_REQUIRED")
        elif self.results or self.traversal_complete:
            raise ValueError("FAILED_OBSERVATION_HAS_RESULTS")
        if self.response_evidence is None and self.response_bytes != 0:
            raise ValueError("OBSERVATION_RESPONSE_EVIDENCE_REQUIRED")
        return self


class ObservationSet(StrictModel):
    version: Literal["eis-search-observations-v2"]
    tenant: str
    observations: tuple[Observation, ...]


class BenchmarkLabel(StrictModel):
    tenant: str
    case_id: CaseId
    intent_sha256: Sha256
    scope_sha256: Sha256
    identity: ExactResultId
    verdict: Literal["RELEVANT", "IRRELEVANT", "UNKNOWN"]
    membership: Membership
    review_status: Literal["PROVISIONAL", "REVIEWED"]
    label_author: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    method: str = Field(min_length=1)
    reviewed_at: AwareDatetime
    reason: str = Field(min_length=1)
    evidence: EvidenceRef
    review_evidence: EvidenceRef


class LabelSet(StrictModel):
    version: Literal["eis-search-labels-v2"]
    tenant: str
    labels: tuple[BenchmarkLabel, ...]


class BenchmarkMethod(FiniteDecimalModel):
    version: Literal["eis-search-method-v2"]
    method_id: str = Field(min_length=1)
    dataset_kind: Literal["SYNTHETIC", "REAL_FROZEN"]
    instrument_author: str = Field(min_length=1)
    canonical_json: Literal["UTF-8 JSON, sorted keys, compact separators, ensure_ascii=false"] = (
        "UTF-8 JSON, sorted keys, compact separators, ensure_ascii=false"
    )
    percentile_method: Literal["NEAREST_RANK"] = "NEAREST_RANK"
    max_artifact_bytes: int = Field(ge=1, le=16 * 1024 * 1024)
    max_observations: int = Field(ge=1, le=100000)
    max_labels: int = Field(ge=1, le=100000)
    target_all_outcome_p95_ms: Decimal = Field(gt=0)
    target_precision_at_10: Decimal = Field(ge=0, le=1)
    target_known_reference_recall: Decimal = Field(ge=0, le=1)

    @field_validator(
        "target_all_outcome_p95_ms", "target_precision_at_10", "target_known_reference_recall"
    )
    @classmethod
    def finite_target(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("NON_FINITE_TARGET")
        return value


class PackageManifest(StrictModel):
    version: Literal["eis-search-package-v2"]
    tenant: str
    package_id: str = Field(min_length=1)
    created_at: AwareDatetime
    suite: EvidenceRef
    corpus: EvidenceRef
    observations: EvidenceRef
    labels: EvidenceRef
    method: EvidenceRef


class LatencySummary(FiniteDecimalModel):
    planned_count: int
    attempted_count: int
    completed_count: int
    not_attempted_count: int
    outcome_counts: dict[str, int]
    all_outcome_p50_ms: Decimal | None
    all_outcome_p95_ms: Decimal | None
    success_only_p50_ms: Decimal | None
    success_only_p95_ms: Decimal | None
    error_rate: Decimal | None
    status: Literal["MEASURED", "UNKNOWN"]
    stop_reasons: tuple[str, ...]
    percentile_method: Literal["NEAREST_RANK"] = "NEAREST_RANK"


class QualitySummary(FiniteDecimalModel):
    repeat: int
    unique_returned_count: int
    duplicate_count: int
    precision_numerator: int
    precision_denominator: int
    precision_at_10: Decimal | None
    precision_lower_bound: Decimal | None
    precision_upper_bound: Decimal | None
    precision_status: Literal["MEASURED", "UNKNOWN", "ZERO_DENOMINATOR"]
    eligible_reference_count: int
    retrieved_reference_at_10_count: int
    retrieved_reference_complete_count: int | None
    known_reference_recall_at_10: Decimal | None
    known_reference_recall_complete: Decimal | None
    recall_at_10_status: Literal["MEASURED", "UNKNOWN", "ZERO_DENOMINATOR"]
    recall_complete_status: Literal["MEASURED", "UNKNOWN", "ZERO_DENOMINATOR", "INCOMPLETE"]
    absent_from_corpus_count: int
    out_of_scope_count: int
    version_conflict_count: int
    membership_unknown_count: int
    retrieval_miss_at_10_count: int | None
    retrieval_miss_complete_count: int | None
    status_reasons: tuple[str, ...]


class CaseReport(StrictModel):
    case_id: CaseId
    law: Law
    kind: Literal["MEASURED", "UNSUPPORTED", "INVALID_QUERY"]
    scope_sha256: Sha256
    first_page_latency: LatencySummary
    continuation_latency: LatencySummary
    traversal_latency: LatencySummary
    repeats: tuple[QualitySummary, ...]
    precision_at_10_mean: Decimal | None
    known_reference_recall_at_10_mean: Decimal | None
    known_reference_recall_complete_mean: Decimal | None
    status: Literal["MEASURED", "UNKNOWN"]
    reasons: tuple[str, ...]


class ReferenceAggregate(FiniteDecimalModel):
    case_id: CaseId
    law: Law
    scope_sha256: Sha256
    retrieval_boundary: Literal["AT_10", "COMPLETE_TRAVERSAL"]
    hit_count: int
    eligible_count: int
    recall: Decimal | None
    status: Literal["MEASURED", "UNKNOWN", "ZERO_DENOMINATOR", "INCOMPLETE"]
    diagnostic_kind: Literal["SUM_ACROSS_REPEATS_WITHIN_ONE_CASE"] = (
        "SUM_ACROSS_REPEATS_WITHIN_ONE_CASE"
    )


class BenchmarkReport(StrictModel):
    version: Literal["eis-search-report-v2"]
    calculator_version: Literal["eis-search-calculator-v2"]
    calculator_source_sha256: Sha256
    package_id: str
    tenant: str
    dataset_kind: Literal["SYNTHETIC", "REAL_FROZEN"]
    input_sha256: dict[str, Sha256]
    prerequisites: dict[str, bool]
    planned_case_count: int
    evaluated_case_count: int
    case_status_counts: dict[str, int]
    first_page_latency: LatencySummary
    continuation_latency: LatencySummary
    traversal_latency: LatencySummary
    cases: tuple[CaseReport, ...]
    macro_precision_at_10: Decimal | None
    macro_known_reference_recall_at_10: Decimal | None
    reference_aggregates: tuple[ReferenceAggregate, ...]
    acceptance_status: Literal["PASS", "FAIL", "UNKNOWN", "SYNTHETIC_ONLY"]
    status_reasons: tuple[str, ...]


class LoadedPackage(StrictModel):
    manifest: PackageManifest
    suite: BenchmarkSuite
    corpus: CorpusManifest
    observations: ObservationSet
    labels: LabelSet
    method: BenchmarkMethod
    input_sha256: dict[str, Sha256]


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def canonical_digest(value: object) -> str:
    return digest_bytes(canonical_bytes(value))


def identity_key(identity: ExactResultId) -> tuple[str, str, int, str]:
    return (
        identity.law,
        identity.purchase_number,
        identity.version_number,
        identity.source_xml_sha256,
    )


def ordered_digest(records: Sequence[CorpusRecord]) -> str:
    return digest_bytes(b"".join(canonical_bytes(record) + b"\n" for record in records))


def _resolve_evidence(root: Path, reference: EvidenceRef) -> Path:
    resolved_root = root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(reference.path).parts)
    current = resolved_root
    for part in PurePosixPath(reference.path).parts:
        current /= part
        if current.is_symlink():
            raise ValueError("EVIDENCE_SYMLINK_REJECTED")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ValueError("EVIDENCE_PATH_ESCAPE")
    return resolved


def _resolve_manifest(root: Path, manifest_path: Path) -> tuple[Path, PurePosixPath]:
    candidate = manifest_path if manifest_path.is_absolute() else root / manifest_path
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("EVIDENCE_PATH_ESCAPE") from error
    if ".." in relative.parts:
        raise ValueError("EVIDENCE_PATH_ESCAPE")
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("EVIDENCE_SYMLINK_REJECTED")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("EVIDENCE_PATH_ESCAPE")
    return resolved, PurePosixPath(relative.as_posix())


def _json_pointer(value: object, pointer: str) -> object:
    if pointer == "/":
        return value
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise ValueError("EVIDENCE_LOCATOR_MISSING")
            current = current[int(token)]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ValueError("EVIDENCE_LOCATOR_MISSING")
    return current


def _read_bounded(path: Path, limit: int) -> bytes:
    size = path.stat().st_size
    if size > limit:
        raise ValueError("EVIDENCE_SIZE_LIMIT")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("EVIDENCE_SIZE_LIMIT")
    if len(content) != size:
        raise ValueError("EVIDENCE_SIZE_CHANGED")
    return content


def verify_evidence(root: Path, reference: EvidenceRef, *, method_cap: int) -> bytes:
    path = _resolve_evidence(root, reference)
    content = _read_bounded(path, min(reference.max_bytes, method_cap))
    if digest_bytes(content) != reference.sha256:
        raise ValueError("EVIDENCE_SHA_MISMATCH")
    try:
        parsed = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("EVIDENCE_JSON_INVALID") from error
    _json_pointer(parsed, reference.locator)
    return content


def evidence_value(content: bytes, reference: EvidenceRef) -> object:
    """Return the already-hash-verified JSON value selected by the exact locator."""
    return _json_pointer(json.loads(content), reference.locator)


def verify_evidence_version(content: bytes, expected: str) -> None:
    parsed = json.loads(content)
    if not isinstance(parsed, dict) or parsed.get("version") != expected:
        raise ValueError("EVIDENCE_VERSION_MISMATCH")


def _artifact(
    root: Path, reference: EvidenceRef, model: type[StrictModel], *, method_cap: int
) -> StrictModel:
    content = verify_evidence(root, reference, method_cap=method_cap)
    return model.model_validate_json(content)


def load_package(root: Path, manifest_path: Path) -> LoadedPackage:
    root = root.resolve(strict=True)
    manifest_path, manifest_relative = _resolve_manifest(root, manifest_path)
    manifest_content = _read_bounded(manifest_path, 1024 * 1024)
    manifest_reference = EvidenceRef(
        path=manifest_relative.as_posix(),
        sha256=digest_bytes(manifest_content),
        locator="/",
        max_bytes=1024 * 1024,
    )
    manifest = PackageManifest.model_validate_json(
        verify_evidence(root, manifest_reference, method_cap=1024 * 1024)
    )
    method = _artifact(root, manifest.method, BenchmarkMethod, method_cap=manifest.method.max_bytes)
    assert isinstance(method, BenchmarkMethod)
    artifacts: dict[str, StrictModel] = {
        "suite": _artifact(
            root, manifest.suite, BenchmarkSuite, method_cap=method.max_artifact_bytes
        ),
        "corpus": _artifact(
            root, manifest.corpus, CorpusManifest, method_cap=method.max_artifact_bytes
        ),
        "observations": _artifact(
            root, manifest.observations, ObservationSet, method_cap=method.max_artifact_bytes
        ),
        "labels": _artifact(root, manifest.labels, LabelSet, method_cap=method.max_artifact_bytes),
    }
    suite = artifacts["suite"]
    corpus = artifacts["corpus"]
    observations = artifacts["observations"]
    labels = artifacts["labels"]
    assert isinstance(suite, BenchmarkSuite)
    assert isinstance(corpus, CorpusManifest)
    assert isinstance(observations, ObservationSet)
    assert isinstance(labels, LabelSet)
    tenants = {
        manifest.tenant,
        suite.tenant,
        corpus.tenant,
        observations.tenant,
        labels.tenant,
    }
    if len(tenants) != 1:
        raise ValueError("PACKAGE_TENANT_MISMATCH")
    if len(observations.observations) > method.max_observations:
        raise ValueError("OBSERVATION_LIMIT_EXCEEDED")
    if len(labels.labels) > method.max_labels:
        raise ValueError("LABEL_LIMIT_EXCEEDED")
    proof_content = verify_evidence(
        root, corpus.consistency.proof, method_cap=method.max_artifact_bytes
    )
    verify_evidence_version(proof_content, "eis-search-consistency-proof-v2")
    proof = evidence_value(proof_content, corpus.consistency.proof)
    expected_proof = {
        "tenant": corpus.tenant,
        "capture_id": corpus.capture_id,
        "captured_at": corpus.captured_at.isoformat(),
        "complete": True,
        "partial": False,
        "repeatable_read": True,
        "tenant_rls_bound": True,
        "single_clock": True,
    }
    if proof != expected_proof:
        raise ValueError("CORPUS_CONSISTENCY_PROOF_MISMATCH")
    for observation in observations.observations:
        if observation.response_evidence:
            content = verify_evidence(
                root, observation.response_evidence, method_cap=method.max_artifact_bytes
            )
            verify_evidence_version(content, "eis-search-response-evidence-v2")
            if observation.response_bytes != len(content):
                raise ValueError("OBSERVATION_RESPONSE_SIZE_MISMATCH")
            expected_results = [item.model_dump(mode="json") for item in observation.results]
            if evidence_value(content, observation.response_evidence) != expected_results:
                raise ValueError("OBSERVATION_EXACT_IDENTITY_MISMATCH")
    for label in labels.labels:
        evidence = verify_evidence(root, label.evidence, method_cap=method.max_artifact_bytes)
        verify_evidence_version(evidence, "eis-search-label-source-evidence-v2")
        if evidence_value(evidence, label.evidence) != label.identity.model_dump(mode="json"):
            raise ValueError("LABEL_EXACT_IDENTITY_MISMATCH")
        review = verify_evidence(root, label.review_evidence, method_cap=method.max_artifact_bytes)
        verify_evidence_version(review, "eis-search-label-review-evidence-v2")
        expected_review = {
            "tenant": label.tenant,
            "case_id": label.case_id,
            "reviewer": label.reviewer,
            "label_author": label.label_author,
            "identity": label.identity.model_dump(mode="json"),
            "intent_sha256": label.intent_sha256,
            "scope_sha256": label.scope_sha256,
            "verdict": label.verdict,
            "membership": label.membership,
        }
        if evidence_value(review, label.review_evidence) != expected_review:
            raise ValueError("LABEL_REVIEW_PROOF_MISMATCH")
    return LoadedPackage(
        manifest=manifest,
        suite=suite,
        corpus=corpus,
        observations=observations,
        labels=labels,
        method=method,
        input_sha256={
            "package": manifest_reference.sha256,
            "suite": manifest.suite.sha256,
            "corpus": manifest.corpus.sha256,
            "observations": manifest.observations.sha256,
            "labels": manifest.labels.sha256,
            "method": manifest.method.sha256,
        },
    )


def _nearest_rank(values: Sequence[Decimal], percentile: int) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) * percentile + 99) // 100 - 1
    return ordered[index]


def latency_summary(
    planned: Sequence[PlannedAttempt], observed: Sequence[Observation]
) -> LatencySummary:
    planned_ids = {item.attempt_id for item in planned}
    relevant = [item for item in observed if item.attempt_id in planned_ids]
    durations = [item.duration_ms for item in relevant]
    successes = [item.duration_ms for item in relevant if item.outcome == "SUCCEEDED"]
    counts = Counter(item.outcome for item in relevant)
    not_attempted = len(planned) - len(relevant)
    return LatencySummary(
        planned_count=len(planned),
        attempted_count=len(relevant),
        completed_count=len(relevant),
        not_attempted_count=not_attempted,
        outcome_counts=dict(sorted(counts.items())),
        all_outcome_p50_ms=_nearest_rank(durations, 50),
        all_outcome_p95_ms=_nearest_rank(durations, 95),
        success_only_p50_ms=_nearest_rank(successes, 50),
        success_only_p95_ms=_nearest_rank(successes, 95),
        error_rate=(Decimal(len(relevant) - len(successes)) / len(relevant)) if relevant else None,
        status="MEASURED" if not_attempted == 0 else "UNKNOWN",
        stop_reasons=("PLANNED_ATTEMPT_MISSING",) if not_attempted else (),
    )


def _mean(values: Iterable[Decimal | None]) -> Decimal | None:
    collected = list(values)
    if not collected or any(value is None for value in collected):
        return None
    actual = [value for value in collected if value is not None]
    return sum(actual, Decimal(0)) / len(actual)


def _label_groups(
    package: LoadedPackage, case: BenchmarkCase
) -> tuple[dict[tuple[str, str, int, str], list[BenchmarkLabel]], tuple[str, ...]]:
    corpus_exact = {identity_key(record.identity): record for record in package.corpus.records}
    corpus_numbers = {
        (record.identity.law, record.identity.purchase_number) for record in package.corpus.records
    }
    selected: dict[tuple[str, str, int, str], list[BenchmarkLabel]] = defaultdict(list)
    reasons: list[str] = []
    for label in package.labels.labels:
        if label.case_id != case.case_id:
            continue
        if label.tenant != package.manifest.tenant:
            raise ValueError("LABEL_TENANT_MISMATCH")
        if label.intent_sha256 != case.intent_sha256 or label.scope_sha256 != case.scope_sha256:
            raise ValueError("LABEL_CASE_BINDING_MISMATCH")
        if label.identity.law != case.scope.law:
            raise ValueError("LABEL_LAW_MISMATCH")
        if label.review_status == "REVIEWED" and (
            label.reviewer == label.label_author
            or label.reviewer == package.method.instrument_author
        ):
            raise ValueError("LABEL_SELF_REVIEW")
        key = identity_key(label.identity)
        present = key in corpus_exact
        same_number = (label.identity.law, label.identity.purchase_number) in corpus_numbers
        eligible = present and case.case_id in corpus_exact[key].eligible_case_ids
        if eligible and label.membership in {
            "ABSENT_FROM_CORPUS",
            "OUT_OF_SCOPE",
            "VERSION_CONFLICT",
        }:
            raise ValueError("LABEL_MEMBERSHIP_MISMATCH")
        if label.membership == "IN_SCOPE_PRESENT_EXACT" and not eligible:
            raise ValueError("LABEL_MEMBERSHIP_MISMATCH")
        if label.membership == "ABSENT_FROM_CORPUS" and same_number:
            raise ValueError("LABEL_MEMBERSHIP_MISMATCH")
        if label.membership == "OUT_OF_SCOPE" and (not present or eligible):
            raise ValueError("LABEL_MEMBERSHIP_MISMATCH")
        if label.membership == "VERSION_CONFLICT" and (present or not same_number):
            raise ValueError("LABEL_MEMBERSHIP_MISMATCH")
        selected[key].append(label)
    for key, group in selected.items():
        reviewed = [label for label in group if label.review_status == "REVIEWED"]
        if len({label.verdict for label in reviewed}) > 1:
            reasons.append("CONFLICTING_REVIEWED_LABEL:" + ":".join(map(str, key[:3])))
    return selected, tuple(sorted(reasons))


def _unique_results(results: Sequence[ExactResultId]) -> tuple[list[ExactResultId], int, bool]:
    unique: list[ExactResultId] = []
    seen: set[tuple[str, str]] = set()
    exact_by_number: dict[tuple[str, str], tuple[str, str, int, str]] = {}
    version_conflict = False
    for item in results:
        number_key = (item.law, item.purchase_number)
        exact = identity_key(item)
        if number_key in exact_by_number and exact_by_number[number_key] != exact:
            version_conflict = True
        exact_by_number.setdefault(number_key, exact)
        if number_key not in seen:
            seen.add(number_key)
            unique.append(item)
    return unique, len(results) - len(unique), version_conflict


def _reviewed_verdict(
    groups: Mapping[tuple[str, str, int, str], list[BenchmarkLabel]], identity: ExactResultId
) -> Literal["RELEVANT", "IRRELEVANT", "UNKNOWN"] | None:
    reviewed = [
        label
        for label in groups.get(identity_key(identity), ())
        if label.review_status == "REVIEWED"
    ]
    verdicts = {label.verdict for label in reviewed}
    return next(iter(verdicts)) if len(verdicts) == 1 else None


def _repeat_results(
    case: BenchmarkCase, observations: Sequence[Observation], repeat: int
) -> tuple[tuple[ExactResultId, ...] | None, tuple[ExactResultId, ...] | None, list[str]]:
    reasons: list[str] = []
    pages = sorted(
        (
            item
            for item in observations
            if item.repeat == repeat and item.kind in {"FIRST_PAGE", "CONTINUATION"}
        ),
        key=lambda item: item.page_index or 0,
    )
    successes = [item for item in pages if item.outcome == "SUCCEEDED"]
    first = next(
        (item for item in successes if item.kind == "FIRST_PAGE" and item.page_index == 1), None
    )
    top_results = first.results if first else None
    if first is None:
        reasons.append("FIRST_PAGE_NOT_SUCCESSFUL")
    if successes:
        indices = [item.page_index for item in successes]
        if indices != list(range(1, len(indices) + 1)):
            reasons.append("PAGE_SEQUENCE_INCOMPLETE")
        if len({item.snapshot_at for item in successes}) != 1:
            reasons.append("PAGE_CLOCK_DRIFT")
        if len({item.page_snapshot_sha256 for item in successes}) != 1:
            reasons.append("PAGE_FINGERPRINT_DRIFT")
        first_success = successes[0]
        if first_success.input_cursor_sha256 is not None:
            reasons.append("CURSOR_CHAIN_MISMATCH")
        for previous, current in pairwise(successes):
            if (
                previous.output_cursor_sha256 is None
                or current.input_cursor_sha256 != previous.output_cursor_sha256
            ):
                reasons.append("CURSOR_CHAIN_MISMATCH")
        page_exact = [identity_key(result) for item in successes for result in item.results]
        if len(page_exact) != len(set(page_exact)):
            reasons.append("PAGE_RESULT_DUPLICATE")
    traversal = next(
        (
            item
            for item in observations
            if item.repeat == repeat
            and item.kind == "COMPLETE_TRAVERSAL"
            and item.outcome == "SUCCEEDED"
        ),
        None,
    )
    complete_results: tuple[ExactResultId, ...] | None = None
    if traversal is not None:
        concatenated = tuple(result for page in successes for result in page.results)
        planned_page_ids = {
            item.attempt_id
            for item in case.attempts
            if item.repeat == repeat and item.kind in {"FIRST_PAGE", "CONTINUATION"}
        }
        successful_page_ids = {item.attempt_id for item in successes}
        if successful_page_ids != planned_page_ids:
            reasons.append("PLANNED_PAGE_INCOMPLETE")
        if pages and len(successes) != len(pages):
            reasons.append("PAGE_SEQUENCE_INCOMPLETE")
        if successes and successes[-1].output_cursor_sha256 is not None:
            reasons.append("TERMINAL_CURSOR_PRESENT")
        if traversal.results != concatenated or reasons:
            reasons.append("TRAVERSAL_EVIDENCE_MISMATCH")
        else:
            complete_results = traversal.results
    return top_results, complete_results, reasons


def quality_summary(
    package: LoadedPackage,
    case: BenchmarkCase,
    observations: Sequence[Observation],
    repeat: int,
) -> QualitySummary:
    groups, label_reasons = _label_groups(package, case)
    top_results, complete_results, result_reasons = _repeat_results(case, observations, repeat)
    reasons = list(label_reasons) + result_reasons
    ranked, duplicates, version_conflict = _unique_results(top_results or ())
    top = ranked[:10]
    if version_conflict:
        reasons.append("RETURNED_VERSION_CONFLICT")
    verdicts = [_reviewed_verdict(groups, item) for item in top]
    relevant = sum(item == "RELEVANT" for item in verdicts)
    irrelevant = sum(item == "IRRELEVANT" for item in verdicts)
    unjudged = len(top) - relevant - irrelevant
    reviewed_positive: list[BenchmarkLabel] = []
    conflicting_membership_class = False
    for group in groups.values():
        reviewed = [label for label in group if label.review_status == "REVIEWED"]
        if {label.verdict for label in reviewed} == {"RELEVANT"}:
            memberships = {label.membership for label in reviewed}
            if len(memberships) == 1:
                reviewed_positive.append(reviewed[0])
            else:
                reasons.append("CONFLICTING_MEMBERSHIP_CLASS")
                conflicting_membership_class = True
                resolved = [label for label in reviewed if label.membership != "MEMBERSHIP_UNKNOWN"]
                if len({label.membership for label in resolved}) == 1:
                    reviewed_positive.append(resolved[0])
    known_positive = [
        label
        for label in reviewed_positive
        if label.membership in {"IN_SCOPE_PRESENT_EXACT", "ABSENT_FROM_CORPUS"}
    ]
    denominator = len(top)
    precision: Decimal | None = None
    precision_status: Literal["MEASURED", "UNKNOWN", "ZERO_DENOMINATOR"] = "UNKNOWN"
    if top_results is not None and not top:
        if known_positive:
            precision = Decimal(0)
            precision_status = "MEASURED"
        else:
            precision_status = "ZERO_DENOMINATOR"
            reasons.append("ZERO_DENOMINATOR")
    elif top_results is not None and not unjudged and not version_conflict and not label_reasons:
        precision = Decimal(relevant) / denominator
        precision_status = "MEASURED"
    elif top:
        reasons.append("TOP10_LABEL_COVERAGE_INCOMPLETE")
    lower = Decimal(relevant) / denominator if denominator else None
    upper = Decimal(relevant + unjudged) / denominator if denominator else None
    eligible = [
        label for label in reviewed_positive if label.membership == "IN_SCOPE_PRESENT_EXACT"
    ]
    absent = sum(label.membership == "ABSENT_FROM_CORPUS" for label in reviewed_positive)
    out_scope = sum(label.membership == "OUT_OF_SCOPE" for label in reviewed_positive)
    membership_conflict = sum(label.membership == "VERSION_CONFLICT" for label in reviewed_positive)
    membership_unknown = sum(
        label.membership == "MEMBERSHIP_UNKNOWN" for label in reviewed_positive
    )
    eligible_keys = {identity_key(label.identity) for label in eligible}
    top_keys = {identity_key(item) for item in top}
    at10_hits = len(eligible_keys & top_keys)
    membership_unresolved = bool(
        membership_conflict or membership_unknown or conflicting_membership_class or label_reasons
    )
    recall_at10 = (
        Decimal(at10_hits) / len(eligible_keys)
        if top_results is not None and eligible_keys and not membership_unresolved
        else None
    )
    recall_at10_status: Literal["MEASURED", "UNKNOWN", "ZERO_DENOMINATOR"]
    if top_results is None:
        recall_at10_status = "UNKNOWN"
    elif membership_unresolved:
        recall_at10_status = "UNKNOWN"
        reasons.append("REFERENCE_MEMBERSHIP_UNRESOLVED")
    elif eligible_keys:
        recall_at10_status = "MEASURED"
    else:
        recall_at10_status = "ZERO_DENOMINATOR"
    complete_hits: int | None = None
    recall_complete: Decimal | None = None
    if complete_results is not None:
        complete_keys = {identity_key(item) for item in complete_results}
        complete_hits = len(eligible_keys & complete_keys)
        recall_complete = (
            Decimal(complete_hits) / len(eligible_keys)
            if eligible_keys and not membership_unresolved
            else None
        )
    recall_complete_status: Literal["MEASURED", "UNKNOWN", "ZERO_DENOMINATOR", "INCOMPLETE"]
    if membership_unresolved:
        recall_complete_status = "UNKNOWN"
    elif complete_results is None:
        recall_complete_status = "INCOMPLETE"
    elif eligible_keys:
        recall_complete_status = "MEASURED"
    else:
        recall_complete_status = "ZERO_DENOMINATOR"
    return QualitySummary(
        repeat=repeat,
        unique_returned_count=len(ranked),
        duplicate_count=duplicates,
        precision_numerator=relevant,
        precision_denominator=denominator,
        precision_at_10=precision,
        precision_lower_bound=lower,
        precision_upper_bound=upper,
        precision_status=precision_status,
        eligible_reference_count=len(eligible_keys),
        retrieved_reference_at_10_count=at10_hits,
        retrieved_reference_complete_count=complete_hits,
        known_reference_recall_at_10=recall_at10,
        known_reference_recall_complete=recall_complete,
        recall_at_10_status=recall_at10_status,
        recall_complete_status=recall_complete_status,
        absent_from_corpus_count=absent,
        out_of_scope_count=out_scope,
        version_conflict_count=membership_conflict,
        membership_unknown_count=membership_unknown,
        retrieval_miss_at_10_count=(len(eligible_keys) - at10_hits)
        if top_results is not None
        else None,
        retrieval_miss_complete_count=(len(eligible_keys) - complete_hits)
        if complete_hits is not None
        else None,
        status_reasons=tuple(sorted(set(reasons))),
    )


def calculate_report(package: LoadedPackage) -> BenchmarkReport:
    suite_sha = package.input_sha256["suite"]
    corpus_sha = package.input_sha256["corpus"]
    method_sha = package.input_sha256["method"]
    cases_by_id = {case.case_id: case for case in package.suite.cases}
    observed_ids: set[str] = set()
    for observation in package.observations.observations:
        if observation.attempt_id in observed_ids:
            raise ValueError("OBSERVATION_ATTEMPT_DUPLICATE")
        observed_ids.add(observation.attempt_id)
        case = cases_by_id.get(observation.case_id)
        if case is None:
            raise ValueError("OBSERVATION_CASE_UNKNOWN")
        if case.kind == "UNSUPPORTED":
            raise ValueError("UNSUPPORTED_CASE_HTTP_OBSERVATION")
        plan = {item.attempt_id: item for item in case.attempts}.get(observation.attempt_id)
        if plan is None or (plan.repeat, plan.kind, plan.page_index) != (
            observation.repeat,
            observation.kind,
            observation.page_index,
        ):
            raise ValueError("OBSERVATION_PLAN_MISMATCH")
        if observation.tenant != package.manifest.tenant:
            raise ValueError("OBSERVATION_TENANT_MISMATCH")
        if (
            observation.suite_sha256,
            observation.corpus_sha256,
            observation.method_sha256,
            observation.scope_sha256,
        ) != (suite_sha, corpus_sha, method_sha, case.scope_sha256):
            raise ValueError("OBSERVATION_BINDING_MISMATCH")
        if any(result.law != case.scope.law for result in observation.results):
            raise ValueError("OBSERVATION_LAW_MISMATCH")
        if (
            observation.outcome == "SUCCEEDED"
            and observation.kind != "COMPLETE_TRAVERSAL"
            and (
                observation.snapshot_at != case.scope.clock
                or observation.snapshot_at != package.corpus.captured_at
            )
        ):
            raise ValueError("OBSERVATION_SNAPSHOT_CLOCK_MISMATCH")
    case_reports: list[CaseReport] = []
    global_reasons: list[str] = []
    for case in package.suite.cases:
        observations = [
            item for item in package.observations.observations if item.case_id == case.case_id
        ]
        by_kind = {
            kind: [attempt for attempt in case.attempts if attempt.kind == kind]
            for kind in ("FIRST_PAGE", "CONTINUATION", "COMPLETE_TRAVERSAL")
        }
        latency = {
            kind: latency_summary(planned, observations) for kind, planned in by_kind.items()
        }
        quality = tuple(
            quality_summary(package, case, observations, repeat)
            for repeat in range(1, case.repeats + 1)
        )
        reasons: list[str] = []
        if any(item.status == "UNKNOWN" for item in latency.values()):
            reasons.append("PLANNED_ATTEMPT_MISSING")
        if case.kind == "UNSUPPORTED":
            reasons.append("UNSUPPORTED_FILTER")
        if case.kind == "INVALID_QUERY":
            reasons.append("INVALID_QUERY_CASE")
        if any(item.outcome != "SUCCEEDED" for item in observations):
            reasons.append("NON_SUCCESS_OUTCOME")
        if any(item.precision_status != "MEASURED" for item in quality):
            reasons.append("PRECISION_INCOMPLETE")
        if any(item.known_reference_recall_at_10 is None for item in quality):
            reasons.append("REFERENCE_RECALL_INCOMPLETE")
        if any(item.status_reasons for item in quality):
            reasons.append("QUALITY_PREREQUISITE_INCOMPLETE")
        if case.scope.continuation_policy == "UNTIL_END_OR_PAGE_BUDGET" and any(
            item.recall_complete_status in {"INCOMPLETE", "UNKNOWN"} for item in quality
        ):
            reasons.append("TRAVERSAL_INCOMPLETE")
        status = "MEASURED" if not reasons else "UNKNOWN"
        report = CaseReport(
            case_id=case.case_id,
            law=case.scope.law,
            kind=case.kind,
            scope_sha256=case.scope_sha256,
            first_page_latency=latency["FIRST_PAGE"],
            continuation_latency=latency["CONTINUATION"],
            traversal_latency=latency["COMPLETE_TRAVERSAL"],
            repeats=quality,
            precision_at_10_mean=_mean(item.precision_at_10 for item in quality),
            known_reference_recall_at_10_mean=_mean(
                item.known_reference_recall_at_10 for item in quality
            ),
            known_reference_recall_complete_mean=_mean(
                item.known_reference_recall_complete for item in quality
            ),
            status=status,
            reasons=tuple(sorted(set(reasons))),
        )
        case_reports.append(report)
        global_reasons.extend(f"{case.case_id}:{reason}" for reason in report.reasons)
    macro_precision = _mean(item.precision_at_10_mean for item in case_reports)
    macro_recall = _mean(item.known_reference_recall_at_10_mean for item in case_reports)
    global_latency: dict[str, LatencySummary] = {}
    for kind in ("FIRST_PAGE", "CONTINUATION", "COMPLETE_TRAVERSAL"):
        planned = [
            attempt
            for case in package.suite.cases
            for attempt in case.attempts
            if attempt.kind == kind
        ]
        global_latency[kind] = latency_summary(planned, package.observations.observations)
    reference_aggregates: list[ReferenceAggregate] = []
    for case_report in case_reports:
        at10_eligible = sum(item.eligible_reference_count for item in case_report.repeats)
        at10_hits = sum(item.retrieved_reference_at_10_count for item in case_report.repeats)
        at10_measured = all(item.recall_at_10_status == "MEASURED" for item in case_report.repeats)
        at10_zero = all(
            item.recall_at_10_status == "ZERO_DENOMINATOR" for item in case_report.repeats
        )
        reference_aggregates.append(
            ReferenceAggregate(
                case_id=case_report.case_id,
                law=case_report.law,
                scope_sha256=case_report.scope_sha256,
                retrieval_boundary="AT_10",
                hit_count=at10_hits,
                eligible_count=at10_eligible,
                recall=(Decimal(at10_hits) / at10_eligible)
                if at10_eligible and at10_measured
                else None,
                status="MEASURED"
                if at10_measured
                else "ZERO_DENOMINATOR"
                if at10_zero
                else "UNKNOWN",
            )
        )
        complete_eligible = sum(item.eligible_reference_count for item in case_report.repeats)
        complete_hits = sum(
            item.retrieved_reference_complete_count or 0 for item in case_report.repeats
        )
        complete_measured = all(
            item.recall_complete_status == "MEASURED" for item in case_report.repeats
        )
        complete_zero = all(
            item.recall_complete_status == "ZERO_DENOMINATOR" for item in case_report.repeats
        )
        complete_incomplete = any(
            item.recall_complete_status == "INCOMPLETE" for item in case_report.repeats
        )
        reference_aggregates.append(
            ReferenceAggregate(
                case_id=case_report.case_id,
                law=case_report.law,
                scope_sha256=case_report.scope_sha256,
                retrieval_boundary="COMPLETE_TRAVERSAL",
                hit_count=complete_hits,
                eligible_count=complete_eligible,
                recall=(Decimal(complete_hits) / complete_eligible)
                if complete_eligible and complete_measured
                else None,
                status="MEASURED"
                if complete_measured
                else "ZERO_DENOMINATOR"
                if complete_zero
                else "INCOMPLETE"
                if complete_incomplete
                else "UNKNOWN",
            )
        )
    prerequisites = {
        "declared_consistency_structure_valid": True,
        "all_planned_attempts_completed": all(
            summary.not_attempted_count == 0
            for case in case_reports
            for summary in (
                case.first_page_latency,
                case.continuation_latency,
                case.traversal_latency,
            )
        ),
        "all_cases_measured": all(case.status == "MEASURED" for case in case_reports),
        "declared_independent_label_structure_valid": not any(
            label.review_status == "REVIEWED"
            and (
                label.reviewer == label.label_author
                or label.reviewer == package.method.instrument_author
            )
            for label in package.labels.labels
        ),
        "trusted_m2b_capture_proof_validated": False,
        "trusted_m2b_review_provenance_validated": False,
    }
    if package.method.dataset_kind == "SYNTHETIC":
        acceptance: Literal["PASS", "FAIL", "UNKNOWN", "SYNTHETIC_ONLY"] = "SYNTHETIC_ONLY"
        global_reasons.append("SYNTHETIC_DATASET_NO_PRODUCT_ACCEPTANCE")
    else:
        acceptance = "UNKNOWN"
        global_reasons.append("REAL_CAPTURE_AUTHORITY_NOT_VALIDATED_IN_M2A")
    return BenchmarkReport(
        version="eis-search-report-v2",
        calculator_version=CALCULATOR_VERSION,
        calculator_source_sha256=digest_bytes(Path(__file__).read_bytes()),
        package_id=package.manifest.package_id,
        tenant=package.manifest.tenant,
        dataset_kind=package.method.dataset_kind,
        input_sha256=package.input_sha256,
        prerequisites=prerequisites,
        planned_case_count=len(package.suite.cases),
        evaluated_case_count=len(case_reports),
        case_status_counts=dict(sorted(Counter(item.status for item in case_reports).items())),
        first_page_latency=global_latency["FIRST_PAGE"],
        continuation_latency=global_latency["CONTINUATION"],
        traversal_latency=global_latency["COMPLETE_TRAVERSAL"],
        cases=tuple(case_reports),
        macro_precision_at_10=macro_precision,
        macro_known_reference_recall_at_10=macro_recall,
        reference_aggregates=tuple(reference_aggregates),
        acceptance_status=acceptance,
        status_reasons=tuple(sorted(set(global_reasons))),
    )


def labels_template(package: LoadedPackage) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    seen: set[tuple[str, str, int, str, str]] = set()
    for observation in package.observations.observations:
        case = next(case for case in package.suite.cases if case.case_id == observation.case_id)
        for identity in observation.results:
            key = (*identity_key(identity), case.case_id)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "case_id": case.case_id,
                    "intent": case.intent,
                    "intent_sha256": case.intent_sha256,
                    "scope_sha256": case.scope_sha256,
                    "identity": identity.model_dump(mode="json"),
                    "verdict": "UNKNOWN",
                    "membership": "MEMBERSHIP_UNKNOWN",
                    "review_status": "PROVISIONAL",
                }
            )
    return {
        "version": "eis-search-label-template-v2",
        "tenant": package.manifest.tenant,
        "package_id": package.manifest.package_id,
        "candidates": sorted(
            candidates,
            key=lambda item: (
                str(item["case_id"]),
                canonical_bytes(item["identity"]),
            ),
        ),
    }


def report_markdown(report: BenchmarkReport) -> str:
    lines = [
        "# EIS saved-search benchmark v2",
        "",
        (
            f"Package: `{report.package_id}`; tenant: `{report.tenant}`; "
            f"dataset: `{report.dataset_kind}`."
        ),
        f"Acceptance: **{report.acceptance_status}**.",
        "",
        (
            "| Case | Law | Status | all-outcome p95 first page, ms | "
            "Precision@10 | Known-reference recall@10 |"
        ),
        "|---|---:|---|---:|---:|---:|",
    ]
    for case in report.cases:
        lines.append(
            f"| {case.case_id} | {case.law} | {case.status} | "
            f"{case.first_page_latency.all_outcome_p95_ms} | {case.precision_at_10_mean} | "
            f"{case.known_reference_recall_at_10_mean} |"
        )
    lines.extend(
        [
            "",
            f"Macro precision@10: `{report.macro_precision_at_10}`.",
            f"Macro known-reference recall@10: `{report.macro_known_reference_recall_at_10}`.",
            "Full-corpus recall is not measured.",
            "",
            "## Status reasons",
            "",
        ]
    )
    lines.extend(f"- `{reason}`" for reason in report.status_reasons)
    if not report.status_reasons:
        lines.append("- none")
    return "\n".join(lines) + "\n"
